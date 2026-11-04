"""Output formatters for dependency graphs."""

from __future__ import annotations

import html
import json
from typing import Any

from helm_analyse.conditions import chart_status
from helm_analyse.graph import DependencyGraph, Occurrence


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
    _require_evaluated(graph)
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

    visible = _visible_occurrences(graph, hide_libraries)

    # Nodes: one per chart, in order of first appearance
    charts: dict[str, Occurrence] = {}
    for node in visible.values():
        charts.setdefault(node.name, node)
    for name, node in charts.items():
        label = _chart_label(graph, name, library=_is_library(node))
        if chart_status(graph, name):
            fill, style, border = "lightgreen", "filled", "darkgreen"
        else:
            fill, style, border = "mistyrose", "filled,dashed", "grey"
        lines.append(f'  "{name}" [label={label} fillcolor={fill} style="{style}" color={border}];')

    # Edges: (parent chart, alias, child chart) -> statuses of the occurrences it covers
    edges: dict[tuple[str, str, str], list[bool]] = {}
    for path, node in visible.items():
        if node is graph.root:
            continue
        parent = graph.occurrences[path.rsplit("/", 1)[0]]
        key = (parent.name, node.scope_key, node.name)
        edges.setdefault(key, []).append(bool(node.enabled))
    for (parent_name, scope_key, child_name), statuses in edges.items():
        attrs = f'style="{"solid" if any(statuses) else "dashed"}"'
        if scope_key != child_name:
            attrs += f' label="{scope_key}"'
        lines.append(f'  "{parent_name}" -> "{child_name}" [{attrs}];')

    lines.append("}")

    return "\n".join(lines)


def _chart_label(graph: DependencyGraph, name: str, library: bool) -> str:
    """Build a DOT node label: chart name, its versions, and a library marker.

    When a chart pins several versions, the label is HTML-like and the versions
    with at least one occurrence on (the deployed ones) are bold.
    """
    versions = graph.chart_versions(name)
    if len(versions) < 2:
        label = f"{name}\\n{', '.join(versions)}"
        if library:
            label += "\\n(library)"
        return f'"{label}"'

    deployed = {o.version for o in graph.occurrences_of(name).values() if o.enabled is True}
    shown = ", ".join(
        f"<b>{html.escape(v)}</b>" if v in deployed else html.escape(v) for v in versions
    )
    label = f"{html.escape(name)}<br/>{shown}"
    if library:
        label += "<br/>(library)"
    return f"<{label}>"


def _status_word(enabled: bool) -> str:
    """Convert a status to ``on``/``off``."""
    return "on" if enabled else "off"


def _status_str(enabled: bool | None) -> str:
    """Convert an occurrence status to its text-tree display string."""
    return f"[{_status_word(bool(enabled))}]"
