"""Tests for output formatters."""

from helm_analyse.graph import ChartNode, DependencyGraph
from helm_analyse.output import format_dot, format_json, format_text


def _build_graph() -> DependencyGraph:
    """Build a test graph with mixed enabled states."""
    root = ChartNode(name="root", version="1.0.0", enabled=True)
    sub1 = ChartNode(name="sub1", version="0.1.0", enabled=True)
    sub2 = ChartNode(name="sub2", version="0.2.0", enabled=False)
    sub3 = ChartNode(name="sub3", version="0.3.0", enabled=None)
    leaf = ChartNode(name="leaf", version="0.0.1", enabled=True)
    sub1.children["leaf"] = leaf
    root.children["sub1"] = sub1
    root.children["sub2"] = sub2
    root.children["sub3"] = sub3

    graph = DependencyGraph(root=root)
    graph.flatten()
    return graph


class TestFormatDot:
    """Tests for DOT output format."""

    def test_enabled_node_style(self) -> None:
        graph = _build_graph()
        dot = format_dot(graph)
        assert 'style="filled"' in dot
        assert "fillcolor=lightgreen" in dot
        assert "color=darkgreen" in dot

    def test_disabled_node_style(self) -> None:
        graph = _build_graph()
        dot = format_dot(graph)
        assert 'style="filled,dashed"' in dot
        assert "fillcolor=lightsalmon" in dot
        assert "color=orangered" in dot

    def test_unknown_node_style(self) -> None:
        graph = _build_graph()
        dot = format_dot(graph)
        assert 'style="filled,dotted"' in dot
        assert "fillcolor=lightgrey" in dot
        assert "color=grey" in dot

    def test_alias_in_label(self) -> None:
        root = ChartNode(name="root", version="1.0.0", enabled=True)
        child = ChartNode(name="sub", version="0.1.0", alias="custom", enabled=True)
        root.children["custom"] = child
        graph = DependencyGraph(root=root)
        graph.flatten()

        dot = format_dot(graph)
        assert "(alias: custom)" in dot

    def test_edges_present(self) -> None:
        graph = _build_graph()
        dot = format_dot(graph)
        assert '"root" -> "sub1"' in dot
        assert '"root" -> "sub2"' in dot
        assert '"root" -> "sub3"' in dot
        assert '"sub1" -> "leaf"' in dot

    def test_dot_syntax_valid(self) -> None:
        import subprocess
        import tempfile

        graph = _build_graph()
        dot = format_dot(graph)
        with tempfile.NamedTemporaryFile(suffix=".dot", mode="w") as f:
            f.write(dot)
            f.flush()
            result = subprocess.run(
                ["dot", "-Tsvg", f.name, "-o", "/dev/null"],
                capture_output=True,
                text=True,
            )
        assert result.returncode == 0, f"dot failed: {result.stderr}"

    def test_enabled_edge_solid(self) -> None:
        root = ChartNode(name="root", version="1.0.0", enabled=True)
        sub = ChartNode(name="sub", version="0.1.0", enabled=True)
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        dot = format_dot(graph)
        for line in dot.split("\n"):
            if '"root" -> "sub"' in line:
                assert 'style="solid"' in line
                break
        else:
            raise AssertionError("root -> sub edge not found")

    def test_disabled_edge_dashed(self) -> None:
        root = ChartNode(name="root", version="1.0.0", enabled=True)
        sub = ChartNode(name="sub", version="0.1.0", enabled=False)
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        dot = format_dot(graph)
        for line in dot.split("\n"):
            if '"root" -> "sub"' in line:
                assert 'style="dashed"' in line
                break
        else:
            raise AssertionError("root -> sub edge not found")

    def test_default_enabled_edge_solid(self) -> None:
        root = ChartNode(name="root", version="1.0.0", enabled=True)
        sub = ChartNode(name="sub", version="0.1.0")
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        dot = format_dot(graph)
        for line in dot.split("\n"):
            if '"root" -> "sub"' in line:
                assert 'style="solid"' in line
                break
        else:
            raise AssertionError("root -> sub edge not found")

    def test_unknown_edge_solid(self) -> None:
        root = ChartNode(name="root", version="1.0.0", enabled=True)
        sub = ChartNode(name="sub", version="0.1.0", enabled=None)
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        dot = format_dot(graph)
        for line in dot.split("\n"):
            if '"root" -> "sub"' in line:
                assert 'style="solid"' in line
                break
        else:
            raise AssertionError("root -> sub edge not found")

    def test_dot_syntax_valid_with_edges(self) -> None:
        import subprocess
        import tempfile

        root = ChartNode(name="root", version="1.0.0", enabled=True)
        a = ChartNode(name="a", version="1.0.0", enabled=True)
        x = ChartNode(name="x", version="1.0.0", enabled=True)
        root.children["a"] = a
        a.children["x"] = x
        graph = DependencyGraph(root=root)
        graph.flatten()

        dot = format_dot(graph)
        with tempfile.NamedTemporaryFile(suffix=".dot", mode="w") as f:
            f.write(dot)
            f.flush()
            result = subprocess.run(
                ["dot", "-Tsvg", f.name, "-o", "/dev/null"],
                capture_output=True,
                text=True,
            )
        assert result.returncode == 0, f"dot failed: {result.stderr}"

    """Tests for text output format."""

    def test_root_has_status(self) -> None:
        graph = _build_graph()
        text = format_text(graph)
        assert "root-1.0.0 (root) [active]" in text

    def test_summary_line(self) -> None:
        graph = _build_graph()
        text = format_text(graph)
        assert "3 enabled, 1 disabled, 1 unknown" in text

    def test_enabled_before_disabled(self) -> None:
        graph = _build_graph()
        text = format_text(graph)
        lines = text.split("\n")
        enabled_line = next(i for i, line in enumerate(lines) if "sub1-" in line)
        disabled_line = next(i for i, line in enumerate(lines) if "sub2-" in line)
        assert enabled_line < disabled_line

    def test_unknown_last(self) -> None:
        graph = _build_graph()
        text = format_text(graph)
        lines = text.split("\n")
        disabled_line = next(i for i, line in enumerate(lines) if "sub2-" in line)
        unknown_line = next(i for i, line in enumerate(lines) if "sub3-" in line)
        assert disabled_line < unknown_line

    def test_blank_line_separator(self) -> None:
        graph = _build_graph()
        text = format_text(graph)
        lines = text.split("\n")
        # There should be an empty line between enabled and disabled groups
        has_empty = any(line.strip() == "" for line in lines)
        assert has_empty

    def test_alias_shown(self) -> None:
        root = ChartNode(name="root", version="1.0.0", enabled=True)
        child = ChartNode(name="sub", version="0.1.0", alias="custom", enabled=True)
        root.children["custom"] = child
        graph = DependencyGraph(root=root)
        graph.flatten()

        text = format_text(graph)
        assert "(alias: custom)" in text


class TestFormatJson:
    """Tests for JSON output format."""

    def test_enabled_field_present(self) -> None:
        graph = _build_graph()
        import json

        data = json.loads(format_json(graph))
        assert data["root"]["enabled"] is True
        assert data["nodes"]["root/sub1"]["enabled"] is True
        assert data["nodes"]["root/sub2"]["enabled"] is False
        assert data["nodes"]["root/sub3"]["enabled"] is None

    def test_chart_type_in_json(self) -> None:
        import json

        root = ChartNode(name="root", version="1.0.0", enabled=True)
        lib = ChartNode(name="common", version="1.0.0", chart_type="library", enabled=None)
        sub = ChartNode(name="sub", version="0.1.0", enabled=True)
        root.children["common"] = lib
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        data = json.loads(format_json(graph, hide_libraries=False))
        assert data["root"]["chart_type"] is None
        assert data["nodes"]["root/common"]["chart_type"] == "library"
        assert data["nodes"]["root/sub"]["chart_type"] is None

    def test_hide_libraries(self) -> None:
        import json

        root = ChartNode(name="root", version="1.0.0", enabled=True)
        lib = ChartNode(name="common", version="1.0.0", chart_type="library", enabled=None)
        sub = ChartNode(name="sub", version="0.1.0", enabled=True)
        root.children["common"] = lib
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        data = json.loads(format_json(graph, hide_libraries=True))
        assert "root/common" not in data["nodes"]
        assert "root/sub" in data["nodes"]


class TestLibraryCharts:
    """Tests for library chart handling in output."""

    def test_text_hides_libraries(self) -> None:
        root = ChartNode(name="root", version="1.0.0", enabled=True)
        lib = ChartNode(name="common", version="1.0.0", chart_type="library", enabled=None)
        sub = ChartNode(name="sub", version="0.1.0", enabled=True)
        root.children["common"] = lib
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        text = format_text(graph, hide_libraries=True)
        assert "common" not in text
        assert "sub" in text

    def test_text_shows_libraries_when_not_hidden(self) -> None:
        root = ChartNode(name="root", version="1.0.0", enabled=True)
        lib = ChartNode(name="common", version="1.0.0", chart_type="library", enabled=None)
        sub = ChartNode(name="sub", version="0.1.0", enabled=True)
        root.children["common"] = lib
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        text = format_text(graph, hide_libraries=False)
        assert "common" in text
        assert "(library)" in text

    def test_dot_hides_libraries(self) -> None:
        root = ChartNode(name="root", version="1.0.0", enabled=True)
        lib = ChartNode(name="common", version="1.0.0", chart_type="library", enabled=None)
        sub = ChartNode(name="sub", version="0.1.0", enabled=True)
        root.children["common"] = lib
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        dot = format_dot(graph, hide_libraries=True)
        assert '"common"' not in dot
        assert '"sub"' in dot

    def test_dot_shows_library_label_when_not_hidden(self) -> None:
        root = ChartNode(name="root", version="1.0.0", enabled=True)
        lib = ChartNode(name="common", version="1.0.0", chart_type="library", enabled=None)
        root.children["common"] = lib
        graph = DependencyGraph(root=root)
        graph.flatten()

        dot = format_dot(graph, hide_libraries=False)
        assert "(library)" in dot

    def test_dot_syntax_valid_with_libraries(self) -> None:
        import subprocess
        import tempfile

        root = ChartNode(name="root", version="1.0.0", enabled=True)
        lib = ChartNode(name="common", version="1.0.0", chart_type="library", enabled=None)
        sub = ChartNode(name="sub", version="0.1.0", enabled=True)
        root.children["common"] = lib
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        dot = format_dot(graph, hide_libraries=False)
        with tempfile.NamedTemporaryFile(suffix=".dot", mode="w") as f:
            f.write(dot)
            f.flush()
            result = subprocess.run(
                ["dot", "-Tsvg", f.name, "-o", "/dev/null"],
                capture_output=True,
                text=True,
            )
        assert result.returncode == 0, f"dot failed: {result.stderr}"


class TestMultiPathEnabled:
    """Tests for charts appearing at multiple paths with different enabled states."""

    def _make_diamond_graph(self) -> DependencyGraph:
        """Build: root -> a(disabled) -> shared, root -> b(enabled) -> shared."""
        root = ChartNode(name="root", version="1.0.0", enabled=True)
        a = ChartNode(name="a", version="1.0.0", enabled=False)
        b = ChartNode(name="b", version="1.0.0", enabled=True)
        shared_a = ChartNode(name="shared", version="1.0.0", enabled=False)
        shared_b = ChartNode(name="shared", version="1.0.0", enabled=True)
        a.children["shared"] = shared_a
        b.children["shared"] = shared_b
        root.children["a"] = a
        root.children["b"] = b
        graph = DependencyGraph(root=root)
        graph.flatten()
        return graph

    def test_dot_shows_enabled_when_any_path_enabled(self) -> None:
        graph = self._make_diamond_graph()
        dot = format_dot(graph)
        # shared should appear as green (enabled) because it has an enabled path through b
        for line in dot.split("\n"):
            if '"shared"' in line and "fillcolor" in line:
                assert "lightgreen" in line
                break
        else:
            raise AssertionError("shared node not found in DOT output")

    def test_text_shows_enabled_when_any_path_enabled(self) -> None:
        graph = self._make_diamond_graph()
        text = format_text(graph)
        assert "shared-1.0.0 [active]" in text

    def test_json_shows_enabled_when_any_path_enabled(self) -> None:
        import json

        graph = self._make_diamond_graph()
        data = json.loads(format_json(graph))
        # Find the shared node
        shared_nodes = [v for v in data["nodes"].values() if v["name"] == "shared"]
        assert len(shared_nodes) == 1
        assert shared_nodes[0]["enabled"] is True

    def test_summary_counts_deduplicated(self) -> None:
        graph = self._make_diamond_graph()
        text = format_text(graph)
        # root=enabled, a=disabled, b=enabled, shared=effective_enabled=True
        # So: 3 enabled (root, b, shared), 1 disabled (a), 0 unknown
        assert "3 enabled, 1 disabled, 0 unknown" in text

    def test_edge_from_disabled_parent_dashed_when_enabled_via_other_path(self) -> None:
        """Edge from disabled parent to shared chart is dashed because it does not enable shared."""
        graph = self._make_diamond_graph()
        dot = format_dot(graph)
        for line in dot.split("\n"):
            if '"a" -> "shared"' in line:
                # a is disabled, so its path does not enable shared => dashed
                assert 'style="dashed"' in line
                break
        else:
            raise AssertionError("a -> shared edge not found")

    def test_edge_from_enabled_parent_solid(self) -> None:
        graph = self._make_diamond_graph()
        dot = format_dot(graph)
        for line in dot.split("\n"):
            if '"b" -> "shared"' in line:
                assert 'style="solid"' in line
                break
        else:
            raise AssertionError("b -> shared edge not found")
