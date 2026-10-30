"""Condition and tag evaluator for Helm chart dependencies."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from helm_analyse.graph import ChartNode, DependencyGraph

logger = logging.getLogger(__name__)


def _resolve_path(path: str, values: dict[str, Any]) -> Any:
    """Resolve a dot-separated path against values dict.

    Returns:
        The resolved value if it exists, None if path doesn't exist.
    """
    parts = path.split(".")
    current: Any = values

    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None

    return current


def evaluate_conditions(
    graph: DependencyGraph,
    computed_values: dict[str, Any],
) -> None:
    """Evaluate all conditions in the graph against the computed values.

    Per Helm spec:
    - The first condition path holding a boolean decides; it overrides tags
    - Any true tag enables; otherwise any false tag disables; unset tags have no effect
    - Charts without a decisive condition or tag default to enabled
    - Library charts are evaluated like any other chart

    Args:
        graph: The dependency graph to evaluate.
        computed_values: Fully merged values from ``helm install --dry-run --debug``.
    """

    for path, node in graph.nodes.items():
        if node.key == graph.root.key:
            node.enabled = True
            continue

        # Compute the values prefix: the node's namespace in root values.
        # For path "root/wms/diracx/dex", prefix is "wms.diracx"
        # so condition "dex.enabled" resolves to "wms.diracx.dex.enabled".
        parts = path.split("/")
        prefix = ".".join(parts[1:-1])  # exclude root and self
        _evaluate_node(node, computed_values, prefix)

    _propagate_disabled(graph)


def _propagate_disabled(graph: DependencyGraph) -> None:
    """Propagate disabled state to descendants.

    If a node is disabled, all its descendants are also disabled unless
    they are reachable through at least one alternative path where every
    ancestor is enabled.
    """
    # Map chart key → all flat paths where it appears
    chart_paths: dict[str, list[str]] = defaultdict(list)
    for path, node in graph.nodes.items():
        chart_paths[node.key].append(path)

    for path, node in list(graph.nodes.items()):
        if node.enabled is not False:
            continue

        prefix = path + "/"
        for desc_path, desc_node in list(graph.nodes.items()):
            if not desc_path.startswith(prefix):
                continue

            # Check if same chart appears on another fully-enabled path
            other_paths = [p for p in chart_paths[desc_node.key] if p != desc_path]
            has_enabled_path = any(_is_path_enabled(graph, p) for p in other_paths)
            if not has_enabled_path:
                desc_node.enabled = False


def _is_path_enabled(graph: DependencyGraph, path: str) -> bool:
    """True if the node at path is enabled and every ancestor is enabled."""
    node = graph.nodes.get(path)
    return node is not None and node.enabled is True and _all_ancestors_enabled(graph, path)


def _all_ancestors_enabled(graph: DependencyGraph, path: str) -> bool:
    """Check that every ancestor node on a flat path is enabled."""
    parts = path.split("/")
    for i in range(1, len(parts)):
        ancestor_path = "/".join(parts[:i])
        ancestor = graph.nodes.get(ancestor_path)
        if ancestor is None or ancestor.enabled is not True:
            return False
    return True


def effective_enabled(graph: DependencyGraph, chart_key: str) -> bool | None:
    """Return the effective enabled state for a chart across all its paths.

    A chart that appears at multiple paths (diamond dependencies) is considered
    enabled if *any* of its paths has ``enabled=True``.

    Returns:
        True if any path is enabled, False if all paths are disabled,
        None if no paths found or all are None.
    """
    best: bool | None = None
    for node in graph.nodes.values():
        if node.key != chart_key:
            continue
        if node.enabled is True:
            return True
        if node.enabled is False and best is None:
            best = False
    return best


def _evaluate_node(node: ChartNode, values: dict[str, Any], prefix: str = "") -> None:
    """Evaluate a single node's conditions and tags.

    Args:
        node: The chart node to evaluate.
        values: The root values dict.
        prefix: Dot-separated prefix for the node's values namespace
                (e.g., "wms.diracx" for a chart at root/wms/diracx/dex).
    """
    # Check conditions first (they override tags). Per Helm, the first path
    # holding a boolean decides; missing or non-boolean paths are skipped.
    if node.conditions:
        for condition_path in node.conditions:
            full_path = f"{prefix}.{condition_path}" if prefix else condition_path
            result = _resolve_path(full_path, values)
            if isinstance(result, bool):
                node.enabled = result
                return
            if result is not None:
                logger.warning(
                    "Condition path '%s' for chart %s returned non-bool value",
                    condition_path,
                    node.name,
                )

    # Fall back to tags: any true tag enables; otherwise any false tag disables;
    # tags that are unset (or non-boolean) have no effect.
    tag_values = [_resolve_path(f"tags.{tag}", values) for tag in node.tags]
    if any(v is True for v in tag_values):
        node.enabled = True
        return
    if any(v is False for v in tag_values):
        node.enabled = False
        return

    # Default: enabled
    node.enabled = True
