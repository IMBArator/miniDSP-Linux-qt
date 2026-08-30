---
status: accepted
date: 2026-04-16
decision-makers: Maximilian Zettler
---

# Build on the miniDSP-Linux protocol library instead of speaking USB HID directly

## Context and Problem Statement

The t.racks DSP 4x4 Mini exposes an undocumented vendor protocol over
`/dev/hidraw*`. Its opcodes, value encodings, and quirks were reverse-engineered
in the sibling project [miniDSP-Linux](https://github.com/IMBArator/miniDSP-Linux),
which ships both a CLI and an importable Python library plus a protocol
specification under `analysis/protocol.md`.

This GUI needs the same wire protocol. Either it reuses that library, or it
carries its own copy of the encoding logic.

## Decision Drivers

* The protocol is reverse-engineered and still being corrected; encodings change
  as understanding improves.
* Value encodings are not intuitive (gain raw 120 = 0 dB, crossover slope 0 = bypass,
  delay in samples at 48 kHz), so duplicating them invites silent divergence.
* Bugs found through the GUI are usually protocol bugs, and fixing them upstream
  benefits the CLI too.
* A GUI is a good exercise of the library's public API and surfaces gaps in it.

## Considered Options

* Depend on the `minidsp-linux` library and treat it as the single source of protocol truth
* Vendor a copy of the protocol code into this repository
* Reimplement the protocol independently from `analysis/protocol.md`

## Decision Outcome

Chosen option: **depend on the library**. It owns every byte that reaches the
device: opcode framing, value encoding and decoding, `parse_preset_params`,
`parse_levels`, `decode_link_groups`, `decode_routing_matrix`, the channel-name
constants, and the factory-defaults table. This repository contains no protocol
encoding of its own.

The dependency is deliberately load-bearing in both directions. When the GUI
needs something the library does not expose, the fix goes upstream and the pin
moves forward, rather than a local workaround being added here. Concrete
examples: `decode_link_groups` and `decode_routing_matrix` were added upstream
and then adopted here (`3a40012`, `f007899`, `6ca862e`); `freq_hz_to_raw` — the
inverse frequency encoder that graph-marker dragging needs — was added in
upstream 1.1.0 specifically for this project (`99e539e`); and `DeviceClosedError`
replaced a bare `AssertionError` upstream so this side could catch it properly
(`7b23114`, see ADR-0012).

### Consequences

* Good, because encodings exist once. A protocol correction fixes the CLI and the
  GUI together.
* Good, because `analysis/protocol.md` stays the authoritative specification and
  this repository can cite it rather than restate it.
* Good, because the GUI's needs drive upstream API design, which has repeatedly
  produced a better-factored library.
* Bad, because a GUI feature can be blocked on an upstream release. This happened
  visibly: PEQ marker dragging needed `freq_hz_to_raw`, which was not in the
  pinned 1.0.1 wheel, so for a period the test suite only passed with a local
  library override (see ADR-0003).
* Bad, because the coupling is tight enough that upstream breaking changes are
  felt immediately, which is why the dependency is pinned rather than ranged.

### Confirmation

No module under `minidspqt/` constructs protocol frames or converts raw values
except by calling into `minidsp.*`. The one deliberate exception is filter-curve
maths, which is display-only and never reaches the device (ADR-0015).

## Pros and Cons of the Options

### Depend on the library

* Good, because there is a single source of protocol truth
* Good, because upstream fixes arrive for free
* Bad, because feature work can be gated on an upstream release
* Bad, because the library is not on PyPI, complicating installation (ADR-0003)

### Vendor a copy

* Good, because it decouples release timing entirely
* Bad, because the copy drifts, and reverse-engineered encodings drifting silently
  is the worst possible failure mode — it produces wrong audio, not an error

### Reimplement independently

* Good, because the API could be shaped exactly to the GUI's needs
* Bad, because it duplicates the hardest and least verifiable work in the project
* Bad, because divergence between two implementations of an undocumented protocol
  is effectively undebuggable

## More Information

* Upstream protocol specification: `../miniDSP-Linux/analysis/protocol.md`
* `28da4cd` audited all 25 library methods against GUI coverage and found the
  backend chain already complete, with only detail-view UI missing — evidence
  that the library boundary was drawn in the right place.
* Related: ADR-0003 (how the dependency is pinned), ADR-0014 (factory defaults
  come from the library), ADR-0015 (the one deliberate exception).
* Amended by [ADR-0030](0030-support-windows-by-delegating-transport-selection-to-the-protocol-library.md):
  the library no longer speaks only `/dev/hidraw*`. It selects a transport by
  platform — hidraw on Linux, hidapi on Windows — so "every byte that reaches the
  device" now includes the choice of how it gets there. This side still contains
  no transport code and no platform branch.
