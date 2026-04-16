# Architecture Plan: PySide6 Qt Application for t.racks DSP 4x4 Mini

## Context

The goal is to create a full-featured Qt GUI for the t.racks DSP 4x4 Mini audio processor. A protocol library (`minidsp-linux`) already exists with complete USB HID communication, and a proof-of-concept GUI exists in that repo with basic gain/mute/level meters. This new project (`miniDSP-Linux-qt`) will be a proper, Designer-based Qt application covering all DSP features.

**Key requirements:**
- `.ui` files editable in Qt Designer, compiled to Python via `pyside6-uic`
- Custom Python classes that inherit from generated UI code to add behavior
- Custom-painted widgets (level meters, knobs, graphs) promoted in Designer

## Architecture Overview

**Navigation**: `QStackedWidget` inside `MainWindow` switches between Home and Detail views. Both views stay alive so level meters update continuously.

**Device communication**: A `DeviceThread` (QThread) owns the `DSPmini` instance, polls levels every 150ms, and coalesces pending commands via a thread-safe dict keyed by `(CommandType, channel[, sub_index])`.

**UI pattern**: `.ui` files define layout with promoted custom widgets -> `pyside6-uic` compiles to `Ui_*` classes -> Python view classes use multiple inheritance (`class HomeView(QWidget, Ui_Home)`) to add behavior.

## Package Structure

```
minidspqt/
├── __init__.py
├── cli.py                      # Entry point: main()
├── app.py                      # QApplication setup, theme
├── device_thread.py            # DeviceThread (QThread) - all device I/O
├── model.py                    # Dataclasses for device state
├── forms/                      # .ui source files (checked into git)
│   ├── home.ui
│   └── detail_view.ui
├── ui/                         # Generated Python from .ui (NOT in git)
│   ├── __init__.py
│   ├── ui_home.py
│   └── ui_detail_view.py
├── views/                      # Custom classes inheriting generated UI
│   ├── __init__.py
│   ├── main_window.py          # QMainWindow + QStackedWidget + DeviceThread
│   ├── home_view.py            # HomeView(QWidget, Ui_Home)
│   └── detail_view.py          # DetailView(QWidget, Ui_DetailView)
└── widgets/                    # Custom-painted widgets (promoted in Designer)
    ├── __init__.py
    ├── level_meter.py           # Vertical bar meter with peak hold
    ├── gain_knob.py             # Rotary dial for gain/parameter control
    ├── routing_matrix.py        # Signal flow visualization (4x4)
    ├── toggle_button.py         # Styled on/off button (Mute/Gate/Phase etc.)
    ├── frequency_response.py    # PEQ/crossover frequency response graph
    └── gate_graph.py            # Gate transfer function graph
tests/
    __init__.py
    test_model.py
scripts/
    build_ui.sh                  # Compiles all .ui -> .py
```

## UI Files

### `forms/home.ui` -- Home Screen

Based on concept art wireframe (`doc/concept-art/miniDSP-home.png`):

- **Header**: "Home" label, connection status indicator (styled QLabel), hamburger menu QPushButton
- **Input section** (left, 4x QFrame): Each contains promoted `GainKnob`, `LevelMeter`, 3x `ToggleButton` (Gate, Phase, Mute), channel label
- **Center**: Promoted `RoutingMatrix` widget showing 4->4 signal flow lines
- **Output section** (right, 4x QFrame): Each contains promoted `LevelMeter`, `GainKnob`, 6x `ToggleButton` (Xover, PEQ, Comp, Phase, Delay, Mute), channel label
- **Footer**: Preset QLabel, Store QPushButton, Recall QPushButton

### `forms/detail_view.ui` -- Detail View (shared for input & output)

Based on concept art wireframes (`doc/concept-art/miniDSP-detailView.png`, `miniDSP-detailViewPEQ.png`):

- **Header**: Back QPushButton, "Detail View" label, connection indicator, menu button
- **Channel selector**: 4 input QPushButtons (InA-InD) on left, 4 output QPushButtons (Out1-Out4) on right
- **Channel header**: Promoted `GainKnob`, `LevelMeter`, `ToggleButton` instances
- **Content area** (QStackedWidget): Pages for Gate, PEQ/X-Over, Compressor, Delay settings -- each with appropriate promoted widgets (graphs, knobs, sliders)
- **Side panel**: Mini `LevelMeter` widgets for context

## Custom Widgets (promoted in Designer)

These widgets are implemented as Python classes with custom `paintEvent` methods. In Qt Designer, they are placed as QWidget placeholders and then "promoted" to the actual class.

| Widget | Description | Key API |
|--------|-------------|---------|
| `LevelMeter` | Vertical dB-scaled bar, EMA smoothing, peak hold, gradient (green->yellow->red) | `set_level(uint16)`, `reset()` |
| `GainKnob` | Rotary dial with arc, tick marks, center dB text. Mouse drag + scroll wheel | `setValue(raw)`, `value()->int`, signal `valueChanged(int)` |
| `ToggleButton` | Styled QPushButton, color-coded per feature (red=mute, yellow=phase, green=active) | `setFeature(str)`, inherits `setCheckable(True)` |
| `RoutingMatrix` | Painted 4x4 signal flow with crossing lines, active/inactive routes | `set_routing(list[int])` -- 4 input bitmasks |
| `FrequencyResponse` | Log-frequency graph (20Hz-20kHz), PEQ band curves, crossover curves, draggable points | `set_bands(list[dict])`, `set_crossover(hipass, lopass)` |
| `GateGraph` | Transfer function graph (dB in vs dB out), threshold marker | `set_parameters(attack, release, hold, threshold)` |

## Class Hierarchy

```
QMainWindow
└── MainWindow (minidspqt/views/main_window.py)
    ├── owns DeviceThread
    ├── owns QStackedWidget
    ├── HomeView (QWidget, Ui_Home)          <- generated + custom
    └── DetailView (QWidget, Ui_DetailView)  <- generated + custom
```

### Signal Flow

```
UI widget interaction -> view signal -> MainWindow -> DeviceThread.request_*()
DeviceThread.levels_updated -> MainWindow -> active view.update_levels()
DeviceThread.config_loaded -> MainWindow -> model.DeviceState.from_config() -> views
```

## DeviceThread Design

Extended from the working proof-of-concept pattern in `~/src/miniDSP-Linux/minidsp/gui/device_thread.py`.

### Command Coalescing

A single `dict[tuple, tuple]` keyed by `(CommandType, channel[, band])`. The key design ensures independent coalescing:

- `(GAIN, 2)` -- gain for channel 2 coalesces independently
- `(PEQ_BAND, 4, 3)` -- PEQ band 3 of Out1 coalesces independently from band 5 of Out2

Rapid slider moves between poll cycles -> only the latest value is sent to the device.

### Signals (emitted to main thread)

- `levels_updated(dict)` -- `{inputs: [4], outputs: [4], limiter_mask: int}`
- `connection_changed(bool)` -- True=connected, False=disconnected
- `config_loaded(dict)` -- Full config dict from `read_config()`

### Thread-safe command interface (called from UI thread)

- `request_gain(channel, raw_value)`
- `request_mute(channel, mute)`
- `request_phase(channel, inverted)`
- `request_gate(channel, attack, release, hold, threshold)`
- `request_hipass(channel, freq_raw, slope)`
- `request_lopass(channel, freq_raw, slope)`
- `request_peq_band(channel, band, gain_raw, freq_raw, q_raw, filter_type, bypass)`
- `request_peq_channel_bypass(channel, bypass)`
- `request_compressor(channel, ratio, knee, attack, release, threshold)`
- `request_delay(channel, samples)`
- `request_matrix_route(output_ch, input_mask)`
- `request_load_preset(slot)` -- non-coalescing, queued
- `request_store_preset(slot, name)` -- non-coalescing, queued

### Auto-reconnect

On USB disconnect: closes device, emits `connection_changed(False)`, retries every 2s.

## Model Layer (`model.py`)

Typed dataclasses mapping the config dict from `parse_preset_params()`:

- `InputChannelState`: name, gain_raw, muted, phase_inverted, gate params, link_flags
- `OutputChannelState`: name, gain_raw, muted, phase_inverted, delay, crossover, compressor, 7x PEQ bands, routing bitmask, link_flags
- `DeviceState`: connected, 4 inputs, 4 outputs, active_slot, preset_names
- `DeviceState.from_config(dict)`: factory method from `read_config()` result

`MainWindow` holds a single `DeviceState` instance. When `config_loaded` fires, it creates a fresh `DeviceState.from_config()`. When the UI modifies a value, it updates the local state AND sends the command to `DeviceThread`.

## Build Pipeline

### UI Compilation Script (`scripts/build_ui.sh`)

```bash
#!/bin/bash
set -e
for ui in minidspqt/forms/*.ui; do
    base=$(basename "$ui" .ui)
    out="minidspqt/ui/ui_${base}.py"
    echo "Compiling $ui -> $out"
    pyside6-uic "$ui" -o "$out"
done
```

### Git Policy

- `.ui` source files in `minidspqt/forms/` -- **checked into git**
- Generated `ui_*.py` files in `minidspqt/ui/` -- **NOT checked in** (added to `.gitignore`)

## Dependency Setup

Update `pyproject.toml`:

```toml
dependencies = ["PySide6>=6.5", "minidsp-linux"]

[tool.uv.sources]
minidsp-linux = { path = "../miniDSP-Linux/dist/minidsp_linux-0.1.0-py3-none-any.whl" }
```

## Existing Code to Reuse

| Source | What | Where |
|--------|------|-------|
| `~/src/miniDSP-Linux/minidsp/gui/device_thread.py` | Proven connect/poll/coalesce loop | `device_thread.py` |
| `~/src/miniDSP-Linux/minidsp/gui/level_meter.py` | dB-scaled gradient, EMA smoothing, peak hold | `widgets/level_meter.py` |
| `minidsp_linux.protocol` module | `raw_to_db()`, `db_to_raw()`, `freq_raw_to_hz()`, `level_uint16_to_dbu()`, etc. | Import directly |
| `minidsp_linux.device.DSPmini` | All device commands | Import directly |

## minidsp-linux Library API Coverage

The `DSPmini` class provides **complete coverage** of all DSP features needed by the GUI:

| Device Method | Opcode | Purpose |
|---------------|--------|---------|
| `set_gain(channel, raw)` | 0x34 | Input/output gain (-60 to +12 dB) |
| `mute(channel, mute)` | 0x35 | Mute/unmute per channel |
| `set_phase(channel, inverted)` | 0x36 | Phase invert (180deg) |
| `set_gate(channel, attack, release, hold, threshold)` | 0x3E | Input noise gate |
| `set_delay(channel, samples)` | 0x38 | Output delay (0-680 ms) |
| `set_hipass(channel, freq_raw, slope)` | 0x32 | High-pass crossover |
| `set_lopass(channel, freq_raw, slope)` | 0x31 | Low-pass crossover |
| `set_compressor(channel, ratio, knee, attack, release, threshold)` | 0x30 | Output compressor/limiter |
| `set_peq_band(channel, band, gain, freq, q, type, bypass)` | 0x33 | PEQ band (7 per output) |
| `set_peq_channel_bypass(channel, bypass)` | 0x3C | Bypass all PEQ bands |
| `set_matrix_route(output_ch, input_mask)` | 0x3A | 4x4 routing matrix |
| `set_channel_link(channel, link_flags)` | 0x3B | Channel linking |
| `prepare_link(master_ch, slave_ch)` | 0x2A | Pre-link declaration |
| `set_channel_name(channel, name)` | 0x3D | Channel display name |
| `set_test_tone(mode, freq_index)` | 0x39 | Test signal generator |
| `load_preset(slot)` | 0x20 | Load preset + re-read config |
| `store_preset(slot, name)` | 0x21 | Store to user preset |
| `set_delay_unit(unit)` | 0x15 | Display unit (ms/m/ft) |
| `submit_pin(pin)` | 0x2D | Unlock locked device |
| `read_config()` | sequence | Full startup + config read |
| `poll_levels()` | 0x40 | Real-time level metering |

The `parse_preset_params()` function extracts all parameters including routing bitmasks (key: `routings`), so the GUI has everything it needs from day one.

**Conversion functions** available in `minidsp_linux.protocol`:
- `raw_to_db()` / `db_to_raw()` -- dual-resolution gain
- `freq_raw_to_hz()` -- log-scale frequency
- `peq_raw_to_gain()` / `peq_gain_to_raw()` -- PEQ gain
- `peq_raw_to_q()` / `peq_q_to_raw()` -- PEQ Q factor
- `comp_threshold_to_db()`, `comp_attack_to_ms()`, `comp_release_to_ms()` -- compressor
- `gate_threshold_to_db()`, `gate_time_to_ms()` -- noise gate
- `delay_samples_to_ms()` -- output delay
- `level_uint16_to_dbu()` -- level metering

## Implementation Phases

### Phase 1: Project Skeleton

1. Create directory structure (`minidspqt/`, views/, widgets/, forms/, ui/)
2. `cli.py` -- entry point calling `app.run()`
3. `app.py` -- QApplication with dark palette
4. `model.py` -- dataclasses with `DeviceState.from_config()`
5. `device_thread.py` -- extended DeviceThread with all command types
6. Update `pyproject.toml` with minidsp-linux dependency
7. `scripts/build_ui.sh`
8. Update `.gitignore`

### Phase 2: Custom Widgets

9. `LevelMeter` -- port from PoC, clean up
10. `GainKnob` -- rotary dial with mouse drag/scroll
11. `ToggleButton` -- styled QPushButton with feature colors
12. `RoutingMatrix` -- painted 4x4 signal flow

### Phase 3: Home Screen

13. Design `forms/home.ui` in Qt Designer with promoted widgets
14. Compile with `pyside6-uic`
15. `HomeView(QWidget, Ui_Home)` -- wire signals for gain/mute/phase, update levels
16. `MainWindow` -- QStackedWidget, DeviceThread, signal routing
17. Test: connection, levels, gain, mute, phase

### Phase 4: Detail View

18. `GateGraph` -- transfer function widget
19. `FrequencyResponse` -- PEQ/crossover graph widget
20. Design `forms/detail_view.ui` with promoted widgets
21. Compile with `pyside6-uic`
22. `DetailView(QWidget, Ui_DetailView)` -- wire all parameter controls
23. Navigation: Home <-> Detail via QStackedWidget
24. Test: gate, PEQ, crossover, compressor, delay settings

### Phase 5: Polish

25. Preset management (Store/Recall)
26. Routing matrix editing
27. Channel linking support
28. Error handling and edge cases

## Verification Plan

1. `uv sync` -- dependencies install correctly
2. `scripts/build_ui.sh` -- .ui files compile without errors
3. `uv run minidspqt` -- app launches, shows Home screen
4. Connect DSP device -- status indicator turns green, levels animate
5. Move gain knobs -- dB values update, device responds
6. Toggle mute/phase -- buttons change color, device responds
7. Click channel -> Detail View loads with correct parameters
8. Adjust gate/PEQ/crossover/compressor/delay -> device responds
9. Back button returns to Home
10. Disconnect USB -> status indicator turns red, auto-reconnect on replug
