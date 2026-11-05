# helm-depgraph

CLI tool for building **Helm chart dependency graphs** and evaluating **conditional dependencies** (recursively) against merged values.

`helm-depgraph` parses `Chart.yaml` dependency declarations to build the full dependency tree, then resolves `condition` and `tag` expressions against the root chart's merged values to decide whether each dependency is enabled or disabled. It renders the result as a text tree, JSON, or a Graphviz DOT graph — no manifest/template analysis.

## Features

- Recursively resolves dependency trees from `charts/` (built charts or local unpacked dirs).
- Evaluates Helm `condition` and `tag` expressions against computed values.
- Handles diamond dependencies, grandparent conditions, library charts, and aliases.
- Outputs:
  - **text** — human-readable tree with enabled/disabled status.
  - **json** — machine-readable node/edge data.
  - **dot** — Graphviz graph for rendering images.
  - **mermaid** / **plantuml** — diagram source for Markdown renderers and PlantUML.
  - **svg** / **png** — rendered image (needs the Graphviz `dot` binary).

## Requirements

- Python 3.12+
- [Helm](https://helm.sh) on `PATH` (only needed for the default condition-computation path, which uses `helm install --dry-run`).

## Installation

With [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv sync --extra dev
```

Then the `helm-depgraph` command is available via `uv run`:

```bash
uv run helm-depgraph --help
```

To install the CLI into your environment:

```bash
uv pip install .
```

## Usage

```bash
helm-depgraph <chart_path> [options]
```

`helm-depgraph` resolves the dependency tree for the chart at `chart_path` and evaluates its conditions against the merged values.

### Options

| Option | Default | Description |
| ------ | ------- | ----------- |
| `-f, --values <file>` | — | Values YAML file used during condition evaluation. |
| `--format <text\|json\|dot\|mermaid\|plantuml\|svg\|png>` | `text` | Output format. |
| `-o, --output <file>` | stdout | Write output to a file. Needed for `png` on a terminal. |
| `--duplicates / --no-duplicates` | off | Expand the subtree of a chart every time it occurs, instead of only the first time (text output). |
| `--hide-libraries / --show-libraries` | hide | Exclude library charts from output. |
| `--helm-bin <path>` | `helm` | Path to the helm binary. |
| `--helm-show / --helm-build` | `--helm-build` | Use `helm show` instead of `helm build` for the local chart graph. |
| `--ranksep <float>` | `1.5` | Vertical space between ranks (layers) in DOT output. |
| `--nodesep <float>` | `0.6` | Horizontal space between nodes in the same rank in DOT output. |

### Examples

```bash
# Text tree (default)
helm-depgraph ./mychart

# Text tree with values
helm-depgraph ./mychart -f values.yaml

# JSON output
helm-depgraph ./mychart --format json

# DOT output
helm-depgraph ./mychart --format dot > graph.dot

# Render the DOT to an image with Graphviz
dot -Tpng graph.dot -o graph.png

# Render directly (svg/png use Graphviz)
helm-depgraph ./mychart --format svg -o graph.svg
helm-depgraph ./mychart --format png -o graph.png

# Mermaid / PlantUML source
helm-depgraph ./mychart --format mermaid > graph.mmd
helm-depgraph ./mychart --format plantuml > graph.puml

# Wider layer spacing in the rendered image
helm-depgraph ./mychart --format dot --ranksep 2.0 --nodesep 0.8 | dot -Tpng -o graph.png
```

## Output formats

### text

A tree of **occurrences** (one line per place a chart appears), each annotated with its occurrence status:

- `[on]` / `[off]` — whether Helm renders this occurrence. An occurrence under an `[off]` parent is always `[off]`, even if the same chart is `[on]` elsewhere.

Aliases and library types are shown inline. Children are grouped on first, then off. Without `--duplicates`, the subtree of a chart that was already shown is collapsed to `[deduplicated]`. The summary line counts distinct **charts** by chart status (a chart is on if any of its occurrences is on).

### json

Two flat lists:

- `occurrences` — one entry per place a chart appears, in tree order: `path`, `chart`, `alias`, `version`, `repository`, `type`, `conditions`, `tags`, and the occurrence `status` (`"on"`/`"off"`).
- `charts` — one entry per distinct chart (by name): `name`, `versions` (all versions pinned across its occurrences), `type`, and the chart `status`.

```json
{
  "occurrences": [
    {"path": "root/a/db", "chart": "postgresql", "alias": "db", "version": "15.1.0", "status": "off", ...}
  ],
  "charts": [
    {"name": "postgresql", "versions": ["15.0.0", "15.1.0"], "type": null, "status": "on"}
  ]
}
```

### dot

Graphviz DOT with **one node per chart** and **one edge per dependency** (parent chart, alias, child chart).

Nodes show the chart name and every version pinned across its occurrences (e.g. `common` / `2.1, 2.4`). When a chart has several versions, the deployed ones (at least one occurrence on) are listed one per line, with the rest in parentheses below. Fill and border encode the chart status:

| Chart status | Fill | Border | Style |
| ------------ | ---- | ------ | ----- |
| On | `lightgreen` | `darkgreen` | filled |
| Off | `mistyrose` | `grey` | filled, dashed |

An edge covers every occurrence of that dependency in the tree and is drawn `dashed` only if all of those occurrences are off. When the dependency is aliased, the edge is labelled with the alias; a chart included twice under different aliases gets two edges.

The DOT header includes `ranksep` and `nodesep`, which control the vertical space between dependency layers and the horizontal space between siblings when rendered (see `--ranksep` / `--nodesep`).

### mermaid, plantuml, svg, png

`mermaid` and `plantuml` emit the same nodes, edges and styling as `dot` (green filled = on, pink dashed = off; dashed edges when every occurrence is off; alias edge labels), as a Mermaid `flowchart TD` and a PlantUML diagram. `--ranksep` and `--nodesep` do not apply. `svg` and `png` pipe the DOT output through the Graphviz `dot` binary, so they honour `--ranksep` / `--nodesep`.

## How conditions are evaluated

Helm conditions are comma-separated paths; the **first path holding a boolean wins**, and missing or non-boolean paths are skipped (with a warning for non-boolean values). Tags: any tag `true` enables the dependency; otherwise any tag `false` disables it; unset tags have no effect. A decisive condition overrides tags. Library charts are evaluated like any other chart. Because condition paths are relative to the parent's values scope, `helm-depgraph` merges each parent's block with the root merged values (obtained via `helm install --dry-run=client --debug`, parsed from the `COMPUTED VALUES:` block) to correctly resolve grandparent and diamond cases. If helm fails or its output has no `COMPUTED VALUES:` block, `helm-depgraph` exits with an error showing helm's stderr.

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
src/helm_depgraph/
├── __init__.py      # Package version
├── cli.py           # Click CLI (single command)
├── graph.py         # Occurrence/DependencyGraph models, helm CLI integration
├── conditions.py    # Condition/tag evaluator per Helm spec
└── output.py        # Text tree, JSON, DOT, Mermaid, PlantUML, image rendering
```
