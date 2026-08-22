---
status: accepted
date: 2026-04-16
decision-makers: Maximilian Zettler
---

# Make MainWindow the sole mediator between views and the device

## Context and Problem Statement

Editing one parameter can have surprisingly wide effects. Dragging a PEQ gain
knob on an output has to update the model, send a device command, mirror the
change onto every linked slave channel and send their commands too (ADR-0009),
refresh the strip's "PEQ active" indicator on both the home view and the detail
view, and — if the delay panel happens to be open — refresh its overview graph,
which shows all four outputs at once.

The widget that owns the knob has no business knowing any of that. Something has
to decide where the authority for these cross-cutting effects lives.

## Decision Drivers

* Views must stay reusable. `ChannelStrip` appears in both the home view and as
  the detail view's header, and cannot depend on which one is hosting it.
* One edit legitimately affects several widgets across two views plus the device.
* Widgets are created and destroyed as panels switch; none has a stable enough
  lifetime to coordinate the others.
* The state mirror has to be updated in lock-step with device commands, or the UI
  drifts from the device (ADR-0008).

## Considered Options

* `MainWindow` mediates: views emit intent signals, `MainWindow` owns state and dispatch
* Views hold a `DeviceThread` reference and call `request_*` directly
* A separate controller or presenter object, distinct from the window
* A global event bus that any widget can publish to and subscribe from

## Decision Outcome

Chosen option: **`MainWindow` mediates.** Views emit high-level *intent* signals
and never touch the device. `MainWindow` owns the `DeviceState` (ADR-0008) and the
`DeviceThread` (ADR-0005), and is the only place that mutates state and dispatches
`request_*` calls.

Two conventions make this workable.

**A unified channel index crosses every boundary.** Signals carry channels
0–3 for inputs and 4–7 for outputs, a single flat namespace, so a handler never
needs to know whether it was an input or output strip that emitted. The
translation to the split model layout happens in exactly one private resolver,
`DeviceState._channel_obj`, which maps 0–3 to `inputs[channel]`, 4–7 to
`outputs[channel - 4]`, and returns `None` for anything else. Because every
mutator goes through it, out-of-range indices degrade to a no-op return value
rather than an exception.

**Fan-out is centralised in named helpers.** Rather than each handler
re-deriving what to refresh, `MainWindow` has `_apply_state_to_views` to push the
current state to both views, and `_refresh_active_states` to update only the
`*_active` styling on affected strips. The latter distinction is deliberate and
subtle: it exists precisely so a live edit does **not** call silent setters on a
knob the user is currently dragging, which would fight the drag (`224afff`).

The signal path for a typical edit is: panel emits with a channel index → detail
view re-emits with the channel prepended → `MainWindow` handler mutates state via
`mutate_with_links`, dispatches one `request_*` per affected channel, then
refreshes indicators.

### Consequences

* Good, because views are genuinely reusable — `ChannelStrip` works identically
  in both hosts because it knows nothing about either.
* Good, because there is one place to read to understand what an edit does.
* Good, because state mutation and device dispatch happen adjacently, so they
  cannot drift apart.
* Good, because the flat channel index means panels and strips need no
  input-versus-output branching in their signal contracts.
* Bad, because `MainWindow` is large and accretes a handler per feature. This is
  the accepted cost: the complexity is real and concentrating it beats scattering it.
* Bad, because adding a feature touches several layers — panel signal, detail-view
  re-emit, `MainWindow` handler, `DeviceThread.request_*`. The commit history shows
  this shape repeatedly (for the compressor: `a5c8902`, `aaede02`, `8428b6b`).
* Neutral, because handlers were deliberately scaffolded ahead of their panels, so
  `_on_detail_compressor_changed` existed and worked before `CompressorPanel` had
  any controls. That kept each step small at the cost of briefly-dead code.

### Confirmation

`tests/test_channel_linking_sync.py` drives real panels end-to-end and asserts
that a single panel edit reaches every linked channel's `request_*` with identical
parameters and that the model agrees — which only passes if the mediation path is
intact. No view module imports `DSPmini` or holds a `DeviceThread`.

## Pros and Cons of the Options

### MainWindow mediates

* Good, because views stay decoupled and reusable
* Good, because cross-cutting effects live in one readable place
* Bad, because `MainWindow` grows steadily
* Bad, because a new feature threads through several layers

### Views call the thread directly

* Good, because each feature's wiring is local and short
* Bad, because every view then needs the thread, the state, and knowledge of link
  topology — reimplementing fan-out per widget
* Bad, because `ChannelStrip` could no longer serve two hosts unchanged

### A separate controller object

* Good, because it separates window chrome from mediation, which is cleaner in principle
* Neutral, because it is close to what `MainWindow` already is; the split would be
  nominal at this size
* Bad, because it adds an indirection layer without removing any coupling

### A global event bus

* Good, because publishers and subscribers are fully decoupled
* Bad, because control flow becomes untraceable — the reason an indicator changed
  would no longer be greppable
* Bad, because ordering matters here (state before dispatch), and a bus does not
  express ordering

## More Information

* `5f12b45` — initial wiring; `224afff` — the fan-out helpers and the
  deliberate split between full refresh and indicator-only refresh
* Related: ADR-0005 (the worker), ADR-0008 (the state mirror),
  ADR-0009 (link fan-out), ADR-0022 (panel composition)
