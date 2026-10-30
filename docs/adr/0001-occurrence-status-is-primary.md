# Occurrence status is primary; chart status is derived

A chart in a diamond has several occurrences, and Helm renders each one independently in its own values scope: a copy under a disabled parent never renders, even if another copy does. We therefore evaluate status per occurrence (own condition/tags, then every ancestor must be on) and derive chart status only as a summary ("on if any occurrence is on"). Earlier versions let a chart that was on elsewhere keep a disabled parent's child alive, which misreports what Helm renders.

## Consequences

- Charts are identified by `name`; aliases name occurrences and their values scopes, not charts.
- Text output is an occurrence tree; DOT draws one node per chart (chart status) and one edge per occurrence (dashed when that occurrence is off); JSON carries both lists.
