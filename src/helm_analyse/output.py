"""Output formatters for dependency graphs."""

from __future__ import annotations

import json
from typing import Any

from helm_analyse.conditions import chart_status
from helm_analyse.graph import DependencyGraph, Occurrence


def _is_library(node: Occurrence) -> bool:
    """Check if a node is a library chart."""
    return node.chart_type == "library"


def _filter_libraries(nodes: dict[str, Occurrence]) -> dict[str, Occurrence]:
    """Filter out library charts from a nodes dict."""
    return {path: node for path, node in nodes.items() if not _is_library(node)}


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
    visible = _filter_libraries(graph.occurrences) if hide_libraries else graph.occurrences
    chart_names = {node.name for node in visible.values()}
    on_count = sum(1 for name in chart_names if chart_status(graph, name) is True)
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
    visible = _filter_libraries(graph.occurrences) if hide_libraries else graph.occurrences

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
            "status": _status_word(node.enabled),
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
    """Format graph as Graphviz DOT.

    Args:
        graph: The dependency graph.
        hide_libraries: If True, exclude library charts from output.
        ranksep: Vertical space between ranks (layers). None to omit.
        nodesep: Horizontal space between nodes in the same rank. None to omit.

    Returns:
        DOT string.
    """
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

    seen: set[str] = set()

    def _add_node(node: Occurrence) -> None:
        if hide_libraries and _is_library(node):
            return
        if node.name in seen:
            return
        seen.add(node.name)

        eff = chart_status(graph, node.name)

        label = f"{node.name}\\n{node.version}"
        if node.alias:
            label += f"\\n(alias: {node.alias})"
        if _is_library(node):
            label += "\\n(library)"

        if eff is True:
            fill = "lightgreen"
            style = "filled"
            border = "darkgreen"
        elif eff is False:
            fill = "mistyrose"
            style = "filled,dashed"
            border = "grey"
        else:
            fill = "lightgrey"
            style = "filled,dotted"
            border = "grey"

        lines.append(
            f'  "{node.name}" [label="{label}" fillcolor={fill} style="{style}" color={border}];'
        )

        for child in node.children.values():
            if hide_libraries and _is_library(child):
                continue
            _add_node(child)
            edge_style = "solid" if child.enabled is not False else "dashed"
            lines.append(f'  "{node.name}" -> "{child.name}" [style="{edge_style}"];')

    _add_node(graph.root)
    lines.append("}")

    return "\n".join(lines)


def _status_word(enabled: bool | None) -> str:
    """Convert a status to ``on``/``off``."""
    if enabled is None:
        raise ValueError("Graph has not been evaluated: occurrence status is unset")
    return "on" if enabled else "off"


def _status_str(enabled: bool | None) -> str:
    """Convert a status to its text-tree display string."""
    return f"[{_status_word(enabled)}]"
