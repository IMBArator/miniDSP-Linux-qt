---
status: accepted
date: 2026-04-16
decision-makers: Maximilian Zettler
---

# Isolate all device I/O in a dedicated QThread worker

## Context and Problem Statement

Talking to the DSP means synchronous `ioctl`/read/write against `/dev/hidraw*`.
Individual operations are slow enough to matter — the 0x20 load-preset command
uses a 2000 ms timeout because the device reads from flash — and the UI must poll
level meters continuously to be useful, since the device does not push telemetry.

Doing any of that on the GUI thread freezes the interface. Level polling in
particular has to happen several times a second, forever, while the user is
dragging knobs.

## Decision Drivers

* Level meters need continuous polling (settled at 150 ms) for the display to
  feel live.
* Individual device operations can block for seconds; preset loads legitimately do.
* USB devices disappear mid-operation, so reconnect logic must run somewhere that
  can retry without blocking the UI.
* Device access must be serialised: the protocol is request/response over a
  single handle, so concurrent callers would interleave frames.

## Considered Options

* A dedicated `QThread` worker owning the device handle
* Synchronous calls from the GUI thread, with a `QTimer` for polling
* `asyncio` with a Qt event-loop integration
* A `QThreadPool`/`QRunnable` task per operation

## Decision Outcome

Chosen option: a **single dedicated `QThread` worker**, `DeviceThread`
(`minidspqt/device_thread.py`), which exclusively owns the device handle. No
other code touches the device.

Its `run()` loop connects, performs the initial `read_config()`, then enters
`_poll_loop`. Each iteration drains queued work, polls levels, and sleeps
`POLL_INTERVAL_MS = 150`. On failure it reconnects every
`RECONNECT_INTERVAL_MS = 2000`, giving up on a connection after
`MAX_CONSECUTIVE_FAILURES = 3` consecutive poll failures.

Communication is one-directional per edge and uses Qt signals outward, queues
inward. The worker exposes five signals: `levels_updated(dict)`,
`connection_changed(bool)`, `config_loaded(dict)`, `pin_required()`, and
`pin_result(bool, int)`. The UI never calls into the device; it calls
`request_*` methods that enqueue work (ADR-0007) and receives results as signals.

Because the worker is the sole caller, **device access is serialised by
construction**. This is load-bearing beyond the UI: `VirtualDSP` (ADR-0010)
therefore needs no internal locking at all, and says so explicitly in its
docstring.

Two details in the worker exist because of hard-won failure modes. A failed
`read_config()` during reconnect closes and reconnects immediately rather than
entering the poll loop, because a just-reconnected device is often not ready to
answer yet, and entering the loop meant burning three poll failures first
(`6b41683`). And `run()`'s poll-loop call is wrapped in `try/finally` so
`connection_changed(False)` is always emitted even if the loop tears down
unexpectedly (`9bfaec2`).

### Consequences

* Good, because the UI never blocks on device I/O, including multi-second preset loads.
* Good, because reconnect and retry live in one place with a clear lifecycle.
* Good, because serialisation is structural rather than enforced by discipline,
  which is what lets the offline DSP skip locking entirely.
* Good, because injecting the DSP object makes the whole layer testable without
  hardware (ADR-0025).
* Neutral, because every UI-to-device interaction becomes asynchronous. Callers
  cannot read back a value they just wrote; they wait for `config_loaded`. This
  shapes several later decisions, notably ADR-0011.
* Bad, because writes are inherently latency-bound by the poll cadence: a
  parameter change is sent on the next drain, up to 150 ms later. Acceptable for
  a control surface, and it is precisely what makes coalescing viable (ADR-0007).
* Bad, because state that crosses the boundary needs care. The queues are guarded
  by `self._lock`; the PIN handshake needs a separate blocking `queue.Queue`
  because the worker parks on it (ADR-0017).

### Confirmation

`tests/test_device_thread.py` drives `_drain_pending`, `_drain_preset_queue`, and
the reconnect and PIN paths directly against `FakeDSPmini`, with no real thread
and no hardware (ADR-0025). No module outside `device_thread.py` imports
`DSPmini` for use — only `main_window.py` and `app.py` reference it, to choose
which factory the worker gets.

## Pros and Cons of the Options

### Dedicated QThread worker

* Good, because it serialises access structurally and keeps the UI responsive
* Good, because signals and slots are Qt's native, well-defined thread boundary
* Bad, because all interaction becomes fire-and-forget plus a later signal

### GUI thread plus QTimer

* Good, because it is much simpler with no thread-safety concerns
* Bad, because a 2000 ms preset load visibly freezes the window
* Bad, because polling and user input contend on one thread

### asyncio with a Qt loop integration

* Good, because `await`-style code reads more naturally than queues
* Bad, because it adds an integration layer for a workload that is one serialised
  blocking device, where concurrency buys nothing
* Bad, because `hidraw` I/O is synchronous anyway, so it would need a thread underneath

### QThreadPool task per operation

* Good, because it parallelises naturally
* Bad, because parallelism is exactly wrong here — concurrent tasks would
  interleave request/response frames on one handle
* Bad, because there is no single owner for connection lifecycle or reconnect

## More Information

* `b129cd7`, `5f12b45` — the worker and its wiring
* `6b41683`, `9bfaec2` — the reconnect and teardown hardening
* Related: ADR-0006 (who talks to the worker), ADR-0007 (queue design),
  ADR-0010 (offline DSP at the same seam), ADR-0012 (error policy)
