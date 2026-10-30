# helm-analyse

Builds the dependency graph of a Helm chart and works out which dependencies Helm would actually render for a given set of values. Helm's own behaviour is the definition of every evaluation rule here.

## Charts and occurrences

**Root chart**:
The chart the analysis starts from; the one a user would `helm install`.
_Avoid_: Top chart, main chart

**Chart**:
A Helm chart identified by its `name`. Different occurrences of one chart may pin different versions.
_Avoid_: Node, package

**Occurrence**:
One appearance of a chart at a specific position in the dependency tree, identified by its path from the root chart (e.g. `root/wms/diracx/dex`). Each occurrence is a separate instance with its own values scope and its own version.
_Avoid_: Node, instance, subchart (when the position matters)

**Alias**:
The name a parent gives to a dependency; it names the occurrence and its values scope, never the chart.

**Values scope**:
The key path under which an occurrence's values sit in the computed values, formed from the aliases (or names) along its path.
_Avoid_: Namespace, prefix

**Library chart**:
A chart that provides templates but renders no manifests of its own. Its occurrences are evaluated like any other.

**Diamond**:
A chart that has more than one occurrence in the tree.
_Avoid_: Duplicate

## Evaluation

**Computed values**:
The fully merged values Helm would render the root chart with, after combining chart defaults and user-supplied values files.
_Avoid_: Merged values, raw values

**Condition**:
A comma-separated list of value paths on a dependency, resolved in the parent's values scope; the first path holding a boolean decides, non-boolean or missing paths are skipped.

**Tag**:
A label on a dependency, looked up under the top-level `tags` key of the computed values. A dependency is turned off by tags only if at least one of its tags is `false` and none is `true`; a decisive condition overrides tags.

**Occurrence status**:
Whether a single occurrence renders: on if its own condition/tags allow it and every ancestor occurrence is on.
_Avoid_: Enabled (unqualified)

**Chart status**:
A summary derived from occurrence statuses: a chart is on if any of its occurrences is on.
_Avoid_: Effective enabled
