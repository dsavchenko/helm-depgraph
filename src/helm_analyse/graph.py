"""Dependency graph model for Helm charts."""

from __future__ import annotations

import contextlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml


@dataclass
class ChartNode:
    """A single chart in the dependency graph."""

    name: str
    version: str
    repository: str | None = None
    alias: str | None = None
    chart_type: str | None = None
    conditions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    enabled: bool | None = None
    parent: str | None = None
    children: dict[str, ChartNode] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return self.alias or self.name


@dataclass
class DependencyGraph:
    """Full dependency graph for a chart."""

    root: ChartNode
    nodes: dict[str, ChartNode] = field(default_factory=dict)

    def flatten(self, node: ChartNode | None = None, prefix: str = "") -> None:
        """Flatten the tree into self.nodes with full paths as keys."""
        if node is None:
            node = self.root
            self.nodes = {}

        path = f"{prefix}/{node.key}" if prefix else node.key
        self.nodes[path] = node
        for child in node.children.values():
            self.flatten(child, prefix=path)


def _run_helm(args: list[str], helm_bin: str = "helm") -> str:
    """Run a helm CLI command and return stdout."""
    result = subprocess.run(
        [helm_bin, *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _parse_chart_yaml(path: Path) -> dict[str, Any]:
    """Parse a Chart.yaml file."""
    with open(path) as f:
        result = yaml.safe_load(f)
    return cast(dict[str, Any], result)


def _build_node_from_chart(
    chart_data: dict[str, Any],
    parent: str | None = None,
    repo_url: str | None = None,
) -> ChartNode:
    """Create a ChartNode from parsed Chart.yaml data."""
    return ChartNode(
        name=chart_data["name"],
        version=chart_data.get("version", "0.0.0"),
        repository=repo_url or chart_data.get("repository"),
        chart_type=chart_data.get("type"),
        parent=parent,
    )


def _parse_dependency(dep: dict[str, Any]) -> ChartNode:
    """Parse a single dependency entry from Chart.yaml."""
    conditions = []
    if cond := dep.get("condition"):
        conditions = [c.strip() for c in cond.split(",")]

    return ChartNode(
        name=dep["name"],
        version=dep.get("version", "*"),
        repository=dep.get("repository"),
        alias=dep.get("alias"),
        chart_type=dep.get("type"),
        conditions=conditions,
        tags=dep.get("tags", []),
    )


def build_graph(
    chart_path: Path,
    helm_bin: str = "helm",
    use_helm_build: bool = True,
) -> DependencyGraph:
    """Build a dependency graph by recursively parsing Chart.yaml files.

    Args:
        chart_path: Path to the chart directory.
        helm_bin: Path to helm binary.
        use_helm_build: If True, run `helm dependency build` first.

    Returns:
        DependencyGraph with all nodes.
    """
    chart_yaml = _parse_chart_yaml(chart_path / "Chart.yaml")
    root = _build_node_from_chart(chart_yaml)

    if use_helm_build:
        with contextlib.suppress(subprocess.CalledProcessError):
            _run_helm(["dependency", "build", str(chart_path)], helm_bin=helm_bin)

    _resolve_children(chart_path, root, chart_yaml)

    graph = DependencyGraph(root=root)
    graph.flatten()
    return graph


def _resolve_children(chart_path: Path, node: ChartNode, chart_yaml: dict[str, Any]) -> None:
    """Recursively resolve children from the charts/ directory.

    Parses the parent's Chart.yaml dependencies list to get conditions/tags/alias,
    then matches them to subdirectories in charts/.
    """
    charts_dir = chart_path / "charts"
    if not charts_dir.exists():
        return

    # Build a lookup from Chart.yaml dependencies
    deps_list = chart_yaml.get("dependencies", [])
    deps_by_name: dict[str, dict[str, Any]] = {}
    for dep in deps_list:
        deps_by_name[dep["name"]] = dep

    for dep_dir in sorted(charts_dir.iterdir()):
        if not dep_dir.is_dir():
            continue

        dep_chart_yaml_path = dep_dir / "Chart.yaml"
        if not dep_chart_yaml_path.exists():
            continue

        dep_data = _parse_chart_yaml(dep_chart_yaml_path)
        child = _build_node_from_chart(dep_data, parent=node.key)

        # Apply conditions/tags/alias from parent's dependency definition
        dep_def = deps_by_name.get(child.name, {})
        child.conditions = []
        if cond := dep_def.get("condition"):
            child.conditions = [c.strip() for c in cond.split(",")]
        child.tags = dep_def.get("tags", [])
        child.alias = dep_def.get("alias")

        node.children[child.key] = child
        _resolve_children(dep_dir, child, dep_data)


def build_graph_from_helm_show(
    chart_ref: str,
    helm_bin: str = "helm",
) -> DependencyGraph:
    """Build a graph by recursively running `helm show chart`.

    Args:
        chart_ref: Chart reference (name, path, or OCI URL).
        helm_bin: Path to helm binary.

    Returns:
        DependencyGraph with all nodes.
    """
    chart_output = _run_helm(["show", "chart", "--json", chart_ref], helm_bin=helm_bin)
    chart_data: dict[str, Any] = yaml.safe_load(chart_output)
    root = _build_node_from_chart(chart_data)

    _resolve_children_from_helm_show(chart_ref, root, helm_bin)

    graph = DependencyGraph(root=root)
    graph.flatten()
    return graph


def _resolve_children_from_helm_show(
    chart_ref: str,
    node: ChartNode,
    helm_bin: str,
) -> None:
    """Recursively resolve children using helm show chart."""
    for dep in node.children.values():
        dep_ref = f"{dep.repository}/{dep.name}" if dep.repository else dep.name
        try:
            dep_output = _run_helm(["show", "chart", "--json", dep_ref], helm_bin=helm_bin)
            dep_data: dict[str, Any] = yaml.safe_load(dep_output)
            child = _build_node_from_chart(dep_data, parent=node.key)
            child.conditions = dep.conditions
            child.tags = dep.tags
            child.alias = dep.alias

            node.children[child.key] = child
            _resolve_children_from_helm_show(dep_ref, child, helm_bin)
        except subprocess.CalledProcessError:
            continue


# ---------------------------------------------------------------------------
# Computed values via `helm install --dry-run --debug`
# ---------------------------------------------------------------------------

_COMPUTED_VALUES_RE = re.compile(
    r"^COMPUTED VALUES:\s*\n(.*?)(?=^HOOKS:|^MANIFEST:|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _parse_computed_values(helm_output: str) -> dict[str, Any]:
    """Extract the COMPUTED VALUES YAML block from ``helm install --debug`` output.

    Returns:
        The parsed values dict, or an empty dict if the section is missing/empty.
    """
    match = _COMPUTED_VALUES_RE.search(helm_output)
    if match is None:
        return {}
    raw = match.group(1).strip()
    if not raw or raw in ("{}", "null"):
        return {}
    result = yaml.safe_load(raw)
    if result is None or not isinstance(result, dict):
        return {}
    return cast(dict[str, Any], result)


def get_computed_values(
    chart_path: Path,
    values_file: Path | None = None,
    helm_bin: str = "helm",
) -> dict[str, Any]:
    """Run ``helm install --dry-run=client --debug`` and return the computed values.

    The computed values are the fully merged values after Helm applies all
    chart defaults, subchart defaults, and user overrides. This is the ground
    truth for condition evaluation.

    Raises:
        subprocess.CalledProcessError: If the helm command fails.
    """
    args = [
        "install",
        "--dry-run=client",
        "--debug",
        "-n",
        "default",
        "helm-analyse-tmp",
        str(chart_path),
    ]
    if values_file is not None:
        args.extend(["-f", str(values_file)])

    result = subprocess.run(
        [helm_bin, *args],
        capture_output=True,
        text=True,
        check=True,
    )
    # COMPUTED VALUES is on stdout; debug logs are on stderr.
    return _parse_computed_values(result.stdout)
