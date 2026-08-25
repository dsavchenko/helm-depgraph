"""Condition and tag evaluator for Helm chart dependencies."""

from __future__ import annotations

from typing import Any

from helm_analyse.graph import ChartNode, DependencyGraph


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


def evaluate_conditions(graph: DependencyGraph, values: dict[str, Any]) -> None:
    """Evaluate all conditions in the graph against the given values.

    Per Helm spec:
    - Conditions override tags when the condition path exists
    - Tags are evaluated as OR (any tag true = enabled)
    - Charts without conditions or tags default to enabled

    Args:
        graph: The dependency graph to evaluate.
        values: The values dict to evaluate conditions against.
    """
    for node in graph.nodes.values():
        if node.key == graph.root.key:
            node.enabled = True
            continue

        _evaluate_node(node, values)


def _evaluate_node(node: ChartNode, values: dict[str, Any]) -> None:
    """Evaluate a single node's conditions and tags."""
    # Check conditions first (they override tags)
    if node.conditions:
        for condition_path in node.conditions:
            result = _resolve_path(condition_path, values)
            if result is not None:
                node.enabled = bool(result)
                return

    # Fall back to tags
    if node.tags:
        node.enabled = any(_resolve_path(f"tags.{tag}", values) is True for tag in node.tags)
        return

    # Default: enabled
    node.enabled = True
