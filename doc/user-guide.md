# DSP 4x4 Mini — User Guide

Qt graphical interface for the **t.racks DSP 4x4 Mini** audio processor.

---

## Table of Contents

- [Installation](#installation)
- [Starting the Application](#starting-the-application)
- [Home View Layout](#home-view-layout)
- [Channel Strips](#channel-strips)
  - [Gain Knob](#gain-knob)
  - [Level Meter](#level-meter)
  - [Toggle Buttons](#toggle-buttons)
  - [Channel Names](#channel-names)
  - [Linked Channels](#linked-channels)
- [Channel Detail View](#channel-detail-view)
  - [Gate Panel](#gate-panel)
  - [PEQ Panel](#peq-panel)
  - [Crossover Panel](#crossover-panel)
- [Routing Matrix](#routing-matrix)
- [Preset Management](#preset-management)
  - [Recalling a Preset](#recalling-a-preset)
  - [Storing a Preset](#storing-a-preset)
- [Offline Mode](#offline-mode)
- [.unt Preset Files](#unt-preset-files)
  - [Loading a .unt File](#loading-a-unt-file)
  - [Saving a .unt File](#saving-a-unt-file)
- [Menu](#menu)
- [USB Permissions](#usb-permissions)
- [Troubleshooting](#troubleshooting)

---

## Installation

### Requirements

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/) package manager
- Linux with kernel HID driver
- A t.racks DSP 4x4 Mini connected via USB (or use [offline mode](#offline-mode))

### Install

```bash
git clone https://github.com/IMBArator/miniDSP-Linux-qt.git
cd miniDSP-Linux-qt
uv sync
```

This creates a `.venv` directory and installs all dependencies, including the `minidsp-linux` protocol library.

---

## Starting the Application

```bash
minidspqt              # connect to hardware (default logging)
minidspqt -v           # info-level logging
minidspqt -vv          # debug-level logging (USB frame traces)
minidspqt --offline    # virtual DSP, no hardware needed
```

On launch the application attempts to open the DSP via `/dev/hidraw*`. If the device is found, it reads the full configuration (preset data, channel names, gain, routing, mute/phase state) and populates all controls. Level meters begin updating at ~150 ms intervals.

If no device is found, the UI shows **Disconnected** and all controls are disabled. The application will auto-retry every 2 seconds.

---

## Home View Layout

The main window is divided into three columns:

```
┌──────────────────────────────────────────────────────────┐
│  DSP 4x4 Mini          [Connected]              [≡]      │
├────────────┬──────────────┬──────────────────────────────┤
│            │              │                              │
│  Inputs    │   Routing    │   Outputs                    │
│            │   Matrix     │                              │
│  InA  ●───┤   ●────●     ├───●  Out1                    │
│  InB  ●───┤   ●────●     ├───●  Out2                    │
│  InC  ●───┤   ●────●     ├───●  Out3                    │
│  InD  ●───┤   ●────●     ├───●  Out4                    │
│            │              │                              │
├────────────┴──────────────┴──────────────────────────────┤
│  Preset: U01 — My Studio              [Recall] [Store]   │
└──────────────────────────────────────────────────────────┘
```

- **Left column** — 4 input channel strips (InA through InD)
- **Center** — interactive 4x4 routing matrix
- **Right column** — 4 output channel strips (Out1 through Out4)
- **Bottom bar** — current preset name, Recall and Store buttons

---

## Channel Strips

Each of the 8 channels (4 inputs, 4 outputs) has an identical strip layout:

```
┌──────────┐
│  InA     │  ← Channel name (click to rename)
│  ╭───╮ │  ← Gain knob
│  │ ◠ │ │
│  ╰───╯ │
│▊▊▊▊▊░░░│  ← Level meter
│ -12.3 dB│  ← Peak-held dB value (left-aligned)
│Gate Ph M│  ← Toggle buttons (inputs)

┌────────────┐
│  Out1      │  ← Channel name (click to rename)
│  ╭───╮ │   ← Gain knob
│  │ ◠ │ │
│  ╰───╯ │
│▊▊▊▊▊░░░│   ← Level meter
│ -12.3 dB Lim ●│  ← dB value + Limiter LED (outputs only)
│Xov PEQ Cp Ph Dl M│  ← Toggle buttons (outputs)
└────────────┘
```

### Gain Knob

The rotary dial controls channel gain from **-60 dB** to **+12 dB**. Internally this maps to raw values 0–400 with dual resolution: coarse steps (0.5 dB) below -20 dB and fine steps (0.1 dB) above.

| Action | Effect |
|--------|--------|
| **Click and drag** vertically | Adjust gain — drag up to increase, down to decrease |
| **Scroll wheel** | Step gain by ±1 raw unit (0.1 dB) |
| **Arrow keys** (Up/Right, Down/Left) | Step gain by ±1 raw unit (0.1 dB) |
| **Click the dB label** | Enter an exact dB value via keyboard. Press Enter to apply. Accepts formats like `+3.5`, `-20`, `-inf` |

The arc fills with blue as gain increases from minimum to maximum. The needle indicator shows the current position.

### Level Meter

Each channel has a horizontal LED-style level meter with 20 segments:

- **Green** (15 segments): -60 dB to 0 dB
- **Yellow** (4 segments): 0 dB to +15 dB
- **Red** (1 segment): clip indicator (+15 dB)

A white peak-hold marker tracks the highest recent level and decays slowly (~1.5 s half-life). The numeric readout below the meter shows the peak-held dB value with ~1 s hold before decay.

### Limiter Indicator (Outputs Only)

Output channel strips display a small red LED labeled **Lim** to the right of the dB readout. This indicator lights up when the compressor/limiter on that output channel is actively limiting the signal. The data comes from the device's `limiter_mask` bitmask in the level polling response (~150 ms update rate).

| LED State | Meaning |
|-----------|---------|
| Dim (dark red) | Limiter inactive — signal is below the compressor threshold |
| Bright red | Limiter active — the compressor is attenuating the signal |

### Toggle Buttons

Toggle buttons are color-coded per feature:

| Button | Accent color | Input | Output |
|--------|--------------|-------|--------|
| **Gate** | Green | Yes | — |
| **Phase** | Gold | Yes | Yes |
| **Mute** | Red | Yes | Yes |
| **Xover** | Blue | — | Yes |
| **PEQ** | Purple | — | Yes |
| **Comp** | Teal | — | Yes |
| **Delay** | Light blue | — | Yes |

Click a button to toggle the feature on/off. When **off** the button paints its accent color on the **border and text** (outlined look). When **on** the button fills with the same accent.

Two of the buttons act as **navigation buttons** rather than stateful toggles — they open the [channel detail view](#channel-detail-view) and immediately un-check themselves:

- **Gate** (input strips) opens the Gate panel. The button fills green whenever the gate is "armed" (threshold above the noise floor), regardless of whether the detail view is open.
- **PEQ** (output strips) opens the PEQ panel. The button fills purple whenever any band has non-zero gain and is not bypassed (and channel-bypass is off).
- **Xover** (output strips) opens the Crossover panel. The button fills blue whenever either the hi-pass or lo-pass filter is not bypassed.

> **Note:** The Comp and Delay buttons on output strips are still placeholders — toggling them does not yet control DSP parameters.

### Channel Names

Click the channel name button at the top of any strip to rename it. A dialog appears where you can type a new name (up to 8 characters). Press OK to apply — the name is immediately sent to the device.

### Linked Channels

When channels are linked on the device (e.g., stereo pair), the **slave** channel displays a chain icon (🔗) and its controls (gain knob and toggles) are disabled. Adjusting the master channel automatically updates all linked slaves.

---

## Channel Detail View

Click the **Gate** button on an input strip — or the **PEQ** / **Xover** button on an output strip — in the home view to open the channel detail view:

```
┌──────────────────────────────────────────────────────────┐
│  ← Gate — InA                  [Connected]      [≡]      │
├────┬───────────────────────────────────┬─────────────────┤
│ InA│                                   │  Out1   Out3    │
│ InB│           Channel Strip           │  ▌▌▌▌   ▌▌▌▌    │
│ InC│  (gain, meter, mute/phase/gate)   │   …      …     │
│ InD│                                   │                 │
├────┴───────────────────────────────────┴─────────────────┤
│                                                          │
│       Gate Panel: Threshold / Attack / Hold /             │
│       Release knobs + transfer-function graph             │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

Layout:

- **Header** — back arrow, title (`<feature> — <channel name>`), connection badge, menu
- **Channel navigation** — buttons for all 4 inputs (left) and 4 outputs (right). Switching channels updates the strip and the feature panel without leaving the detail view. The active feature is preserved across channel switches when valid for the new channel type (e.g. moving Out1 → Out2 keeps you on the PEQ panel; moving Out1 → InA falls back to Gate)
- **Channel strip** — same widget as on the home view, kept synchronised with all gain / mute / phase / name edits
- **Routed meters** — when an input is selected, vertical meters for every output it routes to appear on the right; when an output is selected, meters for every input feeding it appear on the left
- **Feature panel** — the **Gate** panel for input channels, the **PEQ** or **Crossover** panel for output channels, or a **placeholder** ("This feature is not available for this channel") when the active feature doesn't apply to the selected channel type

Press **←** in the header to return to the home view.

### Gate Panel

The Gate panel exposes the four parameters of the per-input noise gate. All four are sent to the device atomically every time any one of them changes (the firmware command for the gate is monolithic).

| Knob | Range | Notes |
|------|-------|-------|
| **Threshold** | -89.5 dB to 0 dB | Click the value below the knob to type an exact dB value |
| **Attack** | 1 ms to 999 ms | Time constant for the gate opening |
| **Hold** | 10 ms to 999 ms | Time the gate stays open after the signal drops below threshold |
| **Release** | 1 ms to 3000 ms | Time constant for the gate closing |

The transfer-function graph next to the knobs shows input level (x-axis) versus output level (y-axis), with the threshold marker as a vertical dashed line. Below the threshold the gate is closed (signal cut to the noise floor); above it the gate passes the signal at unity gain. Only the threshold parameter affects the static graph — attack, hold, and release are time-domain parameters with no static representation.

The gate icon on the input channel strip shows green ("armed") whenever the threshold is above the very lowest setting, regardless of whether the detail view is open.

### PEQ Panel

The PEQ panel exposes the 7-band parametric EQ that lives on each output channel. The layout mirrors the t.racks editor: a frequency-response graph at the top showing the summed magnitude across all bands, then 7 columns of per-band controls below.

```
┌─────────────────────────────────────────────────────────────────┐
│  PEQ — Out1                                          [Bypass]   │
├─────────────────────────────────────────────────────────────────┤
│   +18 dB ┊                                                       │
│   +12 dB ┊·····················································│
│    +6 dB ┊·····················································│
│     0 dB ┊─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│
│    -6 dB ┊·····················································│
│   -12 dB ┊·····················································│
│   -18 dB └─────┬───┬────┬────┬────┬────┬────┬────┬─────┬───┬──│
│             20  50 100  200  500  1k   2k   5k  10k  20k       │
├─────────────────────────────────────────────────────────────────┤
│         B1     B2     B3     B4     B5     B6     B7            │
│        [Type] [Type] [Type] [Type] [Type] [Type] [Type]         │
│  Freq   ◍      ◍      ◍      ◍      ◍      ◍      ◍             │
│  Gain   ◍      ◍      ◍      ◍      ◍      ◍      ◍             │
│   Q     ◍      ◍      ◍      ◍      ◍      ◍      ◍             │
│        [Byp]  [Byp]  [Byp]  [Byp]  [Byp]  [Byp]  [Byp]          │
└─────────────────────────────────────────────────────────────────┘
```

#### Per-band controls

| Control | Range | Notes |
|---------|-------|-------|
| **Type** | 7 filter types | Peak, Low Shelf, High Shelf, Low Pass, High Pass, AP1 (1st-order allpass), AP2 (2nd-order allpass) |
| **Freq** | 19.7 Hz – 20.16 kHz | Log-scaled raw 0–300; sub-1 kHz values shown with one decimal (e.g. `300.8 Hz`) to match the original editor; ≥ 1 kHz shown as kHz with two decimals (`5.00 kHz`) |
| **Gain** | −12.0 dB to +12.0 dB | 0.1 dB step; affects Peak / Low Shelf / High Shelf only — for pass and allpass filters the gain knob has no effect on the response |
| **Q** | 0.40 – 128 | Logarithmic scale; **shelves and pass filters are capped at Q = 3.0** (raw 35) per the official editor — switching the type combo to a shelf or pass automatically clamps Q if it was higher; switching back to Peak does *not* restore the previous higher Q |
| **Byp** | toggle | Bypasses *that* band only — the other 6 keep working |

Each control fires the band's parameters atomically: changing any one of the five widgets sends the full band over USB (protocol command `0x33`). All seven bands coalesce independently in the device thread, so dragging Q on band 3 doesn't compete with edits to band 1.

#### Channel-wide bypass

The **Bypass** toggle in the panel header bypasses the entire PEQ block for this output (protocol command `0x3C`). Per-band edits remain editable while bypass is engaged — flip it off and your settings come back exactly as they were.

#### Frequency-response graph

The graph plots the summed magnitude response of all seven bands at 256 log-spaced frequencies between 10 Hz and 25 kHz. Coefficients are computed locally from the raw protocol values using the Audio EQ Cookbook (RBJ) biquad formulas, evaluated at the device's 48 kHz internal sample rate so the displayed curve matches what the hardware actually produces.

- **Markers** — small numbered circles at each band's centre frequency (`1`..`7`). Active bands are green; band-bypassed or channel-bypassed bands are dim grey.
- **Channel-bypass visualisation** — when the channel-wide bypass is engaged the curve renders as a flat 0 dB line at reduced opacity, while the per-band controls remain editable.

The graph is *display-only* in this version — drag-to-edit on the markers is not yet supported. Edit values in the controls below.

#### "PEQ active" indicator on the output strip

The PEQ button on the output channel strip lights up purple whenever the channel's PEQ is shaping the signal, defined as: **at least one band has gain ≠ 0 dB AND is not bypassed AND the channel-wide bypass is off**. The state updates live as you drag knobs and toggle bypasses, on both the home view and the detail view's strip header.

### Crossover Panel

The Crossover panel exposes the hi-pass and lo-pass filters on each output channel. Each filter has three controls:

```
┌──────────────────────────────────────────────────────────────────┐
│  Xover Settings                                                  │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│   +18 dB ┊                                                        │
│    +0 dB ┊─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │
│   -18 dB └────────────────────────────────────────────────────────│
│                                                                   │
├──────────────────────────────────────────────────────────────────┤
│  Hi-Pass   ◍  1.00 kHz    [BW 24 ▾]  [Byp]                      │
│  Lo-Pass   ◍  20.00 kHz   [LR 24 ▾]  [Byp]                      │
└──────────────────────────────────────────────────────────────────┘
```

#### Per-filter controls

| Control | Range | Notes |
|---------|-------|-------|
| **Frequency knob** | 19.7 Hz – 20.16 kHz | Log-scaled, same encoding as PEQ frequency |
| **Slope selector** | 9 slope types | BW 6, BL 6, BW 12, BL 12, LR 12, BW 18, BL 18, BW 24, BL 24, LR 24 |
| **Bypass toggle** | On/Off | Bypasses that filter independently. When bypassed, the slope selector still shows the last-used slope (or LR-24 by default), so un-bypassing re-activates with the correct setting |

> **Important:** The device **forgets** the slope value when a filter is bypassed. The application tracks the last-active slope and re-sends it when you un-bypass. If the application is restarted while a filter is bypassed, the slope defaults to **LR-24** (the device default).

#### Shared frequency-response graph

Both the **Crossover** and **PEQ** panels share a combined frequency-response graph that shows the **summed crossover + PEQ magnitude response**. Editing a crossover filter updates the graph on both panels, and vice versa. The graph uses local biquad coefficient math (Audio EQ Cookbook / RBJ) for both the crossover filters (cascaded 2nd-order Butterworth / Bessel / Linkwitz-Riley sections) and the PEQ bands.

- **PEQ band markers** — numbered circles (`1`..`7`) at each band's centre frequency
- **Crossover markers** — blue triangles labeled `HP` / `LP` at the respective cutoff frequencies

#### "Xover active" indicator on the output strip

The Xover button on the output channel strip lights up blue whenever **either** the hi-pass or lo-pass filter is not bypassed (i.e., has a non-zero slope). The state updates live when you toggle bypass or change the slope selector.

---

## Routing Matrix

The routing matrix in the center of the home view shows which inputs are routed to which outputs. It's a 4×4 grid where each input (left side) can be connected to one or more outputs (right side).

Active connections are drawn as blue lines between input and output nodes. A single output can receive a mix of multiple inputs — each output stores a bitmask of its connected inputs.

### Adding a Route

1. **Click and hold** on an input node (left side circle)
2. **Drag** toward the target output node (right side circle)
3. A dashed preview line follows your cursor
4. **Release** on an output node to connect

The input is OR-ed into the output's routing mask. If the output already had that input routed, nothing changes.

### Removing a Route

1. **Double-click** near an existing connection line
2. The closest connection is removed

The hit detection works within ~8 pixels of the line. The cursor changes to a pointing hand when hovering over nodes or connection lines.

### Visual Feedback

| Element | Appearance |
|---------|------------|
| Active connection | Solid blue line |
| Drag preview | Dashed light-blue line |
| Hovered node | Blue highlight glow |
| Hovered connection line | Pointer cursor |

### Examples

| Routing | Description |
|---------|-------------|
| InA → Out1, InB → Out2, InC → Out3, InD → Out4 | Default 1:1 diagonal routing |
| InA → Out1 + Out2 | Mono input split to two outputs |
| InA + InB → Out1 | Two inputs summed into one output |
| (none) | Output silenced (no input routed) |

---

## Preset Management

The DSP 4x4 Mini stores 1 factory preset (F00) and 30 user presets (U01–U30). Presets are saved in flash memory and persist across power cycles.

### Recalling a Preset

1. Click **Recall** in the bottom bar
2. The preset picker dialog appears listing all available presets
3. Factory (F00) is always available; empty user slots are greyed out
4. Select a preset and click **Recall**
5. The device loads the preset and the UI updates to reflect all settings

### Storing a Preset

1. Click **Store** in the bottom bar
2. The preset picker dialog appears in store mode
3. Factory (F00) is disabled (cannot overwrite)
4. Select a user slot (U01–U30) — you can overwrite existing presets
5. Enter a name (up to 14 characters) in the name field
6. Click **Store**
7. A confirmation dialog appears — confirm to write to flash

> **Warning:** Storing a preset writes to the device's flash memory. This operation takes ~2 seconds during which the device is busy. Existing data in the target slot is overwritten.

---

## Offline Mode

Run without hardware using the `--offline` flag:

```bash
minidspqt --offline
```

In offline mode:

- An in-RAM virtual DSP simulates the hardware
- All controls (gain, mute, phase, routing) are fully functional
- Level meters are idle (no audio signal)
- The status badge shows **Offline** (amber)
- You can load and save `.unt` preset files

This is useful for designing presets on the go, testing configurations, or exploring the UI without a device connected.

---

## .unt Preset Files

The `.unt` file format is used by the manufacturer's software. This application can read and write these files, preserving byte-identical data for untouched fields.

### Loading a .unt File

1. Click the **menu button** (≡) in the top-right corner
2. Select **Load .unt file...**
3. Choose a `.unt` file from the file dialog

**In offline mode:** All 30 preset slots from the file are loaded into the virtual DSP. You can browse and edit any slot.

**With hardware connected (online mode):** The file is loaded as a read-only preview. Controls are disabled, but you can inspect the settings. The status bar shows the filename being previewed.

### Saving a .unt File

> Only available in **offline mode**.

1. Click the **menu button** (≡)
2. Select **Save .unt file...**
3. Choose a location and filename in the file dialog
4. The current state of all 30 virtual preset slots is written to disk

The saved file is byte-identical to the original for any untouched data, making it safe to round-trip existing `.unt` files.

---

## Menu

Click the **menu button** (≡) in the top-right corner of the window:

| Option | Description |
|--------|-------------|
| **Load .unt file...** | Import a manufacturer preset file |
| **Save .unt file...** | Export preset data to a `.unt` file (offline mode only) |
| **About** | Show version, license, and project information |

---

## USB Permissions

The application communicates with the DSP via `/dev/hidraw*` device files. By default, these require root access. To use the application as a regular user, create a udev rule:

```bash
sudo tee /etc/udev/rules.d/99-dspmini.rules << 'EOF'
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0168", ATTRS{idProduct}=="0821", MODE="0666"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Then disconnect and reconnect the DSP. The device should now be accessible without `sudo`.

---

## Troubleshooting

### "Disconnected" status and controls are greyed out

- Check that the DSP 4x4 Mini is connected via USB
- Verify USB permissions (see [USB Permissions](#usb-permissions))
- Try running with `sudo` to rule out permission issues
- Check kernel logs: `dmesg | tail` for USB/HID errors

### Application crashes on startup

- Ensure Python 3.11+ is installed: `python3 --version`
- Reinstall dependencies: `uv sync --reinstall`
- Run with debug logging: `minidspqt -vv`

### Controls don't update the device

- Check the log output for error messages (`-v` or `-vv`)
- The device may be busy (e.g., writing flash after a store operation) — wait a few seconds
- USB communication errors trigger automatic reconnection after 2 seconds

### Linked channel controls are disabled

This is expected behavior. When channels are linked, the slave channel's gain and toggles are controlled by the master. Look for the chain icon (🔗) on the slave strip.

### Level meters show no activity

- Ensure audio is actually playing through the DSP
- Check that the input source and routing matrix are configured correctly
- In offline mode, meters are always idle (no audio signal is generated)

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| **Up / Right arrow** | Increase gain (when knob is focused) |
| **Down / Left arrow** | Decrease gain (when knob is focused) |
| **Enter** | Apply typed dB value (when dB label is being edited) |
