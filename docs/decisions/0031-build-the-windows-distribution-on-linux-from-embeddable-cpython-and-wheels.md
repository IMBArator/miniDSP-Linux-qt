---
status: accepted
date: 2026-09-06
decision-makers: Maximilian Zettler
---

# Build the Windows distribution on Linux from embeddable CPython and wheels

## Context and Problem Statement

[ADR-0030](0030-support-windows-by-delegating-transport-selection-to-the-protocol-library.md)
made the application run on Windows from a source checkout and deliberately
stopped there: a downloadable Windows build "is a real decision with its own
trade-offs" and "gets its own ADR". This is that ADR.

The users who need a Windows build most are the ones the project exists for —
the vendor's editor is Windows-only, and a person who owns a t.racks DSP 4x4 Mini
and a Windows laptop is not going to install `uv` and clone two repositories.
They expect a setup program or a folder with an `.exe` in it.

Two facts frame the decision. First, the maintainer's platform, the existing
packaging pipeline, and the release scripts are all Linux; there is no CI
([ADR-0028](0028-drive-releases-from-conventional-commits.md)), so a build that
needs a Windows machine would need a second machine in every release. Second,
[ADR-0004](0004-license-under-gplv3-with-lgpl-and-interop-notices.md) tells
users that Qt is dynamically linked and replaceable, and
[ADR-0027](0027-distribute-a-self-contained-appimage-with-bundled-cpython.md)
already rejected the single-file freezers on that ground — the defaults most
Windows packaging guides reach for are the ones this project cannot use.

## Decision Drivers

* The build must be producible from Linux, by the maintainer, as one `make`
  target in the existing release sequence.
* Qt must remain a set of ordinary, replaceable DLLs on disk (ADR-0004).
* The application loads its resources with `Path(__file__)` and
  `importlib.resources`, and reads its version from `importlib.metadata`; a real
  `site-packages` with `.dist-info` directories makes all of that work unchanged,
  a frozen archive breaks some of it.
* The dependency set should come from `uv.lock`, so a release ships exactly the
  versions the test suite ran against
  ([ADR-0003](0003-pin-the-protocol-library-to-a-release-wheel-via-pep-508.md),
  [ADR-0026](0026-manage-the-project-with-uv-hatchling-ruff-and-make.md)).
* The Windows PySide6-Essentials wheel is several times larger than what a
  QtWidgets application loads — it carries the whole Qt Quick/QML stack, the Qt
  tool executables, and a software-OpenGL fallback — so the download size has to
  be actively managed.
* Windows users should not need administrator rights: the protocol library uses
  the inbox HID driver, so nothing system-wide is touched (library ADR-0024).
* Anything that can be checked on Linux should be checked on Linux; what cannot
  must be an explicit, written checklist for the Windows machine.

## Considered Options

* Assemble the distribution on Linux: python.org's embeddable CPython, wheels
  installed for Windows with `uv`, a small cross-compiled launcher, an NSIS
  installer
* `pynsist`, which automates a similar assembly
* PyInstaller or Nuitka on a Windows machine or a hosted Windows runner
* Keep Windows run-from-source only

## Decision Outcome

Chosen option: **assemble the distribution on Linux**, in
`packaging/windows/build.py`, driven by `make windows`. It is the AppImage recipe
transposed: bundle an interpreter, install the project wheel and its locked
dependencies into a real `site-packages` beside it, remove what is never loaded,
wrap the result. The output is two artifacts per release — a portable zip and a
per-user NSIS installer — both required by `scripts/publish.sh`.

Several details are decisions in their own right.

**Everything comes from binary wheels, installed for Windows by `uv` on Linux.**
`uv pip install --python-platform x86_64-pc-windows-msvc --target …` resolves and
unpacks wheels for the target platform, evaluating environment markers against
it, so the protocol library's `hidapi ; sys_platform == 'win32'` dependency lands
in the tree even though the host is Linux. PySide6 ships `abi3` wheels and
`hidapi` ships CPython-tagged ones, so nothing is compiled. The requirement list
is `uv export --frozen` of the lockfile, plus the project wheel from `dist/`
installed without dependencies — the same wheel the AppImage and the release
upload use.

**The interpreter is python.org's embeddable CPython 3.13, not the AppImage's
3.11.** python.org stops publishing Windows binaries when a branch leaves bugfix
status, and 3.11 stopped at 3.11.9; only a current branch has an embeddable zip.
The project's `requires-python` allows it, PySide6's `abi3` wheels cover it, and
`hidapi` publishes matching wheels. The zip's `._pth` file lists exactly the
stdlib archive and `Lib\site-packages`, which puts CPython in isolated mode: no
`PYTHONPATH`, no `site`, no chance of a user's own Python leaking into the bundle.
The SHA-256 of the download is pinned in the script.

**PySide6 is pruned by allow-list, and the prune is proven safe on Linux.** The
script keeps the three Qt modules the application imports (`QtCore`, `QtGui`,
`QtWidgets`), the four Qt libraries they and the SVG plugins need, the MSVC
runtime DLLs, and a short list of plugins; everything else under `PySide6/` and
`shiboken6/` is deleted. Two checks guard this. The set of imported Qt modules is
re-derived from the installed application sources, so the list cannot fall behind
the code. And after pruning, the import tables of every remaining `.dll`, `.pyd`
and `.exe` are read (a small PE reader in the script, verified against `pefile`)
and the build fails if any of them names a DLL that was in the tree before the
prune and is gone after it. Windows system DLLs were never in the tree, so they
need no list. This is what makes DLL-level pruning acceptable without a Windows
machine in the loop.

**A small C launcher, cross-compiled with mingw-w64.** `minidspqt.exe` loads
`python3xx.dll` from its own directory and calls `Py_Main` with
`-m minidspqt.cli`. It is a GUI-subsystem binary, so no console flashes; it
carries the icon and version resource, so the portable zip is double-clickable;
and the process is named after the application in Task Manager. It sets no
AppUserModelID — for a single plain executable, Windows' path-derived ID is what
makes taskbar pinning work, and setting one only in the exe would break it.

**Logging falls back to a file when there is no console.** In a GUI-subsystem
process Python sets `sys.stderr` to `None`, and `logging` then drops every record
silently; an uncaught exception would end the process without a trace. `app.py`
now checks the stream — not the platform, keeping ADR-0030's "no `sys.platform`
in `minidspqt/`" invariant — and writes `minidspqt.log` under Qt's
per-application data location, with `sys.excepthook` routed to the logger. A
`minidspqt-debug.cmd` in the bundle runs the console interpreter with `-vv` for
bug reports.

**NSIS, per-user, from Linux.** `makensis` is an ordinary Debian package and
builds Windows installers natively on Linux; Inno Setup would need Wine. The
installer requests no elevation, installs under `%LOCALAPPDATA%\Programs`, writes
one Start Menu shortcut and a per-user Add/Remove entry, runs a previous copy's
uninstaller before upgrading, and on uninstall removes only what it wrote. The
QSettings key (theme choice) is left alone, as is customary.

**The pipeline is Python, not bash.** The AppImage script is bash, and this one
mirrors its step structure and log style. But this pipeline has real logic —
requirements filtering, an allow-list prune, a PE reader, a zip layout check —
that deserves unit tests, and Python's stdlib has `tomllib`, `zipfile`, `struct`
and `hashlib` built in. It runs under `uv run --no-project`, so it needs only a
stdlib interpreter and `uv`, and works in a container that has no venv.

**A dev override for unreleased library changes.** `MINIDSP_LINUX_WHEEL=<path>`
replaces the locked protocol-library requirement with a locally built wheel —
resolved with *its* dependencies, outside the lock — and the build says so
loudly. It is how this packaging was developed while the pinned wheel still
predated the Windows transport (ADR-0030's release blocker, lifted by the v1.3.0
pin in the same change set), and it remains the way to try unreleased library
changes in a bundle. A release build must not use it.

**Verification is layered.** On Linux, every build checks its own zip for the
files that must and must not be there, and runs the Qt offscreen boot under Wine
when `wine` happens to be installed — optional, and never a release gate. The
gate is a written checklist on a Windows 11 machine (installer, portable zip
extracted from Downloads, offline boot, real device, second instance showing
**Device busy**, uninstall), documented with the build.

**Unsigned.** The launcher and the installer carry no Authenticode signature, so
SmartScreen shows its "unrecognised app" dialog on first run. `osslsigncode` could
sign from Linux once a certificate exists; the README documents the click-through
until then.

### Consequences

* Good, because the whole release, both platforms included, is built on the
  maintainer's Linux machine or in a throwaway Debian container, with no second
  machine and no CI account.
* Good, because Qt ships as loose DLLs beside a real `site-packages`, so
  ADR-0004's dynamic-linking claim stays literally true on Windows, and every
  `__file__`, `importlib.resources` and `importlib.metadata` access in the
  application works exactly as in a normal install.
* Good, because the dependency set is the lockfile's, and `hidapi` arrives
  through the same marker mechanism a Windows `uv sync` would use.
* Good, because the prune brings the bundle down to a fraction of the raw wheel
  size, and the import-closure check turns "did we delete something Qt needs"
  from a Windows-only discovery into a Linux build failure.
* Bad, because the bundled interpreter differs from the AppImage's (3.13 versus
  3.11); the test suite runs on the development interpreter and neither bundle
  runs it. Mitigated by `requires-python` and `abi3`, but a real skew.
* Bad, because the import-closure check sees static imports only. Qt loads
  plugins at runtime by scanning directories, which the allow-list handles, but
  a `LoadLibrary` of an optional DLL by name would not be caught. The Windows
  checklist stays necessary.
* Bad, because a third build environment joins the Ubuntu 20.04 AppImage
  container: `nsis` and `gcc-mingw-w64` on the host or a Debian container.
* Bad, because the build is not verifiable end-to-end without a Windows machine.
  Wine helps when present; it is not proof.
* Neutral, because the release now has one more manual step and two more assets
  (ADR-0028's sequence grows), and `publish.sh` refuses to publish without them
  unless told `SKIP_WINDOWS=1`.

### Confirmation

`tests/test_windows_build.py` covers the pure parts: the `._pth` content, the
requirements filter, the prune on a fake PySide6 tree (kept, removed, refused
layouts), the DLL-closure rule with injected import tables, the PE reader on a
synthetic PE32+ image, and the zip layout check. `tests/test_headless_logging.py`
drives both logging paths by swapping `sys.stderr`. Every real build enforces the
closure check and the zip layout check on itself, and `grep` for `sys.platform`,
`fcntl` and `/dev/` under `minidspqt/` must stay empty. Before a release the
Windows 11 checklist in [Building the Windows distribution](../development.md#building-the-windows-distribution)
is walked through by hand.

## Pros and Cons of the Options

### Assemble on Linux from embeddable CPython and wheels

* Good, because it runs where everything else runs and needs only Debian packages
* Good, because it is the AppImage design again — one mental model for both
  bundles — and keeps ADR-0004's claim true
* Good, because the lockfile stays the single source of dependency truth
* Bad, because it is bespoke: a few hundred lines of pipeline the project owns
* Bad, because it cannot execute what it builds, except under Wine

### pynsist

* Good, because it does embeddable Python + wheels + NSIS from Linux out of the
  box, with a launcher
* Bad, because it resolves wheels itself from exact PyPI pins and knows nothing of
  `uv.lock`; the protocol library is a GitHub-release URL, not a PyPI package,
  and would have to be pre-downloaded and passed around the tool
* Bad, because it produces an installer only, and pruning PySide6 would happen
  outside the tool anyway
* Bad, because the hard part — cross-platform installation — is the part `uv`
  already does; pynsist would add a dependency for the easy part

### PyInstaller or Nuitka on Windows

* Good, because it is the well-trodden path with the most documentation
* Bad, because it needs a Windows machine or a hosted runner in every release,
  which ADR-0028's manual, single-machine flow does not have
* Bad, because the one-file defaults bundle Qt in a way that undermines the
  LGPL notice (ADR-0027), and the one-folder mode still hides resources behind
  hooks and `sys._MEIPASS`
* Bad, because PySide6 support in freezers is historically fragile (ADR-0027)

### Keep Windows run-from-source

* Good, because nothing new to maintain
* Bad, because it excludes exactly the users the project exists for

## More Information

* [Building the Windows distribution](../development.md#building-the-windows-distribution)
  — prerequisites, the container recipe, the dev override, the Windows checklist
* Upstream:
  [library ADR-0024](https://github.com/IMBArator/miniDSP-Linux/blob/main/docs/decisions/0024-support-windows-through-a-hidapi-transport.md)
  — the hidapi transport and its `sys_platform` marker that the cross-install
  relies on
* Amends [ADR-0004](0004-license-under-gplv3-with-lgpl-and-interop-notices.md)
  (the dynamic-linking claim now also describes the Windows tree),
  [ADR-0027](0027-distribute-a-self-contained-appimage-with-bundled-cpython.md)
  (a sibling pipeline, in Python), [ADR-0028](0028-drive-releases-from-conventional-commits.md)
  (one more step, two more assets) and [ADR-0030](0030-support-windows-by-delegating-transport-selection-to-the-protocol-library.md)
  (the packaged build it deferred); see the amendment notes there.
* Related: [ADR-0002](0002-use-pyside6-essentials-as-the-gui-toolkit.md) (the
  three Qt modules the prune keeps), [ADR-0003](0003-pin-the-protocol-library-to-a-release-wheel-via-pep-508.md)
  (the pin the dev override bypasses), [ADR-0010](0010-implement-offline-mode-as-an-in-ram-virtual-dsp.md)
  (offline mode, used by the smoke test), [ADR-0026](0026-manage-the-project-with-uv-hatchling-ruff-and-make.md)
  (`uv` and `make`)
* Expected to be revisited if a code-signing certificate is obtained, if
  Windows on ARM becomes a target (`uv` and PySide6 both support `win_arm64`;
  the embeddable zip and the mingw triple would follow), or when the AppImage
  moves to a newer CPython and the two bundles can share a version again.
