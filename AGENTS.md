# AGENTS.md

## Project

Python CLI tool for building Helm chart dependency graphs and analysing rendered manifests against them. Evaluates conditional dependencies recursively.

## Conventions

- **Python version**: 3.12+
- **Dependency management**: `uv` (preferred)
- **Linting**: `ruff check .`
- **Formatting**: `ruff format .`
- **Type checking**: `mypy .`
- **Testing**: `pytest` — run single test: `pytest path/to/test.py::test_name -v`

## Command order

```bash
uv run ruff format . && uv run ruff check . && uv run mypy . && uv run pytest tests/ -v
```

## Project structure

```
src/helm_analyse/
├── __init__.py      # Package version
├── cli.py           # Click CLI (build, analyse commands)
├── graph.py         # ChartNode/DependencyGraph models, helm CLI integration
├── conditions.py    # Condition/tag evaluator per Helm spec
├── manifest.py      # Manifest parser, resource-to-node mapper
└── output.py        # Text tree, JSON, DOT formatters
```

## CLI usage

```bash
# Build dependency graph
helm-analyse build <chart_path> [-f values.yaml] [--format text|json|dot] [--duplicates]

# Analyse rendered manifest against graph
helm-analyse analyse <chart_path> <manifest_path> [-f values.yaml] [--format text|json|dot]
```

## Helm-specific notes

- Graph built by parsing `Chart.yaml` files from `charts/` directory (requires `helm dependency build` or local charts).
- Condition paths are comma-separated; first valid path wins (per Helm spec).
- Tags evaluated as OR (any tag true = enabled); conditions override tags.
- Resources matched to graph nodes via `helm.sh/chart` label or `# Source:` comments.
- Chart `values.yaml` can contain Go templates — treat them as opaque strings unless rendering is required.
- Expect charts from the CTA GitLab (`gitlab.cta-observatory.org`); some may reference internal OCI registries.
