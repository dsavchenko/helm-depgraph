"""Output formatters for dependency graphs."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

from helm_depgraph.conditions import chart_status
from helm_depgraph.graph import DependencyGraph, Occurrence


def _is_library(node: Occurrence) -> bool:
    """Check if a node is a library chart."""
    return node.chart_type == "library"


def _require_evaluated(graph: DependencyGraph) -> None:
    """Raise if any occurrence has no status yet."""
    if any(o.enabled is None for o in graph.occurrences.values()):
        raise ValueError("Graph has not been evaluated: occurrence status is unset")


def _visible_occurrences(graph: DependencyGraph, hide_libraries: bool) -> dict[str, Occurrence]:
    """Occurrences to show; hiding libraries also hides their descendants."""
    if not hide_libraries:
        return graph.occurrences
    hidden = [p for p, o in graph.occurrences.items() if _is_library(o)]
    return {
        path: node
        for path, node in graph.occurrences.items()
        if not any(path == h or path.startswith(h + "/") for h in hidden)
    }


def format_text(
    graph: DependencyGraph,
    show_duplicates: bool = False,
    hide_libraries: bool = True,
) -> str:
    """Format graph as a human-readable occurrence tree.

    Each line shows the occurrence status. Children are grouped on first,
    then a blank line separator, then off. The summary line counts charts
    by chart status.

    Args:
        graph: The evaluated dependency graph.
        show_duplicates: If False, collapse the subtree of a chart already shown.
        hide_libraries: If True, exclude library charts from output.

    Returns:
        Formatted text string.
    """
    _require_evaluated(graph)
    lines: list[str] = []
    seen: set[str] = set()

    def _walk(node: Occurrence, prefix: str = "", is_last: bool = True) -> None:
        if hide_libraries and _is_library(node):
            return

        connector = "└── " if is_last else "├── "
        status = _status_str(node.enabled)
        alias_str = f" (alias: {node.alias})" if node.alias else ""
        type_str = " (library)" if _is_library(node) else ""
        lines.append(f"{prefix}{connector}{node.name}-{node.version}{alias_str}{type_str} {status}")

        child_prefix = prefix + ("    " if is_last else "│   ")
        children = [c for c in node.children.values() if not (hide_libraries and _is_library(c))]

        if not show_duplicates and node.name in seen:
            if children:
                lines.append(f"{child_prefix}[deduplicated]")
            return
        seen.add(node.name)

        on = [c for c in children if c.enabled is True]
        off = [c for c in children if c.enabled is not True]

        for i, child in enumerate(on):
            _walk(child, child_prefix, i == len(on) - 1 and not off)

        if on and off:
            lines.append(f"{child_prefix}│   ")

        for i, child in enumerate(off):
            _walk(child, child_prefix, i == len(off) - 1)

    # Root node
    root_status = _status_str(graph.root.enabled)
    root_type = " (library)" if _is_library(graph.root) else ""
    lines.append(f"{graph.root.name}-{graph.root.version} (root){root_type} {root_status}")

    # Summary: distinct charts by chart status
    visible = _visible_occurrences(graph, hide_libraries)
    chart_names = {node.name for node in visible.values()}
    on_count = sum(1 for name in chart_names if chart_status(graph, name))
    lines.append(f"  {on_count} on, {len(chart_names) - on_count} off")
    lines.append("")

    seen.add(graph.root.name)

    children = [c for c in graph.root.children.values() if not (hide_libraries and _is_library(c))]
    for i, child in enumerate(children):
        _walk(child, "", i == len(children) - 1)

    return "\n".join(lines)


def format_json(
    graph: DependencyGraph,
    hide_libraries: bool = True,
) -> str:
    """Format graph as JSON with an ``occurrences`` list and a ``charts`` list.

    Occurrences are in tree pre-order and carry the occurrence status; charts
    are in order of first appearance and carry the chart status.

    Args:
        graph: The evaluated dependency graph.
        hide_libraries: If True, exclude library charts from output.

    Returns:
        JSON string.
    """
    _require_evaluated(graph)
    visible = _visible_occurrences(graph, hide_libraries)

    occurrences = [
        {
            "path": path,
            "chart": node.name,
            "alias": node.alias,
            "version": node.version,
            "repository": node.repository,
            "type": node.chart_type,
            "conditions": node.conditions,
            "tags": node.tags,
            "status": _status_word(bool(node.enabled)),
        }
        for path, node in visible.items()
    ]

    charts: dict[str, dict[str, Any]] = {}
    for node in visible.values():
        if node.name not in charts:
            charts[node.name] = {
                "name": node.name,
                "versions": graph.chart_versions(node.name),
                "type": node.chart_type,
                "status": _status_word(chart_status(graph, node.name)),
            }

    return json.dumps({"occurrences": occurrences, "charts": list(charts.values())}, indent=2)


@dataclass(frozen=True)
class _GraphNode:
    """A chart node of the diagram formats."""

    name: str
    lines: list[str]
    enabled: bool


@dataclass(frozen=True)
class _GraphEdge:
    """A (parent chart, alias, child chart) dependency; dashed only if all occurrences are off."""

    parent: str
    child: str
    alias: str | None
    enabled: bool


def _diagram_model(
    graph: DependencyGraph, hide_libraries: bool
) -> tuple[list[_GraphNode], list[_GraphEdge]]:
    """Collect one node per chart (in order of first appearance) and one edge per dependency."""
    _require_evaluated(graph)
    visible = _visible_occurrences(graph, hide_libraries)

    charts: dict[str, Occurrence] = {}
    for node in visible.values():
        charts.setdefault(node.name, node)
    nodes = [
        _GraphNode(
            name,
            _chart_label_lines(graph, name, library=_is_library(node)),
            bool(chart_status(graph, name)),
        )
        for name, node in charts.items()
    ]

    statuses: dict[tuple[str, str, str], list[bool]] = {}
    for path, node in visible.items():
        if node is graph.root:
            continue
        parent = graph.occurrences[path.rsplit("/", 1)[0]]
        statuses.setdefault((parent.name, node.scope_key, node.name), []).append(bool(node.enabled))
    edges = [
        _GraphEdge(parent, child, alias if alias != child else None, any(enabled))
        for (parent, alias, child), enabled in statuses.items()
    ]
    return nodes, edges


def format_dot(
    graph: DependencyGraph,
    hide_libraries: bool = True,
    ranksep: float | None = 1.5,
    nodesep: float | None = 0.6,
) -> str:
    """Format graph as Graphviz DOT: one node per chart, one edge per dependency.

    Nodes are styled by chart status and list every version pinned across the
    chart's occurrences. An edge stands for all occurrences of a (parent chart,
    alias, child chart) dependency and is dashed only if every one of them is off.

    Args:
        graph: The evaluated dependency graph.
        hide_libraries: If True, exclude library charts from output.
        ranksep: Vertical space between ranks (layers). None to omit.
        nodesep: Horizontal space between nodes in the same rank. None to omit.

    Returns:
        DOT string.
    """
    nodes, edges = _diagram_model(graph, hide_libraries)
    lines = [
        "digraph helm_deps {",
        "  rankdir=TB;",
        "  node [shape=box];",
    ]
    if ranksep is not None:
        lines.append(f"  ranksep={ranksep};")
    if nodesep is not None:
        lines.append(f"  nodesep={nodesep};")
    lines.append("")

    for n in nodes:
        label = '"' + "\\n".join(n.lines) + '"'
        if n.enabled:
            fill, style, border = "lightgreen", "filled", "darkgreen"
        else:
            fill, style, border = "mistyrose", "filled,dashed", "grey"
        lines.append(
            f'  "{n.name}" [label={label} fillcolor={fill} style="{style}" color={border}];'
        )

    for e in edges:
        attrs = f'style="{"solid" if e.enabled else "dashed"}"'
        if e.alias is not None:
            attrs += f' label="{e.alias}"'
        lines.append(f'  "{e.parent}" -> "{e.child}" [{attrs}];')

    lines.append("}")

    return "\n".join(lines)


def format_mermaid(graph: DependencyGraph, hide_libraries: bool = True) -> str:
    """Format graph as a Mermaid flowchart (same nodes, edges and styling as DOT)."""
    nodes, edges = _diagram_model(graph, hide_libraries)
    ids = {n.name: f"n{i}" for i, n in enumerate(nodes)}

    def quote(text: str) -> str:
        return '"' + text.replace('"', "#quot;") + '"'

    lines = ["flowchart TD"]
    for n in nodes:
        lines.append(f"  {ids[n.name]}[{quote('<br/>'.join(n.lines))}]")
    for e in edges:
        arrow = "-->" if e.enabled else "-.->"
        if e.alias is not None:
            arrow += f"|{quote(e.alias)}|"
        lines.append(f"  {ids[e.parent]} {arrow} {ids[e.child]}")
    lines.append("  classDef enabled fill:#90ee90,stroke:#006400,color:#000")
    lines.append("  classDef disabled fill:#ffe4e1,stroke:#808080,stroke-dasharray:5 5,color:#000")
    for cls, on in (("enabled", True), ("disabled", False)):
        members = ",".join(ids[n.name] for n in nodes if n.enabled is on)
        if members:
            lines.append(f"  class {members} {cls}")
    return "\n".join(lines)


def format_plantuml(graph: DependencyGraph, hide_libraries: bool = True) -> str:
    """Format graph as PlantUML (same nodes, edges and styling as DOT)."""
    nodes, edges = _diagram_model(graph, hide_libraries)
    ids = {n.name: f"n{i}" for i, n in enumerate(nodes)}

    lines = ["@startuml", "skinparam shadowing false"]
    for n in nodes:
        label = "\\n".join(n.lines).replace('"', "'")
        color = "#lightgreen;line:darkgreen" if n.enabled else "#mistyrose;line:grey;line.dashed"
        lines.append(f'rectangle "{label}" as {ids[n.name]} {color}')
    for e in edges:
        arrow = "-->" if e.enabled else "..>"
        text = f" : {e.alias}" if e.alias is not None else ""
        lines.append(f"{ids[e.parent]} {arrow} {ids[e.child]}{text}")
    lines.append("@enduml")
    return "\n".join(lines)


def render_dot(dot: str, image_format: str, dot_bin: str = "dot") -> bytes:
    """Render DOT source to an image ("svg" or "png") with the Graphviz binary.

    Raises:
        RuntimeError: If Graphviz is missing or fails.
    """
    try:
        result = subprocess.run(
            [dot_bin, f"-T{image_format}"], input=dot.encode(), capture_output=True, check=False
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"Graphviz binary not found: {dot_bin}") from e
    if result.returncode != 0:
        raise RuntimeError(f"{dot_bin} failed: {result.stderr.decode(errors='replace')}")
    return result.stdout


def _chart_label_lines(graph: DependencyGraph, name: str, library: bool) -> list[str]:
    """Build the label lines of a chart node: chart name, its versions, and a library marker.

    When a chart pins several versions, the versions with at least one
    occurrence on (the deployed ones) get one line each, followed by the
    remaining versions on one line in parentheses. The label is plain text, not
    HTML-like: SVG output anchors HTML-like text at its start, which breaks
    centering whenever the viewer's font differs from the one Graphviz measured.
    """
    versions = graph.chart_versions(name)
    lines = [name]
    if len(versions) < 2:
        lines.append(", ".join(versions))
    else:
        deployed = {o.version for o in graph.occurrences_of(name).values() if o.enabled is True}
        lines += [v for v in versions if v in deployed]
        others = [v for v in versions if v not in deployed]
        if others:
            lines.append(f"({', '.join(others)})")
    if library:
        lines.append("(library)")
    return lines


def _status_word(enabled: bool) -> str:
    """Convert a status to ``on``/``off``."""
    return "on" if enabled else "off"


def _status_str(enabled: bool | None) -> str:
    """Convert an occurrence status to its text-tree display string."""
    return f"[{_status_word(bool(enabled))}]"
