---
status: accepted
date: 2026-04-21
decision-makers: Maximilian Zettler
---

# Implement offline mode as an in-RAM VirtualDSP behind the DSPmini interface

## Context and Problem Statement

Two needs pointed the same way. Users want to build and audition configurations
without the hardware plugged in — editing a `.unt` file on a laptop, away from the
rack. And the test suite needs to exercise the full application stack without a
device (ADR-0025).

The naive approach is to make the UI aware of a disconnected state and branch:
skip device calls, keep values locally, re-enable controls. That branching would
spread across every handler in `MainWindow` and every panel.

## Decision Drivers

* Offline behaviour should be indistinguishable from connected behaviour wherever
  it can be, so bugs surface in both or neither.
* The UI must not accumulate `if offline:` branches; they would double the paths
  through every handler.
* Tests need a substitutable device with inspectable state.
* Offline edits must be persistable, which means `.unt` round-tripping (ADR-0016).

## Considered Options

* An in-RAM `VirtualDSP` duck-typing the `DSPmini` interface, injected at the same seam
* Conditional branches in the UI layer for the disconnected case
* A recorded-fixture replay layer
* No offline mode; require hardware

## Decision Outcome

Chosen option: an **in-RAM `VirtualDSP`** (`minidspqt/virtual_dsp.py`) presenting
the same public interface as `minidsp.device.DSPmini`, injected into
`DeviceThread` through the existing `dsp_factory`/`dsp_instance` parameters
(ADR-0005). Every setter mutates an internal config dict; `load_preset` and
`store_preset` manage 30 user slots.

It **duck-types rather than subclasses** `DSPmini`. It imports only
`DeviceLockedError` from the real device module. There is no shared abstract base
class: conformance is by convention and verified by the tests that run the real
application against both.

Because the worker serialises all device access (ADR-0005), `VirtualDSP` needs no
internal locking, and says so explicitly.

The consequence that justifies the whole design is that the UI has **no
offline-specific code paths**. `DeviceThread` dispatches uniformly, which is why
`VirtualDSP` carries a no-op `prepare_link` rather than the worker branching on
DSP type. When a copy-channel refresh initially guarded against offline mode, the
fix was to *remove* the guard so both paths went through
`request_read_config` → `config_loaded` → UI refresh (`5e55cee`).

Two extensions followed. `dsp_instance` is reused across reconnects while
`dsp_factory` produces a fresh object per attempt — deliberate, so in-RAM state
survives a close/open cycle whereas a real USB device gets re-opened. And runtime
mode switching (`7a1eb01`) lets the user flip between connected and offline
without restarting: online→offline seeds the virtual DSP from the device's
last-known config so editing continues against live state, while offline→online
prompts before discarding offline edits.

**The virtual DSP must mirror firmware side effects, not just accept commands.**
This is the subtlest obligation and was learned twice:

* `prepare_link` copies the master's parameters to the slave, mirroring the 0x2A
  handshake. Without it, the post-link `read_config()` returned the slaves' old
  parameters and the offline UI showed a linked group with diverging settings
  (`c650f63`). It deliberately excludes `names` (user identifiers), `routings`
  (firmware keeps routing per-channel so linked outputs can still draw from
  different inputs), `link_flags` (set separately), and the global test-tone keys.
* Lock semantics are mirrored so the PIN flow drives offline identically
  (ADR-0017): `read_config()` raises `DeviceLockedError` while locked,
  `poll_levels()` returns `None` when closed or locked so the reconnect path
  engages, and `set_lock_pin` leaves the session open because the real device ACKs
  and stays connected — closing is the worker's job (`752c861`).

Lock state is deliberately **not** persisted: it lives outside the config dict, so
it never reaches `store_preset` or `.unt` export. The `.unt` format has no field
for it, and offline is a workbench rather than a simulated device.

### Consequences

* Good, because the UI is genuinely mode-agnostic; one code path is exercised by
  both real and virtual devices.
* Good, because it doubles as the test-fixture base — `FakeDSPmini` extends
  `VirtualDSP` and adds call recording (ADR-0025), so tests run against a
  behaviourally realistic device rather than a bare mock.
* Good, because runtime switching makes it a practical workflow rather than a
  launch-time flag.
* Bad, because it is a **second implementation of device behaviour** and can
  diverge. Every firmware side effect must be discovered and mirrored by hand, and
  both known divergences were found through visible offline-only bugs rather than
  by design review.
* Bad, because duck-typing without a shared base means an interface change
  upstream produces an `AttributeError` at runtime rather than a definition-time error.
* Neutral, because `poll_levels()` returns all zeros, so meters are inert offline.
  Acceptable — there is no signal to meter.

### Confirmation

`tests/test_virtual_dsp.py` covers state persistence and load/store round-trips;
`tests/test_virtual_dsp_lock.py` covers the full lock round-trip. More
importantly, the majority of the suite runs the real `MainWindow`, `DeviceThread`,
and panels against `FakeDSPmini`, so interface conformance is verified by the
application itself rather than asserted separately.

## Pros and Cons of the Options

### In-RAM VirtualDSP at the injection seam

* Good, because the UI needs no offline awareness at all
* Good, because it serves both the offline feature and the test strategy
* Bad, because firmware side effects must be rediscovered and mirrored by hand

### Conditional branches in the UI

* Good, because no second device implementation is needed
* Bad, because it doubles the paths through every handler and every panel
* Bad, because offline-only bugs become likely precisely where branches diverge

### Recorded-fixture replay

* Good, because responses are guaranteed faithful to a real device
* Bad, because it cannot support editing — a workbench needs to accept arbitrary
  writes and reflect them, which a recording cannot
* Bad, because fixtures go stale with firmware and protocol changes

### No offline mode

* Good, because there is exactly one implementation and no divergence risk
* Bad, because the test suite would then need hardware, or a mock built anyway
* Bad, because it removes a genuinely useful workflow

## More Information

* `c8d3747` — the virtual DSP and `--offline`; `8b54dcb` — factory-defaults
  seeding (ADR-0014); `c650f63` — the `prepare_link` copy; `752c861` — lock
  semantics; `7a1eb01` — runtime mode switching
* Related: ADR-0005 (the injection seam), ADR-0009 (fan-out parity),
  ADR-0016 (`.unt` persistence), ADR-0025 (test fixtures)
