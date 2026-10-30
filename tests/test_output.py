"""Tests for output formatters."""

import json

import pytest

from helm_analyse.graph import DependencyGraph, Occurrence
from helm_analyse.output import format_dot, format_json, format_text


def _build_graph() -> DependencyGraph:
    """Build a test graph with mixed enabled states."""
    root = Occurrence(name="root", version="1.0.0", enabled=True)
    sub1 = Occurrence(name="sub1", version="0.1.0", enabled=True)
    sub2 = Occurrence(name="sub2", version="0.2.0", enabled=False)
    sub3 = Occurrence(name="sub3", version="0.3.0", enabled=None)
    leaf = Occurrence(name="leaf", version="0.0.1", enabled=True)
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
        assert "fillcolor=mistyrose" in dot
        assert "color=grey" in dot

    def test_unknown_node_style(self) -> None:
        graph = _build_graph()
        dot = format_dot(graph)
        assert 'style="filled,dotted"' in dot
        assert "fillcolor=lightgrey" in dot
        assert "color=grey" in dot

    def test_alias_in_label(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        child = Occurrence(name="sub", version="0.1.0", alias="custom", enabled=True)
        root.children["custom"] = child
        graph = DependencyGraph(root=root)
        graph.flatten()

        dot = format_dot(graph)
        assert "(alias: custom)" in dot

    def test_default_spacing(self) -> None:
        graph = _build_graph()
        dot = format_dot(graph)
        assert "ranksep=1.5;" in dot
        assert "nodesep=0.6;" in dot

    def test_custom_spacing(self) -> None:
        graph = _build_graph()
        dot = format_dot(graph, ranksep=2.5, nodesep=1.0)
        assert "ranksep=2.5;" in dot
        assert "nodesep=1.0;" in dot

    def test_spacing_omitted_when_none(self) -> None:
        graph = _build_graph()
        dot = format_dot(graph, ranksep=None, nodesep=None)
        assert "ranksep=" not in dot
        assert "nodesep=" not in dot

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
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        sub = Occurrence(name="sub", version="0.1.0", enabled=True)
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
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        sub = Occurrence(name="sub", version="0.1.0", enabled=False)
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
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        sub = Occurrence(name="sub", version="0.1.0")
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
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        sub = Occurrence(name="sub", version="0.1.0", enabled=None)
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

        root = Occurrence(name="root", version="1.0.0", enabled=True)
        a = Occurrence(name="a", version="1.0.0", enabled=True)
        x = Occurrence(name="x", version="1.0.0", enabled=True)
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


def _build_evaluated_graph() -> DependencyGraph:
    """Build a test graph where every occurrence has a status."""
    graph = _build_graph()
    graph.occurrences["root/sub3"].enabled = False
    return graph


class TestFormatText:
    """Tests for text output format."""

    def test_root_has_status(self) -> None:
        graph = _build_evaluated_graph()
        text = format_text(graph)
        assert "root-1.0.0 (root) [on]" in text

    def test_occurrence_status_labels(self) -> None:
        graph = _build_evaluated_graph()
        text = format_text(graph)
        assert "sub1-0.1.0 [on]" in text
        assert "sub2-0.2.0 [off]" in text

    def test_summary_line(self) -> None:
        graph = _build_evaluated_graph()
        text = format_text(graph)
        assert "3 on, 2 off" in text

    def test_unevaluated_graph_raises(self) -> None:
        graph = _build_graph()
        with pytest.raises(ValueError, match="not been evaluated"):
            format_text(graph)

    def test_enabled_before_disabled(self) -> None:
        graph = _build_evaluated_graph()
        text = format_text(graph)
        lines = text.split("\n")
        enabled_line = next(i for i, line in enumerate(lines) if "sub1-" in line)
        disabled_line = next(i for i, line in enumerate(lines) if "sub2-" in line)
        assert enabled_line < disabled_line

    def test_blank_line_separator(self) -> None:
        graph = _build_evaluated_graph()
        text = format_text(graph)
        lines = text.split("\n")
        # There should be an empty line between enabled and disabled groups
        has_empty = any(line.strip() == "" for line in lines)
        assert has_empty

    def test_alias_shown(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        child = Occurrence(name="sub", version="0.1.0", alias="custom", enabled=True)
        root.children["custom"] = child
        graph = DependencyGraph(root=root)
        graph.flatten()

        text = format_text(graph)
        assert "(alias: custom)" in text

    def test_duplicate_subtree_collapsed(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        for parent in ("a", "b"):
            p = Occurrence(name=parent, version="1.0.0", enabled=True)
            shared = Occurrence(name="shared", version="1.0.0", enabled=True)
            shared.children["leaf"] = Occurrence(name="leaf", version="1.0.0", enabled=True)
            p.children["shared"] = shared
            root.children[parent] = p
        graph = DependencyGraph(root=root)
        graph.flatten()

        text = format_text(graph)
        assert text.count("leaf-1.0.0") == 1
        assert text.count("[deduplicated]") == 1
        assert format_text(graph, show_duplicates=True).count("leaf-1.0.0") == 2

    def test_no_dedup_marker_for_repeated_leaf(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        for parent in ("a", "b"):
            p = Occurrence(name=parent, version="1.0.0", enabled=True)
            p.children["leaf"] = Occurrence(name="leaf", version="1.0.0", enabled=True)
            root.children[parent] = p
        graph = DependencyGraph(root=root)
        graph.flatten()

        assert "[deduplicated]" not in format_text(graph)


class TestFormatJson:
    """Tests for JSON output format."""

    def test_occurrences_and_charts(self) -> None:
        data = json.loads(format_json(_build_evaluated_graph()))
        assert set(data) == {"occurrences", "charts"}
        occ = {o["path"]: o for o in data["occurrences"]}
        assert list(occ) == ["root", "root/sub1", "root/sub1/leaf", "root/sub2", "root/sub3"]
        assert occ["root/sub1"] == {
            "path": "root/sub1",
            "chart": "sub1",
            "alias": None,
            "version": "0.1.0",
            "repository": None,
            "type": None,
            "conditions": [],
            "tags": [],
            "status": "on",
        }
        assert occ["root/sub2"]["status"] == "off"
        charts = {c["name"]: c for c in data["charts"]}
        assert charts["sub2"] == {
            "name": "sub2",
            "versions": ["0.2.0"],
            "type": None,
            "status": "off",
        }

    def test_diamond_occurrence_vs_chart_status(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        a = Occurrence(name="a", version="1.0.0", enabled=False)
        b = Occurrence(name="b", version="1.0.0", enabled=True)
        a.children["db"] = Occurrence(
            name="postgresql", version="15.1.0", alias="db", enabled=False
        )
        b.children["postgresql"] = Occurrence(name="postgresql", version="15.0.0", enabled=True)
        root.children["a"] = a
        root.children["b"] = b
        graph = DependencyGraph(root=root)
        graph.flatten()

        data = json.loads(format_json(graph))
        occ = {o["path"]: o for o in data["occurrences"]}
        assert occ["root/a/db"]["chart"] == "postgresql"
        assert occ["root/a/db"]["alias"] == "db"
        assert occ["root/a/db"]["status"] == "off"
        assert occ["root/b/postgresql"]["status"] == "on"
        pg = [c for c in data["charts"] if c["name"] == "postgresql"]
        assert pg == [
            {"name": "postgresql", "versions": ["15.0.0", "15.1.0"], "type": None, "status": "on"}
        ]

    def test_chart_type_in_json(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        lib = Occurrence(name="common", version="1.0.0", chart_type="library", enabled=True)
        sub = Occurrence(name="sub", version="0.1.0", enabled=True)
        root.children["common"] = lib
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        data = json.loads(format_json(graph, hide_libraries=False))
        types = {c["name"]: c["type"] for c in data["charts"]}
        assert types == {"root": None, "common": "library", "sub": None}

    def test_hide_libraries(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        lib = Occurrence(name="common", version="1.0.0", chart_type="library", enabled=True)
        sub = Occurrence(name="sub", version="0.1.0", enabled=True)
        root.children["common"] = lib
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        data = json.loads(format_json(graph, hide_libraries=True))
        assert [o["path"] for o in data["occurrences"]] == ["root", "root/sub"]
        assert [c["name"] for c in data["charts"]] == ["root", "sub"]

    def test_unevaluated_graph_raises(self) -> None:
        with pytest.raises(ValueError, match="not been evaluated"):
            format_json(_build_graph())


class TestLibraryCharts:
    """Tests for library chart handling in output."""

    def test_text_hides_libraries(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        lib = Occurrence(name="common", version="1.0.0", chart_type="library", enabled=None)
        sub = Occurrence(name="sub", version="0.1.0", enabled=True)
        root.children["common"] = lib
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        text = format_text(graph, hide_libraries=True)
        assert "common" not in text
        assert "sub" in text

    def test_text_shows_libraries_when_not_hidden(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        lib = Occurrence(name="common", version="1.0.0", chart_type="library", enabled=True)
        sub = Occurrence(name="sub", version="0.1.0", enabled=True)
        root.children["common"] = lib
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        text = format_text(graph, hide_libraries=False)
        assert "common" in text
        assert "(library)" in text

    def test_dot_hides_libraries(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        lib = Occurrence(name="common", version="1.0.0", chart_type="library", enabled=None)
        sub = Occurrence(name="sub", version="0.1.0", enabled=True)
        root.children["common"] = lib
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        dot = format_dot(graph, hide_libraries=True)
        assert '"common"' not in dot
        assert '"sub"' in dot

    def test_dot_shows_library_label_when_not_hidden(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        lib = Occurrence(name="common", version="1.0.0", chart_type="library", enabled=None)
        root.children["common"] = lib
        graph = DependencyGraph(root=root)
        graph.flatten()

        dot = format_dot(graph, hide_libraries=False)
        assert "(library)" in dot

    def test_dot_syntax_valid_with_libraries(self) -> None:
        import subprocess
        import tempfile

        root = Occurrence(name="root", version="1.0.0", enabled=True)
        lib = Occurrence(name="common", version="1.0.0", chart_type="library", enabled=None)
        sub = Occurrence(name="sub", version="0.1.0", enabled=True)
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
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        a = Occurrence(name="a", version="1.0.0", enabled=False)
        b = Occurrence(name="b", version="1.0.0", enabled=True)
        shared_a = Occurrence(name="shared", version="1.0.0", enabled=False)
        shared_b = Occurrence(name="shared", version="1.0.0", enabled=True)
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

    def test_text_shows_occurrence_status(self) -> None:
        graph = self._make_diamond_graph()
        text = format_text(graph, show_duplicates=True)
        assert "shared-1.0.0 [off]" in text
        assert "shared-1.0.0 [on]" in text

    def test_json_chart_on_when_any_occurrence_on(self) -> None:
        graph = self._make_diamond_graph()
        data = json.loads(format_json(graph))
        shared = [c for c in data["charts"] if c["name"] == "shared"]
        assert len(shared) == 1
        assert shared[0]["status"] == "on"

    def test_summary_counts_deduplicated(self) -> None:
        graph = self._make_diamond_graph()
        text = format_text(graph)
        # Charts: root on, a off, b on, shared on (via b) => 3 on, 1 off
        assert "3 on, 1 off" in text

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
