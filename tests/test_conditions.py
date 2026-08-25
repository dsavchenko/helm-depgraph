"""Tests for condition evaluator."""

from helm_analyse.conditions import _resolve_path, evaluate_conditions
from helm_analyse.graph import ChartNode, DependencyGraph


class TestResolvePath:
    """Tests for _resolve_path function."""

    def test_simple_path(self) -> None:
        values = {"subchart": {"enabled": True}}
        assert _resolve_path("subchart.enabled", values) is True

    def test_simple_path_false(self) -> None:
        values = {"subchart": {"enabled": False}}
        assert _resolve_path("subchart.enabled", values) is False

    def test_missing_path(self) -> None:
        values = {"other": {"enabled": True}}
        assert _resolve_path("subchart.enabled", values) is None

    def test_nested_path(self) -> None:
        values = {"global": {"subchart": {"enabled": True}}}
        assert _resolve_path("global.subchart.enabled", values) is True

    def test_truthy_non_boolean(self) -> None:
        values = {"subchart": {"replicas": 3}}
        result = _resolve_path("subchart.replicas", values)
        assert result == 3
        assert result is not None

    def test_falsy_non_boolean(self) -> None:
        values = {"subchart": {"replicas": 0}}
        assert _resolve_path("subchart.replicas", values) == 0

    def test_non_dict_intermediate(self) -> None:
        values = {"subchart": "not-a-dict"}
        assert _resolve_path("subchart.enabled", values) is None


class TestEvaluateConditions:
    """Tests for evaluate_conditions function."""

    def _make_graph(self, conditions: list[str], tags: list[str] | None = None) -> DependencyGraph:
        """Helper to create a graph with one child node."""
        root = ChartNode(name="root", version="1.0.0")
        child = ChartNode(
            name="subchart",
            version="1.0.0",
            conditions=conditions,
            tags=tags or [],
        )
        root.children["subchart"] = child
        graph = DependencyGraph(root=root)
        graph.flatten()
        return graph

    def test_condition_true(self) -> None:
        graph = self._make_graph(conditions=["subchart.enabled"])
        evaluate_conditions(graph, {"subchart": {"enabled": True}})
        assert graph.nodes["root/subchart"].enabled is True

    def test_condition_false(self) -> None:
        graph = self._make_graph(conditions=["subchart.enabled"])
        evaluate_conditions(graph, {"subchart": {"enabled": False}})
        assert graph.nodes["root/subchart"].enabled is False

    def test_condition_missing_defaults_to_enabled(self) -> None:
        graph = self._make_graph(conditions=["subchart.enabled"])
        evaluate_conditions(graph, {})
        assert graph.nodes["root/subchart"].enabled is True

    def test_multiple_conditions_first_valid_wins(self) -> None:
        graph = self._make_graph(conditions=["subchart.enabled", "global.subchart.enabled"])
        evaluate_conditions(graph, {"global": {"subchart": {"enabled": False}}})
        assert graph.nodes["root/subchart"].enabled is False

    def test_condition_overrides_tag(self) -> None:
        graph = self._make_graph(conditions=["subchart.enabled"], tags=["web"])
        evaluate_conditions(graph, {"subchart": {"enabled": False}, "tags": {"web": True}})
        assert graph.nodes["root/subchart"].enabled is False

    def test_tag_true(self) -> None:
        graph = self._make_graph(conditions=[], tags=["web"])
        evaluate_conditions(graph, {"tags": {"web": True}})
        assert graph.nodes["root/subchart"].enabled is True

    def test_tag_false(self) -> None:
        graph = self._make_graph(conditions=[], tags=["web"])
        evaluate_conditions(graph, {"tags": {"web": False}})
        assert graph.nodes["root/subchart"].enabled is False

    def test_any_tag_true_enables(self) -> None:
        graph = self._make_graph(conditions=[], tags=["web", "backend"])
        evaluate_conditions(graph, {"tags": {"web": False, "backend": True}})
        assert graph.nodes["root/subchart"].enabled is True

    def test_no_conditions_no_tags_defaults_enabled(self) -> None:
        graph = self._make_graph(conditions=[], tags=[])
        evaluate_conditions(graph, {})
        assert graph.nodes["root/subchart"].enabled is True
