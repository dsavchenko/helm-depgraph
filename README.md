# helm-analyse

CLI tool for building **Helm chart dependency graphs** and evaluating **conditional dependencies** (recursively) against merged values.

`helm-analyse` parses `Chart.yaml` dependency declarations to build the full dependency tree, then resolves `condition` and `tag` expressions against the root chart's merged values to decide whether each dependency is enabled or disabled. It renders the result as a text tree, JSON, or a Graphviz DOT graph — no manifest/template analysis.

## Features

- Recursively resolves dependency trees from `charts/` (built charts or local unpacked dirs).
- Evaluates Helm `condition` and `tag` expressions against computed values.
- Handles diamond dependencies, grandparent conditions, library charts, and aliases.
- Outputs:
  - **text** — human-readable tree with enabled/disabled status.
  - **json** — machine-readable node/edge data.
  - **dot** — Graphviz graph for rendering images.

## Requirements

- Python 3.12+
- [Helm](https://helm.sh) on `PATH` (only needed for the default condition-computation path, which uses `helm install --dry-run`).

## Installation

With [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv sync --extra dev
```

Then the `helm-analyse` command is available via `uv run`:

```bash
uv run helm-analyse --help
```

To install the CLI into your environment:

```bash
uv pip install .
```

## Usage

```bash
helm-analyse build <chart_path> [options]
```

The `build` command resolves the dependency tree for the chart at `chart_path` and evaluates its conditions against the merged values.

### Options

| Option | Default | Description |
| ------ | ------- | ----------- |
| `-f, --values <file>` | — | Values YAML file used during condition evaluation. |
| `--format <text\|json\|dot>` | `text` | Output format. |
| `--duplicates / --no-duplicates` | off | Expand the subtree of a chart every time it occurs, instead of only the first time (text output). |
| `--hide-libraries / --show-libraries` | hide | Exclude library charts from output. |
| `--helm-bin <path>` | `helm` | Path to the helm binary. |
| `--helm-show / --helm-build` | `--helm-build` | Use `helm show` instead of `helm build` for the local chart graph. |
| `--ranksep <float>` | `1.5` | Vertical space between ranks (layers) in DOT output. |
| `--nodesep <float>` | `0.6` | Horizontal space between nodes in the same rank in DOT output. |

### Examples

```bash
# Text tree (default)
helm-analyse build ./mychart

# Text tree with values
helm-analyse build ./mychart -f values.yaml

# JSON output
helm-analyse build ./mychart --format json

# DOT output
helm-analyse build ./mychart --format dot > graph.dot

# Render the DOT to an image with Graphviz
dot -Tpng graph.dot -o graph.png

# Wider layer spacing in the rendered image
helm-analyse build ./mychart --format dot --ranksep 2.0 --nodesep 0.8 | dot -Tpng -o graph.png
```

## Output formats

### text

A tree of **occurrences** (one line per place a chart appears), each annotated with its occurrence status:

- `[on]` / `[off]` — whether Helm renders this occurrence. An occurrence under an `[off]` parent is always `[off]`, even if the same chart is `[on]` elsewhere.

Aliases and library types are shown inline. Children are grouped on first, then off. Without `--duplicates`, the subtree of a chart that was already shown is collapsed to `[deduplicated]`. The summary line counts distinct **charts** by chart status (a chart is on if any of its occurrences is on).

### json

Structured representation of nodes and edges. Each node includes its name, version, alias, chart type, conditions, tags, and effective enabled status.

### dot

Graphviz DOT. Node fill and border colors encode status:

| Status | Fill | Border | Style |
| ------ | ---- | ------ | ----- |
| Enabled | `lightgreen` | `darkgreen` | filled |
| Disabled | `mistyrose` | `grey` | filled, dashed |
| Unknown | `lightgrey` | `grey` | filled, dotted |

Edges from a disabled parent to a child that stays enabled via another path are drawn `dashed`.

The DOT header includes `ranksep` and `nodesep`, which control the vertical space between dependency layers and the horizontal space between siblings when rendered (see `--ranksep` / `--nodesep`).

## How conditions are evaluated

Helm conditions are comma-separated paths; the **first path holding a boolean wins**, and missing or non-boolean paths are skipped (with a warning for non-boolean values). Tags: any tag `true` enables the dependency; otherwise any tag `false` disables it; unset tags have no effect. A decisive condition overrides tags. Library charts are evaluated like any other chart. Because condition paths are relative to the parent's values scope, `helm-analyse` merges each parent's block with the root merged values (obtained via `helm install --dry-run=client --debug`, parsed from the `COMPUTED VALUES:` block) to correctly resolve grandparent and diamond cases. If helm fails or its output has no `COMPUTED VALUES:` block, `build` exits with an error showing helm's stderr.

The two design-coupled entry points are:

- `get_computed_values(chart_path, values_file=None)` — returns the parsed root-merged values; raises `ComputedValuesError` on failure.
- `evaluate_conditions(graph, computed_values)` — applies conditions/tags to the graph.

## How the graph is built

The graph is built by parsing `Chart.yaml` files from the chart's `charts/` directory (either `helm dependency build` output or local chart directories). `Chart.yaml` values may contain Go templates; they are treated as opaque strings unless rendering is required.

## Development

```bash
# Lint, format, type-check, and test
uv run ruff format .
uv run ruff check .
uv run mypy .
uv run pytest tests/ -v
```

Or in one line:

```bash
uv run ruff format . && uv run ruff check . && uv run mypy . && uv run pytest tests/ -v
```

Run a single test:

```bash
uv run pytest tests/test_conditions.py::TestChartStatus::test_diamond_child_disabled_when_enabled_path_condition_false -v
```

### Project layout

```
src/helm_analyse/
├── __init__.py      # Package version
├── cli.py           # Click CLI (build command)
├── graph.py         # Occurrence/DependencyGraph models, helm CLI integration
├── conditions.py    # Condition/tag evaluator per Helm spec
└── output.py        # Text tree, JSON, DOT formatters
```
