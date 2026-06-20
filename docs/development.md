# Development

Setup, testing, packaging, and release workflow for contributors.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — manages the virtual environment and dependencies
- [miniDSP-Linux](https://github.com/IMBArator/miniDSP-Linux) — protocol library (installed automatically from the pinned upstream release wheel)
- Linux with kernel HID driver — communicates via `/dev/hidraw*`
- Read/write access to `/dev/hidraw*` (see [Permissions](https://github.com/IMBArator/miniDSP-Linux-qt#permissions))

## Development environment

```bash
git clone https://github.com/IMBArator/miniDSP-Linux-qt.git
cd miniDSP-Linux-qt
uv sync              # creates .venv, installs dependencies
uv sync --extra dev  # also installs pytest for development
```

### Developing against a local protocol library

By default `minidsp-linux` is pulled from the pinned upstream release wheel.
When hacking on the protocol library in a sibling checkout, reinstall it on top
of the synced env from your local source tree:

```bash
uv pip install --reinstall --no-cache ../miniDSP-Linux/
```

`--no-cache` matters: the local version string doesn't change between edits, so
without it `uv` rebuilds from its wheel cache and your fresh changes are
silently ignored.

> **Important — run tests with `--no-sync`.** A plain `uv run pytest` (and the
> `make test` target) first resyncs the env to the lockfile, which reverts the
> override back to the pinned release wheel. While testing against local protocol
> changes, run with sync disabled so your reinstall sticks:
>
> ```bash
> QT_QPA_PLATFORM=offscreen uv run --no-sync pytest
> ```

The override is reverted by the next `uv sync` / `uv lock` (or any plain
`uv run`). Re-run the reinstall whenever you want to test fresh local changes.

## Running tests

The suite uses `pytest` and `pytest-qt`, which ship in the `dev`
optional-dependency group. Install them once with:

```bash
make sync            # runs `uv sync --extra dev`
```

Then run the tests:

```bash
make test            # QT_QPA_PLATFORM=offscreen uv run pytest -v
```

`make test` sets `QT_QPA_PLATFORM=offscreen` so the Qt widgets run headless —
no display server required, which also makes it safe for CI.

480 tests covering the device thread, model, virtual DSP, preset picker, routing matrix, PEQ panel, crossover panel, the "show other outputs" graph overlay, the About dialog, compressor panel + graph, delay panel + graph, channel-linking dialog, channel-linking sync (master → slave fan-out), runtime offline-mode switching, param knob widget, and .unt read/write round-trip.

## Building the AppImage

A self-contained AppImage — a single executable file bundling its own CPython 3.11 and PySide6 — can be built locally. End users only need to download the resulting `.AppImage`, make it executable, and run it. No Python, no `uv`, no virtualenv on the user's machine.

Two steps: build the project wheel on the host with `uv` (fast, uses your dev venv), then build the AppImage in a container which downloads pyenv's `python-build`, compiles CPython from source into an `AppDir`, installs that wheel, and runs `linuxdeploy` + `appimagetool`.

**Step 1 — build the wheel on the host:**

```bash
make build      # produces dist/minidsp_linux_qt-<version>-py3-none-any.whl via uv
```

**Step 2a — Docker/Podman build** (recommended for releases — Ubuntu 20.04, glibc 2.31):

```bash
podman run --rm -v "$PWD":/src -w /src docker.io/library/ubuntu:20.04 bash -c \
    "bash packaging/appimage/init_environment.sh && make appimage"
# AppImage lands in ./dist/ on the host.
```

Replace `podman` with `docker` if that's what you have. With rootless Podman, add `--userns=keep-id` so `dist/` ends up owned by your host user.

For an interactive session (faster iteration, keeps the apt/pyenv install warm):

```bash
podman run --rm -it -v "$PWD":/src -w /src docker.io/library/ubuntu:20.04 bash
# inside the container, once:
bash packaging/appimage/init_environment.sh
# then, every time you want to (re)build (after `make build` on the host):
make appimage
exit
```

**Step 2b — native build** (without a container, whatever your host glibc is — fine for development):

```bash
bash packaging/appimage/init_environment.sh   # one-time, may prompt for sudo
make appimage                                  # produces dist/minidspqt-<version>-x86_64.AppImage
```

The resulting AppImage only runs on systems with a glibc at least as new as your build host.

`make appimage-clean` removes only the AppDir, the Python build tree, and `dist/*.AppImage`, leaving the `python-build` and `linuxdeploy` downloads cached under `build/cache/` so subsequent rebuilds are fast.

### Delta updates (optional)

Set `APPIMAGE_UPDATE_INFO` before `make appimage` to embed update metadata into the AppImage and emit a sibling `.zsync` file. AppImageUpdate-aware clients can then download only the chunks that changed between versions instead of the full ~160 MB.

For a GitHub-Releases-hosted artifact, run a native build with:

```bash
APPIMAGE_UPDATE_INFO="gh-releases-zsync|<owner>|<repo>|latest|minidspqt-*-x86_64.AppImage.zsync" \
    make appimage
# dist/ now also contains minidspqt-<version>-x86_64.AppImage.zsync
```

…or, inside the Podman/Docker container, pass the value via `-e` **without** adding inner double quotes (the single quotes around the whole `-e` argument already protect the `|` and `*` from the host shell — extra inner quotes end up *inside* the env var and `appimagetool` rejects the result as "unknown format"):

```bash
podman run --rm \
    -e 'APPIMAGE_UPDATE_INFO=gh-releases-zsync|<owner>|<repo>|latest|minidspqt-*-x86_64.AppImage.zsync' \
    -v "$PWD":/src -w /src docker.io/library/ubuntu:20.04 bash -c \
    "bash packaging/appimage/init_environment.sh && make appimage"
```

Upload both files (`.AppImage` and `.AppImage.zsync`) as release assets. Without `APPIMAGE_UPDATE_INFO`, no `.zsync` is produced and the AppImage carries no update info — that's the right choice for one-off local builds.

## Releasing

The release flow uses two helper scripts under [`scripts/`](https://github.com/IMBArator/miniDSP-Linux-qt/tree/main/scripts), wired into the Makefile:

```bash
# 1. Bump version in pyproject.toml, regenerate CHANGELOG.md (git-cliff),
#    commit `chore(release): vX.Y.Z`, tag vX.Y.Z, optionally push.
make version VERSION=X.Y.Z

# 2. Push the commit + tag if you skipped the prompt above.
git push && git push origin vX.Y.Z

# 3. Build the artifacts that publish.sh will attach.
make build           # wheel + sdist
make appimage        # AppImage (requires Ubuntu 20.04 build env or container)

# 4. Create the GitHub Release, upload wheel + sdist + AppImage (+ .zsync
#    if present), and deploy docs to GitHub Pages. Needs GITHUB_TOKEN
#    (PAT with `repo` scope) in the environment.
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
make publish         # or: make publish VERSION=X.Y.Z
```

Release notes are extracted from the `## [X.Y.Z]` section of the [Changelog](changelog.md), which `make version` regenerates from Conventional Commits via [`cliff.toml`](https://github.com/IMBArator/miniDSP-Linux-qt/blob/main/cliff.toml). Tags matching `-rc`, `-beta`, or `-alpha` are auto-flagged as prereleases.

## Repository structure

```
minidspqt/                     Main package
  cli.py                       Entry point: -v/--offline flags
  app.py                       QApplication setup, theme manager binding, offline seeding
  theme.py                     Theme registry (DARK_THEME / LIGHT_THEME) and ThemeManager singleton
  model.py                     Typed device state (DeviceState dataclass)
  device_thread.py             QThread: poll loop, command coalescing, preset queue
  virtual_dsp.py               In-RAM DSP implementing DSPmini interface
  blank_seed.py                Bundled blank.unt seed helper (shared by app + runtime mode switch)
  unt_loader.py                Parse .unt files (single-slot and all-slots)
  unt_writer.py                Write .unt files with field-level overwrites
  views/
    main_window.py             Main window: owns thread, state, Recall/Store, channel-linking apply flow
    home_view.py               8 channel strips + routing matrix + level meters
    preset_picker.py           Recall/Store preset dialog (F00 + 30 user slots)
    device_pin_dialog.py       UnlockPinDialog + SetPinDialog for the device-lock feature
    channel_linking_dialog.py  Triangular radio matrices for input/output channel linking
    channel_strip.py           ChannelStrip + InputChannelStrip / OutputChannelStrip
    detail_view.py             Per-channel detail view with feature panels and routed meters
    panels/
      gate_panel.py            Gate parameters (threshold, attack, hold, release) + transfer graph
      peq_panel.py             7 bands × (Type / Freq / Gain / Q / Byp) + channel bypass + summed-response graph
      xover_panel.py           Hi-Pass / Lo-Pass crossover (freq + slope + bypass) + shared response graph
      compressor_panel.py      Threshold / Ratio (combo) / Knee / Attack / Release + transfer-function graph
      delay_panel.py           Single edit knob for the displayed output + overview graph of all four delays
      _slave_lock.py           Shared "Linked to <master> — read-only" banner used by every feature panel
      _overlay_controls.py     Shared "show other outputs" overlay checkboxes for the PEQ + Xover graphs
      placeholder_panel.py     Shown when the active feature is N/A for the selected channel
  widgets/                     Custom Qt widgets (CompressorGraph, DelayGraph, FreqResponseGraph, GateGraph, LedIndicator, LevelMeter, ParamKnob, PEQGraph, RoutingMatrix, ToggleButton)
  resources/                   blank.unt template, icons, style_dark.qss + style_light.qss (selected by ThemeManager)

tests/                         pytest suite (480 tests)
  conftest.py                  FakeDSPmini test fixture (extends VirtualDSP)
  test_device_thread.py        Command coalescing, queue behaviour, prepare_link / read_config sequencing
  test_model.py                DeviceState.from_config parsing, comp_active / delay_active / linked-mutator helpers
  test_virtual_dsp.py          State persistence, load/store round-trip
  test_preset_picker.py        Dialog behaviour (disabled slots, F00, store)
  test_routing_matrix.py       Drag-to-connect, double-click-disconnect, hit detection
  test_param_knob.py           Construction, value API, clamping, wheel/keyboard/drag interaction, highlight, text input
  test_peq_panel.py            Atomic emit, silent setters, peq_active state, per-type Q clamping
  test_xover_panel.py          Crossover bypass/slope behavior, biquad math, xover_active indicator
  test_overlay_controls.py     "Show other outputs" overlay checkboxes: reset-on-switch, graph push, always-enabled
  test_freq_response_graph_overlay.py  Overlay storage + shared response-polyline helper (flat vs active)
  test_detail_view_overlay.py  Sibling-output overlay sources pushed to both output graphs
  test_about_dialog.py         About HTML: app version always, device model/firmware when connected
  test_compressor_panel.py     Combined 5-value emit, ratio combo contents, silent setters, slave lock, graph wiring
  test_compressor_graph.py     Curve math (baseline, slope, Limit clamp, knee smoothing), parameter binding
  test_delay_panel.py          Knob emit, silent setters, set_active_channel retarget, ms/samples parser, slave lock
  test_delay_graph.py          set_delays clamping, active row, channel names, dynamic-axis snap, tick generation
  test_channel_linking_dialog.py  Flag computation, enabled-state rules, custom channel-name handling
  test_channel_linking_sync.py    Master → slave fan-out for gate / PEQ / xover / compressor / delay / gain / mute, link banner + slave-lock plumbing
  test_unt_loader.py           .unt parsing and validation
  test_unt_writer.py           Byte-identical round-trip, field-level edits
  test_device_pin_dialog.py    UnlockPinDialog + SetPinDialog interaction (validator, in-flight gate, result handling)
  test_virtual_dsp_lock.py     VirtualDSP lock/unlock round-trip (submit_pin, set_lock_pin, DeviceLockedError)

docs/                          MkDocs Material site source
  index.md                     Transcludes README at the site root
  user-guide.md                End-user documentation
  development.md               This page — contributor setup, testing, packaging, release
  changelog.md                 Transcludes CHANGELOG.md
  concepts.md                  UI concepts page (references concept-art/)
  concept-art/                 UI mockups (.excalidraw + .png)
  img/                         Screenshots and recordings
  gen_ref_pages.py             Builds the mkdocstrings API reference
  hooks.py                     Post-processes the transcluded README
```
