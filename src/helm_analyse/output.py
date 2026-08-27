"""Output formatters for dependency graphs."""

from __future__ import annotations

import json
from typing import Any

from helm_analyse.conditions import effective_enabled
from helm_analyse.graph import ChartNode, DependencyGraph
from helm_analyse.manifest import ResourceMapping


def _is_library(node: ChartNode) -> bool:
    """Check if a node is a library chart."""
    return node.chart_type == "library"


def _filter_libraries(nodes: dict[str, ChartNode]) -> dict[str, ChartNode]:
    """Filter out library charts from a nodes dict."""
    return {path: node for path, node in nodes.items() if not _is_library(node)}


def format_text(
    graph: DependencyGraph,
    show_duplicates: bool = False,
    hide_libraries: bool = True,
) -> str:
    """Format graph as a human-readable text tree.

    Children are grouped by enabled status: enabled first, then a blank
    line separator, then disabled/unknown.

    Args:
        graph: The dependency graph.
        show_duplicates: If False, deduplicate nodes by name.
        hide_libraries: If True, exclude library charts from output.

    Returns:
        Formatted text string.
    """
    lines: list[str] = []
    seen: set[str] = set()

    def _walk(node: ChartNode, prefix: str = "", is_last: bool = True) -> None:
        if hide_libraries and _is_library(node):
            return

        eff = effective_enabled(graph, node.key)
        connector = "└── " if is_last else "├── "
        status = _status_str(eff)
        alias_str = f" (alias: {node.alias})" if node.alias else ""
        type_str = " (library)" if _is_library(node) else ""
        lines.append(f"{prefix}{connector}{node.name}-{node.version}{alias_str}{type_str} {status}")

        if not show_duplicates and node.name in seen:
            lines.append(f"{prefix}{'    ' if is_last else '│   '}[deduplicated]")
            return
        seen.add(node.name)

        children = list(node.children.values())
        child_prefix = prefix + ("    " if is_last else "│   ")

        enabled = [c for c in children if effective_enabled(graph, c.key) is True]
        other = [c for c in children if effective_enabled(graph, c.key) is not True]

        for i, child in enumerate(enabled):
            _walk(child, child_prefix, i == len(enabled) - 1 and not other)

        if enabled and other:
            lines.append(f"{child_prefix}{'    ' if not other else '│   '}")

        for i, child in enumerate(other):
            _walk(child, child_prefix, i == len(other) - 1)

    # Root node
    root_status = _status_str(graph.root.enabled)
    root_type = " (library)" if _is_library(graph.root) else ""
    lines.append(f"{graph.root.name}-{graph.root.version} (root){root_type} {root_status}")

    # Summary
    visible_nodes = _filter_libraries(graph.nodes) if hide_libraries else graph.nodes
    seen_keys: set[str] = set()
    enabled_count = 0
    disabled_count = 0
    unknown_count = 0
    for node in visible_nodes.values():
        if node.key in seen_keys:
            continue
        seen_keys.add(node.key)
        eff = effective_enabled(graph, node.key)
        if eff is True:
            enabled_count += 1
        elif eff is False:
            disabled_count += 1
        else:
            unknown_count += 1
    lines.append(f"  {enabled_count} enabled, {disabled_count} disabled, {unknown_count} unknown")
    lines.append("")

    seen.add(graph.root.name)

    children = list(graph.root.children.values())
    for i, child in enumerate(children):
        _walk(child, "", i == len(children) - 1)

    return "\n".join(lines)


def format_json(
    graph: DependencyGraph,
    hide_libraries: bool = True,
) -> str:
    """Format graph as JSON.

    Args:
        graph: The dependency graph.
        hide_libraries: If True, exclude library charts from output.

    Returns:
        JSON string.
    """

    def _node_to_dict(node: ChartNode) -> dict[str, Any]:
        children = {
            k: _node_to_dict(v)
            for k, v in node.children.items()
            if not (hide_libraries and _is_library(v))
        }
        return {
            "name": node.name,
            "version": node.version,
            "alias": node.alias,
            "repository": node.repository,
            "chart_type": node.chart_type,
            "conditions": node.conditions,
            "tags": node.tags,
            "enabled": effective_enabled(graph, node.key),
            "children": children,
        }

    visible_nodes = _filter_libraries(graph.nodes) if hide_libraries else graph.nodes
    # Deduplicate nodes by chart key, using effective enabled state
    seen_keys: set[str] = set()
    nodes_dict: dict[str, dict[str, Any]] = {}
    for path, node in visible_nodes.items():
        if node.key in seen_keys:
            continue
        seen_keys.add(node.key)
        nodes_dict[path] = {
            "name": node.name,
            "version": node.version,
            "alias": node.alias,
            "chart_type": node.chart_type,
            "enabled": effective_enabled(graph, node.key),
        }
    data = {
        "root": _node_to_dict(graph.root),
        "nodes": nodes_dict,
    }

    return json.dumps(data, indent=2)


def format_dot(
    graph: DependencyGraph,
    hide_libraries: bool = True,
    mappings: list[ResourceMapping] | None = None,
) -> str:
    """Format graph as Graphviz DOT.

    Args:
        graph: The dependency graph.
        hide_libraries: If True, exclude library charts from output.
        mappings: Optional manifest analysis results. When provided, uses
            a 4-state color scheme to indicate deployment status.

    Returns:
        DOT string.
    """
    # Build set of chart names that have resources in the manifest
    deployed: set[str] = set()
    if mappings is not None:
        for m in mappings:
            if m.chart_node_name:
                deployed.add(m.chart_node_name)

    lines = [
        "digraph helm_deps {",
        "  rankdir=TB;",
        "  node [shape=box];",
        "",
    ]

    seen: set[str] = set()

    def _add_node(node: ChartNode) -> None:
        if hide_libraries and _is_library(node):
            return
        if node.name in seen:
            return
        seen.add(node.name)

        eff = effective_enabled(graph, node.key)

        label = f"{node.name}\\n{node.version}"
        if node.alias:
            label += f"\\n(alias: {node.alias})"
        if _is_library(node):
            label += "\\n(library)"

        if mappings is not None:
            # 4-state: enabled+deployed, enabled+not deployed, disabled, unknown
            is_deployed = node.name in deployed
            if eff is True and is_deployed:
                fill = "lightgreen"
                style = "filled"
                border = "darkgreen"
            elif eff is True and not is_deployed:
                fill = "moccasin"
                style = "filled,dashed"
                border = "darkorange"
            elif eff is False:
                fill = "lightsalmon"
                style = "filled,dashed"
                border = "orangered"
            else:
                fill = "lightgrey"
                style = "filled,dotted"
                border = "grey"
        else:
            # 3-state: enabled, disabled, unknown
            if eff is True:
                fill = "lightgreen"
                style = "filled"
                border = "darkgreen"
            elif eff is False:
                fill = "lightsalmon"
                style = "filled,dashed"
                border = "orangered"
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
            child_eff = effective_enabled(graph, child.key)
            edge_style = "solid" if child_eff is not False else "dashed"
            lines.append(f'  "{node.name}" -> "{child.name}" [style="{edge_style}"];')

    _add_node(graph.root)
    lines.append("}")

    return "\n".join(lines)


def format_manifest_text(
    mappings: list[ResourceMapping],
    graph: DependencyGraph,
    hide_libraries: bool = True,
) -> str:
    """Format manifest analysis as human-readable text.

    Groups resources by chart, then sections charts by enabled status
    with blank line separators.

    Args:
        mappings: Resource mappings from manifest analysis.
        graph: The dependency graph.
        hide_libraries: If True, exclude library charts from output.

    Returns:
        Formatted text string.
    """
    lines: list[str] = ["Manifest Analysis", "=" * 40, ""]

    # Build a set of library chart names to skip
    library_names: set[str] = set()
    if hide_libraries:
        for node in graph.nodes.values():
            if _is_library(node):
                library_names.add(node.name)

    # Group by chart
    by_chart: dict[str, list[ResourceMapping]] = {}
    unmapped: list[ResourceMapping] = []
    for mapping in mappings:
        if mapping.chart_node_name:
            if hide_libraries and mapping.chart_node_name in library_names:
                continue
            by_chart.setdefault(mapping.chart_node_name, []).append(mapping)
        else:
            unmapped.append(mapping)

    # Resolve chart statuses using effective_enabled
    chart_status: dict[str, bool | None] = {}
    for chart_name in by_chart:
        chart_status[chart_name] = effective_enabled(graph, chart_name)

    def _render_chart_section(chart_name: str) -> None:
        status = _status_str(chart_status.get(chart_name))
        lines.append(f"Chart: {chart_name} {status}")
        lines.append("-" * 40)
        for m in by_chart[chart_name]:
            ns_str = f" (ns: {m.namespace})" if m.namespace else ""
            lines.append(f"  {m.kind}/{m.name}{ns_str}")
        lines.append("")

    enabled_charts = [c for c, s in chart_status.items() if s is True]
    disabled_charts = [c for c, s in chart_status.items() if s is False]
    unknown_charts = [c for c, s in chart_status.items() if s is None]

    if enabled_charts:
        lines.append("Enabled charts:")
        lines.append("-" * 40)
        for chart_name in sorted(enabled_charts):
            _render_chart_section(chart_name)

    if disabled_charts:
        lines.append("Disabled charts:")
        lines.append("-" * 40)
        for chart_name in sorted(disabled_charts):
            _render_chart_section(chart_name)

    if unknown_charts:
        lines.append("Unknown charts:")
        lines.append("-" * 40)
        for chart_name in sorted(unknown_charts):
            _render_chart_section(chart_name)

    if unmapped:
        lines.append("Unmapped resources:")
        lines.append("-" * 40)
        for m in unmapped:
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
