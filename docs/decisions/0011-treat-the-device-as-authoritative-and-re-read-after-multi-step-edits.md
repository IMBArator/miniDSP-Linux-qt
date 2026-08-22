---
status: accepted
date: 2026-05-10
decision-makers: Maximilian Zettler
---

# Treat the device as authoritative and re-read configuration after multi-step edits

## Context and Problem Statement

The application keeps a local mirror of device state (ADR-0008) and updates it
optimistically on every edit, because there is no synchronous read-back
(ADR-0005). For single parameter writes that is fine: the device accepts the value
and the mirror is right.

It stops being fine for operations where the device may do something other than
what was asked. Channel linking is the clear case — several commands must land in
sequence (`OP_PREPARE_LINK` then `OP_LINK` per affected channel), the firmware
enforces its own rules about which topologies are legal, and it **rejects silently**.
An optimistic mirror would then show a link that does not exist, with no error
anywhere.

Storing a preset has a similar shape: the write settles an active slot, a name,
and the full channel set, and the authoritative post-store state is whatever the
device ended up with.

## Decision Drivers

* The firmware can silently reject or alter a requested configuration.
* Multi-command operations can partially succeed.
* Users need to see what the device actually did, particularly when experimenting.
* Re-reading is too slow to do after every edit (ADR-0007), so it must be applied
  selectively.

## Considered Options

* Re-read the full configuration after multi-step or destructive operations only
* Trust optimistic local state everywhere
* Re-read after every write
* Verify by reading back only the specific fields written

## Decision Outcome

Chosen option: **re-read after multi-step or destructive operations, and trust
optimistic state for ordinary parameter edits.** The device is the authority; the
mirror is a cache that gets reconciled at the points where it is most likely to be
wrong.

`DeviceThread.request_read_config()` exists for exactly this. It re-reads the live
configuration through the preset queue and, unlike `request_load_preset`,
preserves the active slot and avoids the destructive flash-recall step — making it
suitable purely for refreshing after edits (`4925094`). Its handler explicitly
flushes pending writes first, without which the read would observe pre-write state
(see ADR-0007, where this race is described).

Three call sites use it:

* **Channel linking apply** — "send, re-read, stay open". Queue `prepare_link` for
  each new pair, `channel_link` for each changed channel, then `request_read_config()`.
  The dialog snaps to whatever the device actually committed, so a silent rejection
  is visible as the matrix bouncing back rather than as a phantom link (`5d2189f`).
* **After storing a preset** — re-read so the UI reflects the authoritative
  post-store active slot, preset name, and channel data (`dd60b2d`).
* **After copying channel settings** — the same path in both connected and offline
  mode, which is why the initial offline guard was removed (`5e55cee`, ADR-0010).

The linking dialog is non-modal specifically so this reconcile loop is usable for
trial and error (ADR-0024).

### Consequences

* Good, because silent firmware rejections become visible to the user as a
  snap-back, which is the only feedback the protocol makes possible.
* Good, because the mirror is reconciled exactly where it is most likely wrong,
  without paying read cost on ordinary edits.
* Good, because it forced a single reusable primitive rather than three ad-hoc
  refresh paths, and that primitive works identically offline.
* Bad, because "which operations warrant a re-read" is a judgement encoded at each
  call site rather than a rule the code enforces. A future multi-step operation
  could omit it and reintroduce phantom state.
* Bad, because the flush-before-read dependency is subtle. If `request_read_config`
  ever loses its explicit `_drain_pending`, every one of these call sites silently
  starts reading stale state — and in connected mode USB latency would mask it
  intermittently, which is the worst kind of bug.
* Neutral, because the user sees a brief settle: the UI shows optimistic state,
  then reconciles a moment later. Acceptable, and arguably honest.

### Confirmation

`tests/test_device_thread.py` pins the read-after-write semantics. The linking
dialog tests cover `refresh()` snap-back, asserting that the matrix re-derives from
device state rather than retaining the user's selection.

## Pros and Cons of the Options

### Re-read after multi-step and destructive operations

* Good, because it catches silent rejection where it actually happens
* Good, because ordinary edits stay fast
* Bad, because the policy is applied by convention per call site

### Trust optimistic state everywhere

* Good, because it is simplest and always feels instant
* Bad, because a silently rejected link is displayed as successful indefinitely
* Bad, because there is then no mechanism at all for detecting divergence

### Re-read after every write

* Good, because the mirror is never meaningfully stale
* Bad, because a full config read per knob movement is far too slow
* Bad, because it would defeat write coalescing (ADR-0007)

### Read back only the written fields

* Good, because it is cheaper than a full read
* Bad, because the protocol offers no per-field read; configuration comes as a page
* Bad, because it would miss side effects on *other* channels, which is exactly
  what linking produces (ADR-0009)

## More Information

* `4925094` — `request_read_config` and the flush; `5d2189f` — the linking apply
  flow; `dd60b2d` — post-store reload; `5e55cee` — offline parity
* Related: ADR-0007 (queue ordering and the flush), ADR-0009 (client-side fan-out
  is the optimistic counterpart), ADR-0024 (non-modal dialogs make snap-back usable)
