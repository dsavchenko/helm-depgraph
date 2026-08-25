"""Output formatters for dependency graphs."""

from __future__ import annotations

import json
from typing import Any

from helm_analyse.graph import ChartNode, DependencyGraph
from helm_analyse.manifest import ResourceMapping


def format_text(graph: DependencyGraph, show_duplicates: bool = False) -> str:
    """Format graph as a human-readable text tree.

    Args:
        graph: The dependency graph.
        show_duplicates: If False, deduplicate nodes by name.

    Returns:
        Formatted text string.
    """
    lines: list[str] = []
    seen: set[str] = set()

    def _walk(node: ChartNode, prefix: str = "", is_last: bool = True) -> None:
        connector = "└── " if is_last else "├── "
        status = _status_str(node.enabled)
        alias_str = f" (alias: {node.alias})" if node.alias else ""
        lines.append(f"{prefix}{connector}{node.name}-{node.version}{alias_str} {status}")

        if not show_duplicates and node.name in seen:
            lines.append(f"{prefix}{'    ' if is_last else '│   '}[deduplicated]")
            return
        seen.add(node.name)

        children = list(node.children.values())
        child_prefix = prefix + ("    " if is_last else "│   ")
        for i, child in enumerate(children):
            _walk(child, child_prefix, i == len(children) - 1)

    # Root node
    lines.append(f"{graph.root.name}-{graph.root.version} (root)")
    seen.add(graph.root.name)

    children = list(graph.root.children.values())
    for i, child in enumerate(children):
        _walk(child, "", i == len(children) - 1)

    return "\n".join(lines)


def format_json(graph: DependencyGraph) -> str:
    """Format graph as JSON.

    Args:
        graph: The dependency graph.

    Returns:
        JSON string.
    """

    def _node_to_dict(node: ChartNode) -> dict[str, Any]:
        return {
            "name": node.name,
            "version": node.version,
            "alias": node.alias,
            "repository": node.repository,
            "conditions": node.conditions,
            "tags": node.tags,
            "enabled": node.enabled,
            "children": {k: _node_to_dict(v) for k, v in node.children.items()},
        }

    data = {
        "root": _node_to_dict(graph.root),
        "nodes": {
            path: {
                "name": node.name,
                "version": node.version,
                "alias": node.alias,
                "enabled": node.enabled,
            }
            for path, node in graph.nodes.items()
        },
    }

    return json.dumps(data, indent=2)


def format_dot(graph: DependencyGraph) -> str:
    """Format graph as Graphviz DOT.

    Args:
        graph: The dependency graph.

    Returns:
        DOT string.
    """
    lines = [
        "digraph helm_deps {",
        "  rankdir=TB;",
        "  node [shape=box];",
        "",
    ]

    seen: set[str] = set()

    def _add_node(node: ChartNode) -> None:
        if node.name in seen:
            return
        seen.add(node.name)

        label = f"{node.name}\\n{node.version}"
        if node.alias:
            label += f"\\n(alias: {node.alias})"

        color = "lightgreen" if node.enabled else "lightgrey"
        lines.append(f'  "{node.name}" [label="{label}" fillcolor={color} style=filled];')

        for child in node.children.values():
            _add_node(child)
            lines.append(f'  "{node.name}" -> "{child.name}";')

    _add_node(graph.root)
    lines.append("}")

    return "\n".join(lines)


def format_manifest_text(
    mappings: list[ResourceMapping],
    graph: DependencyGraph,
) -> str:
    """Format manifest analysis as human-readable text.

    Args:
        mappings: Resource mappings from manifest analysis.
        graph: The dependency graph.

    Returns:
        Formatted text string.
    """
    lines: list[str] = ["Manifest Analysis", "=" * 40, ""]

    # Group by chart
    by_chart: dict[str | None, list[ResourceMapping]] = {}
    for mapping in mappings:
        chart = mapping.chart_node_name or "unknown"
        by_chart.setdefault(chart, []).append(mapping)

    for chart_name, chart_mappings in sorted(by_chart.items()):
        # Find node status
        status = "unknown"
        for node in graph.nodes.values():
            if node.name == chart_name:
                status = _status_str(node.enabled)
                break

        lines.append(f"Chart: {chart_name} {status}")
        lines.append("-" * 40)

        for m in chart_mappings:
            ns_str = f" (ns: {m.namespace})" if m.namespace else ""
            lines.append(f"  {m.kind}/{m.name}{ns_str}")

        lines.append("")

    return "\n".join(lines)


def _status_str(enabled: bool | None) -> str:
    """Convert enabled status to display string."""
    if enabled is True:
        return "[active]"
    elif enabled is False:
        return "[inactive]"
    else:
        return "[unknown]"
