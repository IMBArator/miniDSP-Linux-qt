---
status: accepted
date: 2026-05-08
decision-makers: Maximilian Zettler
---

# Compose the detail view from pluggable feature panels with shared helpers

## Context and Problem Statement

The channel detail view has to present six different feature panels — gate, PEQ,
crossover, compressor, delay, and a placeholder — while switching freely between
eight channels. The complication is that **features are not available on all
channels**: gate is input-only; PEQ, crossover, compressor, and delay are
output-only.

So navigating from an input to an output while the gate panel is showing has to do
something sensible, and the panels themselves accumulate concerns that are not
about their own parameters: the read-only banner for linked slaves (ADR-0023), the
overlay checkbox row, and the per-feature Reset button.

Without a structure, each panel ends up reimplementing all of it.

## Decision Drivers

* Panels are added incrementally; the first shipped alone and five followed.
* Feature availability depends on channel type, so panel selection is conditional.
* The active feature should survive channel navigation when it remains valid.
* Cross-panel concerns must not be copy-pasted five times.
* PEQ and crossover interact, so their graphs cannot be independent.

## Considered Options

* A `QStackedWidget` of panels, an availability table, and free-function helpers
  for cross-panel concerns
* A panel base class carrying the shared behaviour by inheritance
* One monolithic detail widget with conditional sections
* A separate window or view per feature

## Decision Outcome

Chosen option: a **`QStackedWidget` of panels plus an availability table**, with
cross-panel concerns provided by **composition rather than inheritance**.

Panel selection routes through a `_show_feature_panel()` helper consulting a small
availability table. When a feature does not apply to the selected channel, a
`PlaceholderPanel` is shown instead — added as soon as the mismatch became
reachable, since selecting an output while the gate panel was open otherwise
displayed an input-only panel (`446a723`). `set_channel` preserves the active
feature across channel switches when it remains valid for the new channel type.

**Cross-panel concerns are free functions and small helper objects, not a base
class.** `_slave_lock.py` provides `install_link_banner(layout)` and
`apply_link_state(banner, is_slave, master_name, interactive)` — two functions, no
class. The panel stores the returned banner and passes its own list of interactive
widgets. `_overlay_controls.py` provides an `OverlayControls` object mirroring the
same install-and-configure shape. Both are composed by the panels that need them:
the slave lock by all five feature panels, the overlay controls by the two that
host a response graph.

**One `FreqResponseGraph` class serves both the PEQ and crossover panels, gated by
a constructor flag** rather than subclassed. It was extracted from the original
`PEQGraph` (`c03eddc`) so both panels share one summed curve — editing the
crossover updates the PEQ panel's plot and vice versa, which is correct because the
two filter stages genuinely interact.

The `feature="peq"|"xover"` flag gates interaction at the *hit-test* level:
`_hit_band` returns immediately unless the feature is `peq`, and `_hit_xover`
unless it is `xover`. So a PEQ-hosted graph can never emit crossover signals, and
vice versa — the separation is structural, not a matter of ignoring unwanted
signals. Adding crossover marker interaction meant giving each event handler an
`elif self._feature == "xover":` arm beside the existing `peq` arm, leaving the PEQ
paths untouched (`5e73e15`).

Interactive marker gestures — drag for frequency and gain, wheel for Q or slope,
double-click for bypass — flow through each panel's existing parameter-change
funnel via thin slots, so they inherit atomic emission (ADR-0013) and command
coalescing (ADR-0007) with no new device plumbing. Bypassed markers draw dim at
their last-known position rather than vanishing, so they can be re-grabbed and
re-enabled; hit-testing includes them only for double-click, so a dim marker can be
re-enabled but not dragged.

### Consequences

* Good, because adding a panel is additive: build it, add an availability entry,
  wire one signal. Five panels arrived this way without restructuring.
* Good, because shared concerns exist once, so a fix to the slave-lock banner
  applies to all five panels at once.
* Good, because composition avoids a deep panel hierarchy — panels differ enough
  that a common base class would have accumulated conditionals.
* Good, because the shared graph makes crossover-plus-PEQ summation automatic
  rather than a synchronisation problem.
* Good, because feature-flag gating at hit-test level makes cross-feature signal
  leakage structurally impossible.
* Bad, because composition is opt-in. A new panel that forgets to install the
  slave-lock banner is editable on a linked slave — a silent correctness bug that
  inheritance would have prevented.
* Bad, because `FreqResponseGraph` is large and serves two masters, with `_feature`
  branches through every event handler. Cohesive today; it would strain if a third
  host appeared.
* Neutral, because the availability table is a small hand-maintained structure
  that must be updated when a panel's channel-type applicability changes.

### Confirmation

`tests/test_detail_view_overlay.py` covers sibling-output overlay sources reaching
both graphs; `tests/test_overlay_controls.py` covers reset-on-switch, graph push,
and always-enabled behaviour; `tests/test_freq_response_graph_drag.py` covers
hit-testing including the bypassed-marker flag, drag mapping with edge clamping,
wheel, double-click, and explicitly that a PEQ graph emits no `xover_*` signals.
Feature-availability tests cover the placeholder routing.

## Pros and Cons of the Options

### QStackedWidget, availability table, composed helpers

* Good, because panels are independent and shared concerns are centralised
* Good, because it grew smoothly from one panel to six
* Bad, because helper installation is opt-in and can be forgotten

### A panel base class

* Good, because shared behaviour is inherited automatically and cannot be forgotten
* Bad, because the five panels differ substantially — one knob versus seven band
  columns versus a combo box — so the base class would fill with conditionals
* Bad, because the delay panel's cross-channel overview graph fits no shared shape

### One monolithic widget with conditional sections

* Good, because there is no plumbing between panels and host
* Bad, because it would be a very large class mixing six unrelated feature sets
* Bad, because incremental delivery would have been far harder

### A window per feature

* Good, because each feature would be fully independent
* Bad, because comparing features on one channel means juggling windows
* Bad, because the shared channel strip header and routed meters would be duplicated

## More Information

* `4081d79` — the detail view and first panel; `446a723` — availability table and
  placeholder; `c03eddc` — extracting the shared graph; `e855cf9` — the slave-lock
  helper; `edd5538` — the overlay controls; `be68b24`, `1ec14da`, `5e73e15` —
  marker interaction reusing the panel funnels
* Related: ADR-0013 (atomic emission the markers reuse), ADR-0015 (the curve
  maths), ADR-0021 (overlay colour ring), ADR-0023 (the slave lock)
