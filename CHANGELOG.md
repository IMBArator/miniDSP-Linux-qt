# Changelog

All notable changes to this project will be documented in this file.

## [1.1.0] - 2026-06-20

### Added

- Drag PEQ graph markers to set frequency & gain ([`be68b24`](https://github.com/IMBArator/miniDSP-Linux-qt/commit/be68b24f8a42963bef0ca5066a6fb291fe238dd7))
- Wheel-to-Q and double-click-to-bypass on PEQ markers ([`1ec14da`](https://github.com/IMBArator/miniDSP-Linux-qt/commit/1ec14dab0d47158c20be95392ed1b5b44fedaec5))
- Interactive crossover markers — drag freq, wheel slope, double-click bypass ([`5e73e15`](https://github.com/IMBArator/miniDSP-Linux-qt/commit/5e73e151057b63ecab91af7891d6b7e257e699a5))
- Overlay other output curves on the PEQ and Xover graphs ([`edd5538`](https://github.com/IMBArator/miniDSP-Linux-qt/commit/edd553897bc347c9610558a4e3ffe100b71fb65a))
- Show device model/firmware and app version in the About dialog ([`558c433`](https://github.com/IMBArator/miniDSP-Linux-qt/commit/558c43379b04b58057fa6450aae5dfb4a86f9c61))

### Documentation

- Dedupe user-guide USB permissions against the README ([`0246dc0`](https://github.com/IMBArator/miniDSP-Linux-qt/commit/0246dc0f167b21f48dce3fb7ae5f6afa4f62e160))
- Note --no-sync/--no-cache for local protocol lib ([`2a4e854`](https://github.com/IMBArator/miniDSP-Linux-qt/commit/2a4e85419591bfef74564492c1e7aedc41a13c42))
- Prune stale roadmap and wishlist entries ([`4080c15`](https://github.com/IMBArator/miniDSP-Linux-qt/commit/4080c1552201f2a8a9250c287fbaee7f865af4a1))

### Fixed

- Honour explicit light/dark choice on KDE Plasma ([`2770558`](https://github.com/IMBArator/miniDSP-Linux-qt/commit/27705588ddc3340f7cc7e7be45f99b0c08743dde))

## [1.0.0] - 2026-05-26

First public release of the Qt graphical interface for the **t.racks DSP
4x4 Mini** audio processor (Musicrown-based, VID:PID `0168:0821`). Built
on top of the [miniDSP-Linux](https://github.com/IMBArator/miniDSP-Linux)
protocol library (`v1.0.1`) — every implemented control has been
exercised against real hardware.

The full DSP signal chain is editable end-to-end: input/output gain,
routing matrix, noise gate, parametric EQ, crossover, compressor /
limiter, output delay. The application also covers preset management,
channel linking, a test-tone generator, device lock / PIN, system-
aware light/dark theming, and an offline mode for editing without the
hardware connected.

Status is **work-in-progress**: every feature below is functional, but
expect rough edges in less-trodden corners.

### Added

- **Home view** — four input and four output channel strips with
  gain knobs (−60 to +12 dB), mute, phase invert, an interactive 4×4
  routing matrix (drag to connect, double-click to disconnect), dB-
  scaled level meters for all eight channels, a limiter LED on outputs,
  feature-toggle buttons (gate / xover / peq / comp / delay) whose
  accent colour fills when the feature is active, click-to-rename
  channel labels (max 8 characters), startup config read, and auto-
  reconnect on USB disconnect.

- **Channel detail view** — opens by clicking a feature button on any
  strip. Header repeats the channel strip; the panel area hosts one of:
    - **Gate** (inputs) — Threshold / Attack / Hold / Release knobs and
      a live transfer-function graph; all four parameters sent
      atomically.
    - **PEQ** (outputs) — seven bands of Type / Freq / Gain / Q /
      Bypass with channel-bypass toggle, summed frequency-response
      graph. Shelves and pass filters cap Q at 3.0 to match the
      manufacturer editor.
    - **Crossover** (outputs) — independent Hi-Pass and Lo-Pass rows,
      ten slope types (BW / BL / LR at 6 / 12 / 18 / 24 dB/oct), bypass
      independent of slope selection. Shares its frequency-response
      graph with PEQ so the summed curve is visible in both panels.
    - **Compressor** (outputs) — Threshold / Knee / Ratio (16 named
      ratios from 1:1.0 to Limit) / Attack / Release, sent atomically,
      visualised on an input-vs-output transfer-function graph that
      renders the soft/hard knee elbow and the Limit clamp.
    - **Delay** (outputs) — single edit knob (0–680 ms; typed input
      accepts `"12.5 ms"` or `"601 sa"`) plus an overview bar graph
      showing every output's delay on a shared auto-scaling axis.
  - Per-panel **Reset** button restores just that feature to F00 factory
    defaults (with confirmation). Routed-channel level meters are shown
    alongside the panel, driven by the routing matrix.

- **Channel linking** — popup with two triangular radio-button
  matrices (inputs / outputs) where each row picks the channel it is
  linked to (or its own diagonal for *standalone*). Lowest-indexed
  channel automatically becomes the master, matching the device's
  master = OR-bitmask / slave = `0x00` wire convention. Forbidden
  configurations (chains, demoting a master with active slaves) are
  greyed out. Slave strips display a chain icon and disable controls
  with a tooltip pointing at the master. Master → slave parameter
  fan-out mirrors edits in both the UI and the device requests.

- **Copy channel settings** — select a source channel, pick parameter
  groups to copy (Name / Gain / Mute / Phase / Gate for inputs; plus
  Routing / Crossover / PEQ / Compressor / Delay for outputs), copy to
  any number of compatible targets. Linked slave targets are restricted
  to Name-only with a warning banner.

- **Preset management** — recall any of the 30 user presets (U01–U30)
  or the F00 factory preset; store current settings to any user slot
  with a custom name (with confirmation before writing device flash);
  preset name label updates in real time.

- **Offline mode** — enter at launch with `--offline` or switch at
  runtime via the menu. In-RAM virtual DSP, no hardware required. All
  parameters editable. Online → Offline carries the live device state
  into the virtual DSP so editing continues seamlessly; Offline →
  Online prompts before discarding offline edits. Cold-launching
  offline seeds from the bundled `blank.unt` template.

- **.unt file support** — load and save manufacturer `.unt` files
  with byte-identical round-trip for untouched data; unknown bytes are
  preserved when editing individual fields. All 30 preset slots are
  parsed.

- **Test-tone generator** — non-modal dialog with Off / Pink / White /
  Sine selection, 31-step ISO 1/3-octave sine frequency selector
  (20 Hz – 20 kHz), and a full-width red **Disable test tone** panic
  button.

- **Device lock / PIN** — auto-prompt on connect when the device
  reports it is locked; up to three PIN attempts with inline retry
  count; **Set device PIN** menu entry for arming a new PIN (treated
  as a one-shot admin action). PINs accept any 4 printable ASCII
  characters, not just digits.

- **Light/dark theming** — follows the system colour scheme
  automatically (Qt 6.5+ `QStyleHints.colorSchemeChanged`); manual
  override via the menu, persisted via `QSettings`. Custom-painted
  widgets (graphs, level meters, knobs, routing matrix, limiter LED)
  are theme-aware.

- **Knob interaction** — click-drag, scroll wheel, or arrow keys for
  ±1 raw unit steps; Ctrl + modifier for range-adaptive fast editing
  (~2 % per step); click the dB label to type an exact value; double-
  click to reset to the default.

- **Verbosity & diagnostics** — `-v` / `-vv` flags for runtime logging
  and recall-path diagnostics.

- **AppImage packaging** — `make appimage` produces a self-contained
  `minidspqt-<version>-x86_64.AppImage` with a bundled CPython 3.11
  and PySide6, built against Ubuntu 20.04 (glibc 2.31) for wide
  compatibility. Optional `APPIMAGE_UPDATE_INFO` env var emits a
  sibling `.zsync` file for delta updates via AppImageUpdate-aware
  clients.

- **Release pipeline** — `make version VERSION=X.Y.Z` (bump
  `pyproject.toml`, regenerate `CHANGELOG.md` via git-cliff, commit
  and tag), `make build` (wheel + sdist), `make appimage` (Linux
  binary), `make publish` (GitHub Release with wheel + sdist + AppImage
  + optional `.zsync`, plus `mkdocs gh-deploy` to GitHub Pages — all
  in one step, no `gh` CLI required).

- **Documentation site** — full user guide rendered with mkdocs-
  material, deployed to <https://imbarator.github.io/miniDSP-Linux-qt/>.

- **Test suite** — 374 tests covering the device thread, model,
  virtual DSP, preset picker, routing matrix, PEQ panel, crossover
  panel, compressor panel + graph, delay panel + graph, channel-
  linking dialog, channel-linking sync (master → slave fan-out),
  runtime offline-mode switching, param knob widget, and `.unt`
  read/write round-trip.
