---
status: accepted
date: 2026-05-21
decision-makers: Maximilian Zettler
---

# Distribute a self-contained AppImage with a bundled CPython

## Context and Problem Statement

The target user is someone with a t.racks DSP 4x4 Mini and a Linux machine who
wants a control panel for it. They are not necessarily a Python developer. Asking
them to install Python 3.11+, create a virtual environment, and `pip install` a
wheel that pulls a dependency from a GitHub release URL is a real barrier.

The distribution problem is also harder than usual: the dependency is not on PyPI
(ADR-0003), and PySide6 is a large binary dependency with its own Qt payload.

## Decision Drivers

* End users should download one file, make it executable, and run it.
* No Python toolchain, virtual environment, or `uv` on the user's machine.
* It must run across distributions and reasonably old ones.
* The Qt LGPL notice claims dynamic linking and user-replaceable Qt, so packaging
  must keep that true (ADR-0004).

## Considered Options

* An AppImage bundling CPython compiled from source, plus PySide6 and the project wheel
* Distribution packages (`.deb`, `.rpm`, AUR)
* Flatpak
* pip installation only
* PyInstaller or Nuitka single-file binary

## Decision Outcome

Chosen option: an **AppImage bundling its own CPython**, built by
`packaging/appimage/build.sh`.

The pipeline verifies prerequisites without auto-installing them, fetches
`linuxdeploy`, `appimagetool`, and pyenv's `python-build`, compiles CPython into
`build/AppDir/usr` with `--enable-shared` and an rpath of `$ORIGIN/../lib` so the
install is relocatable, verifies the interpreter has a complete standard library,
`pip`-installs the prebuilt project wheel, strips unused Qt plugin directories and
the entire `PySide6/Qt/qml` tree, runs `linuxdeploy`, packages with `appimagetool`,
and smoke-tests the result.

Several details are decisions in their own right.

**The wheel is built on the host with `uv`; the AppImage is built in a container.**
Two steps, deliberately: `make build` on the host is fast and uses the existing dev
environment, while the container provides the old glibc. Releases are built on
Ubuntu 20.04 (glibc 2.31), because an AppImage only runs on systems with glibc at
least as new as the build host.

**`linuxdeploy` runs without its Qt plugin.** The Qt plugin needs `qmake`, which is
absent, and PySide6 already ships a complete Qt. `AppRun` wires the runtime through
`PYTHONHOME`, `LD_LIBRARY_PATH`, and `QT_PLUGIN_PATH` instead. This also keeps Qt as
ordinary replaceable shared objects, which is what makes the LGPL dynamic-linking
claim accurate (ADR-0004).

**Bundled libraries must not leak into child processes.** Clicking a link in the
About dialog forked `xdg-open`, which inherited the AppImage's `LD_LIBRARY_PATH`,
so the system browser loaded the bundled glib against the system libgobject and
crashed with `undefined symbol: g_dir_unref`. `AppRun` now snapshots the host's
`LD_LIBRARY_PATH`, `PYTHONHOME`, and Qt variables into `APPIMAGE_ORIGINAL_*` before
overriding them, and prepends a `host-wrappers/` directory to `PATH` containing an
`xdg-open` shim that restores them before exec'ing the real one (`46db139`). This is
a general hazard of the approach, not a one-off bug.

**The smoke test boots Qt, not just `--help`.** `--help` exits before Qt
initialises, so it cannot catch a missing platform plugin or a `libQt6*.so` version
mismatch. A second pass boots the GUI under the offscreen platform in offline mode
and lets `timeout --preserve-status` kill it after five seconds; exit 0 or 143 means
the event loop ran (`c34205d`). This reuses offline mode and the offscreen platform
from ADR-0010 and ADR-0025.

**Delta updates are opt-in.** Setting `APPIMAGE_UPDATE_INFO` embeds update metadata
and emits a sibling `.zsync`, so AppImageUpdate-aware clients fetch only changed
chunks rather than the full ~160 MB. Unset means no update info, which is right for
one-off local builds (`2cb2682`).

### Consequences

* Good, because installation is download, `chmod +x`, run — including `--offline`
  with no hardware.
* Good, because the non-PyPI dependency becomes invisible to users; it is resolved
  once at build time.
* Good, because building on old glibc gives wide distribution compatibility from a
  single artifact.
* Good, because Qt stays dynamically linked and replaceable, keeping the licence
  notice accurate.
* Bad, because the artifact is roughly 160 MB, mitigated but not solved by zsync.
* Bad, because release builds need a container, so the release process is not purely
  host-local.
* Bad, because compiling CPython from source makes the build slow. Mitigated by
  caching `python-build` and `linuxdeploy` under `build/cache/`, which
  `make appimage-clean` deliberately preserves.
* Bad, because environment leakage into child processes is a permanent hazard of
  bundling. The `xdg-open` shim fixes the one known case; any future subprocess
  needs the same treatment.
* Neutral, because AppImages have no automatic update mechanism or desktop
  integration by default, only what the optional zsync metadata enables.

### Confirmation

The pipeline's own smoke tests gate the build: `--help` plus an offscreen Qt boot,
with `desktop-file-validate` run against the `.desktop` file at stage time — a tool
that had been listed as a prerequisite but never actually invoked until `c34205d`.
The project version is parsed with `tomllib` using the just-built interpreter rather
than `grep | cut`, so quoting or whitespace changes in `pyproject.toml` cannot
silently break version extraction.

## Pros and Cons of the Options

### AppImage with bundled CPython

* Good, because it is a single file with no dependencies and works across distributions
* Good, because Qt remains dynamically linked, satisfying the licence notice
* Bad, because it is large, slow to build, and needs a container for releases
* Bad, because bundled-library leakage into subprocesses must be handled explicitly

### Distribution packages

* Good, because they integrate natively, with real dependency management and updates
* Bad, because they need per-distribution packaging and maintenance
* Bad, because the non-PyPI dependency is awkward to express in distro packaging
* Bad, because getting into official repositories is slow and largely out of the
  project's control

### Flatpak

* Good, because it is sandboxed, with desktop integration and real updates
* Neutral, because the runtime model would handle Qt well
* Bad, because sandboxing raw `/dev/hidraw*` access requires a permission that
  undercuts the sandbox's value
* Bad, because it adds Flatpak as a user prerequisite

### pip only

* Good, because it is trivial to publish and is offered as a secondary path
* Bad, because it requires Python 3.11+, a virtual environment, and comfort with
  installing from a URL

### PyInstaller or Nuitka single-file

* Good, because it produces a single file without compiling CPython
* Bad, because bundling Qt this way tends toward static or opaque linking, which
  would invalidate the LGPL dynamic-linking claim (ADR-0004)
* Bad, because PySide6 bundling in freezers is historically fragile

## More Information

* `3179db6` — the pipeline; `46db139` — the `xdg-open` environment leak;
  `7211814` — dropping the hardcoded Python version from `AppRun` in favour of a
  runtime glob; `c34205d` — robustness pass; `2cb2682` — zsync delta updates
* [Building the AppImage](../development.md#building-the-appimage)
* Related: ADR-0003 (dependency resolved at build time), ADR-0004 (licence
  constraint), ADR-0010 (offline mode used by the smoke test), ADR-0028 (release flow)
