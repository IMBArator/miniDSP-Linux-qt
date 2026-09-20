---
status: accepted
date: 2026-09-20
decision-makers: Maximilian Zettler
---

# Meter from the device's 24-bit levels and decide clip on the raw sample

## Context and Problem Statement

The level meters were built from what the protocol library exposed at the time: a
16-bit level per channel, smoothed with an exponential moving average, with the
last of the 20 LED segments treated as a level zone that lit at **+15 dB** on the
smoothed value. Both halves of that turned out to be wrong.

The library's own analysis session decompiled the manufacturer's Windows editor
and bench-verified the result (upstream `3e8cc16`, `5c7793a`, `4b67af2`,
`1aa5e1f`). Three findings land directly on this GUI:

* Each channel level is really a **24-bit** linear amplitude; the value this
  project has always used is just its upper 16 bits. `parse_levels()` now returns
  `inputs24` / `outputs24` next to the legacy lists.
* The editor's red **Clip** segment lights **per channel**, on inputs and
  outputs, at `level24 >= LEVEL_CLIP_LEVEL24` — its "+11 dB" table entry, about
  +11.3 dBu once calibrated. Our +15 dB rule was both the wrong threshold and
  applied to the wrong quantity: an overload lasting one poll is averaged away by
  the EMA, and inputs at 0 dB gain sit well below +15 dB in any case, so the red
  segment was effectively dead.
* The calibration reference was off by about 6.5 dB, so every dB readout was too.

There is also a decoy: the level response's byte-27 flag, surfaced as `clip` in
the payload. It trips at a different level, covers **inputs only**, and the
editor ignores it.

The library API that fixes all this landed on upstream `main` while this change
was being built and was released as v1.4.0 before the change was committed. This
project pins a published wheel ([ADR-0003](0003-pin-the-protocol-library-to-a-release-wheel-via-pep-508.md));
the pin moved from v1.3.0, which has none of it, to v1.4.0 as part of this change.

## Decision Drivers

* A clip indicator that cannot light is worse than none: it reads as "never
  clipping" to a user setting gain structure.
* [ADR-0001](0001-build-on-the-minidsp-linux-protocol-library.md) and
  [ADR-0014](0014-source-factory-defaults-from-the-protocol-library.md) put
  device-derived numbers in the library, not in widget constants — a threshold
  transcribed from a decompiler is exactly the kind of value ADR-0014 says will
  drift silently.
* While the library release was pending, the application had to run on both
  APIs; whatever compatibility code that needed had to sit in one place so it
  could be deleted cleanly the moment the pin moved.
* Meter units are touched by three `update_levels` methods, a channel strip and
  the meter widget; a unit change that has to be applied in five places will be
  applied in four.
* Smoothing exists to make the *bar* readable. Applying it to a yes/no overload
  decision is a category error.

## Considered Options

* Feed the meters 24-bit levels and drive the red segment from a raw-sample clip
  decision, latched, behind one adapter module
* Keep the uint16 feed and only correct the threshold to the editor's clip point
* Use the payload's byte-27 `clip` flag for the red segment
* Wait for the library's v1.4.0 release and change nothing until then

## Decision Outcome

Chosen option: **24-bit feed plus a latched, raw-sample clip decision, with a
single adapter module**. Concretely:

**Meters work in 24-bit units end to end.** `LevelMeter.set_level(value,
clipping=None)` takes the 24-bit level and converts with `level24_to_dbu()`. The
EMA, peak-hold and readout logic is untouched — only the unit of the number
going in changed, and with it the resolution: ~0.0005 dB near 0 dBu instead of
~0.1 dB, which is the difference between a bar that glides and one that steps.

**Clip is decided before smoothing and held.** `set_level` evaluates the clip
condition on the raw sample — the explicit `clipping` flag from the payload when
the device parser supplied one, otherwise the library's `level24_is_clipping()` —
and latches it for `CLIP_HOLD = LED_PEAK_HOLD` frames (~1 s at the 150 ms poll
rate), mirroring the peak marker's hold so the two decay together.

**The red segment stops being a level zone.** `_db_to_segments()` now returns at
most `NUM_SEGMENTS - RED_SEGMENTS`, and the top of its scale is the clip point
itself (`_db_ceil()` = `level24_to_dbu(LEVEL_CLIP_LEVEL24)`), so the yellow zone
ends exactly where the LED lights. `_db_ceil()` is `lru_cache`d rather than a
module constant because the library loads its calibration file on first
conversion; computing it at import time would freeze the reference before the
process is fully set up.

**One adapter, one import point.** `minidspqt/levels.py` holds a frozen `ChannelLevels`
record plus `levels_from_payload()`, `level24_for()` and `clip_for()`. The views
call those three functions and nothing else; they no longer index payload lists
themselves. The same module is the only place that imports the four new library
symbols; every other module takes them *from `minidspqt.levels`*. While the
library release was pending, that import carried a fallback which reconstructed
24-bit values as `uint16 × 256` and restated the clip threshold locally, and the
single import point is what made deleting it, when the pin moved to v1.4.0 in
this same change, a one-block edit.

**The byte-27 `clip` flag is not used.** It is inputs-only and trips at an
unrelated level; the manufacturer's own editor ignores it. Using it would light
red on four channels at a level the editor calls fine, and never on the outputs.

**The pin moves with the feature.** The PEP 508 URL now points at the
minidsp-linux v1.4.0 wheel (per ADR-0003) and the lockfile follows, so no
compatibility code ships and the threshold lives only in the library.

### Consequences

* Good, because the red segment now means what the manufacturer's editor means by
  it, per channel and on outputs too, and a one-frame overload is actually seen.
* Good, because the threshold and both conversions come from the library, so an
  upstream recalibration reaches the GUI through a dependency bump
  (ADR-0001/0014) rather than a hunt for constants.
* Good, because the views got smaller: three `update_levels` methods stopped
  doing index arithmetic on payload lists and now read one normalised record.
* Neutral, because `levels_from_payload` still accepts a payload without the
  24-bit keys and scales the uint16 lists by 256. That is exact for the bits it
  has (the uint16 *is* the top of the 24-bit value) and keeps the views tolerant
  of any older payload shape at no cost; it is not a code path any supported
  library version exercises.
* Bad, because the feature is welded to a dependency bump: it is unusable
  against any published library before v1.4.0, and rolling the pin back would
  break the import rather than degrade gracefully.
* Bad, because the meter's public contract changed units silently — any future
  caller passing a uint16 value would under-read by 48 dB rather than fail.
  `levels.py` is the only supported way to produce the argument, and the
  docstrings say so.

### Confirmation

`tests/test_level_meter_clip.py` covers the adapter (24-bit keys preferred, the
legacy payload scaled, short lists reported as `None`), the raw-sample decision
(just below the clip level does not light, just at it does), the latch (a single
loud frame stays lit for exactly `CLIP_HOLD` frames while the smoothed bar never
reaches the red index — which is what proves the decision bypasses the EMA), the
device flag overriding the level in both directions, `reset()` clearing the
latch, the 24-bit resolution (two levels sharing a uint16 give different dB), and
the plumbing through `HomeView` and `RoutedMetersPanel` on both payload shapes.
Every threshold in those tests is derived from the library constant. The
reviewable invariant is the import rule: no module outside `minidspqt/levels.py`
may import `level24_to_dbu`, `level24_is_clipping` or `LEVEL_CLIP_LEVEL24` from
`minidsp.protocol`, which a grep confirms.

## Pros and Cons of the Options

### 24-bit feed with a latched raw-sample clip decision

* Good, because it matches the editor's observed behaviour on both the threshold
  and the channels it applies to
* Good, because the bar and the LED answer different questions with the
  smoothing each one needs
* Bad, because it changes the meter's unit contract and needs a compatibility
  block until the library releases

### Correct the threshold only, keep the uint16 feed

* Good, because it is a one-line change with no new module
* Bad, because the EMA still hides short overloads, which is half the defect
* Bad, because the readout keeps stepping in ~0.1 dB jumps for no reason once the
  finer data is available

### Use the payload's byte-27 `clip` flag

* Good, because it is the device's own opinion, requiring no threshold here
* Bad, because it covers inputs only, so output clipping would stay invisible
* Bad, because the manufacturer's editor ignores it, which is strong evidence it
  does not mean what its name suggests

### Wait for v1.4.0

* Good, because it avoids any interim compatibility code
* Bad, because the release is not scheduled here, and shipping a meter with a
  clip LED that cannot light in the meantime is the status quo defect

## More Information

* Upstream commits behind this change: `3e8cc16`, `5c7793a`, `4b67af2`,
  `1aa5e1f` — the 24-bit parse, the editor's meter routine recovered by
  decompilation, the clip constants and helpers, and the recalibrated reference.
  The protocol documentation for the level response is in the library's
  `analysis/protocol.md`.
* Reverses the meter half of the original implementation: "+15 dB on the smoothed
  uint16 level" as a level zone.
* Related: [ADR-0001](0001-build-on-the-minidsp-linux-protocol-library.md)
  (library as source of protocol truth),
  [ADR-0003](0003-pin-the-protocol-library-to-a-release-wheel-via-pep-508.md)
  (the pin whose next bump is this decision's ship condition),
  [ADR-0014](0014-source-factory-defaults-from-the-protocol-library.md) (why
  device-derived numbers do not live next to widgets),
  [ADR-0025](0025-test-headlessly-against-an-injected-fake-dsp.md) (the headless
  widget tests that confirm it).
* The pin bump to v1.4.0 and the deletion of the interim compatibility fallback
  happened in the same change as this record, so nothing here is pending.
