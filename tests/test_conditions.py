"""Tests for condition evaluator."""

import logging
from pathlib import Path

import pytest

from helm_analyse.conditions import (
    _propagate_disabled,
    _resolve_path,
    effective_enabled,
    evaluate_conditions,
)
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

    def test_non_boolean_condition_skipped(self) -> None:
        graph = self._make_graph(conditions=["subchart.enabled", "global.subchart.enabled"])
        evaluate_conditions(
            graph,
            {"subchart": {"enabled": "false"}, "global": {"subchart": {"enabled": False}}},
        )
        assert graph.nodes["root/subchart"].enabled is False

    def test_non_boolean_condition_falls_through_to_default(self) -> None:
        graph = self._make_graph(conditions=["subchart.enabled"])
        evaluate_conditions(graph, {"subchart": {"enabled": 0}})
        assert graph.nodes["root/subchart"].enabled is True

    def test_non_boolean_condition_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        graph = self._make_graph(conditions=["subchart.enabled"])
        with caplog.at_level(logging.WARNING, logger="helm_analyse.conditions"):
            evaluate_conditions(graph, {"subchart": {"enabled": "yes"}})
        assert "Condition path 'subchart.enabled' for chart subchart" in caplog.text

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

    def test_unset_tags_default_enabled(self) -> None:
        graph = self._make_graph(conditions=[], tags=["web", "backend"])
        evaluate_conditions(graph, {})
        assert graph.nodes["root/subchart"].enabled is True

    def test_false_tag_with_unset_tag_disables(self) -> None:
        graph = self._make_graph(conditions=[], tags=["web", "backend"])
        evaluate_conditions(graph, {"tags": {"web": False}})
        assert graph.nodes["root/subchart"].enabled is False

    def test_non_boolean_tag_has_no_effect(self) -> None:
        graph = self._make_graph(conditions=[], tags=["web"])
        evaluate_conditions(graph, {"tags": {"web": 0}})
        assert graph.nodes["root/subchart"].enabled is True

    def test_non_decisive_condition_falls_back_to_tags(self) -> None:
        graph = self._make_graph(conditions=["subchart.enabled"], tags=["web"])
        evaluate_conditions(graph, {"tags": {"web": False}})
        assert graph.nodes["root/subchart"].enabled is False

    def test_no_conditions_no_tags_defaults_enabled(self) -> None:
        graph = self._make_graph(conditions=[], tags=[])
        evaluate_conditions(graph, {})
        assert graph.nodes["root/subchart"].enabled is True

    def test_library_chart_condition_evaluated(self) -> None:
        root = ChartNode(name="root", version="1.0.0")
        lib = ChartNode(
            name="common",
            version="1.0.0",
            chart_type="library",
            conditions=["common.enabled"],
        )
        root.children["common"] = lib
        graph = DependencyGraph(root=root)
        graph.flatten()

        evaluate_conditions(graph, {"common": {"enabled": False}})
        assert graph.nodes["root/common"].enabled is False

    def test_library_chart_without_condition_defaults_enabled(self) -> None:
        root = ChartNode(name="root", version="1.0.0")
        lib = ChartNode(
            name="common",
            version="1.0.0",
            chart_type="library",
        )
        root.children["common"] = lib
        graph = DependencyGraph(root=root)
        graph.flatten()

        evaluate_conditions(graph, {})
        assert graph.nodes["root/common"].enabled is True


class TestPropagateDisabled:
    """Tests for disabled state propagation to descendants."""

    def test_linear_chain_all_disabled(self) -> None:
        """root(A disabled) -> B -> C => all descendants disabled."""
        root = ChartNode(name="root", version="1.0.0")
        a = ChartNode(name="a", version="1.0.0", conditions=["a.enabled"])
        b = ChartNode(name="b", version="1.0.0")
        c = ChartNode(name="c", version="1.0.0")
        a.children["b"] = b
        b.children["c"] = c
        root.children["a"] = a
        graph = DependencyGraph(root=root)
        graph.flatten()

        evaluate_conditions(graph, {"a": {"enabled": False}})
        assert graph.nodes["root"].enabled is True
        assert graph.nodes["root/a"].enabled is False
        assert graph.nodes["root/a/b"].enabled is False
        assert graph.nodes["root/a/b/c"].enabled is False

    def test_diamond_preserves_enabled(self) -> None:
        """root -> A(disabled) -> C, root -> B(enabled) -> C => C stays enabled."""
        root = ChartNode(name="root", version="1.0.0")
        a = ChartNode(name="a", version="1.0.0", conditions=["a.enabled"])
        b = ChartNode(name="b", version="1.0.0", conditions=["b.enabled"])
        c = ChartNode(name="c", version="1.0.0")
        a.children["c"] = c
        b.children["c"] = c
        root.children["a"] = a
        root.children["b"] = b
        graph = DependencyGraph(root=root)
        graph.flatten()

        evaluate_conditions(graph, {"a": {"enabled": False}, "b": {"enabled": True}})
        assert graph.nodes["root/a"].enabled is False
        assert graph.nodes["root/b"].enabled is True
        # C under A: also exists at root/b/c where root and b are enabled => not force-disabled
        assert graph.nodes["root/a/c"].enabled is True
        assert graph.nodes["root/b/c"].enabled is True

    def test_all_paths_disabled(self) -> None:
        """root -> A(disabled) -> C, root -> B(disabled) -> C => C disabled."""
        root = ChartNode(name="root", version="1.0.0")
        a = ChartNode(name="a", version="1.0.0", conditions=["a.enabled"])
        b = ChartNode(name="b", version="1.0.0", conditions=["b.enabled"])
        c = ChartNode(name="c", version="1.0.0")
        a.children["c"] = c
        b.children["c"] = c
        root.children["a"] = a
        root.children["b"] = b
        graph = DependencyGraph(root=root)
        graph.flatten()

        evaluate_conditions(graph, {"a": {"enabled": False}, "b": {"enabled": False}})
        assert graph.nodes["root/a"].enabled is False
        assert graph.nodes["root/b"].enabled is False
        assert graph.nodes["root/a/c"].enabled is False
        assert graph.nodes["root/b/c"].enabled is False

    def test_keeps_via_path_with_enabled_node(self) -> None:
        """Child stays enabled when an alternative path has an enabled node."""
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

        _propagate_disabled(graph)
        assert graph.nodes["root/a/shared"].enabled is False
        assert graph.nodes["root/b/shared"].enabled is True
        assert effective_enabled(graph, "shared") is True

    def test_disables_via_path_with_disabled_node(self) -> None:
        """Child is disabled when the alternative path node itself is disabled."""
        root = ChartNode(name="root", version="1.0.0", enabled=True)
        a = ChartNode(name="a", version="1.0.0", enabled=True)
        b = ChartNode(name="b", version="1.0.0", enabled=False)
        shared_a = ChartNode(name="shared", version="1.0.0", enabled=False)
        shared_b = ChartNode(name="shared", version="1.0.0", enabled=True)
        a.children["shared"] = shared_a
        b.children["shared"] = shared_b
        root.children["a"] = a
        root.children["b"] = b
        graph = DependencyGraph(root=root)
        graph.flatten()

        _propagate_disabled(graph)
        assert graph.nodes["root/a/shared"].enabled is False
        assert graph.nodes["root/b/shared"].enabled is False
        assert effective_enabled(graph, "shared") is False

    def test_intermediate_disabled_preserves_sibling_path(self) -> None:
        """root -> A(disabled) -> B -> C, root -> D(enabled) -> C => C enabled."""
        root = ChartNode(name="root", version="1.0.0")
        a = ChartNode(name="a", version="1.0.0", conditions=["a.enabled"])
        b = ChartNode(name="b", version="1.0.0")
        c = ChartNode(name="c", version="1.0.0")
        d = ChartNode(name="d", version="1.0.0", conditions=["d.enabled"])
        a.children["b"] = b
        b.children["c"] = c
        d.children["c"] = c
        root.children["a"] = a
        root.children["d"] = d
        graph = DependencyGraph(root=root)
        graph.flatten()

        evaluate_conditions(graph, {"a": {"enabled": False}, "d": {"enabled": True}})
        assert graph.nodes["root/a"].enabled is False
        assert graph.nodes["root/a/b"].enabled is False
        # C under A/B also at root/d/c where root and d are enabled => not force-disabled
        assert graph.nodes["root/a/b/c"].enabled is True

    def test_library_disabled_under_disabled_parent(self) -> None:
        """Library charts are disabled by propagation like any other chart."""
        root = ChartNode(name="root", version="1.0.0")
        a = ChartNode(name="a", version="1.0.0", conditions=["a.enabled"])
        lib = ChartNode(name="common", version="1.0.0", chart_type="library")
        a.children["common"] = lib
        root.children["a"] = a
        graph = DependencyGraph(root=root)
        graph.flatten()

        evaluate_conditions(graph, {"a": {"enabled": False}})
        assert graph.nodes["root/a"].enabled is False
        assert graph.nodes["root/a/common"].enabled is False

    def test_own_condition_overridden_when_disabled_parent(self) -> None:
        """Descendant's own condition is overridden when all parent paths disabled."""
        root = ChartNode(name="root", version="1.0.0")
        a = ChartNode(name="a", version="1.0.0", conditions=["a.enabled"])
        b = ChartNode(name="b", version="1.0.0", conditions=["b.enabled"])
        a.children["b"] = b
        root.children["a"] = a
        graph = DependencyGraph(root=root)
        graph.flatten()

        evaluate_conditions(graph, {"a": {"enabled": False}, "b": {"enabled": True}})
        assert graph.nodes["root/a"].enabled is False
        # B's own condition says True, but parent A is disabled => forced False
        assert graph.nodes["root/a/b"].enabled is False

    def test_root_always_enabled(self) -> None:
        """Root is always enabled regardless of conditions."""
        root = ChartNode(name="root", version="1.0.0")
        a = ChartNode(name="a", version="1.0.0")
        root.children["a"] = a
        graph = DependencyGraph(root=root)
        graph.flatten()

        evaluate_conditions(graph, {})
        assert graph.nodes["root"].enabled is True


class TestConditionPathResolution:
    """Tests for resolving condition paths relative to chart's values namespace."""

    def test_direct_child_condition_resolves(self) -> None:
        """Direct child condition (subchart.enabled) resolves at root level."""
        root = ChartNode(name="root", version="1.0.0")
        sub = ChartNode(name="sub", version="1.0.0", conditions=["sub.enabled"])
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()

        evaluate_conditions(graph, {"sub": {"enabled": False}})
        assert graph.nodes["root/sub"].enabled is False

    def test_nested_condition_resolves_relative_to_parent(self) -> None:
        """Nested subchart condition resolves relative to parent's values namespace.

        root -> wms -> diracx -> dex with condition dex.enabled.
        In root values, dex's values are at wms.diracx.dex.
        So dex.enabled should resolve to wms.diracx.dex.enabled.
        """
        root = ChartNode(name="root", version="1.0.0")
        wms = ChartNode(name="wms", version="1.0.0")
        diracx = ChartNode(name="diracx", version="1.0.0")
        dex = ChartNode(name="dex", version="1.0.0", conditions=["dex.enabled"])
        diracx.children["dex"] = dex
        wms.children["diracx"] = diracx
        root.children["wms"] = wms
        graph = DependencyGraph(root=root)
        graph.flatten()

        values = {"wms": {"diracx": {"dex": {"enabled": False}}}}
        evaluate_conditions(graph, values)
        assert graph.nodes["root/wms/diracx/dex"].enabled is False

    def test_nested_condition_true(self) -> None:
        """Nested subchart condition resolves and evaluates to True."""
        root = ChartNode(name="root", version="1.0.0")
        wms = ChartNode(name="wms", version="1.0.0")
        diracx = ChartNode(name="diracx", version="1.0.0")
        dex = ChartNode(name="dex", version="1.0.0", conditions=["dex.enabled"])
        diracx.children["dex"] = dex
        wms.children["diracx"] = diracx
        root.children["wms"] = wms
        graph = DependencyGraph(root=root)
        graph.flatten()

        values = {"wms": {"diracx": {"dex": {"enabled": True}}}}
        evaluate_conditions(graph, values)
        assert graph.nodes["root/wms/diracx/dex"].enabled is True

    def test_nested_condition_missing_defaults_enabled(self) -> None:
        """Nested subchart condition missing from values defaults to enabled."""
        root = ChartNode(name="root", version="1.0.0")
        wms = ChartNode(name="wms", version="1.0.0")
        diracx = ChartNode(name="diracx", version="1.0.0")
        dex = ChartNode(name="dex", version="1.0.0", conditions=["dex.enabled"])
        diracx.children["dex"] = dex
        wms.children["diracx"] = diracx
        root.children["wms"] = wms
        graph = DependencyGraph(root=root)
        graph.flatten()

        evaluate_conditions(graph, {})
        assert graph.nodes["root/wms/diracx/dex"].enabled is True

    def test_deeply_nested_condition_resolves(self) -> None:
        """4-level deep nesting: root -> a -> b -> c with condition c.enabled."""
        root = ChartNode(name="root", version="1.0.0")
        a = ChartNode(name="a", version="1.0.0")
        b = ChartNode(name="b", version="1.0.0")
        c = ChartNode(name="c", version="1.0.0", conditions=["c.enabled"])
        b.children["c"] = c
        a.children["b"] = b
        root.children["a"] = a
        graph = DependencyGraph(root=root)
        graph.flatten()

        values = {"a": {"b": {"c": {"enabled": False}}}}
        evaluate_conditions(graph, values)
        assert graph.nodes["root/a/b/c"].enabled is False

    def test_alias_prefixed_condition_resolves(self) -> None:
        """Alias is used in values namespace, not the chart name."""
        root = ChartNode(name="root", version="1.0.0")
        parent = ChartNode(name="parent", version="1.0.0")
        child = ChartNode(
            name="my-chart", version="1.0.0", alias="myalias", conditions=["myalias.enabled"]
        )
        parent.children["myalias"] = child
        root.children["parent"] = parent
        graph = DependencyGraph(root=root)
        graph.flatten()

        values = {"parent": {"myalias": {"enabled": False}}}
        evaluate_conditions(graph, values)
        assert graph.nodes["root/parent/myalias"].enabled is False

    def test_real_scenario_dpps_wms_diracx_dex(self) -> None:
        """Reproduce the real scenario from the DOT file.

        dpps -> wms -> diracx -> dex with condition dex.enabled=false
        dpps -> wms -> diracx -> jaeger with condition jaeger.enabled=false
        """
        root = ChartNode(name="dpps", version="0.0.0-dev")
        wms = ChartNode(name="wms", version="v0.9.0-rc3")
        diracx = ChartNode(name="diracx", version="1.0.22")
        dex = ChartNode(name="dex", version="0.14.2", conditions=["dex.enabled"])
        jaeger = ChartNode(name="jaeger", version="0.71.14", conditions=["jaeger.enabled"])
        cassandra = ChartNode(name="cassandra", version="0.15.3")
        jaeger.children["cassandra"] = cassandra
        diracx.children["dex"] = dex
        diracx.children["jaeger"] = jaeger
        wms.children["diracx"] = diracx
        root.children["wms"] = wms
        graph = DependencyGraph(root=root)
        graph.flatten()

        values = {
            "wms": {
                "diracx": {
                    "dex": {"enabled": False},
                    "jaeger": {"enabled": False},
                }
            }
        }
        evaluate_conditions(graph, values)
        assert graph.nodes["dpps/wms/diracx/dex"].enabled is False
        assert graph.nodes["dpps/wms/diracx/jaeger"].enabled is False
        assert graph.nodes["dpps/wms/diracx/jaeger/cassandra"].enabled is False


class TestEffectiveEnabled:
    """Tests for effective_enabled helper."""

    def test_single_path_enabled(self) -> None:
        root = ChartNode(name="root", version="1.0.0")
        sub = ChartNode(name="sub", version="1.0.0", enabled=True)
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()
        assert effective_enabled(graph, "sub") is True

    def test_single_path_disabled(self) -> None:
        root = ChartNode(name="root", version="1.0.0")
        sub = ChartNode(name="sub", version="1.0.0", enabled=False)
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()
        assert effective_enabled(graph, "sub") is False

    def test_single_path_unknown(self) -> None:
        root = ChartNode(name="root", version="1.0.0")
        sub = ChartNode(name="sub", version="1.0.0", enabled=None)
        root.children["sub"] = sub
        graph = DependencyGraph(root=root)
        graph.flatten()
        assert effective_enabled(graph, "sub") is None

    def test_diamond_one_enabled(self) -> None:
        """Chart at two paths, one enabled one disabled => effective True."""
        root = ChartNode(name="root", version="1.0.0")
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
        assert effective_enabled(graph, "shared") is True

    def test_diamond_both_disabled(self) -> None:
        root = ChartNode(name="root", version="1.0.0")
        a = ChartNode(name="a", version="1.0.0", enabled=False)
        b = ChartNode(name="b", version="1.0.0", enabled=False)
        shared_a = ChartNode(name="shared", version="1.0.0", enabled=False)
        shared_b = ChartNode(name="shared", version="1.0.0", enabled=False)
        a.children["shared"] = shared_a
        b.children["shared"] = shared_b
        root.children["a"] = a
        root.children["b"] = b
        graph = DependencyGraph(root=root)
        graph.flatten()
        assert effective_enabled(graph, "shared") is False

    def test_diamond_child_disabled_when_enabled_path_condition_false(self) -> None:
        """Enabled parent has child condition false; disabled parent has it true.

        The child must end up disabled because neither path is active: the
        enabled parent's path does not enable it, and the disabled parent's
        path is invalid. (Regression: previously the child wrongly stayed
        enabled via the disabled parent's path.)
        """
        root = ChartNode(name="root", version="1.0.0")
        a = ChartNode(name="a", version="1.0.0", conditions=["a.enabled"])
        b = ChartNode(name="b", version="1.0.0", conditions=["b.enabled"])
        shared_a = ChartNode(name="shared", version="1.0.0", conditions=["shared.enabled"])
        shared_b = ChartNode(name="shared", version="1.0.0", conditions=["shared.enabled"])
        a.children["shared"] = shared_a
        b.children["shared"] = shared_b
        root.children["a"] = a
        root.children["b"] = b
        graph = DependencyGraph(root=root)
        graph.flatten()

        values = {
            "a": {"enabled": True, "shared": {"enabled": False}},
            "b": {"enabled": False, "shared": {"enabled": True}},
        }
        evaluate_conditions(graph, values)

        assert graph.nodes["root/a/shared"].enabled is False
        # Regression: previously this stayed True (wrongly shown as enabled)
        assert graph.nodes["root/b/shared"].enabled is False
        assert effective_enabled(graph, "shared") is False

    def test_not_found_returns_none(self) -> None:
        root = ChartNode(name="root", version="1.0.0")
        graph = DependencyGraph(root=root)
        graph.flatten()
        assert effective_enabled(graph, "nonexistent") is None

    def test_real_scenario_minio_diamond(self) -> None:
        """minio under disabled loki AND enabled diracx => effective True."""
        root = ChartNode(name="dpps", version="0.0.0-dev")
        loki = ChartNode(name="loki", version="6.30.1", enabled=False)
        wms = ChartNode(name="wms", version="v0.9.0-rc3", enabled=True)
        diracx = ChartNode(name="diracx", version="1.0.22", enabled=True)
        minio_loki = ChartNode(name="minio", version="5.4.0", enabled=False)
        minio_diracx = ChartNode(name="minio", version="5.4.0", enabled=True)
        loki.children["minio"] = minio_loki
        diracx.children["minio"] = minio_diracx
        wms.children["diracx"] = diracx
        root.children["loki"] = loki
        root.children["wms"] = wms
        graph = DependencyGraph(root=root)
        graph.flatten()
        assert effective_enabled(graph, "minio") is True


class TestComputedValuesIntegration:
    """Integration tests using get_computed_values with the test fixture chart."""

    FIXTURE = Path(__file__).parent / "fixtures" / "charts" / "test-values-analysis"

    def _build_and_evaluate(self, values_file: Path | None = None) -> DependencyGraph:
        """Build graph and evaluate conditions using computed values."""
        from helm_analyse.graph import build_graph, get_computed_values

        graph = build_graph(self.FIXTURE, use_helm_build=False)
        computed = get_computed_values(self.FIXTURE, values_file=values_file)
        evaluate_conditions(graph, computed)
        return graph

    def test_shared_enabled_when_parent_a_enables(self) -> None:
        """shared defaults to false, but parent-a sets shared.enabled: true."""
        graph = self._build_and_evaluate()
        assert graph.nodes["test-values-analysis/parent-a/shared"].enabled is True

    def test_child_enabled_when_grandparent_sets_it(self) -> None:
        """child defaults to false, but grandparent sets parent-c.child.enabled: true."""
        graph = self._build_and_evaluate()
        assert graph.nodes["test-values-analysis/grandparent/parent-c/child"].enabled is True

    def test_deep_nesting_all_enabled(self) -> None:
        """level1→level2→level3→level4 chain all enabled via computed values."""
        graph = self._build_and_evaluate()
        assert graph.nodes["test-values-analysis/level1"].enabled is True
        assert graph.nodes["test-values-analysis/level1/level2"].enabled is True
        assert graph.nodes["test-values-analysis/level1/level2/level3"].enabled is True
        assert graph.nodes["test-values-analysis/level1/level2/level3/level4"].enabled is True

    def test_library_chart_evaluated(self) -> None:
        """Library charts are evaluated like any other chart."""
        graph = self._build_and_evaluate()
        lib_node = graph.nodes["test-values-analysis/library-parent/lib-chart"]
        assert lib_node.enabled is True

    def test_library_parent_enabled(self) -> None:
        """library-parent (non-library) is evaluated normally."""
        graph = self._build_and_evaluate()
        assert graph.nodes["test-values-analysis/library-parent"].enabled is True

    def test_effective_enabled_diamond(self) -> None:
        """shared at two paths: parent-a enables, parent-b disables => effective True."""
        graph = self._build_and_evaluate()
        assert effective_enabled(graph, "shared") is True

    def test_with_values_file_override(self, tmp_path: Path) -> None:
        """Values file override changes computed values."""
        from helm_analyse.graph import build_graph, get_computed_values

        values_file = tmp_path / "values.yaml"
        values_file.write_text("grandparent:\n  parent-c:\n    child:\n      enabled: false\n")
        graph = build_graph(self.FIXTURE, use_helm_build=False)
        computed = get_computed_values(self.FIXTURE, values_file=values_file)
        evaluate_conditions(graph, computed)
        assert graph.nodes["test-values-analysis/grandparent/parent-c/child"].enabled is False
