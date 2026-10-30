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
- Condition paths are comma-separated; the first path holding a boolean wins, missing/non-boolean paths are skipped (per Helm spec).
- Tags: any tag `true` enables; otherwise any tag `false` disables; unset tags have no effect. A decisive condition overrides tags.
- Library charts are evaluated like any other chart.
- Chart `values.yaml` can contain Go templates — treat them as opaque strings unless rendering is required.
- Merged values obtained via `helm install --dry-run=client --debug`; parse the `COMPUTED VALUES:` YAML block. Debug logs go to stderr, values to stdout.
- Computed values (root-merged values from helm) are the only evaluation input; combined with the prefix rule (`prefix.condition_path`) they resolve grandparent and diamond cases.
- `get_computed_values(chart_path, values_file=None)` returns the parsed `COMPUTED VALUES:` block and raises `ComputedValuesError` (with helm's stderr) if helm fails or the block is missing/unparseable; the CLI turns that into a non-zero exit.
- Edit `conditions.py`/`graph.py` in sync: `evaluate_conditions(graph, computed_values)` and `get_computed_values()` are design-coupled.

## Agent skills

### Issue tracker

Issues and specs live as local markdown files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix` (stored as a `Status:` line in each issue file). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
