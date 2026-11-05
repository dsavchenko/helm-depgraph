"""Dependency graph model for Helm charts."""

from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml


@dataclass
class Occurrence:
    """One appearance of a chart at a specific path in the dependency tree."""

    name: str
    version: str
    repository: str | None = None
    alias: str | None = None
    chart_type: str | None = None
    conditions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    enabled: bool | None = None
    children: dict[str, Occurrence] = field(default_factory=dict)

    @property
    def scope_key(self) -> str:
        """Name of this occurrence's values scope (and path segment): alias or chart name."""
        return self.alias or self.name


@dataclass
class DependencyGraph:
    """Full dependency graph for a chart."""

    root: Occurrence
    occurrences: dict[str, Occurrence] = field(default_factory=dict)

    def flatten(self, node: Occurrence | None = None, prefix: str = "") -> None:
        """Flatten the tree into self.occurrences with full paths as keys."""
        if node is None:
            node = self.root
            self.occurrences = {}

        path = f"{prefix}/{node.scope_key}" if prefix else node.scope_key
        self.occurrences[path] = node
        for child in node.children.values():
            self.flatten(child, prefix=path)

    def occurrences_of(self, chart_name: str) -> dict[str, Occurrence]:
        """All occurrences of a chart (identified by name), keyed by path."""
        return {p: o for p, o in self.occurrences.items() if o.name == chart_name}

    def chart_versions(self, chart_name: str) -> list[str]:
        """Sorted distinct versions pinned across a chart's occurrences."""
        return sorted({o.version for o in self.occurrences_of(chart_name).values()})


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
    repo_url: str | None = None,
) -> Occurrence:
    """Create a Occurrence from parsed Chart.yaml data."""
    return Occurrence(
        name=chart_data["name"],
        version=chart_data.get("version", "0.0.0"),
        repository=repo_url or chart_data.get("repository"),
        chart_type=chart_data.get("type"),
    )


def _parse_dependency(dep: dict[str, Any]) -> Occurrence:
    """Parse a single dependency entry from Chart.yaml."""
    conditions = []
    if cond := dep.get("condition"):
        conditions = [c.strip() for c in cond.split(",")]

    return Occurrence(
        name=dep["name"],
        version=dep.get("version", "*"),
        repository=dep.get("repository"),
        alias=dep.get("alias"),
        chart_type=dep.get("type"),
        conditions=conditions,
        tags=dep.get("tags", []),
    )


def _extract_tgz(tgz_path: Path, dest_dir: Path) -> None:
    """Extract a .tgz chart archive into dest_dir, safe against path traversal."""
    dest = dest_dir.resolve()
    with tarfile.open(tgz_path, "r:gz") as tf:
        for member in tf.getmembers():
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError(f"Unsafe path in archive: {member.name}")
            if not (dest / member.name).resolve().is_relative_to(dest):
                raise ValueError(f"Unsafe path in archive: {member.name}")
        tf.extractall(dest)


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
        DependencyGraph with all occurrences.
    """
    chart_yaml = _parse_chart_yaml(chart_path / "Chart.yaml")
    root = _build_node_from_chart(chart_yaml)

    if use_helm_build:
        with contextlib.suppress(subprocess.CalledProcessError):
            _run_helm(["dependency", "build", str(chart_path)], helm_bin=helm_bin)

    # helm dependency build/update archives dependencies as .tgz files. Extract
    # any archives into a temp dir instead of modifying the original chart path.
    charts_dir: Path | None = None
    original_charts_dir = chart_path / "charts"
    if original_charts_dir.is_dir() and any(
        p.suffix == ".tgz" for p in original_charts_dir.iterdir()
    ):
        charts_dir = Path(tempfile.mkdtemp(prefix="helm-depgraph-"))

    try:
        _resolve_children(
            chart_path,
            root,
            chart_yaml,
            charts_dir=charts_dir,
            mirror_root=charts_dir,
        )
    finally:
        if charts_dir is not None:
            shutil.rmtree(charts_dir, ignore_errors=True)

    graph = DependencyGraph(root=root)
    graph.flatten()
    return graph


def _resolve_children(
    chart_path: Path,
    node: Occurrence,
    chart_yaml: dict[str, Any],
    charts_dir: Path | None = None,
    mirror_root: Path | None = None,
) -> None:
    """Recursively resolve children from the charts/ directory.

    Parses the parent's Chart.yaml dependencies list to get conditions/tags/alias,
    then matches them to subdirectories in charts/.

    Args:
        chart_path: Path to the chart directory.
        charts_dir: Optional temp directory that receives the unpacked .tgz
            archives from the top-level chart's charts/ directory, so the original
            chart path is left untouched.
        mirror_root: Temp directory holding the extracted dependency tree. Nested
            .tgz archives found inside mirrored (temp) subcharts are unpacked in
            place there; the original chart path is never modified.
    """
    original_charts_dir = chart_path / "charts"
    if not original_charts_dir.exists():
        return

    deps_list = chart_yaml.get("dependencies", [])
    deps_by_name: dict[str, dict[str, Any]] = {}
    for dep in deps_list:
        deps_by_name[dep["name"]] = dep

    # Unpack archived dependencies. Top-level archives go into the temp mirror
    # (charts_dir); nested archives found inside already-mirrored charts are
    # unpacked in place there. The original chart path is never modified.
    mirror_is_safe = mirror_root is not None and chart_path.resolve().is_relative_to(
        mirror_root.resolve()
    )
    if charts_dir is not None:
        for tgz_path in sorted(original_charts_dir.glob("*.tgz")):
            _extract_tgz(tgz_path, charts_dir)
    elif mirror_is_safe:
        for tgz_path in sorted(original_charts_dir.glob("*.tgz")):
            _extract_tgz(tgz_path, original_charts_dir)

    # Collect candidate child directories. Extracted (temp) copies win over
    # pre-existing directories of the same name; unpacked dirs without a tarball
    # counterpart are still picked up from the original charts/ directory.
    candidates: dict[str, Path] = {}
    if charts_dir is not None:
        for dep_dir in sorted(charts_dir.iterdir()):
            if dep_dir.is_dir():
                candidates[dep_dir.name] = dep_dir
    for dep_dir in sorted(original_charts_dir.iterdir()):
        if dep_dir.is_dir():
            candidates.setdefault(dep_dir.name, dep_dir)

    for dep_dir in sorted(candidates.values(), key=lambda p: p.name):
        dep_chart_yaml_path = dep_dir / "Chart.yaml"
        if not dep_chart_yaml_path.exists():
            continue

        dep_data = _parse_chart_yaml(dep_chart_yaml_path)
        child = _build_node_from_chart(dep_data)

        # Apply conditions/tags/alias from parent's dependency definition
        dep_def = deps_by_name.get(child.name, {})
        child.conditions = []
        if cond := dep_def.get("condition"):
            child.conditions = [c.strip() for c in cond.split(",")]
        child.tags = dep_def.get("tags", [])
        child.alias = dep_def.get("alias")

        node.children[child.scope_key] = child
        _resolve_children(dep_dir, child, dep_data, mirror_root=mirror_root)


def build_graph_from_helm_show(
    chart_ref: str,
    helm_bin: str = "helm",
) -> DependencyGraph:
    """Build a graph by recursively running `helm show chart`.

    Args:
        chart_ref: Chart reference (name, path, or OCI URL).
        helm_bin: Path to helm binary.

    Returns:
        DependencyGraph with all occurrences.
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
    node: Occurrence,
    helm_bin: str,
) -> None:
    """Recursively resolve children using helm show chart."""
    for dep in node.children.values():
        dep_ref = f"{dep.repository}/{dep.name}" if dep.repository else dep.name
        try:
            dep_output = _run_helm(["show", "chart", "--json", dep_ref], helm_bin=helm_bin)
            dep_data: dict[str, Any] = yaml.safe_load(dep_output)
            child = _build_node_from_chart(dep_data)
            child.conditions = dep.conditions
            child.tags = dep.tags
            child.alias = dep.alias

            node.children[child.scope_key] = child
            _resolve_children_from_helm_show(dep_ref, child, helm_bin)
        except subprocess.CalledProcessError:
            continue


# ---------------------------------------------------------------------------
# Computed values via `helm install --dry-run --debug`
# ---------------------------------------------------------------------------


class ComputedValuesError(Exception):
    """Raised when helm cannot produce the computed values for a chart."""


_COMPUTED_VALUES_RE = re.compile(
    r"^COMPUTED VALUES:\s*\n(.*?)(?=^HOOKS:|^MANIFEST:|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _parse_computed_values(helm_output: str) -> dict[str, Any]:
    """Extract the COMPUTED VALUES YAML block from ``helm install --debug`` output.

    Returns:
        The parsed values dict; an empty dict if the chart has no values.

    Raises:
        ComputedValuesError: If the section is missing or is not a YAML mapping.
    """
    match = _COMPUTED_VALUES_RE.search(helm_output)
    if match is None:
        raise ComputedValuesError("No COMPUTED VALUES section in helm output")
    raw = match.group(1).strip()
    if not raw or raw in ("{}", "null"):
        return {}
    try:
        result = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ComputedValuesError(f"Cannot parse COMPUTED VALUES: {e}") from e
    if result is None:
        return {}
    if not isinstance(result, dict):
        raise ComputedValuesError("COMPUTED VALUES is not a mapping")
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
        ComputedValuesError: If helm fails or its output has no usable values.
    """
    args = [
        "install",
        "--dry-run=client",
        "--debug",
        "-n",
        "default",
        "helm-depgraph-tmp",
        str(chart_path),
    ]
    if values_file is not None:
        args.extend(["-f", str(values_file)])

    try:
        result = subprocess.run(
            [helm_bin, *args],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as e:
        raise ComputedValuesError(f"helm binary not found: {helm_bin}") from e
    except subprocess.CalledProcessError as e:
        raise ComputedValuesError(
            f"helm install --dry-run failed (exit {e.returncode}):\n{e.stderr.strip()}"
        ) from e
    # COMPUTED VALUES is on stdout; debug logs are on stderr.
    return _parse_computed_values(result.stdout)
