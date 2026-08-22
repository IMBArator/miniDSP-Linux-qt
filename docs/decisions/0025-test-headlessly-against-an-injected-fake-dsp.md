---
status: accepted
date: 2026-04-16
decision-makers: Maximilian Zettler
---

# Test headlessly against an injected fake DSP

## Context and Problem Statement

This is a GUI application whose entire purpose is to talk to a specific piece of
hardware that most machines do not have. A test strategy requiring either a display
server or a plugged-in DSP 4x4 Mini would be unrunnable in CI, unrunnable over SSH,
and unrunnable by any contributor without the device.

Yet the parts most worth testing are exactly the parts that touch both ends: the
command coalescing in the worker, the master-to-slave fan-out, the panel emit-and-
silent-setter contract. Testing those without a device and without a screen is the
requirement.

## Decision Drivers

* No display server, so widgets must instantiate and paint headlessly.
* No hardware, so the device must be substitutable.
* The substitute needs to be behaviourally realistic — a bare mock returning canned
  values cannot exercise read-after-write or link side effects.
* Tests must not disturb the developer's environment.

## Considered Options

* Offscreen Qt platform plugin, plus a fake DSP extending `VirtualDSP`, injected
  through the existing factory seam
* A virtual framebuffer (`xvfb-run`) with `unittest.mock` for the device
* Test only non-GUI logic, leaving widgets uncovered
* Integration tests against real hardware

## Decision Outcome

Chosen option: **offscreen Qt plus an injected fake DSP.**

Widgets run under `QT_QPA_PLATFORM=offscreen`, set by the `make test` target so no
display server is needed and the suite is safe for CI (`5472080`). `pytest` and
`pytest-qt` live in the `dev` optional-dependency group.

The device substitute is `FakeDSPmini` in `tests/conftest.py`, and the important
property is that it **extends `VirtualDSP`** (ADR-0010) rather than being a mock. It
inherits real stateful behaviour — writes are retained, `read_config` reflects them,
`prepare_link` performs the master-to-slave copy, the lock flow works — and adds
call recording on top. So a test can assert both *that* a command was issued and
*that* the resulting state is right, against a device model that behaves like the
firmware.

Injection uses the seam that already existed for offline mode: `DeviceThread`'s
`dsp_factory`/`dsp_instance` parameters (ADR-0005). No test-only hook was added to
production code.

This makes end-to-end tests practical, and the suite leans on that. Tests drive real
`MainWindow`, `DeviceThread`, and panel instances rather than units in isolation —
`tests/test_channel_linking_sync.py` drives a real `CompressorPanel` and asserts the
request reaches every linked channel. That is what gives ADR-0009's client-side
fan-out meaningful coverage.

**Tests must not touch the developer's real configuration.** `conftest.py` enables
`QStandardPaths` test mode before any `QApplication` exists, so `QSettings` and all
standard paths resolve to a throwaway location. This was a real incident: the theme
tests call `set_user_preference()`, which persists through
`QSettings("miniDSP", "minidspqt")` — the same org and app the application uses — so
running the suite overwrote `~/.config/miniDSP/minidspqt.conf` and the application
subsequently started in whatever theme the last test had set, with no user action
(`c4c68b8`).

Two smaller conventions: tests are organised one file per feature, matching the
source layout, and a `conftest` shim synthesizes `PySide6.__version__` because
`pytest-qt` reads it unconditionally while `PySide6-Essentials` does not provide it
(ADR-0002).

### Consequences

* Good, because the full suite — 480 tests as of v1.1.0 — runs on any Linux machine
  with no display and no hardware.
* Good, because the fake is behaviourally realistic, so tests catch protocol-order
  and state-propagation bugs a mock would silently accept.
* Good, because the test double and the offline feature are the same code, so
  offline mode is continuously exercised by the whole suite.
* Good, because no test-only seams exist in production code; the injection point is
  a real feature.
* Bad, because offscreen rendering cannot catch visual regressions. Nothing verifies
  that a widget actually looks right, so layout and colour bugs are found by hand.
* Bad, because `FakeDSPmini` inherits `VirtualDSP`'s assumptions. If `VirtualDSP`
  mirrors firmware incorrectly (a known risk under ADR-0010), tests will agree with
  the wrong model and pass.
* Neutral, because integration fixtures need care with worker lifecycle: several
  stop the worker *and* drain queued signals before seeding state, since
  `VirtualDSP`'s initial `config_loaded` would otherwise overwrite the test's
  assignment (`7058014`).

### Confirmation

`make test` runs the suite headlessly and is the documented workflow. A related
defensive fix belongs to this decision: `MainWindow` now auto-constructs a
`VirtualDSP` when `offline=True` is passed without an instance, because previously
such a call silently selected the real `DSPmini` factory and probed actual
hardware — which, with a locked device plugged in, flashed a real unlock dialog per
test fixture (`7058014`).

## Pros and Cons of the Options

### Offscreen Qt plus injected fake DSP

* Good, because it needs no display and no hardware
* Good, because the fake is realistic and shared with the offline feature
* Bad, because visual regressions are invisible to it

### xvfb plus unittest.mock

* Good, because a virtual framebuffer is closer to real rendering
* Bad, because it adds an external system dependency the offscreen plugin makes unnecessary
* Bad, because a mock returns canned values, so read-after-write and link side
  effects cannot be exercised at all

### Test non-GUI logic only

* Good, because it is simple and fast with no Qt in the test path
* Bad, because panels are where the emit-and-silent-setter contract lives, and
  getting that wrong causes write-on-load feedback loops (ADR-0013)
* Bad, because the fan-out that most needs coverage spans view and model

### Integration tests against real hardware

* Good, because it is the only way to verify actual firmware behaviour, including
  the assumptions in ADR-0009 and ADR-0010
* Bad, because it cannot run in CI or for most contributors
* Bad, because tests would mutate a real device's flash

## More Information

* `8459db6` — `FakeDSPmini` and the first coalescing tests; `5472080` — the
  offscreen platform; `c4c68b8` — `QStandardPaths` test-mode isolation
* Related: ADR-0002 (the `pytest-qt` shim), ADR-0005 (the injection seam),
  ADR-0010 (the fake's realistic base), ADR-0020 (the theme tests that forced isolation)
