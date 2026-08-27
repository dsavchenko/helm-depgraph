"""CLI entrypoint for helm-analyse."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import yaml

from helm_analyse.conditions import evaluate_conditions
from helm_analyse.graph import build_graph, build_graph_from_helm_show, get_computed_values
from helm_analyse.output import format_dot, format_json, format_text


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
@click.option("--hide-libraries/--show-libraries", default=True, help="Hide library charts")
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
    hide_libraries: bool,
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

    computed = get_computed_values(chart_path, values_file, helm_bin=helm_bin)
    evaluate_conditions(graph, values, computed_values=computed)

    # Output
    if output_format == "text":
        click.echo(format_text(graph, show_duplicates=duplicates, hide_libraries=hide_libraries))
    elif output_format == "json":
        click.echo(format_json(graph, hide_libraries=hide_libraries))
    elif output_format == "dot":
        click.echo(format_dot(graph, hide_libraries=hide_libraries))


if __name__ == "__main__":
    main()
