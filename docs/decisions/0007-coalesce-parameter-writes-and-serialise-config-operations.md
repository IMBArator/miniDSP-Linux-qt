---
status: accepted
date: 2026-04-16
decision-makers: Maximilian Zettler
---

# Coalesce parameter writes in a keyed dict; serialise config operations in a FIFO queue

## Context and Problem Statement

Dragging a knob emits a value change per mouse-move event — potentially dozens
per second. Sending each one to the device is both pointless and harmful: the
protocol is request/response over a single handle, the device is slow, and only
the final value matters. But not every operation is like that. Recalling a preset
must not be collapsed with another recall; each one is a distinct, destructive
flash operation that also re-reads the full configuration.

So the worker (ADR-0005) needs two different queueing disciplines, and needs to
know which applies to what.

## Decision Drivers

* Rapid parameter edits must collapse to the latest value per target.
* Independent targets must not collapse into each other — a gain change on
  channel 1 and one on channel 2 are unrelated, as are two different PEQ bands.
* Preset recalls and stores are destructive and order-dependent; they must never
  be dropped or reordered.
* Some operations have a required ordering relative to each other. The protocol
  requires `OP_PREPARE_LINK` (0x2A) before `OP_LINK` (0x3B) when establishing a
  new pairing.

## Considered Options

* Two structures: a keyed dict for coalescing writes, a FIFO deque for config operations
* One FIFO queue for everything
* One FIFO queue, deduplicated at drain time
* Per-parameter debounce timers in the UI layer

## Decision Outcome

Chosen option: **two structures with different disciplines.**

`self._pending: dict[tuple, tuple]` coalesces parameter writes. The key is
`(CommandType, channel)`, extended to a third element only where a channel alone
is not specific enough: `(PEQ_BAND, channel, band)` and
`(PREPARE_LINK, master, slave)`. `TEST_TONE` is device-wide and is pinned to
channel slot 0 so the key shape stays uniform. The value is the tuple of raw
protocol arguments. Last write per key wins, under `self._lock`. There are 15
`CommandType` members, one per distinct opcode group.

`self._preset_queue: deque[tuple]` is FIFO and never coalesces. Four entry
shapes: `("load", slot)`, `("store", slot, name)`, `("read_config",)`, and
`("set_pin", pin)`.

Two consequences of this design are load-bearing and easy to break by accident.

**The pending dict's insertion order is part of the protocol contract.**
`_drain_pending` snapshots with `dict(self._pending)`, and Python's
insertion-order guarantee is what makes `PREPARE_LINK` reach the device before
`CHANNEL_LINK` for the same operation. This is a real dependency on dict ordering,
not an incidental one, and switching to any unordered container would silently
break channel linking.

**A `read_config` must flush pending writes first.** The poll loop drains the
preset queue *before* the pending dict. So a caller that queues several writes and
then a `read_config` would have the read execute first and observe stale
pre-write state. The `"read_config"` handler therefore calls `_drain_pending`
itself before `dsp.read_config()`. This was found the hard way: in offline mode
the channel-linking dialog visibly snapped back to unlinked right after Apply,
while in connected mode USB latency masked the same race intermittently
(`4925094`). ADR-0011 depends on this flush being correct.

Per poll iteration the order is: drain preset queue → bail early if a preset
operation stopped the worker → drain pending writes → poll levels → sleep 150 ms.

### Consequences

* Good, because knob drags produce one device write per 150 ms window per target
  instead of one per mouse event, with no UI-side debouncing needed.
* Good, because unrelated targets stay independent, so linked-channel fan-out
  (ADR-0009) enqueues one entry per affected channel and all of them survive.
* Good, because it composes with later features for free — graph-marker gestures
  reuse the knob path and inherit coalescing without new code (ADR-0013).
* Bad, because correctness now depends on dict insertion order, which is invisible
  at the call site and easy to break during a refactor.
* Bad, because the read-after-write flush is a special case in one branch. Any
  future operation that reads device state must remember it.
* Neutral, because coalescing means intermediate values never reach the device.
  Correct for a control surface; it would be wrong if the device needed to
  observe every step of a sweep.

### Confirmation

`tests/test_device_thread.py` pins the behaviour directly: rapid gain writes on
one channel collapse to the latest value, writes on different channels stay
separate, PEQ bands coalesce per `(channel, band)`, mute and phase do not
collide, preset loads are never coalesced, and a regression test pins the
read-after-write semantics introduced in `4925094`.

## Pros and Cons of the Options

### Keyed dict plus FIFO deque

* Good, because each operation class gets the discipline it actually needs
* Good, because the key structure makes independence explicit and greppable
* Bad, because it relies on dict insertion order for cross-command sequencing
* Bad, because the two structures need an explicit flush rule between them

### One FIFO queue for everything

* Good, because it is the simplest possible model with obvious ordering
* Bad, because a knob drag floods it with hundreds of stale writes
* Bad, because the device would spend seconds working through values the user has
  already scrolled past

### One FIFO queue, deduplicated at drain

* Good, because it preserves ordering while removing redundancy
* Neutral, because it is close to the chosen design with the key derived later
* Bad, because deduplicating a mixed queue means encoding "which entries may
  collapse" as drain-time logic rather than as a data-structure property, which
  is easier to get wrong

### UI-side debounce timers

* Good, because it keeps the worker trivial
* Bad, because it puts a timer in every widget and duplicates the policy per feature
* Bad, because it cannot coalesce writes originating from a single fan-out
  (ADR-0009), where several channels are written at once by design

## More Information

* `b129cd7` — the original coalescing design, ported from the CLI proof of concept
* `4925094` — `request_prepare_link`, `request_read_config`, and the read-after-write flush
* Related: ADR-0005 (the worker), ADR-0011 (re-read after edits),
  ADR-0013 (atomic emission), ADR-0017 (the separate blocking PIN queue)
