"""Tests for manifest analyzer."""

from helm_analyse.graph import ChartNode, DependencyGraph
from helm_analyse.manifest import (
    _extract_chart_from_source,
    _match_resource_to_node,
    _parse_source_comment,
    analyse_manifest,
)


class TestParseSourceComment:
    """Tests for _parse_source_comment."""

    def test_valid_source(self) -> None:
        assert (
            _parse_source_comment("# Source: mychart/templates/deploy.yaml")
            == "mychart/templates/deploy.yaml"
        )

    def test_with_spaces(self) -> None:
        assert (
            _parse_source_comment("#  Source:  mychart/templates/deploy.yaml")
            == "mychart/templates/deploy.yaml"
        )

    def test_no_source(self) -> None:
        assert _parse_source_comment("apiVersion: v1") is None

    def test_empty(self) -> None:
        assert _parse_source_comment("") is None


class TestExtractChartFromSource:
    """Tests for _extract_chart_from_source."""

    def test_root_chart(self) -> None:
        assert _extract_chart_from_source("mychart/templates/deploy.yaml") == "mychart"

    def test_subchart(self) -> None:
        assert _extract_chart_from_source("mychart/charts/sub/templates/deploy.yaml") == "sub"

    def test_nested_subchart(self) -> None:
        assert (
            _extract_chart_from_source("mychart/charts/sub/charts/leaf/templates/deploy.yaml")
            == "leaf"
        )

    def test_empty(self) -> None:
        assert _extract_chart_from_source("") is None


class TestMatchResourceToNode:
    """Tests for _match_resource_to_node."""

    def _make_graph(self) -> DependencyGraph:
        root = ChartNode(name="mychart", version="1.0.0")
        sub = ChartNode(name="sub1", version="0.1.0")
        root.children["sub1"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()
        return graph

    def test_match_by_chart_label(self) -> None:
        graph = self._make_graph()
        path, name = _match_resource_to_node("sub1-0.1.0", None, graph)
        assert path == "mychart/sub1"
        assert name == "sub1"

    def test_match_by_source(self) -> None:
        graph = self._make_graph()
        path, name = _match_resource_to_node(
            None, "mychart/charts/sub1/templates/deploy.yaml", graph
        )
        assert path == "mychart/sub1"
        assert name == "sub1"

    def test_no_match(self) -> None:
        graph = self._make_graph()
        path, name = _match_resource_to_node("unknown-1.0.0", None, graph)
        assert path is None
        assert name is None

    def test_match_by_alias(self) -> None:
        root = ChartNode(name="mychart", version="1.0.0")
        sub = ChartNode(name="sub1", version="0.1.0", alias="custom")
        root.children["custom"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        path, name = _match_resource_to_node("custom-0.1.0", None, graph)
        assert path == "mychart/custom"
        assert name == "sub1"


class TestAnalyseManifest:
    """Tests for analyse_manifest."""

    def _make_graph(self) -> DependencyGraph:
        root = ChartNode(name="mychart", version="1.0.0", enabled=True)
        sub = ChartNode(name="sub1", version="0.1.0", enabled=False)
        root.children["sub1"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()
        return graph

    def test_basic_manifest(self) -> None:
        graph = self._make_graph()
        manifest = """
# Source: mychart/templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-config
  labels:
    helm.sh/chart: mychart-1.0.0
---
# Source: mychart/charts/sub1/templates/deploy.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sub-deploy
  labels:
    helm.sh/chart: sub1-0.1.0
"""
        mappings = analyse_manifest(manifest, graph)

        assert len(mappings) == 2

        # Root chart resource
        root_mapping = next(m for m in mappings if m.name == "my-config")
        assert root_mapping.kind == "ConfigMap"
        assert root_mapping.chart_node_name == "mychart"
        assert root_mapping.is_active is True

        # Subchart resource
        sub_mapping = next(m for m in mappings if m.name == "sub-deploy")
        assert sub_mapping.kind == "Deployment"
        assert sub_mapping.chart_node_name == "sub1"
        assert sub_mapping.is_active is False

    def test_empty_manifest(self) -> None:
        graph = self._make_graph()
        mappings = analyse_manifest("", graph)
        assert len(mappings) == 0

    def test_unknown_chart(self) -> None:
        graph = self._make_graph()
        manifest = """
apiVersion: v1
kind: ConfigMap
metadata:
  name: unknown
  labels:
    helm.sh/chart: unknown-1.0.0
"""
        mappings = analyse_manifest(manifest, graph)
        assert len(mappings) == 1
        assert mappings[0].chart_node_name is None
        assert mappings[0].is_active is None
