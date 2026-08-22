---
status: accepted
date: 2026-05-07
decision-makers: Maximilian Zettler
---

# Emit multi-parameter DSP commands atomically from the panel

## Context and Problem Statement

Several DSP features are a single opcode carrying several parameters at once. The
gate command (0x3E) takes attack, release, hold, and threshold together. The
compressor command (0x30) takes ratio, knee, attack, release, and threshold. A PEQ
band write (0x33) takes gain, frequency, Q, filter type, and bypass for one band.

The UI presents these as separate knobs and combo boxes. So when the user moves
the compressor's attack knob, the application does not have an "attack" command to
send — it has to send all five values, four of which are unchanged.

This means every panel needs a defined answer to: what does one widget change
actually emit?

## Decision Drivers

* The protocol has no partial write for these opcodes; the full parameter set goes
  out or nothing does.
* The values sent must be internally consistent — a mix of new and stale values
  would write a configuration the user never asked for.
* Rapid edits must still coalesce properly (ADR-0007).
* Loading state into a panel must not trigger emissions, or opening a panel would
  write to the device.

## Considered Options

* Panels emit the full parameter tuple on any control change
* Panels emit per-control signals, with the handler assembling the full set
* Panels emit only on focus-out or an explicit Apply button
* Read the current values back from the device before each write

## Decision Outcome

Chosen option: **panels emit the full parameter tuple on any control change.** Any
widget movement re-emits every parameter for that opcode, read from the panel's own
widgets, in the opcode's argument order.

`CompressorPanel` emits `compressor_params_changed(ratio, knee, attack, release,
threshold)` whenever any of its five controls changes. `GatePanel` emits all four
gate parameters. `PEQPanel` emits per band, since the opcode is per band. Signal
argument order deliberately matches the existing `MainWindow` handler and
`request_*` signature, so adding a panel required no plumbing changes on the device
side (`a5c8902`).

The counterpart is a **silent setter** on every panel: `set_params_silently`,
`set_bands_silently`, and equivalents. These refresh every control without firing
the change signal, and are used by `DetailView.set_channel()` and the linked-channel
apply paths. Without them, populating a panel from device state would emit a write
back to the device — a feedback loop.

This composes with the coalescing design rather than fighting it. Five knob
movements produce five full tuples, all keyed identically in `_pending`
(ADR-0007), so the device receives one write with the final consistent state.

The same funnel is reused rather than duplicated for alternative input methods.
Graph-marker gestures push raw values into the relevant knobs silently and then
fire the panel's normal atomic emit, so they inherit consistency and coalescing
for free — see ADR-0022 and the marker work in `be68b24`, `1ec14da`, `5e73e15`.

### Consequences

* Good, because every device write is internally consistent by construction; there
  is no code path that can send a half-updated parameter set.
* Good, because coalescing collapses the redundancy, so the "wasteful" full-tuple
  emission costs nothing at the wire.
* Good, because new input methods reuse one funnel per panel, which is why
  marker dragging needed no new device plumbing.
* Good, because handler signatures are stable — the panel adapts to the opcode
  rather than the reverse.
* Bad, because every panel needs a silent-setter twin for each emitting path, and
  forgetting one produces a write-on-load feedback loop. This is a real trap and
  the reason silent setters are explicitly tested.
* Bad, because the panel's widgets become the source of truth at emit time. A
  widget left stale by an incomplete refresh will confidently write its stale
  value into the next emission.
* Neutral, because parameters are carried in raw protocol units (ADR-0008), so
  panels convert at the widget boundary and pass raws outward.

### Confirmation

Panel tests assert both halves explicitly. `tests/test_compressor_panel.py` covers
the unified five-value emission, and that silent setters neither emit nor break
subsequent emissions. `tests/test_peq_panel.py` covers atomic per-band emit and
silent setters. `tests/test_delay_panel.py` and `tests/test_xover_panel.py` do the
same for their panels, with the xover tests additionally covering each
marker-gesture slot's atomic emit.

## Pros and Cons of the Options

### Full tuple on any change

* Good, because writes are always internally consistent
* Good, because it matches the opcode shape exactly, so no assembly logic is needed
* Bad, because each panel needs a silent-setter counterpart

### Per-control signals assembled by the handler

* Good, because signals mirror what the user actually changed
* Bad, because the handler would need its own copy of the parameter set to fill the
  gaps, duplicating panel state and creating a second place to go stale
* Bad, because it moves opcode knowledge out of the panel that owns those widgets

### Emit on focus-out or Apply

* Good, because it minimises device traffic without relying on coalescing
* Bad, because it breaks live feedback — the graphs and the audible result should
  track a knob as it moves
* Bad, because an Apply button per panel is poor UX for a real-time control surface

### Read back before each write

* Good, because the unchanged values would be guaranteed current
* Bad, because reads are asynchronous and slow; a knob drag cannot wait on USB
* Bad, because it would serialise a read before every write in the drain loop

## More Information

* `4081d79` — gate panel, atomic emission for 0x3E; `d665602` — per-band PEQ emit
  for 0x33; `a5c8902` — compressor's five-value emit for 0x30
* Related: ADR-0007 (coalescing makes the redundancy free), ADR-0008 (raw units),
  ADR-0022 (panel composition and the shared graph funnel)
