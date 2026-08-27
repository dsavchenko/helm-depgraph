# AGENTS.md

## Project

Python CLI tool for building Helm chart dependency graphs and evaluating conditional dependencies (recursively) against merged values. No manifest analysis — a single `build` command covers condition evaluation via `get_computed_values()`.

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
├── cli.py           # Click CLI (build command)
├── graph.py         # ChartNode/DependencyGraph models, helm CLI integration
├── conditions.py    # Condition/tag evaluator per Helm spec
└── output.py        # Text tree, JSON, DOT formatters
```

## CLI usage

```bash
# Build dependency graph
helm-analyse build <chart_path> [-f values.yaml] [--format text|json|dot] [--duplicates]
```

## Helm-specific notes

- Graph built by parsing `Chart.yaml` files from `charts/` directory (requires `helm dependency build` or local charts).
- Condition paths are comma-separated; first valid path wins (per Helm spec).
- Tags evaluated as OR (any tag true = enabled); conditions override tags.
- Chart `values.yaml` can contain Go templates — treat them as opaque strings unless rendering is required.
- Merged values obtained via `helm install --dry-run=client --debug`; parse the `COMPUTED VALUES:` YAML block. Debug logs go to stderr, values to stdout.
- Condition evaluation accepts a `computed_values` param (root-merged values from helm) used in place of raw root values; combined with the prefix rule (`prefix.condition_path`) it correctly resolves grandparent and diamond cases.
- `get_computed_values(chart_path, values_file=None)` returns the parsed `COMPUTED VALUES:` block; CLI passes it to `evaluate_conditions()` via the `computed_values` keyword.
- Edit `conditions.py`/`graph.py` in sync: `evaluate_conditions(graph, values, computed_values=None)` and `get_computed_values()` are design-coupled.
