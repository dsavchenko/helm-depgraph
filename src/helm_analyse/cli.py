"""CLI entrypoint for helm-analyse."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from helm_analyse.conditions import evaluate_conditions
from helm_analyse.graph import (
    ComputedValuesError,
    build_graph,
    build_graph_from_helm_show,
    get_computed_values,
)
from helm_analyse.output import (
    format_dot,
    format_json,
    format_mermaid,
    format_plantuml,
    format_text,
    render_dot,
)


@click.command()
@click.version_option()
@click.argument("chart_path", type=click.Path(exists=True, path_type=Path))
@click.option("-f", "--values", "values_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json", "dot", "mermaid", "plantuml", "svg", "png"]),
    default="text",
    help="Output format (svg and png are rendered with Graphviz)",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write output to this file instead of stdout",
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
@click.option("--ranksep", type=float, default=1.5, help="Vertical space between ranks (DOT)")
@click.option("--nodesep", type=float, default=0.6, help="Horizontal space between nodes (DOT)")
def main(
    chart_path: Path,
    values_file: Path | None,
    output_format: str,
    output_path: Path | None,
    duplicates: bool,
    hide_libraries: bool,
    helm_bin: str,
    use_helm_show: bool,
    ranksep: float,
    nodesep: float,
) -> None:
    """Helm chart dependency graph analyser.

    Builds the dependency graph for the chart at CHART_PATH, resolves the
    tree recursively and evaluates conditions against provided values.
    """
    # Build graph
    if use_helm_show:
        graph = build_graph_from_helm_show(str(chart_path), helm_bin=helm_bin)
    else:
        graph = build_graph(chart_path, helm_bin=helm_bin)

    # Evaluate conditions against helm's computed values (values file applied by helm)
    try:
        computed = get_computed_values(chart_path, values_file, helm_bin=helm_bin)
    except ComputedValuesError as e:
        raise click.ClickException(str(e)) from e
    evaluate_conditions(graph, computed)

    # Output
    if output_format == "text":
        out = format_text(graph, show_duplicates=duplicates, hide_libraries=hide_libraries)
    elif output_format == "json":
        out = format_json(graph, hide_libraries=hide_libraries)
    elif output_format == "mermaid":
        out = format_mermaid(graph, hide_libraries=hide_libraries)
    elif output_format == "plantuml":
        out = format_plantuml(graph, hide_libraries=hide_libraries)
    else:
        dot = format_dot(graph, hide_libraries=hide_libraries, ranksep=ranksep, nodesep=nodesep)
        if output_format == "dot":
            out = dot
        else:
            try:
                image = render_dot(dot, output_format)
            except RuntimeError as e:
                raise click.ClickException(str(e)) from e
            if output_path is not None:
                output_path.write_bytes(image)
            elif output_format == "png" and sys.stdout.isatty():
                raise click.ClickException("Refusing to write PNG to a terminal; use -o FILE")
            else:
                sys.stdout.buffer.write(image)
            return

    if output_path is not None:
        output_path.write_text(out + "\n")
    else:
        click.echo(out)


if __name__ == "__main__":
    main()
