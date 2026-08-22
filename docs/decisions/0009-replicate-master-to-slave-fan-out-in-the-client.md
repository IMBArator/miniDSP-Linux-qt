---
status: accepted
date: 2026-05-11
decision-makers: Maximilian Zettler
---

# Replicate master-to-slave parameter fan-out in the client

## Context and Problem Statement

The DSP supports channel linking: channels can be grouped so that one master's
settings govern its slaves. On the wire the convention is that a master carries an
OR-bitmask of its group and slaves carry `0x00`.

The firmware does the right thing internally — when a link is created it copies
the master's parameters to the slaves, and when a master parameter changes the
slaves follow. The problem is that **it reports none of this.** There is no
telemetry, no change notification, and no per-command echo describing side
effects. The only way to observe the result is a full `read_config()`.

So after editing a master's PEQ band, the application's mirror (ADR-0008) is
correct for the master and stale for every slave, and the UI shows a linked group
with visibly diverging settings until something triggers a re-read.

## Decision Drivers

* The mirror must stay truthful, because it drives both views and all derived
  indicators (ADR-0008).
* A full `read_config()` after every knob movement is not viable — it is slow and
  would fight the coalescing design (ADR-0007).
* The rule is not one rule. Flat fields like gain differ from nested parameter
  objects like gate, crossover, and the PEQ band list.
* Link topology must not be mutated by a parameter edit, because it is memoised.

## Considered Options

* Replicate the fan-out client-side through a generic linked mutator
* Re-read the full configuration after every edit
* Show only the master's values and hide slave parameters entirely
* Duplicate the master/slave loop in each feature's handler

## Decision Outcome

Chosen option: **replicate the fan-out client-side**, through one generic
primitive in the model.

`DeviceState.mutate_with_links(channel, mutator)` runs a callable against the
channel's own state object and against every linked slave's, returning the list of
affected channels with the originating channel first. `MainWindow` then emits one
device `request_*` per affected channel with identical parameters. Because
`get_linked_slaves` returns an empty list for non-masters, calling it on a slave
correctly mutates that channel alone.

`set_field_with_links(channel, field, value)` is a thin wrapper over it for flat
attributes; `set_field` remains for single-channel mutation without fan-out.

The primitive carries a **documented contract: a mutator must touch only
parameter fields and never `link_flags`.** Link topology is memoised in
`_link_info_cache`, so a mutator that changed topology would leave the cache
describing a group that no longer exists. Topology changes go through the linking
dialog's explicit apply path instead, which re-reads afterwards (ADR-0011).

The generic form was arrived at deliberately. The first version,
`set_field_with_links`, handled only flat attributes; nested parameters would have
needed their own near-identical loop each, so the loop was lifted into
`mutate_with_links` and the flat version became a wrapper (`05e29f1`).

`VirtualDSP` mirrors the same firmware side effect, so offline mode behaves
identically — see ADR-0010.

### Consequences

* Good, because the mirror stays truthful without a read after every edit, so
  coalescing and 150 ms cadence are preserved.
* Good, because one primitive covers gate, PEQ bands, crossover, compressor,
  delay, gain, mute, and phase; a new linked feature needs a mutator lambda, not a
  new loop.
* Good, because the affected-channel list drives device dispatch and indicator
  refresh in one pass, so they cannot disagree about scope.
* Bad, because this is a **reimplementation of undocumented firmware behaviour**,
  and the two can diverge silently. If the firmware's copy rules differ from the
  assumed ones for some parameter, the UI will confidently display something the
  device does not have. This is the central risk of the decision and the reason
  for the end-to-end test suite below.
* Bad, because the no-topology-mutation contract is invisible at call sites and
  enforced only by convention and review.
* Neutral, because nested parameters must be deep-copied into fresh instances
  rather than aliased, or slaves would share a mutable object with the master.
  `copy_params` does this explicitly for `GateState`, `CrossoverState`, the
  `PEQBand` list, and `CompressorState`.

### Confirmation

`tests/test_channel_linking_sync.py` exists specifically to cover this gap. It
drives real panels end-to-end and asserts, per feature, that the device request
fires for every linked channel with identical parameters and that the model
agrees, plus that `*_active` indicators propagate to slave strips. It also pins a
related regression: crossover slope 0 must still be sent, because slope 0 *is* the
bypass command, and skipping it left the device's previous slope intact so a
hardware restart re-armed a crossover the user had just disabled (`224afff`).

## Pros and Cons of the Options

### Client-side replication via a generic mutator

* Good, because it is fast, and correct as long as the assumed rules match firmware
* Good, because one primitive serves every feature
* Bad, because it duplicates undocumented firmware behaviour that can drift

### Re-read after every edit

* Good, because the device stays the single source of truth, with no duplicated rules
* Bad, because a full config read per knob movement is far too slow
* Bad, because it would defeat write coalescing entirely

### Show only the master's values

* Good, because there is nothing to replicate and nothing to get wrong
* Bad, because the user cannot see what a slave channel is actually doing
* Bad, because it would make the linked-slave detail view useless rather than read-only

### Duplicate the loop per feature handler

* Good, because each handler is explicit and self-contained
* Bad, because the identical master/slave loop is repeated per feature and drifts
* Bad, because it is precisely the shape that `05e29f1` refactored away

## More Information

* `05e29f1` — `mutate_with_links`; `224afff` — handler adoption and the slope-0 fix;
  `44bd3b1` — the end-to-end coverage; `c650f63` — the offline mirror
* Related: ADR-0008 (the mirror and its link cache), ADR-0010 (offline parity),
  ADR-0011 (topology changes re-read), ADR-0023 (slaves are read-only in the UI)
