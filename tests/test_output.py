"""Tests for output formatters."""

import json
import subprocess
import tempfile

import pytest

from helm_analyse.graph import DependencyGraph, Occurrence
from helm_analyse.output import format_dot, format_json, format_text


def _build_graph() -> DependencyGraph:
    """Build a test graph with mixed enabled states."""
    root = Occurrence(name="root", version="1.0.0", enabled=True)
    sub1 = Occurrence(name="sub1", version="0.1.0", enabled=True)
    sub2 = Occurrence(name="sub2", version="0.2.0", enabled=False)
    sub3 = Occurrence(name="sub3", version="0.3.0", enabled=False)
    leaf = Occurrence(name="leaf", version="0.0.1", enabled=True)
    sub1.children["leaf"] = leaf
    root.children["sub1"] = sub1
    root.children["sub2"] = sub2
    root.children["sub3"] = sub3

    graph = DependencyGraph(root=root)
    graph.flatten()
    return graph


def _edge_line(dot: str, parent: str, child: str) -> str:
    """Return the single DOT edge line from parent to child chart."""
    found = [line for line in dot.split("\n") if f'"{parent}" -> "{child}"' in line]
    assert len(found) == 1, found
    return found[0]


def _assert_valid_dot(dot: str) -> None:
    with tempfile.NamedTemporaryFile(suffix=".dot", mode="w") as f:
        f.write(dot)
        f.flush()
        result = subprocess.run(
            ["dot", "-Tsvg", f.name, "-o", "/dev/null"],
            capture_output=True,
            text=True,
        )
    assert result.returncode == 0, f"dot failed: {result.stderr}"


class TestFormatDot:
    """Tests for DOT output format."""

    def test_enabled_node_style(self) -> None:
        dot = format_dot(_build_graph())
        assert 'style="filled"' in dot
        assert "fillcolor=lightgreen" in dot
        assert "color=darkgreen" in dot

    def test_disabled_node_style(self) -> None:
        dot = format_dot(_build_graph())
        assert 'style="filled,dashed"' in dot
        assert "fillcolor=mistyrose" in dot
        assert "color=grey" in dot

    def test_no_unknown_style(self) -> None:
        dot = format_dot(_build_graph())
        assert "dotted" not in dot
        assert "lightgrey" not in dot

    def test_unevaluated_graph_raises(self) -> None:
        graph = _build_graph()
        graph.occurrences["root/sub3"].enabled = None
        with pytest.raises(ValueError, match="not been evaluated"):
            format_dot(graph)

    def test_alias_on_edge_not_node(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        child = Occurrence(name="sub", version="0.1.0", alias="custom", enabled=True)
        root.children["custom"] = child
        graph = DependencyGraph(root=root)
        graph.flatten()

        dot = format_dot(graph)
        assert 'label="custom"' in _edge_line(dot, "root", "sub")
        assert "alias" not in dot

    def test_no_edge_label_without_alias(self) -> None:
        dot = format_dot(_build_graph())
        assert "label" not in _edge_line(dot, "root", "sub1")

    def test_versions_in_node_label(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        a = Occurrence(name="a", version="1.0.0", enabled=True)
        a.children["common"] = Occurrence(name="common", version="2.4", enabled=True)
        root.children["a"] = a
        root.children["common"] = Occurrence(name="common", version="2.1", enabled=True)
        graph = DependencyGraph(root=root)
        graph.flatten()

        dot = format_dot(graph)
        assert 'label="common\\n2.1, 2.4"' in dot
        assert sum(1 for line in dot.split("\n") if line.startswith('  "common" [')) == 1

    def test_default_spacing(self) -> None:
        dot = format_dot(_build_graph())
        assert "ranksep=1.5;" in dot
        assert "nodesep=0.6;" in dot

    def test_custom_spacing(self) -> None:
        dot = format_dot(_build_graph(), ranksep=2.5, nodesep=1.0)
        assert "ranksep=2.5;" in dot
        assert "nodesep=1.0;" in dot

    def test_spacing_omitted_when_none(self) -> None:
        dot = format_dot(_build_graph(), ranksep=None, nodesep=None)
        assert "ranksep=" not in dot
        assert "nodesep=" not in dot

    def test_edges_present(self) -> None:
        dot = format_dot(_build_graph())
        assert '"root" -> "sub1"' in dot
        assert '"root" -> "sub2"' in dot
        assert '"root" -> "sub3"' in dot
        assert '"sub1" -> "leaf"' in dot

    def test_enabled_edge_solid(self) -> None:
        dot = format_dot(_build_graph())
        assert 'style="solid"' in _edge_line(dot, "root", "sub1")

    def test_disabled_edge_dashed(self) -> None:
        dot = format_dot(_build_graph())
        assert 'style="dashed"' in _edge_line(dot, "root", "sub2")

    def test_same_child_under_two_aliases_gives_two_edges(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        root.children["db-main"] = Occurrence(
            name="postgresql", version="15.0.0", alias="db-main", enabled=True
        )
        root.children["db-audit"] = Occurrence(
            name="postgresql", version="15.0.0", alias="db-audit", enabled=False
        )
        graph = DependencyGraph(root=root)
        graph.flatten()

        dot = format_dot(graph)
        edges = [line for line in dot.split("\n") if '"root" -> "postgresql"' in line]
        assert len(edges) == 2
        assert any('label="db-main"' in e and 'style="solid"' in e for e in edges)
        assert any('label="db-audit"' in e and 'style="dashed"' in e for e in edges)

    def test_dot_syntax_valid(self) -> None:
        _assert_valid_dot(format_dot(_build_graph()))


class TestFormatText:
    """Tests for text output format."""

    def test_root_has_status(self) -> None:
        graph = _build_graph()
        text = format_text(graph)
        assert "root-1.0.0 (root) [on]" in text

    def test_occurrence_status_labels(self) -> None:
        graph = _build_graph()
        text = format_text(graph)
        assert "sub1-0.1.0 [on]" in text
        assert "sub2-0.2.0 [off]" in text

    def test_summary_line(self) -> None:
        graph = _build_graph()
        text = format_text(graph)
        assert "3 on, 2 off" in text

    def test_unevaluated_graph_raises(self) -> None:
        graph = _build_graph()
        graph.occurrences["root/sub3"].enabled = None
        with pytest.raises(ValueError, match="not been evaluated"):
            format_text(graph)

    def test_enabled_before_disabled(self) -> None:
        graph = _build_graph()
        text = format_text(graph)
        lines = text.split("\n")
        enabled_line = next(i for i, line in enumerate(lines) if "sub1-" in line)
        disabled_line = next(i for i, line in enumerate(lines) if "sub2-" in line)
        assert enabled_line < disabled_line

    def test_blank_line_separator(self) -> None:
        graph = _build_graph()
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
        data = json.loads(format_json(_build_graph()))
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
        graph = _build_graph()
        graph.occurrences["root/sub3"].enabled = None
        with pytest.raises(ValueError, match="not been evaluated"):
            format_json(graph)


class TestLibraryCharts:
    """Tests for library chart handling in output."""

    def test_text_hides_libraries(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        lib = Occurrence(name="common", version="1.0.0", chart_type="library", enabled=True)
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
        lib = Occurrence(name="common", version="1.0.0", chart_type="library", enabled=True)
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
        lib = Occurrence(name="common", version="1.0.0", chart_type="library", enabled=True)
        root.children["common"] = lib
        graph = DependencyGraph(root=root)
        graph.flatten()

        dot = format_dot(graph, hide_libraries=False)
        assert "(library)" in dot

    def test_dot_syntax_valid_with_libraries(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        lib = Occurrence(name="common", version="1.0.0", chart_type="library", enabled=True)
        sub = Occurrence(name="sub", version="0.1.0", enabled=True)
        root.children["common"] = lib
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        _assert_valid_dot(format_dot(graph, hide_libraries=False))

    def test_hidden_library_hides_its_descendants(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        lib = Occurrence(name="common", version="1.0.0", chart_type="library", enabled=True)
        lib.children["helper"] = Occurrence(name="helper", version="1.0.0", enabled=True)
        root.children["common"] = lib
        graph = DependencyGraph(root=root)
        graph.flatten()

        assert '"helper"' not in format_dot(graph)
        assert "helper" not in format_text(graph)
        assert "helper" not in format_json(graph)


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

    def test_edges_per_occurrence_style(self) -> None:
        dot = format_dot(self._make_diamond_graph())
        assert 'style="dashed"' in _edge_line(dot, "a", "shared")
        assert 'style="solid"' in _edge_line(dot, "b", "shared")

    def test_diamond_parent_keeps_edges_below_second_occurrence(self) -> None:
        """mid appears under a and b; its child edge must exist even if only b's copy has it on."""
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        for parent, on in (("a", False), ("b", True)):
            p = Occurrence(name=parent, version="1.0.0", enabled=on)
            mid = Occurrence(name="mid", version="1.0.0", enabled=on)
            mid.children["leaf"] = Occurrence(name="leaf", version="1.0.0", enabled=on)
            p.children["mid"] = mid
            root.children[parent] = p
        graph = DependencyGraph(root=root)
        graph.flatten()

        dot = format_dot(graph)
        # One merged mid -> leaf edge covering both occurrences; solid since b's copy is on
        assert 'style="solid"' in _edge_line(dot, "mid", "leaf")

    def test_merged_edge_dashed_only_if_all_occurrences_off(self) -> None:
        root = Occurrence(name="root", version="1.0.0", enabled=True)
        for parent in ("a", "b"):
            p = Occurrence(name=parent, version="1.0.0", enabled=True)
            mid = Occurrence(name="mid", version="1.0.0", enabled=True)
            mid.children["leaf"] = Occurrence(name="leaf", version="1.0.0", enabled=False)
            p.children["mid"] = mid
            root.children[parent] = p
        graph = DependencyGraph(root=root)
        graph.flatten()

        assert 'style="dashed"' in _edge_line(format_dot(graph), "mid", "leaf")
