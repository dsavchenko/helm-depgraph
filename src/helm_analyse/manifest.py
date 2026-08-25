"""Manifest parser and resource-to-node mapper."""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

from helm_analyse.graph import DependencyGraph


@dataclass
class ResourceMapping:
    """A mapping of a manifest resource to a graph node."""

    kind: str
    name: str
    namespace: str | None
    chart_label: str | None
    source_comment: str | None
    chart_node_path: str | None
    chart_node_name: str | None
    is_active: bool | None


def _parse_source_comment(line: str) -> str | None:
    """Extract chart path from '# Source:' comment."""
    match = re.match(r"^#\s*Source:\s*(.+)$", line.strip())
    if match:
        return match.group(1).strip()
    return None


def _extract_chart_from_source(source: str) -> str | None:
    """Extract chart name from source path.

    Examples:
        - "mychart/templates/deploy.yaml" -> "mychart"
        - "mychart/charts/sub/templates/deploy.yaml" -> "sub"
        - "mychart/charts/sub/charts/leaf/templates/deploy.yaml" -> "leaf"
    """
    if not source:
        return None

    parts = source.split("/")
    result: str | None = None
    for i, part in enumerate(parts):
        if part == "charts" and i + 1 < len(parts):
            result = parts[i + 1]
    # Return the last chart found, or the first part if no charts/ in path
    return result or parts[0]


def _match_resource_to_node(
    chart_label: str | None,
    source_comment: str | None,
    graph: DependencyGraph,
) -> tuple[str | None, str | None]:
    """Match a resource to a graph node using chart label and source comment.

    Returns:
        Tuple of (node_path, node_name) or (None, None) if no match.
    """
    # Try matching by helm.sh/chart label
    if chart_label:
        # helm.sh/chart format: "NAME-VERSION"
        chart_name = chart_label.rsplit("-", 1)[0] if "-" in chart_label else chart_label
        for path, node in graph.nodes.items():
            if node.name == chart_name or node.alias == chart_name:
                return path, node.name

    # Try matching by source comment
    if source_comment:
        extracted_name = _extract_chart_from_source(source_comment)
        if extracted_name:
            for path, node in graph.nodes.items():
                if node.name == extracted_name or node.alias == extracted_name:
                    return path, node.name

    return None, None


def analyse_manifest(manifest_yaml: str, graph: DependencyGraph) -> list[ResourceMapping]:
    """Analyse a rendered manifest and map resources to graph nodes.

    Args:
        manifest_yaml: The rendered YAML manifest (may contain multiple documents).
        graph: The dependency graph.

    Returns:
        List of ResourceMapping objects.
    """
    mappings: list[ResourceMapping] = []

    # Parse all YAML documents
    docs = list(yaml.safe_load_all(manifest_yaml))

    # Extract source comments for each document
    doc_sources = _extract_doc_sources(manifest_yaml)

    for i, doc in enumerate(docs):
        if not isinstance(doc, dict):
            continue

        metadata = doc.get("metadata", {})
        kind = doc.get("kind", "Unknown")
        name = metadata.get("name", "unknown")
        namespace = metadata.get("namespace")
        labels = metadata.get("labels", {})
        chart_label = labels.get("helm.sh/chart")
        source_comment = doc_sources.get(i)

        node_path, node_name = _match_resource_to_node(chart_label, source_comment, graph)

        # Get active status from matched node
        is_active = None
        if node_path and node_path in graph.nodes:
            is_active = graph.nodes[node_path].enabled

        mappings.append(
            ResourceMapping(
                kind=kind,
                name=name,
                namespace=namespace,
                chart_label=chart_label,
                source_comment=source_comment,
                chart_node_path=node_path,
                chart_node_name=node_name,
                is_active=is_active,
            )
        )

    return mappings


def _extract_doc_sources(manifest_yaml: str) -> dict[int, str]:
    """Extract source comments for each YAML document index."""
    sources: dict[int, str] = {}
    doc_index = 0
    last_source: str | None = None

    for line in manifest_yaml.splitlines():
        if line.strip() == "---":
            if last_source:
                sources[doc_index] = last_source
            doc_index += 1
            last_source = None
        else:
            source = _parse_source_comment(line)
            if source:
                last_source = source

    # Handle last document
    if last_source:
        sources[doc_index] = last_source

    return sources
