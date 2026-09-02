---
status: accepted
date: 2026-08-30
decision-makers: Maximilian Zettler
---

# Support Windows by delegating transport selection to the protocol library

## Context and Problem Statement

The device's own vendor software is Windows-only, and this project exists to give
its users a free alternative — yet the application ran on Linux only, for a reason
that was never in this repository: the protocol library opened `/dev/hidrawN`
directly and imported `fcntl` at module scope, so on Windows the import failed
before a `QApplication` could even be constructed.

Upstream fixed that in
[library ADR-0024](https://github.com/IMBArator/miniDSP-Linux/blob/main/docs/decisions/0024-support-windows-through-a-hidapi-transport.md):
byte-level HID I/O now lives behind a `Transport` interface in
`minidsp/transport.py`, with `HidrawTransport` on Linux and `HidapiTransport` on
Windows, and `default_transport()` selecting by `sys.platform`. `hidapi` is a hard
dependency gated by a `sys_platform == 'win32'` marker, and Windows binds its
inbox HID driver on its own — no driver install, no udev equivalent.

That leaves this side with a much smaller question: how much of Windows support
belongs here, and what has to change for the GUI to run there.

## Decision Drivers

* [ADR-0001](0001-build-on-the-minidsp-linux-protocol-library.md) makes the
  library the single source of protocol and transport truth; a platform branch
  here would be the first crack in that boundary.
* The audit before this change found nothing to port: no `sys.platform`, `fcntl`,
  or `/dev/` reference anywhere under `minidspqt/`, `QSettings` is already
  platform-native, `.unt` saving uses `os.fsync` + `os.replace`, and file dialogs
  are Qt's native ones.
* `DEVICE_ERRORS` in `device_thread.py` must keep matching what the library
  raises ([ADR-0012](0012-catch-only-device-and-transport-errors.md)); a second
  transport is a second source of `OSError`.
* The developer workflow had two hard Linux assumptions — a POSIX `VAR=x cmd`
  prefix in `make test`, and an absolute `/home/max/...` path to the `.unt`
  fixture — and neither is a real platform constraint.
* Distribution is a separate problem from execution, and the packaging decision
  in [ADR-0027](0027-distribute-a-self-contained-appimage-with-bundled-cpython.md)
  does not transfer to Windows unexamined.

## Considered Options

* Inherit the library's platform-selected transport and change nothing in the
  application layer
* Branch on `sys.platform` in the application and construct the transport here
* Add a Windows-specific transport or HID code path in this repository
* Stay Linux-only and document Windows as unsupported

## Decision Outcome

Chosen option: **inherit the library's transport selection**. `DSPmini()` is
constructed exactly as before, with no platform argument and no branch;
everything Windows-specific happens below the library's public API. The
application changes are limited to portability of the development workflow:

* `tests/conftest.py` sets `QT_QPA_PLATFORM=offscreen` before importing PySide6,
  and `make test` drops its POSIX env-var prefix. The variable had to be set
  somewhere; setting it in the fixture module rather than the recipe makes the
  suite headless under any runner and any shell, and `os.environ.setdefault`
  keeps an explicit override working for debugging a test against a real window.
* The `.unt` round-trip fixtures are located relative to `__file__` as a sibling
  `../miniDSP-Linux` checkout instead of an absolute home path. They kept their
  graceful skip, but they now actually run wherever the protocol library is
  cloned next to this repository — on any OS.

Two things are deliberately **not** decided here.

**Windows is supported as run-from-source, not as a download.** A packaged
Windows distributable is a real decision with its own trade-offs, and the LGPL
reasoning in [ADR-0027](0027-distribute-a-self-contained-appimage-with-bundled-cpython.md)
is exactly why it cannot be settled in passing: the licence notice in
[ADR-0004](0004-license-under-gplv3-with-lgpl-and-interop-notices.md) claims Qt
is dynamically linked and user-replaceable, which rules out the freezer defaults
most Windows packagers reach for. When that build happens it gets its own ADR.

**The dependency pin does not move yet.** The library's Windows work is on an
unreleased branch, so `pyproject.toml` still points at the v1.2.0 release wheel —
a Linux-only build. Windows therefore needs the local-checkout override already
documented for protocol development
([ADR-0003](0003-pin-the-protocol-library-to-a-release-wheel-via-pep-508.md)),
and needs it for *everything* on that platform, not only hardware access: the
pinned wheel cannot even be imported there. This is recorded as a release
blocker — publishing Windows support requires the library's v1.3.0 wheel and a
pin bump plus `uv lock`, per ADR-0003.

### Consequences

* Good, because Windows support cost this repository no platform branch at all,
  which is the strongest possible confirmation that ADR-0001 drew the library
  boundary in the right place.
* Good, because the test suite is now headless by construction rather than by
  Makefile convention, so it behaves the same under `make test`, a bare
  `uv run pytest`, an IDE runner, and PowerShell.
* Good, because the `.unt` round-trip tests — byte-identical save and
  field-level edit, the highest-value tests in the suite for a format this
  project must not corrupt — went from skipped-on-every-machine-but-one to
  running wherever the sibling checkout exists.
* Bad, because a second transport doubles the ways device I/O can fail while only
  one of them is exercised on the maintainer's usual platform, and neither is
  covered by CI (there is none).
* Bad, because Windows users get a source checkout and a manual library override
  until the pin moves, which is a far worse experience than the AppImage.
* Neutral, because `DEVICE_ERRORS` needed no change: `hidapi` failures surface as
  `OSError` just as hidraw's did, and `DeviceClosedError` subclasses `OSError` on
  both platforms.
* Neutral, because the library's single-instance guarantee is a named Win32 mutex
  on Windows rather than a `flock`. The GUI never sees the difference — a second
  instance fails to open, exactly as on Linux.

### Confirmation

The absence of platform code is the thing to keep true: `minidspqt/` must contain
no `sys.platform`, `fcntl`, or `/dev/` reference, which a grep confirms and a
review should re-check. The suite passes headless on Windows without any
environment variable set by the caller, including the `.unt` round-trip tests
against the sibling fixture, and `minidspqt --offline` boots its event loop under
the offscreen platform plugin. On-hardware confirmation on Windows — connect,
config read, a gain edit, a preset recall — rides along with the checklist the
library's ADR-0024 still has open. The lock-conflict item of that checklist is
exercised by the **Device busy** chip (ADR-0012's second amendment): holding the
DSP from a second process must produce the busy chip on both platforms, and
releasing it must reconnect on its own — which tests the named mutex and the
`hidraw` flock through the same UI path.

## Pros and Cons of the Options

### Inherit the library's transport selection

* Good, because the application stays free of platform code and the protocol
  boundary holds
* Good, because a transport fix upstream reaches the CLI and the GUI together
* Bad, because Windows support is gated on an upstream release before it can ship

### Branch on `sys.platform` in the application

* Good, because Windows could be enabled without waiting for a library release
* Bad, because the GUI would start making transport decisions, which is the one
  responsibility ADR-0001 assigns entirely to the library
* Bad, because the branch would have to be kept in step with the library's own
  selection logic forever

### Windows HID code in this repository

* Good, because it would be self-contained here
* Bad, because it duplicates reverse-engineered I/O behaviour whose failure mode
  is wrong audio rather than an error — the same argument that rejected vendoring
  the protocol in ADR-0001

### Stay Linux-only

* Good, because zero new risk and no second untested path
* Bad, because the vendor software is Windows-only, so the users with no free
  alternative at all are precisely the ones being turned away

## More Information

* Upstream:
  [library ADR-0024](https://github.com/IMBArator/miniDSP-Linux/blob/main/docs/decisions/0024-support-windows-through-a-hidapi-transport.md)
  — the `Transport` interface, the hidapi report-ID and timeout handling, and the
  named-mutex replacement for `flock`.
* Amends [ADR-0001](0001-build-on-the-minidsp-linux-protocol-library.md) and
  [ADR-0012](0012-catch-only-device-and-transport-errors.md), both of which
  describe device I/O as hidraw-specific; see the amendment notes there.
* Related: [ADR-0003](0003-pin-the-protocol-library-to-a-release-wheel-via-pep-508.md)
  (the pin and the local override), [ADR-0025](0025-test-headlessly-against-an-injected-fake-dsp.md)
  (headless testing, which the conftest change generalises),
  [ADR-0026](0026-manage-the-project-with-uv-hatchling-ruff-and-make.md) (the
  Makefile whose targets are now mostly shell-agnostic),
  [ADR-0027](0027-distribute-a-self-contained-appimage-with-bundled-cpython.md)
  (the packaging reasoning a future Windows build must answer to).
* Expected to be revisited twice: when the library's Windows release lands and the
  pin moves, and if a packaged Windows build is taken on.
