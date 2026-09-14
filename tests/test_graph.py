"""Tests for graph model."""

import tarfile
from pathlib import Path

from helm_analyse.graph import (
    ChartNode,
    DependencyGraph,
    _parse_computed_values,
    _parse_dependency,
)


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

    def test_dependency_with_type(self) -> None:
        dep = {
            "name": "common",
            "version": "1.0.0",
            "type": "library",
        }
        node = _parse_dependency(dep)
        assert node.chart_type == "library"


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

    def test_build_graph_with_library_chart(self, tmp_path: Path) -> None:
        """Test building graph with a library chart."""
        root_chart = tmp_path / "mychart"
        root_chart.mkdir()
        (root_chart / "Chart.yaml").write_text(
            """
apiVersion: v2
name: mychart
version: 0.1.0
dependencies:
  - name: common
    version: 1.0.0
  - name: sub1
    version: 1.0.0
    condition: sub1.enabled
"""
        )

        # Create common library chart
        common_dir = root_chart / "charts" / "common"
        common_dir.mkdir(parents=True)
        (common_dir / "Chart.yaml").write_text(
            """
apiVersion: v2
name: common
version: 1.0.0
type: library
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

        from helm_analyse.graph import build_graph

        graph = build_graph(root_chart, use_helm_build=False)

        assert graph.root.name == "mychart"
        assert len(graph.nodes) == 3

        common_node = graph.nodes["mychart/common"]
        assert common_node.chart_type == "library"

        sub1_node = graph.nodes["mychart/sub1"]
        assert sub1_node.chart_type is None

    def test_build_graph_from_archived_dependencies(self, tmp_path: Path) -> None:
        """Graph is built from .tgz archives only (like after `helm dependency build`).

        The original chart directory must not be modified: no unpacked
        directories may appear next to the .tgz files.
        """
        # Root chart whose charts/ dir contains only archived dependencies.
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
"""
        )
        charts_dir = root_chart / "charts"
        charts_dir.mkdir()

        # Stage sub1 with a nested dependency (sub2) and archive it.
        stage = tmp_path / "stage"
        sub1_dir = stage / "sub1"
        sub2_dir = sub1_dir / "charts" / "sub2"
        sub2_dir.mkdir(parents=True)
        (sub1_dir / "Chart.yaml").write_text(
            """
apiVersion: v2
name: sub1
version: 1.0.0
dependencies:
  - name: sub2
    version: 0.2.0
"""
        )
        (sub2_dir / "Chart.yaml").write_text(
            """
apiVersion: v2
name: sub2
version: 0.2.0
"""
        )

        tgz_path = charts_dir / "sub1-1.0.0.tgz"
        with tarfile.open(tgz_path, "w:gz") as tf:
            tf.add(sub1_dir, arcname="sub1")

        from helm_analyse.graph import build_graph

        graph = build_graph(root_chart, use_helm_build=False)

        assert graph.root.name == "mychart"
        assert "mychart/sub1" in graph.nodes
        assert "mychart/sub1/sub2" in graph.nodes
        assert graph.nodes["mychart/sub1"].conditions == ["sub1.enabled"]

        # The original chart path must be left untouched (only the .tgz remains).
        assert sorted(p.name for p in charts_dir.iterdir()) == ["sub1-1.0.0.tgz"]

    def test_build_graph_from_archived_dependency_chain(self, tmp_path: Path) -> None:
        """Nested archives (subchart whose own charts/ is archived) are resolved."""
        root_chart = tmp_path / "mychart"
        root_chart.mkdir()
        (root_chart / "Chart.yaml").write_text(
            """
apiVersion: v2
name: mychart
version: 0.1.0
dependencies:
  - name: parent
    version: 1.0.0
"""
        )
        charts_dir = root_chart / "charts"
        charts_dir.mkdir()

        # parent's charts/ also only contains a .tgz archive.
        stage = tmp_path / "stage"
        parent_dir = stage / "parent"
        parent_dir.mkdir(parents=True)
        (parent_dir / "Chart.yaml").write_text(
            """
apiVersion: v2
name: parent
version: 1.0.0
dependencies:
  - name: leaf
    version: 0.1.0
"""
        )
        parent_charts = parent_dir / "charts"
        parent_charts.mkdir()
        leaf_dir = stage / "leaf"
        leaf_dir.mkdir()
        (leaf_dir / "Chart.yaml").write_text(
            """
apiVersion: v2
name: leaf
version: 0.1.0
"""
        )
        with tarfile.open(parent_charts / "leaf-0.1.0.tgz", "w:gz") as tf:
            tf.add(leaf_dir, arcname="leaf")

        # parent itself is archived alongside its (already archived) charts/.
        with tarfile.open(charts_dir / "parent-1.0.0.tgz", "w:gz") as tf:
            tf.add(parent_dir, arcname="parent")

        from helm_analyse.graph import build_graph

        graph = build_graph(root_chart, use_helm_build=False)

        assert "mychart/parent" in graph.nodes
        assert "mychart/parent/leaf" in graph.nodes

        # Original chart path untouched — no unpacked dirs next to the archives.
        assert sorted(p.name for p in charts_dir.iterdir()) == ["parent-1.0.0.tgz"]


class TestParseComputedValues:
    """Tests for _parse_computed_values function."""

    def test_parses_standard_output(self) -> None:
        output = (
            "NAME: test\n"
            "NAMESPACE: default\n"
            "COMPUTED VALUES:\n"
            "key1: value1\n"
            "subchart:\n"
            "  enabled: true\n"
            "\n"
            "HOOKS:\n"
            "---\n"
            "# Source: test/templates/foo.yaml\n"
        )
        result = _parse_computed_values(output)
        assert result == {"key1": "value1", "subchart": {"enabled": True}}

    def test_empty_values_section(self) -> None:
        output = "NAME: test\nCOMPUTED VALUES:\n{}\n\nHOOKS:\n"
        result = _parse_computed_values(output)
        assert result == {}

    def test_null_values_section(self) -> None:
        output = "NAME: test\nCOMPUTED VALUES:\nnull\n\nHOOKS:\n"
        result = _parse_computed_values(output)
        assert result == {}

    def test_missing_computed_values(self) -> None:
        output = "NAME: test\nHOOKS:\n"
        result = _parse_computed_values(output)
        assert result == {}

    def test_manifest_without_hooks_section(self) -> None:
        output = "NAME: test\nCOMPUTED VALUES:\na: 1\n\nMANIFEST:\n---\n"
        result = _parse_computed_values(output)
        assert result == {"a": 1}

    def test_real_helm_output(self) -> None:
        """Test with actual helm install --dry-run --debug output."""
        output = (
            "NAME: test\n"
            "LAST DEPLOYED: Wed Aug 26 18:31:19 2026\n"
            "NAMESPACE: default\n"
            "STATUS: pending-install\n"
            "REVISION: 1\n"
            "DESCRIPTION: Dry run complete\n"
            "TEST SUITE: None\n"
            "USER-SUPPLIED VALUES:\n"
            "{}\n"
            "\n"
            "COMPUTED VALUES:\n"
            "global:\n"
            "  env: test\n"
            "parent-a:\n"
            "  shared:\n"
            "    enabled: true\n"
            "  global:\n"
            "    env: test\n"
            "parent-b:\n"
            "  shared:\n"
            "    enabled: false\n"
            "  global:\n"
            "    env: test\n"
            "\n"
            "HOOKS:\n"
            "---\n"
            "# Source: test/templates/foo.yaml\n"
        )
        result = _parse_computed_values(output)
        assert result["global"] == {"env": "test"}
        assert result["parent-a"]["shared"]["enabled"] is True
        assert result["parent-b"]["shared"]["enabled"] is False

    def test_empty_string(self) -> None:
        assert _parse_computed_values("") == {}


class TestGetComputedValues:
    """Integration tests for get_computed_values with real chart."""

    FIXTURE = Path(__file__).parent / "fixtures" / "charts" / "test-values-analysis"

    def test_returns_computed_values(self) -> None:
        from helm_analyse.graph import get_computed_values

        result = get_computed_values(self.FIXTURE)
        assert isinstance(result, dict)
        assert "global" in result
        assert result["global"]["env"] == "test"

    def test_shared_enabled_via_parent_a(self) -> None:
        """parent-a enables shared (shared.enabled: true) in its values."""
        from helm_analyse.graph import get_computed_values

        result = get_computed_values(self.FIXTURE)
        # parent-a's values override shared's default (false)
        assert result["parent-a"]["shared"]["enabled"] is True

    def test_child_enabled_via_grandparent(self) -> None:
        """grandparent sets parent-c.child.enabled: true, overriding parent-c default."""
        from helm_analyse.graph import get_computed_values

        result = get_computed_values(self.FIXTURE)
        assert result["grandparent"]["parent-c"]["child"]["enabled"] is True

    def test_deep_nesting_preserves_values(self) -> None:
        """level1 → level2 → level3 → level4 condition chain is preserved."""
        from helm_analyse.graph import get_computed_values

        result = get_computed_values(self.FIXTURE)
        assert result["level1"]["level2"]["enabled"] is True
        assert result["level1"]["level2"]["level3"]["enabled"] is True
        assert result["level1"]["level2"]["level3"]["level4"]["enabled"] is True

    def test_with_values_file(self, tmp_path: Path) -> None:
        """Values file overrides are reflected in computed values."""
        from helm_analyse.graph import get_computed_values

        values_file = tmp_path / "values.yaml"
        values_file.write_text("global:\n  env: production\n")
        result = get_computed_values(self.FIXTURE, values_file=values_file)
        assert result["global"]["env"] == "production"
