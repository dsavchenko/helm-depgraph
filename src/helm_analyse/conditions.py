"""Condition and tag evaluator for Helm chart dependencies."""

from __future__ import annotations

import logging
from typing import Any

from helm_analyse.graph import DependencyGraph, Occurrence

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

    for path, node in graph.occurrences.items():
        if node is graph.root:
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
    """Disable every occurrence whose parent occurrence is disabled.

    Each occurrence renders independently (ADR 0001): a chart that is on
    elsewhere in the tree does not keep an occurrence under a disabled parent on.
    Relies on ``graph.occurrences`` being in pre-order (parents before children).
    """
    for path, node in graph.occurrences.items():
        if "/" not in path:
            continue
        parent = graph.occurrences[path.rsplit("/", 1)[0]]
        if parent.enabled is False:
            node.enabled = False


def chart_status(graph: DependencyGraph, chart_name: str) -> bool | None:
    """Return the chart status: on if any of the chart's occurrences is on.

    Returns:
        True if any occurrence is enabled, False if all evaluated occurrences
        are disabled, None if the chart has no evaluated occurrences.
    """
    statuses = [o.enabled for o in graph.occurrences_of(chart_name).values()]
    if True in statuses:
        return True
    if False in statuses:
        return False
    return None


def _evaluate_node(node: Occurrence, values: dict[str, Any], prefix: str = "") -> None:
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
