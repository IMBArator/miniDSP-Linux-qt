# Architecture

This document describes how miniDSP-Linux-qt is built and why. It draws the
architecture decision records in [decisions/](decisions/index.md) together
into one reading order: the records stay the place for *why*, this page is the
map of *what* and *how*. The rules every change must keep are collected in
[Invariants](#invariants). How changes are made is in
[CONTRIBUTING.md](../CONTRIBUTING.md), and how to work on the code from a
checkout in the [developer guide](development.md).

<!-- Keep this page in step with the code and the records: update it in the
     same change that alters the design, adds or removes a module, or accepts
     a record that changes the picture. -->

## Goal and shape

miniDSP-Linux-qt is a graphical editor for the t.racks DSP 4x4 Mini, written
with PySide6
([ADR-0002](decisions/0002-use-pyside6-essentials-as-the-gui-toolkit.md)). It
covers what the manufacturer's Windows editor does (gain, routing, gate, PEQ,
crossover, compressor, delay, presets, channel linking, test tone, device
lock) on Linux and Windows, and adds an offline mode that edits `.unt` preset
files without a device.

The application speaks no USB itself. Everything about the device, from the
wire format to the `.unt` file format, comes from the
[miniDSP-Linux](https://github.com/IMBArator/miniDSP-Linux) protocol library,
pinned to one of its release wheels
([ADR-0001](decisions/0001-build-on-the-minidsp-linux-protocol-library.md),
[ADR-0003](decisions/0003-pin-the-protocol-library-to-a-release-wheel-via-pep-508.md)).

```
  cli.py ─► app.py ─► MainWindow ─── request_*() ───► DeviceThread (QThread)
                       │   ▲                            │  poll loop, coalesced
              refresh  │   │ signals                    │  writes, preset queue
                       ▼   │                            ▼
            HomeView, DetailView,          DSPmini (minidsp.device) ─► DSP 4x4 Mini
            panels, dialogs, widgets       or VirtualDSP (offline, tests)
                       ▲
                       │ read by every view
                  DeviceState (model.py) ◄── config_loaded / levels from the worker
```

## The core idea

Four choices shape everything else:

1. **One thread owns the device.** All device I/O runs in `DeviceThread`, so
   the GUI never blocks on USB
   ([ADR-0005](decisions/0005-isolate-device-io-in-a-dedicated-qthread-worker.md)).
   Edits are coalesced per poll cycle, so dragging a knob sends one command
   per cycle, while preset and configuration operations queue in order
   ([ADR-0007](decisions/0007-coalesce-parameter-writes-and-serialise-config-operations.md)).
2. **`MainWindow` is the only mediator.** Views emit signals; `MainWindow`
   updates the state, fans edits out to linked channels and asks the worker
   to send them
   ([ADR-0006](decisions/0006-make-mainwindow-the-sole-mediator-between-views-and-device.md),
   [ADR-0009](decisions/0009-replicate-master-to-slave-fan-out-in-the-client.md)).
3. **The device is authoritative.** `DeviceState` mirrors the configuration
   the device reports
   ([ADR-0008](decisions/0008-mirror-device-configuration-in-a-typed-devicestate-dataclass.md));
   after a multi-step edit the GUI reads it back instead of trusting its own
   copy
   ([ADR-0011](decisions/0011-treat-the-device-as-authoritative-and-re-read-after-multi-step-edits.md)).
4. **Offline is the same interface in RAM.** `VirtualDSP` implements the
   `DSPmini` interface, so offline mode runs through the same worker and the
   same code paths as a real device
   ([ADR-0010](decisions/0010-implement-offline-mode-as-an-in-ram-virtual-dsp.md)),
   and the tests use it as their fake device
   ([ADR-0025](decisions/0025-test-headlessly-against-an-injected-fake-dsp.md)).

## Components

### Device worker (`device_thread`)

`DeviceThread` opens the device through a factory (`DSPmini` by default,
`VirtualDSP` offline, a fake in tests), reads the configuration, and then
polls levels about every 150 ms. Parameter writes arrive through
`request_*()` methods and are stored in a dict keyed by `CommandType`,
channel and (for PEQ) band; each poll cycle sends what is pending, so only the
latest value of a fast edit reaches the device; the dict keeps insertion
order, which link preparation relies on. Preset load and store, configuration
reads and the `.unt` export are queued in order instead, because each of them
reads the configuration back. The worker catches
only the device and transport errors listed in `DEVICE_ERRORS` and reconnects
after them; any other exception is a bug and propagates
([ADR-0012](decisions/0012-catch-only-device-and-transport-errors.md)). When
the device reports a lock, the worker pauses and asks for the PIN; a cancelled
or failed unlock, and a newly set PIN, stop the worker instead of retrying
([ADR-0017](decisions/0017-device-lock-pin-flow-stops-the-worker-rather-than-retrying.md)).

### Main window (`views/main_window`)

`MainWindow` owns the worker, the `DeviceState` and the stack of views. It
connects the views' signals to state updates and worker requests, switches
between connected and offline mode at runtime, and runs the multi-step flows:
recall and store presets, channel linking, copying channel settings, loading
and saving `.unt` files, the test tone and the device PIN. Presets are stored
only to the user slots U01–U30: the factory preset F00 can be recalled but is
never offered as a store target, and the library refuses to write it too.
Saving a `.unt`
while connected exports the presets as stored on the device, like the
manufacturer's editor, and asks whether unsaved edits of the active preset
should go into the file
([ADR-0033](decisions/0033-save-unt-files-from-the-stored-presets-like-the-original-editor.md)).

### Device state (`model`)

`DeviceState` and its per-channel dataclasses mirror the dict that
`DSPmini.read_config()` returns, in raw protocol units: inputs are channels
0–3, outputs 4–7. `mutate_with_links()` applies an edit to a master channel
and every slave linked to it. The `*_active` helpers decide when a strip
button shows its feature as active.

### Offline mode (`virtual_dsp`, `blank_seed`, `unt_files`)

`VirtualDSP` keeps a configuration and the 30 preset slots in memory and
answers like a device, including the lock and PIN behaviour. `blank_seed`
fills it from the library's empty `.unt` file when offline mode starts
without a device configuration. Switching from online to offline carries the
live configuration over. `unt_files` holds the GUI-side `.unt` helpers that
compare stored and live presets; reading and writing the file itself is the
library's `minidsp.unt`
([ADR-0016](decisions/0016-preserve-unknown-unt-bytes-with-field-level-overwrites.md)).

### Views and panels (`views/`)

The home view shows four input and four output strips, the routing matrix and
the level meters. The detail view shows one channel with its strip, a feature
panel and the meters of the channels routed to it
([ADR-0022](decisions/0022-compose-the-detail-view-from-pluggable-feature-panels.md)).
Each feature panel (gate, PEQ, crossover, compressor, delay) emits all values
of its feature together, because the device takes them as one command
([ADR-0013](decisions/0013-emit-multi-parameter-dsp-commands-atomically.md)).
A linked slave channel is shown read-only with a banner naming its master
([ADR-0023](decisions/0023-make-linked-slave-channels-read-only-in-the-ui.md)).
The dialogs for iterative tools (channel linking, test tone) stay open after
Apply
([ADR-0024](decisions/0024-use-non-modal-apply-and-stay-open-dialogs-for-iterative-tools.md)).
The whole UI is built in code, without Designer files
([ADR-0018](decisions/0018-build-the-ui-programmatically-instead-of-qt-designer-files.md)).

### Widgets (`widgets/`)

Custom-painted widgets: knobs, toggle buttons, level meters, the routing
matrix and the graphs for gate, PEQ, crossover, compressor and delay. They
know nothing about the device. The filter curves are computed locally from
biquad formulas at the device's 48 kHz sample rate
([ADR-0015](decisions/0015-render-filter-curves-locally-from-biquad-math-at-48-khz.md)),
and the level meters work on the device's 24-bit levels
([ADR-0032](decisions/0032-meter-from-24-bit-levels-and-decide-clip-on-the-raw-sample.md)).

### Theme and styling (`theme`, `resources/`)

`ThemeManager` follows the desktop's light or dark scheme unless the user
picked one, which is stored in `QSettings`
([ADR-0020](decisions/0020-let-an-explicit-theme-preference-override-the-reported-system-scheme.md)).
Widget styles live in `style_dark.qss` and `style_light.qss`; state-dependent
looks are switched through dynamic properties such as `peq_active`
([ADR-0019](decisions/0019-style-with-qss-and-drive-state-styling-through-dynamic-properties.md)).
Each DSP feature has one hue, used for its button, its active indicator and
its graph
([ADR-0021](decisions/0021-give-each-dsp-feature-one-brand-hue-across-the-whole-ui.md)).

### Library adapters (`defaults`, `levels`)

`defaults` turns the library's factory preset F00 into the GUI's default
values
([ADR-0014](decisions/0014-source-factory-defaults-from-the-protocol-library.md)).
`levels` is the one place that imports the library's level symbols and turns a
poll response into a `ChannelLevels` record.

### Entry point (`cli`, `app`)

`cli.main()` parses `--offline` and `-v`/`-vv`; `app.run()` configures
logging (to stderr, or to `minidspqt.log` in the application data directory
when there is no console), creates the `QApplication`, binds the theme
manager and shows `MainWindow`.

### Packaging (`packaging/`)

The Linux AppImage bundles its own CPython and PySide6
([ADR-0027](decisions/0027-distribute-a-self-contained-appimage-with-bundled-cpython.md)).
The Windows installer and portable zip are assembled on Linux from the
embeddable CPython and Windows wheels
([ADR-0031](decisions/0031-build-the-windows-distribution-on-linux-from-embeddable-cpython-and-wheels.md)).
Both keep Qt as ordinary shared libraries next to the application, which the
licence notice relies on
([ADR-0004](decisions/0004-license-under-gplv3-with-lgpl-and-interop-notices.md)).

## Module map

| Path | Role |
|---|---|
| `minidspqt/__init__.py` | Package docstring and `__version__` |
| `minidspqt/cli.py` | Entry point `minidspqt`: `--offline`, `-v`/`-vv` |
| `minidspqt/app.py` | Logging set-up, `QApplication`, theme binding, offline seeding |
| `minidspqt/device_thread.py` | `DeviceThread`: poll loop, coalesced writes, ordered config operations, lock handling |
| `minidspqt/model.py` | `DeviceState` and the per-channel dataclasses |
| `minidspqt/virtual_dsp.py` | `VirtualDSP`, the in-memory device for offline mode and tests |
| `minidspqt/blank_seed.py` | Seeds a `VirtualDSP` from the library's empty `.unt` file |
| `minidspqt/unt_files.py` | Stored-versus-live helpers and file-dialog constants for `.unt` files |
| `minidspqt/defaults.py` | Default values from the library's factory preset F00 |
| `minidspqt/levels.py` | The library's level symbols and `ChannelLevels` |
| `minidspqt/theme.py` | `Theme` colours (`DARK_THEME`, `LIGHT_THEME`) and the `ThemeManager` singleton |
| `minidspqt/resources/` | Logo, `style_dark.qss`, `style_light.qss` |
| `minidspqt/views/main_window.py` | `MainWindow`: owns worker, state and views; runs the multi-step flows |
| `minidspqt/views/home_view.py` | Eight channel strips, routing matrix, level meters |
| `minidspqt/views/detail_view.py` | One channel with its feature panel and routed meters |
| `minidspqt/views/channel_strip.py` | `InputChannelStrip`, `OutputChannelStrip` |
| `minidspqt/views/_connection_chip.py` | The connection status chip of both views |
| `minidspqt/views/preset_picker.py`, `channel_linking_dialog.py`, `copy_channel_dialog.py`, `test_tone_dialog.py`, `device_pin_dialog.py` | The dialogs |
| `minidspqt/views/panels/` | Feature panels (`gate`, `peq`, `xover`, `compressor`, `delay`, `placeholder`) and their shared helpers `_slave_lock.py` and `_overlay_controls.py` |
| `minidspqt/widgets/` | Custom-painted widgets (knob, toggle button, LED, gain indicator, level meter, routing matrix, graphs) |
| `tests/` | The test suite, one module per feature; `conftest.py` provides `FakeDSPmini` and the headless set-up |
| `packaging/appimage/` | AppImage build script, `AppRun`, desktop entry and icon |
| `packaging/windows/` | `build.py` (Windows distribution from Linux), launcher, installer script, icon |
| `docs/` | MkDocs site sources: include stubs, `user-guide.md`, `hooks.py`, `gen_ref_pages.py`, this page, `decisions/`, screenshots and concept art |
| `scripts/` | `version.sh` and `publish.sh`, the release tooling |
| `Makefile` | The only entry point for setup, tests, checks, builds, docs and releases |

### Import rules

* The core modules (`model`, `levels`, `defaults`, `virtual_dsp`,
  `blank_seed`, `unt_files`, `device_thread`, `theme`) import no views and no
  widgets.
* `widgets/` import only `theme`, `model`, `levels` and `minidsp.protocol`;
  they never import `views/`.
* `views/` and `views/panels/` import `widgets/` and the core modules, but not
  `device_thread`; only `views/main_window.py` imports `device_thread`.
* `minidsp.device` is imported by `device_thread` (for `DSPmini` and the
  errors), by `virtual_dsp` (for `DeviceLockedError`) and by `MainWindow`,
  which only hands `DSPmini` to the worker as its factory. Otherwise the views
  use `minidsp.protocol` for conversions, and `MainWindow` uses `minidsp.unt`
  for files.
* The library's level symbols are imported only in `levels`, its factory
  defaults only in `defaults`.

### How things plug in

* **A device command.** When the library offers a new command the GUI should
  use: add a `CommandType` and a `request_<name>()` method to `DeviceThread`
  and dispatch it to the `DSPmini` method; implement the same method in
  `VirtualDSP`, so offline mode and the tests have it too; add the value to
  `DeviceState` if the device reports it; and connect the view's signal to the
  request in `MainWindow`, through `mutate_with_links()` when the value is per
  channel. A feature with several values is one command.
* **A feature panel.** A widget in `views/panels/` that emits one signal with
  all values of its feature and offers `set_params_silently()` and
  `set_linked_slave()`. `DetailView` creates it, adds it to its panel stack
  and picks it by feature name and channel type; channels it doesn't apply to
  get the placeholder panel.
* **A widget.** A class in `widgets/`, exported from `widgets/__init__.py`.
  A custom-painted widget takes its colours from the current `Theme` and
  repaints on `theme_manager.themeChanged`; a widget styled by QSS needs
  only its rules in both `.qss` files.
* **A colour or style.** A named colour in both `Theme` instances in
  `theme.py`, and the matching rules in both `.qss` files.
* **A test.** A module `tests/test_<feature>.py` that drives the code against
  `FakeDSPmini`.

## Invariants

The rules below follow from the design above. A change that breaks one is
wrong even when every test passes; the record named with each rule explains
why.

### Device access

- Only `DeviceThread` talks to the device: it opens it through the factory it
  is given (`DSPmini`, `VirtualDSP` or a fake) and is the only code that calls
  its methods
  ([ADR-0005](decisions/0005-isolate-device-io-in-a-dedicated-qthread-worker.md)).
- No view except `MainWindow` calls the worker; every edit goes through
  `MainWindow`, which updates `DeviceState` and makes the request
  ([ADR-0006](decisions/0006-make-mainwindow-the-sole-mediator-between-views-and-device.md)).
- A feature with several values (gate, a crossover filter, compressor, a PEQ
  band) is sent as one command with all its values, never field by field
  ([ADR-0013](decisions/0013-emit-multi-parameter-dsp-commands-atomically.md)).
- The worker catches only `DEVICE_ERRORS`; every other exception propagates
  ([ADR-0012](decisions/0012-catch-only-device-and-transport-errors.md)).

### Device state and safety

- After a preset recall or store, a link change or any other multi-step edit,
  the GUI reads the configuration back from the device
  ([ADR-0011](decisions/0011-treat-the-device-as-authoritative-and-re-read-after-multi-step-edits.md)).
- An edit of a master channel reaches every linked slave, in `DeviceState` and
  in the device requests; slave channels are read-only in the UI
  ([ADR-0009](decisions/0009-replicate-master-to-slave-fan-out-in-the-client.md),
  [ADR-0023](decisions/0023-make-linked-slave-channels-read-only-in-the-ui.md)).
- A cancelled or failed unlock, and a newly set PIN, stop the worker; it never
  reconnects on its own after them
  ([ADR-0017](decisions/0017-device-lock-pin-flow-stops-the-worker-rather-than-retrying.md)).
- The GUI never offers F00 as a store target; presets are stored only to
  U01–U30 ([Main window](#main-window-viewsmain_window)).
- A `.unt` saved while connected holds the presets as stored on the device;
  live edits go into it only when the user agrees
  ([ADR-0033](decisions/0033-save-unt-files-from-the-stored-presets-like-the-original-editor.md)).

### Sources of truth

- `DeviceState` is the GUI's only copy of the device configuration; views
  render from it and keep none of their own
  ([ADR-0008](decisions/0008-mirror-device-configuration-in-a-typed-devicestate-dataclass.md)).
- Default values come from the library's factory preset, never from constants
  in the GUI
  ([ADR-0014](decisions/0014-source-factory-defaults-from-the-protocol-library.md)).
- The `.unt` format belongs to the library's `minidsp.unt`; the GUI never
  parses or packs `.unt` bytes itself
  ([ADR-0016](decisions/0016-preserve-unknown-unt-bytes-with-field-level-overwrites.md)).
- Level symbols of the library are imported only in `minidspqt/levels.py`
  ([ADR-0032](decisions/0032-meter-from-24-bit-levels-and-decide-clip-on-the-raw-sample.md)).
- Filter curves are computed at the device's 48 kHz sample rate
  ([ADR-0015](decisions/0015-render-filter-curves-locally-from-biquad-math-at-48-khz.md)).

### Layering and platforms

- `minidspqt/` contains no operating-system branch; platform differences live
  in the protocol library and in `packaging/`
  ([ADR-0030](decisions/0030-support-windows-by-delegating-transport-selection-to-the-protocol-library.md)).
- The imports follow the [import rules](#import-rules): widgets never import
  views, and only `MainWindow` imports the worker
  ([ADR-0006](decisions/0006-make-mainwindow-the-sole-mediator-between-views-and-device.md)).
- Every distribution keeps Qt as separate, replaceable shared libraries;
  nothing freezes or statically links PySide6
  ([ADR-0004](decisions/0004-license-under-gplv3-with-lgpl-and-interop-notices.md),
  [ADR-0031](decisions/0031-build-the-windows-distribution-on-linux-from-embeddable-cpython-and-wheels.md)).

### Tests

- Tests never talk to a real DSP: they inject `FakeDSPmini` and run headless
  on Qt's offscreen platform
  ([ADR-0025](decisions/0025-test-headlessly-against-an-injected-fake-dsp.md)).
- Tests never touch the developer's real settings: `QStandardPaths` test mode
  is on for the whole suite
  ([ADR-0025](decisions/0025-test-headlessly-against-an-injected-fake-dsp.md)).

## Decision records

Every architectural decision has a record under
[decisions/](decisions/index.md); the index groups them by area and lists the
decisions that reversed an earlier position. The sections above link to the
record behind each choice where it is made.
