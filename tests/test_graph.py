"""Tests for graph model."""

from pathlib import Path

from helm_analyse.graph import ChartNode, DependencyGraph, _parse_dependency


class TestChartNode:
    """Tests for ChartNode."""

    def test_key_without_alias(self) -> None:
        node = ChartNode(name="mychart", version="1.0.0")
        assert node.key == "mychart"

    def test_key_with_alias(self) -> None:
        node = ChartNode(name="mychart", version="1.0.0", alias="custom")
        assert node.key == "custom"


class TestDependencyGraph:
    """Tests for DependencyGraph flatten."""

    def test_flatten_simple(self) -> None:
        root = ChartNode(name="root", version="1.0.0")
        child = ChartNode(name="sub", version="0.1.0")
        root.children["sub"] = child

        graph = DependencyGraph(root=root)
        graph.flatten()

        assert "root" in graph.nodes
        assert "root/sub" in graph.nodes
        assert len(graph.nodes) == 2

    def test_flatten_nested(self) -> None:
        root = ChartNode(name="root", version="1.0.0")
        sub = ChartNode(name="sub", version="0.1.0")
        leaf = ChartNode(name="leaf", version="0.0.1")
        sub.children["leaf"] = leaf
        root.children["sub"] = sub

        graph = DependencyGraph(root=root)
        graph.flatten()

        assert "root" in graph.nodes
        assert "root/sub" in graph.nodes
        assert "root/sub/leaf" in graph.nodes
        assert len(graph.nodes) == 3

    def test_flatten_with_alias(self) -> None:
        root = ChartNode(name="root", version="1.0.0")
        sub = ChartNode(name="sub", version="0.1.0", alias="custom")
        root.children["custom"] = sub

        graph = DependencyGraph(root=root)
        graph.flatten()

        assert "root/custom" in graph.nodes


class TestParseDependency:
    """Tests for _parse_dependency."""

    def test_simple_dependency(self) -> None:
        dep = {"name": "nginx", "version": "1.0.0", "repository": "https://example.com"}
        node = _parse_dependency(dep)
        assert node.name == "nginx"
        assert node.version == "1.0.0"
        assert node.repository == "https://example.com"

    def test_dependency_with_condition(self) -> None:
        dep = {
            "name": "sub",
            "version": "0.1.0",
            "condition": "sub.enabled",
        }
        node = _parse_dependency(dep)
        assert node.conditions == ["sub.enabled"]

    def test_dependency_with_multiple_conditions(self) -> None:
        dep = {
            "name": "sub",
            "version": "0.1.0",
            "condition": "sub.enabled,global.sub.enabled",
        }
        node = _parse_dependency(dep)
        assert node.conditions == ["sub.enabled", "global.sub.enabled"]

    def test_dependency_with_alias(self) -> None:
        dep = {
            "name": "sub",
            "version": "0.1.0",
            "alias": "custom",
        }
        node = _parse_dependency(dep)
        assert node.alias == "custom"
        assert node.key == "custom"

    def test_dependency_with_tags(self) -> None:
        dep = {
            "name": "sub",
            "version": "0.1.0",
            "tags": ["frontend", "web"],
        }
        node = _parse_dependency(dep)
        assert node.tags == ["frontend", "web"]


class TestBuildGraph:
    """Tests for build_graph with local chart directories."""

    def test_build_graph_local(self, tmp_path: Path) -> None:
        """Test building graph from local chart directory structure."""
        # Create root chart
        root_chart = tmp_path / "mychart"
        root_chart.mkdir()
        (root_chart / "Chart.yaml").write_text(
            """
apiVersion: v2
name: mychart
version: 0.1.0
dependencies:
  - name: sub1
    version: 1.0.0
    condition: sub1.enabled
  - name: sub2
    version: 2.0.0
    tags:
      - backend
"""
        )

        # Create sub1 chart
        sub1_dir = root_chart / "charts" / "sub1"
        sub1_dir.mkdir(parents=True)
        (sub1_dir / "Chart.yaml").write_text(
            """
apiVersion: v2
name: sub1
version: 1.0.0
"""
        )

        # Create sub2 chart
        sub2_dir = root_chart / "charts" / "sub2"
        sub2_dir.mkdir(parents=True)
        (sub2_dir / "Chart.yaml").write_text(
            """
apiVersion: v2
name: sub2
version: 2.0.0
"""
        )

        from helm_analyse.graph import build_graph

        graph = build_graph(root_chart, use_helm_build=False)

        assert graph.root.name == "mychart"
        assert len(graph.nodes) == 3
        assert "mychart" in graph.nodes
        assert "mychart/sub1" in graph.nodes
        assert "mychart/sub2" in graph.nodes

        sub1_node = graph.nodes["mychart/sub1"]
        assert sub1_node.conditions == ["sub1.enabled"]

        sub2_node = graph.nodes["mychart/sub2"]
        assert sub2_node.tags == ["backend"]
