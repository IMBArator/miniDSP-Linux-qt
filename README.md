# miniDSP-Linux-qt

> **Status:** Work in progress — home view (8 channel strips, routing matrix, level meters), preset management, and the channel detail view are functional. The detail view ships with the **Gate** panel for inputs and the **PEQ** panel (7 bands + summed frequency-response graph), **Crossover** panel, and **Compressor** panel for outputs. The Delay panel is the last remaining placeholder.

Qt graphical interface for the **the t.racks DSP 4x4 Mini**, built on top of the [miniDSP-Linux](https://github.com/IMBArator/miniDSP-Linux) protocol library. Provides full preset management, real-time metering, and an offline mode for editing without hardware connected.

## Home View

![Home View](doc/Home-View.gif)

## UI concepts

![Home](doc/concept-art/miniDSP-home.png)

![Detail View](doc/concept-art/miniDSP-detailView.png)

![Detail View PEQ](doc/concept-art/miniDSP-detailViewPEQ.png)

## Features

### Home view

- Per-channel **gain knobs** (−60 to +12 dB) for 4 inputs and 4 outputs
- **Mute** and **phase invert** toggles per channel
- **Routing matrix** — interactive 4×4 input-to-output mapping (drag to connect, double-click to disconnect)
- **dB-scaled level meters** for all 8 channels
- **Outlined toggle buttons** — each feature button (gate / mute / phase / xover / peq / comp / delay) paints its accent color on the border and text when off, and fills with the same accent when on
- Startup **config read** — knobs and toggles reflect device state on connect
- **Auto-reconnect** on USB disconnect

### Light / dark theme

- Follows the **system color scheme** automatically (Qt 6.5+ `QStyleHints.colorSchemeChanged`); switches live when the OS appearance changes
- Manual override via **Menu → Theme** (System / Light / Dark), persisted across sessions via `QSettings`
- Custom-painted widgets (PEQ / crossover / gate graphs, level meter, knobs, routing matrix, limiter LED) are theme-aware: graph backgrounds use a soft tinted off-white in light mode rather than pure white

### Channel linking

- Editable from **Menu → Channel linking…** — a popup with two triangular radio-button matrices (inputs / outputs) where each row picks the channel it is linked to (or its own diagonal for *standalone*)
- The lowest-indexed channel in each group automatically becomes the master, matching the device's master = OR-bitmask / slave = 0x00 wire convention
- Forbidden configurations are greyed out: a slave can't itself be picked as a target (no chains), and a master with active slaves can't be demoted before they are released
- Headers, row labels, and the live "InA: master of …" / "InB: linked to InA" status text use the user's custom channel names from the home view
- Apply sends `OP_PREPARE_LINK` (0x2A) for every new pair followed by `OP_LINK` (0x3B) for each affected channel, then re-reads the device config so the dialog reflects whatever the device actually committed; offline mode uses the same code path against the in-memory virtual DSP

### Channel detail view

Click the **Gate** button on any input strip — or the **PEQ** / **Xover** / **Comp** button on any output strip — to open the per-channel detail view:

- Header with the same channel strip from the home view (gain knob, level meter, mute/phase/gate or mute/phase/peq/… toggles, name)
- Quick navigation buttons for all 4 inputs and 4 outputs; the active feature is preserved across channel switches when valid for the new channel type
- A feature panel area:
  - **Gate** (inputs) — Threshold, Attack, Hold, Release knobs plus a live transfer-function graph; all four parameters are sent atomically (protocol command 0x3E)
  - **PEQ** (outputs) — 7 bands of (Type / Freq / Gain / Q / Bypass) below a summed frequency-response graph, plus a channel-bypass toggle in the panel header. Per-band atomic emit (protocol command 0x33). Shelves and pass filters cap Q at 3.0 to match the official editor; Peak and the two allpass forms keep the full Q range
  - **Crossover** (outputs) — Hi-Pass and Lo-Pass rows, each with frequency knob, slope selector (BW 6 / BL 6 / BW 12 / BL 12 / LR 12 / BW 18 / BL 18 / BW 24 / BL 24 / LR 24), and bypass toggle. Bypass is independent of the slope selector (matching the manufacturer software). Both the Xover and PEQ panels share a combined frequency-response graph that shows the summed crossover + PEQ curve
  - **Compressor** (outputs) — Threshold (−90 to +20 dB) and Knee (0 – 12 dB) knobs, a Ratio combo (16 named ratios from 1:1.0 to Limit), and Attack (1–999 ms) / Release (10–3000 ms) knobs. All five parameters are sent atomically (protocol command 0x30) and visualised on a live input-vs-output transfer-function graph that renders the soft/hard knee elbow and the Limit clamp
  - A **placeholder panel** is shown when the active feature does not apply to the selected channel (e.g. Gate on an output) and for the not-yet-implemented Delay panel
- Routed-channel level meters — outputs to the right of an input, inputs to the left of an output, driven by the routing matrix
- Strip-level "active" indicators: the input Gate button fills green when the gate threshold is above the noise floor; the output PEQ button fills purple when at least one band has non-zero gain and is not bypassed; the output Xover button fills blue when either hi-pass or lo-pass is not bypassed; the output Comp button fills teal when the ratio is anything other than 1:1.0
- Master → slave parameter fan-out: editing any compressor (or gate / PEQ / crossover) parameter on a master channel mirrors the change to every linked slave in both the on-screen model and the device requests, since the hardware emits no telemetry for its own master-to-slave copy

### Preset management

- **Recall** any of the 30 user presets (U01–U30) or the factory preset (F00)
- **Store** current settings to any user slot with a custom name
- Confirmation dialog before writing to device flash
- Preset name label updates in real time

### Offline mode (`--offline`)

- In-RAM virtual DSP — no hardware required
- Edit gains, mutes, phases, routing, PEQ, crossovers, compressors, delays
- **Load and save .unt files** — round-trip with the manufacturer file format
- Seed from a bundled `blank.unt` template

### .unt file support

- **Load** manufacturer .unt files — parses all 30 preset slots
- **Save** .unt files with byte-identical round-trip for untouched data
- Preserves unknown bytes when editing individual fields

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — manages the virtual environment and dependencies
- [miniDSP-Linux](https://github.com/IMBArator/miniDSP-Linux) — protocol library (installed from local wheel)
- Linux with kernel HID driver — communicates via `/dev/hidraw*`
- Read/write access to `/dev/hidraw*` (see [Permissions](#permissions))

## Installation

```bash
git clone https://github.com/IMBArator/miniDSP-Linux-qt.git
cd miniDSP-Linux-qt
uv sync              # creates .venv, installs dependencies
uv sync --extra dev  # also installs pytest for development
```

## Usage

### Connected mode

```bash
minidspqt              # connect to hardware (WARNING level)
minidspqt -v           # info-level logging (recall tracing, config reads)
minidspqt -vv          # debug-level logging (USB frame traces)
```

### Offline mode

```bash
minidspqt --offline    # virtual DSP, no hardware needed
```

### .unt files

Use the menu button (top-right) to load or save `.unt` preset files. In offline mode, all 30 slots are editable and can be saved back to disk.

## Permissions

The tool communicates via `/dev/hidraw*`. By default this requires root. To allow regular users, create a udev rule:

```bash
sudo tee /etc/udev/rules.d/99-dspmini.rules << 'EOF'
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0168", ATTRS{idProduct}=="0821", MODE="0666"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Then reconnect the device.

## Running tests

```bash
uv run --with pytest --with pytest-qt pytest tests/ -v
```

198 tests covering the device thread, model, virtual DSP, preset picker, routing matrix, PEQ panel, crossover panel, compressor panel + graph, channel-linking dialog, channel-linking sync (master → slave fan-out), and .unt read/write round-trip.

## Repository structure

```
minidspqt/                     Main package
  cli.py                       Entry point: -v/--offline flags
  app.py                       QApplication setup, theme manager binding, offline seeding
  theme.py                     Theme registry (DARK_THEME / LIGHT_THEME) and ThemeManager singleton
  model.py                     Typed device state (DeviceState dataclass)
  device_thread.py             QThread: poll loop, command coalescing, preset queue
  virtual_dsp.py               In-RAM DSP implementing DSPmini interface
  unt_loader.py                Parse .unt files (single-slot and all-slots)
  unt_writer.py                Write .unt files with field-level overwrites
  views/
    main_window.py             Main window: owns thread, state, Recall/Store, channel-linking apply flow
    home_view.py               8 channel strips + routing matrix + level meters
    preset_picker.py           Recall/Store preset dialog (F00 + 30 user slots)
    channel_linking_dialog.py  Triangular radio matrices for input/output channel linking
    channel_strip.py           ChannelStrip + InputChannelStrip / OutputChannelStrip
    detail_view.py             Per-channel detail view with feature panels and routed meters
    panels/
      gate_panel.py            Gate parameters (threshold, attack, hold, release) + transfer graph
      peq_panel.py             7 bands × (Type / Freq / Gain / Q / Byp) + channel bypass + summed-response graph
      xover_panel.py           Hi-Pass / Lo-Pass crossover (freq + slope + bypass) + shared response graph
      compressor_panel.py      Threshold / Ratio (combo) / Knee / Attack / Release + transfer-function graph
      delay_panel.py           Placeholder for the upcoming delay panel
      _slave_lock.py           Shared "Linked to <master> — read-only" banner used by every feature panel
      placeholder_panel.py     Shown when the active feature is N/A for the selected channel
  widgets/                     Custom Qt widgets (CompressorGraph, FreqResponseGraph, GainKnob, GateGraph, LedIndicator, LevelMeter, ParamKnob, PEQGraph, RoutingMatrix, ToggleButton)
  resources/                   blank.unt template, icons, style_dark.qss + style_light.qss (selected by ThemeManager)

tests/                         pytest suite (198 tests)
  conftest.py                  FakeDSPmini test fixture (extends VirtualDSP)
  test_device_thread.py        Command coalescing, queue behaviour, prepare_link / read_config sequencing
  test_model.py                DeviceState.from_config parsing, comp_active / linked-mutator helpers
  test_virtual_dsp.py          State persistence, load/store round-trip
  test_preset_picker.py        Dialog behaviour (disabled slots, F00, store)
  test_routing_matrix.py       Drag-to-connect, double-click-disconnect, hit detection
  test_peq_panel.py            Atomic emit, silent setters, peq_active state, per-type Q clamping
  test_xover_panel.py          Crossover bypass/slope behavior, biquad math, xover_active indicator
  test_compressor_panel.py     Combined 5-value emit, ratio combo contents, silent setters, slave lock, graph wiring
  test_compressor_graph.py     Curve math (baseline, slope, Limit clamp, knee smoothing), parameter binding
  test_channel_linking_dialog.py  Flag computation, enabled-state rules, custom channel-name handling
  test_channel_linking_sync.py    Master → slave fan-out for gate / PEQ / xover / compressor / gain / mute, link banner + slave-lock plumbing
  test_unt_loader.py           .unt parsing and validation
  test_unt_writer.py           Byte-identical round-trip, field-level edits

doc/
  concept-art/                 UI mockups (.excalidraw + .png)
  user-guide.md                End-user documentation
  architecture-plan.md         Original architecture plan (historical)
  offline-mode-unt-read-write.md  Implementation plan
```

## Roadmap

> Comparison against the [miniDSP-Linux](https://github.com/IMBArator/miniDSP-Linux) protocol library.

### Done

| Feature | Library API | Notes |
|---------|------------|-------|
| Gain control (8 ch) | `set_gain` | Knob, linked-channel sync |
| Mute (8 ch) | `mute` | Per-channel toggle |
| Phase invert (8 ch) | `set_phase` | Per-channel toggle |
| Level meters (8 ch) | `poll_levels` | 150 ms poll, dB-scaled, peak-hold |
| Channel names | `set_channel_name` | Click-to-edit, max 8 chars |
| Preset recall | `load_preset` | F00 + U01–U30, slot names |
| Preset store | `store_preset` | Name entry, flash-write confirm |
| Config read | `read_config` | Full state on connect |
| Routing matrix | `set_matrix_route` | Interactive: drag-to-connect, double-click-to-disconnect |
| Auto-reconnect | — | 2 s retry on USB disconnect |
| Offline mode | — | VirtualDSP, no hardware |
| .unt load/save | — | 30-slot round-trip |
| Linked channel display | `decode_link_groups` | Icon + disabled controls on slaves |
| Limiter indicator | `limiter_mask` in `poll_levels` | Red LED + "Lim" label on output strips, bitmask-driven |
| Channel detail view (Gate) | `set_gate` | Per-channel canvas with quick-nav, routed meters, and a Gate panel for input channels (threshold / attack / hold / release + transfer-function graph). Outputs and other features show a placeholder |
| Channel detail view (PEQ) | `set_peq_band`, `set_peq_channel_bypass` | 7-band PEQ panel for output channels with per-band Type / Freq / Gain / Q / Byp controls, channel-wide bypass, and a summed frequency-response graph. Per-band atomic emit, shelf/pass Q capped at 3.0, output strip's PEQ button lights up when any band is shaping signal |
| Channel detail view (Crossover) | `set_hipass`, `set_lopass` | Hi-Pass / Lo-Pass panel for output channels with frequency knob, slope selector (9 slope types), and per-filter bypass toggle. Shared frequency-response graph shows summed crossover + PEQ curve on both the Xover and PEQ panels. Output strip's Xover button lights up when either filter is active |
| Channel detail view (Compressor) | `set_compressor` | Threshold / Knee / Attack / Release knobs + 16-entry Ratio combo (1:1.0 … 1:20.0 / Limit), atomic 5-value emit (protocol command 0x30). Live input-vs-output transfer-function graph with soft/hard knee elbow and Limit clamp. Output strip's Comp button lights teal when the ratio is not 1:1.0 |
| Master → slave parameter sync | `mutate_with_links` (model) | Editing any parameter on a master channel mirrors the change to every linked slave in both DeviceState and the device queue — required because the hardware emits no telemetry for its own master-to-slave copy. Slave feature panels are read-only and show a "Linked to <master>" banner |
| EQ curve visualisation | — | QPainter log-frequency / dB graph driven by local biquad coefficient math (Audio EQ Cookbook formulas) — shared by PEQ and Crossover panels via `FreqResponseGraph` widget |

### High priority

| Feature | Library API | What's missing |
|---------|------------|----------------|
| **Detail view: Delay panel** | `set_delay` | Output-channel feature panel. Detail-view scaffolding (navigation, routed meters, placeholder fallback, MainWindow wiring) is already in place; backend fully exists in DeviceThread, VirtualDSP, and model |
| **PEQ extras** | — | "Reset EQ" button (7× flat bands), copy-band / paste-band, A/B compare, draggable graph markers |

### Medium priority

| Feature | Library API | What's missing |
|---------|------------|----------------|
| **Channel linking UI** | `prepare_link` + `set_channel_link` | Context menu or link button; `request_prepare_link()` missing from DeviceThread |
| **Test tone generator** | `set_test_tone` | Dialog: Off / Pink / White / Sine + 31-step freq picker |

### Low priority

| Feature | Library API | What's missing |
|---------|------------|----------------|
| Delay display unit (ms/m/ft) | `set_delay_unit` | Dropdown in delay view |
| Firmware string display | `cmd_firmware` response | Surface in About dialog |
| Device lock / PIN | `is_locked`, `submit_pin`, `set_lock_pin` | PIN entry dialog; dangerous feature |
| Copy channel settings | — | "Copy from…" context menu |
| Show-all-EQ overlay | — | Checkbox to overlay 4 output curves |

## Related projects

- [miniDSP-Linux](https://github.com/IMBArator/miniDSP-Linux) — Protocol library and CLI tool this project depends on
- [dsp-408-ui](https://github.com/Aeternitaas/dsp-408-ui) — Same Musicrown protocol over TCP for the DSP 408

## Acknowledgments

- [PySide6](https://wiki.qt.io/Qt_for_Python) — GUI framework (Qt for Python, licensed under LGPLv3/GPLv3)
- [miniDSP-Linux](https://github.com/IMBArator/miniDSP-Linux) — Protocol library and CLI tool this project depends on

This application uses the PySide6 Qt binding. PySide6 is licensed under the
[GNU Lesser General Public License v3](https://www.gnu.org/licenses/lgpl-3.0.en.html).
Users have the right to obtain, modify, and redistribute the Qt/PySide6 library
source code. The library is dynamically linked; users can replace the PySide6
version at runtime without modifying this application.

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).

Not affiliated with Musicrown, the t.racks, or Thomann. Protocol reverse-engineered for interoperability purposes under applicable law.
