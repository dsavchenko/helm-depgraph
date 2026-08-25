"""CLI entrypoint for helm-analyse."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import yaml

from helm_analyse.conditions import evaluate_conditions
from helm_analyse.graph import build_graph, build_graph_from_helm_show
from helm_analyse.manifest import analyse_manifest
from helm_analyse.output import (
    format_dot,
    format_json,
    format_manifest_text,
    format_text,
)


@click.group()
@click.version_option()
def main() -> None:
    """Helm chart dependency graph analyser."""


@main.command()
@click.argument("chart_path", type=click.Path(exists=True, path_type=Path))
@click.option("-f", "--values", "values_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--format", "output_format", type=click.Choice(["text", "json", "dot"]), default="text"
)
@click.option("--duplicates/--no-duplicates", default=False, help="Show duplicate subcharts")
@click.option("--helm-bin", default="helm", help="Path to helm binary")
@click.option(
    "--helm-show/--helm-build",
    "use_helm_show",
    default=False,
    help="Use helm show instead of helm build",
)
def build(
    chart_path: Path,
    values_file: Path | None,
    output_format: str,
    duplicates: bool,
    helm_bin: str,
    use_helm_show: bool,
) -> None:
    """Build dependency graph for a chart.

    Resolves the dependency tree recursively and evaluates conditions
    against provided values.
    """
    # Build graph
    if use_helm_show:
        graph = build_graph_from_helm_show(str(chart_path), helm_bin=helm_bin)
    else:
        graph = build_graph(chart_path, helm_bin=helm_bin)

    # Evaluate conditions
    values: dict[str, Any] = {}
    if values_file:
        with open(values_file) as f:
            values = yaml.safe_load(f) or {}

    evaluate_conditions(graph, values)

    # Output
    if output_format == "text":
        click.echo(format_text(graph, show_duplicates=duplicates))
    elif output_format == "json":
        click.echo(format_json(graph))
    elif output_format == "dot":
        click.echo(format_dot(graph))


@main.command()
@click.argument("chart_path", type=click.Path(exists=True, path_type=Path))
@click.argument("manifest_path", type=click.Path(exists=True, path_type=Path))
@click.option("-f", "--values", "values_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--format", "output_format", type=click.Choice(["text", "json", "dot"]), default="text"
)
@click.option("--duplicates/--no-duplicates", default=False, help="Show duplicate subcharts")
@click.option("--helm-bin", default="helm", help="Path to helm binary")
def analyse(
    chart_path: Path,
    manifest_path: Path,
    values_file: Path | None,
    output_format: str,
    duplicates: bool,
    helm_bin: str,
) -> None:
    """Analyse rendered manifest against dependency graph.

    Maps resources in the manifest to their source charts and marks
    them as active or inactive based on the dependency graph.
    """
    # Build graph
    graph = build_graph(chart_path, helm_bin=helm_bin)

    # Evaluate conditions
    values: dict[str, Any] = {}
    if values_file:
        with open(values_file) as f:
            values = yaml.safe_load(f) or {}

    evaluate_conditions(graph, values)

    # Parse manifest
    with open(manifest_path) as f:
        manifest_yaml = f.read()

    mappings = analyse_manifest(manifest_yaml, graph)

    # Output
    if output_format == "text":
        click.echo(format_manifest_text(mappings, graph))
    elif output_format == "json":
        import json

        data = [
            {
                "kind": m.kind,
                "name": m.name,
                "namespace": m.namespace,
                "chart_label": m.chart_label,
                "source_comment": m.source_comment,
                "chart_node_path": m.chart_node_path,
                "chart_node_name": m.chart_node_name,
                "is_active": m.is_active,
            }
            for m in mappings
        ]
        click.echo(json.dumps(data, indent=2))
    elif output_format == "dot":
        click.echo(format_dot(graph))


if __name__ == "__main__":
    main()
