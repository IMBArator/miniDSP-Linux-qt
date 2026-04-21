# Offline Mode: Virtual DSP + Recall/Store + .unt Read/Write

## Context

The app currently only does something useful when a real t.racks DSP 4x4 Mini is plugged in. An earlier iteration let the user load a `.unt` file as a read-only preview — but with the device unplugged every control is greyed out, so there's no way to actually tune presets at a desk without hardware. Two independent observations collapse into one clean solution:

1. There's already a factory injection point at [device_thread.py:52](minidspqt/device_thread.py#L52) (`dsp_factory=DSPmini`) and an almost-complete `FakeDSPmini` test double at [tests/conftest.py:55-112](tests/conftest.py#L55) that just needs stateful setters and slot storage.
2. The existing **Recall** and **Store** footer buttons ([home.ui:97-117](minidspqt/forms/home.ui#L97)) are visible but unwired — they're the natural UI for slot switching, mirroring the physical unit's buttons.

**The design** therefore: launch the app with `--offline` to run against a **stateful in-RAM virtual DSP** that implements the same interface as `DSPmini`. The rest of the app (DeviceThread, MainWindow, HomeView) stays unaware — it sees a connected device and behaves normally. Editing works, level-polling works, Recall/Store work, and a loaded `.unt` file simply **seeds the virtual DSP's 30 slots**. Saving writes the virtual DSP's full state back to a `.unt` file. The same code path serves both online and offline; no `Mode` enum, no state-split between a live device and an offline session.

Non-goals (future work):
- Editing PEQ/xover/comp/delay/gate/routing from Home — those remain display-only until detail views land.
- Pushing an in-memory preset to a connected *real* device ("Apply to device"). When connected live, edits still go to the physical DSP via existing request_* calls.
- A full "preset browser" sidebar UI. Slot switching happens through Recall, like hardware.

## Approach

Five cohesive pieces, built in three commits.

**(1) Stateful `VirtualDSP` as production code.** Promote `FakeDSPmini` out of `tests/conftest.py` and into `minidspqt/virtual_dsp.py`, rewritten to actually mutate its config: `set_gain()` updates `self._config["gains"][ch]`, `mute()` updates `self._config["mutes"][ch]`, etc. Maintain an internal `self._slots: list[dict | None]` of length 30 for preset storage; `load_preset(slot)` overwrites `self._config` from `self._slots[slot]` and sets `active_slot`; `store_preset(slot, name)` copies `self._config` into `self._slots[slot]` and updates the name. `poll_levels()` keeps returning a fixed zero/low dict (no synthesis needed — this is offline, meters staying quiet is fine). `read_config()` returns the current `self._config` (including `active_slot` and `preset_names`).

**(2) `--offline` launch flag.** Thread a `dsp_factory` parameter through `cli.main → app.run → MainWindow → DeviceThread`. In offline mode, factory is `VirtualDSP` (pre-seeded with a sane default — e.g. a single bundled 429-byte "blank" blob parsed into slot 0). Default is `DSPmini`. Badge in offline mode shows "Offline" (amber) rather than "Connected" (green), so the user always knows they're on a virtual unit; edits still work exactly as if connected.

**(3) Recall / Store buttons wired.** Wire the existing footer buttons to open small picker dialogs:
- **Recall**: opens a `QDialog` listing all 30 slots (`U01 — <name>` for non-empty, "`U<NN> — (empty)`" dimmed for empty). On confirm, calls `DeviceThread.request_load_preset(slot)` — which already exists. DeviceThread emits `config_loaded` after the load; MainWindow's existing `_on_config_loaded` handler already rebuilds `_state` and refreshes the view. Works identically for real and virtual DSP.
- **Store**: same picker, plus a `QLineEdit` pre-filled with the current preset name. On confirm, calls `DeviceThread.request_store_preset(slot, name)`. The virtual DSP persists into `self._slots[slot]`; the real DSP writes to flash.

**(4) `.unt` seeds / dumps the DSP.** When `Load .unt file…` is used:
- If running offline, parse all 30 slots into a list of dicts and seed `virtual_dsp._slots[:]`, then call `virtual_dsp.load_preset(active_slot)` so the UI reflects the file's active slot. Also store the **raw 13,010 bytes** on the virtual DSP (as `_source_bytes`) so Save can preserve unknown/reserved fields (test tone mode, sine freq, delay unit, padding).
- If running online (real device), keep today's behaviour: load shows a read-only preview banner. (This path stays minimal — offline is the main workflow for editing files.)

Add **`Save .unt file…`** menu action. In offline, pulls all 30 slots + header template out of the virtual DSP and calls `save_unt(path, slots, active_slot, template_bytes)`. In online mode, the menu item is disabled (saving live device state to .unt is a future enhancement — would require reading all 30 slots from the real device, a multi-second operation).

**(5) `unt_writer.py`.** Pure function. Starts from a 13,010-byte template (`virtual_dsp._source_bytes` if a file was loaded; otherwise a bundled blank template), overwrites the active-slot byte (0x11) and each non-empty slot's 429-byte blob. Each blob starts as a mutable copy of the original slot bytes so unknown fields survive, then only the fields we model get rewritten (channel names, gains, mutes via footer bitmasks, phases, gates, routing, PEQ bands/bypass, crossovers, compressors, output delays, link flags). Round-trip unit test proves byte-identity.

## Critical files

**New:**
- [minidspqt/virtual_dsp.py](minidspqt/virtual_dsp.py) — stateful in-RAM DSP (~180 lines). Implements the same public interface as `minidsp.device.DSPmini`.
- [minidspqt/unt_writer.py](minidspqt/unt_writer.py) — `save_unt(path, slots, active_slot, template)` (~150 lines).
- [minidspqt/views/preset_picker.py](minidspqt/views/preset_picker.py) — a small `QDialog` for Recall/Store (~80 lines). Reused by both buttons.
- [minidspqt/resources/blank.unt](minidspqt/resources/blank.unt) — bundled 13,010-byte template for `--offline` with no file loaded (generate once by running `--offline`, doing nothing, saving — or copy from the fixture, but strip user-specific PIN).
- [tests/test_virtual_dsp.py](tests/test_virtual_dsp.py) — state persistence, load/store round-trip, read-after-write.
- [tests/test_unt_writer.py](tests/test_unt_writer.py) — byte-level round-trip + targeted-edit tests.

**Modified:**
- [minidspqt/unt_loader.py](minidspqt/unt_loader.py) — add `load_unt_all_slots(path)` returning `(slots: list[dict|None], active_slot, slot_names, raw_bytes)`. Keep the existing `load_unt()` as a thin wrapper over it for backward compatibility with the already-wired menu handler.
- [minidspqt/cli.py](minidspqt/cli.py) — argparse with `--offline` flag, passes through.
- [minidspqt/app.py](minidspqt/app.py) — `run(offline: bool = False)` accepts the flag and picks the factory.
- [minidspqt/views/main_window.py](minidspqt/views/main_window.py) — accept `dsp_factory` in `__init__`, pre-seed the virtual DSP from `blank.unt` when `--offline`, add Save menu action, wire Recall/Store buttons, change Load .unt path so it seeds the virtual DSP when offline.
- [minidspqt/views/home_view.py](minidspqt/views/home_view.py) — add `set_connected_offline()` that sets an amber "Offline" badge; reuse the existing enable/disable logic (no more split into set_editable — offline mode just looks like connected).
- [tests/conftest.py](tests/conftest.py) — strip down to a thin import shim that aliases `FakeDSPmini = VirtualDSP`. Existing device_thread tests keep working because the interface is unchanged.

## Implementation details

### (1) `virtual_dsp.py`

The `DSPmini` public interface to mirror (from [minidsp/device.py]): `open()`, `close()`, `read_config() → dict`, `poll_levels() → dict`, `set_gain(ch, raw)`, `mute(ch, muted)`, `set_phase(ch, inverted)`, `set_gate(ch, attack, release, hold, threshold)`, `set_hipass(ch, freq, slope)`, `set_lopass(ch, freq, slope)`, `set_peq_band(ch, band, gain, freq, q, type, bypass)`, `set_peq_channel_bypass(ch, bypass)`, `set_compressor(ch, ratio, knee, attack, release, threshold)`, `set_delay(ch, samples)`, `set_matrix_route(out, mask)`, `set_channel_link(ch, flags)`, `set_channel_name(ch, name)`, `load_preset(slot) → dict`, `store_preset(slot, name)`. The exact set visible to the UI is whatever `DeviceThread._drain_pending` / `_handle_preset` calls — audit those two methods during implementation.

```python
class VirtualDSP:
    def __init__(self) -> None:
        self._config: dict = _default_config()
        self._slots: list[dict | None] = [None] * 30
        self._source_bytes: bytes | None = None  # set by load_from_unt_bytes()

    def load_from_unt_bytes(self, raw: bytes, slots: list[dict|None], active: int) -> None:
        """Seed state from a parsed .unt file."""
        self._source_bytes = raw
        self._slots = list(slots)
        if slots[active] is not None:
            self._config = dict(slots[active])
            self._config["active_slot"] = active
            self._config["preset_names"] = _names_from_slots(slots)

    def export_to_unt_args(self) -> tuple[list[dict|None], int, bytes | None]:
        return list(self._slots), self._config["active_slot"], self._source_bytes

    # ... setters mutate self._config; load_preset restores from _slots; store_preset copies _config→_slots
```

Thread safety: `DeviceThread` already serializes access (all DSP calls happen on its worker thread). No extra lock needed.

### (2) CLI / app wiring

`cli.py`:
```python
import argparse
def main() -> None:
    parser = argparse.ArgumentParser(prog="minidspqt")
    parser.add_argument("--offline", action="store_true",
                        help="Run against an in-RAM virtual DSP (no hardware required)")
    args = parser.parse_args()
    from .app import run
    run(offline=args.offline)
```

`app.py run(offline=False)` picks `VirtualDSP` vs `DSPmini` and passes as `dsp_factory` to `MainWindow(dsp_factory=...)`.

`MainWindow.__init__(self, dsp_factory=DSPmini)` forwards to `DeviceThread(dsp_factory=dsp_factory, parent=self)`. If `dsp_factory is VirtualDSP` (check via `is`), pre-seed it with the bundled blank template: load `minidspqt/resources/blank.unt`, parse, call `virtual_dsp.load_from_unt_bytes(...)`. Store a reference to the factory instance (DeviceThread needs to instantiate it once and keep it around — small refactor of `DeviceThread._poll_loop` at [device_thread.py:149]: instead of `self._dsp_factory()` on each (re)connect, use an already-constructed instance when a `dsp_instance` attribute is set).

Badge: add `HomeView.set_offline_mode(True)` which sets an amber "Offline" badge and bypasses the Disconnected styling. MainWindow calls this in `__init__` when `dsp_factory is VirtualDSP`. The existing `_on_connection_changed(connected)` handler is a no-op for the offline case (the VirtualDSP's open() always succeeds, so connected=True fires once and that's fine — but we want "Offline" text, so override).

### (3) Recall / Store — `preset_picker.py`

```python
class PresetPickerDialog(QDialog):
    def __init__(self, parent, slot_names: list[str], active_slot: int, mode: Literal["recall","store"], current_name: str = ""):
        # QListWidget with 30 rows, empties dimmed.
        # If mode == "store": extra QLineEdit pre-filled with current_name.
        # OK button returns (slot_index, name) via a property.
```

Wiring in `main_window.py`:
- `_home_view.recallButton.clicked.connect(self._on_recall)`
- `_home_view.storeButton.clicked.connect(self._on_store)`

```python
def _on_recall(self) -> None:
    dlg = PresetPickerDialog(self, self._state.preset_names, self._state.active_slot or 0, "recall")
    if dlg.exec() == QDialog.Accepted:
        self._thread.request_load_preset(dlg.chosen_slot)

def _on_store(self) -> None:
    current_name = ""
    if self._state.active_slot is not None and self._state.preset_names:
        current_name = self._state.preset_names[self._state.active_slot]
    dlg = PresetPickerDialog(self, self._state.preset_names, self._state.active_slot or 0, "store", current_name)
    if dlg.exec() == QDialog.Accepted:
        self._thread.request_store_preset(dlg.chosen_slot, dlg.chosen_name)
```

The `config_loaded` signal already fires after `load_preset`, and the existing handler rebuilds state + refreshes the view — zero extra work for Recall.

For Store, the current code **doesn't** trigger a refresh — we should emit a `config_loaded` after store (or just update `preset_names` locally). Simpler: after a successful store, MainWindow updates its own `_state.preset_names[slot] = name` and calls `home_view.apply_state(self._state)`.

### (4) `unt_writer.py`

Byte layout reversed from [analysis/protocol.md:1105-1300]. The writer is a pure function and doesn't know about `VirtualDSP`:

```python
def save_unt(path, slots: list[dict|None], active_slot: int, template: bytes | None) -> None:
    data = bytearray(template) if template else bytearray(_bundled_blank())
    data[ACTIVE_SLOT_OFFSET] = active_slot + 1  # 1-indexed
    for i, cfg in enumerate(slots):
        if cfg is None:
            continue
        _write_slot(data, i, cfg, original_blob=data[_slot_blob_slice(i)])
    path = str(path)
    with open(path, "wb") as f:
        f.write(bytes(data))
```

`_write_slot` starts from the existing 429 bytes of that slot (so unknown bytes round-trip) and overwrites the known fields from `cfg` (the dict shape produced by `parse_preset_params`, optionally extended by the writer's own pack helpers for fields we edit). Field encoders: `_pack_input_block(cfg, channel)`, `_pack_output_block(cfg, channel)`, plus footer bitmasks for mutes and PEQ band bypass. All little-endian uint16 where the protocol specifies.

Important gotchas from exploration:
- **Preset name**: `parse_preset_params` doesn't extract the 14-byte preset name (it's only in `session.preset_names[slot]`). The writer needs the name passed alongside the cfg. Simplest: have `VirtualDSP.export_to_unt_args()` return a list of `(cfg, name)` tuples instead of bare cfgs. Or extend slot dicts with a `name` field before passing to the writer.
- **`_PEQ_CHANNEL_BYPASS_OFFSET + i` (i=0..3)** in the upstream parser reads bytes 428, 429, 430, 431 — only 428 is actually inside the 429-byte blob. For the writer, write only byte 428 from `cfg["peqs"][0]["channel_bypass"]`; leave 429-bytes boundary unchanged. Document as an upstream quirk.
- **Mute bitmasks**: bytes 408-409 (inputs) and 410-411 (outputs), both LE uint16, bit `i` = channel `i+1`.
- **PEQ band bypass**: bytes 412-415, one uint8 per output, bit `b` = band `b+1`.
- **Empty slots**: if `cfg is None`, do nothing — the existing bytes (usually 0x64 × 432) stay. This is correct: empty slots remain empty.

### (5) Tests

**`tests/test_virtual_dsp.py`:**
- `test_set_gain_persists`: `dsp.set_gain(0, 250); assert dsp.read_config()["gains"][0] == 250`
- `test_store_then_load_roundtrip`: set some values, store to slot 5, change values, load slot 5, verify original values back
- `test_load_preset_updates_active_slot`: assert config["active_slot"] reflects last load
- `test_load_from_unt_bytes_populates_slots`: seed from the analysis fixture, assert 30 slots and active_slot

**`tests/test_unt_writer.py`:**
- `test_round_trip_byte_identical`: load analysis fixture → export_to_unt_args → save_unt → reload file → bytes equal
- `test_edit_gain_only_touches_two_bytes`: load, edit `inputs[0].gain_raw`, save, diff bytes — expect only bytes `0x32 + active*432 + 1 + 16 + 18..19` to differ
- `test_edit_mute_touches_footer_bitmask`: confirm input mute mask byte 408 matches pattern
- `test_save_without_template_uses_blank`: pass `template=None`, produces a valid 13010-byte file that parses cleanly

**`tests/test_preset_picker.py`:** minimal smoke with pytest-qt (open dialog, programmatically pick slot 3, accept, assert chosen_slot == 3).

All tests: `uv run --with pytest --with pytest-qt pytest -v`.

### Reused functions

- [minidsp/protocol.py] `parse_preset_params()` — reused for reading (including when seeding VirtualDSP from .unt bytes).
- [minidspqt/model.py:85] `DeviceState.from_config()` — reused unchanged.
- [minidspqt/device_thread.py] — interface unchanged; only the factory-instance handling in `_poll_loop` needs a tiny tweak so VirtualDSP persists across the (non-disconnect-able) lifetime.
- [minidspqt/unt_loader.py] — `load_unt` extended to `load_unt_all_slots` for the full-file case.
- [minidspqt/views/home_view.py:198] `apply_state()` — reused; the Recall-triggered `config_loaded` signal already drives it.

## Verification

### Manual end-to-end

1. `uv run minidspqt --offline` with no hardware.
2. Badge shows amber "Offline", all strips **enabled**. Home shows default preset (from bundled `blank.unt`).
3. Drag InA gain, toggle Out2 mute. Values stick (knob doesn't jump back — state is persistent in VirtualDSP). Release the knob; in the background `DeviceThread` calls `VirtualDSP.set_gain(0, raw)` which updates its config.
4. ≡ → Load .unt file → pick the analysis fixture. Home view switches to the file's active preset (U02 "DIY Mon offset"). Slot switching works via Recall.
5. Click **Recall** → dialog lists all 30 slots by name. Pick U01. Home view refreshes to U01's values.
6. Edit a knob, click **Store** → dialog lists slots + has a name field pre-filled with "DIY Mon". Rename to "Living Room", pick U05, confirm. The change is now in slot 5 of the VirtualDSP.
7. ≡ → Save .unt file → `/tmp/edited.unt`. Reload with ≡ → Load .unt file → `/tmp/edited.unt`. Slot 5 should be "Living Room" with the edited values; slots 1–4 should match the original fixture byte-for-byte.
8. `xxd /tmp/edited.unt > /tmp/a; xxd <fixture> > /tmp/b; diff /tmp/a /tmp/b` — only changed slots + active-slot byte differ.
9. Run `uv run minidspqt` (no `--offline`) with real device unplugged. Should behave as today: Disconnected badge, controls greyed. Plug device in → Connected, controls enable. Recall/Store now drive the real hardware. (No regression.)

### Commit cadence

1. **Commit 1 — `feat(offline): stateful virtual DSP + --offline flag`**: `virtual_dsp.py` with setters + slot store, `test_virtual_dsp.py`, CLI/app wiring, amber "Offline" badge. Migrate `tests/conftest.py` to import from `virtual_dsp`.
2. **Commit 2 — `feat(ui): wire Recall/Store buttons + preset picker dialog`**: `preset_picker.py`, `_on_recall`/`_on_store` in MainWindow, local `preset_names` refresh after store. Works identically online and offline.
3. **Commit 3 — `feat(unt): write .unt files + seed virtual DSP from .unt`**: `unt_writer.py` + round-trip tests, extend `unt_loader.py` with `load_unt_all_slots`, `Save .unt file…` menu action, offline Load-.unt seeds the VirtualDSP.

## Risks

- **`DeviceThread._poll_loop` assumes `dsp_factory()` is called on every reconnect.** The VirtualDSP should be instantiated once and survive. A one-line refactor: if an instance is already set, reuse it; otherwise call the factory. Zero impact on the real `DSPmini` path.
- **Pre-seeded `blank.unt` generation**: producing a clean 13,010-byte blank template requires a real device read once (or carefully zeroing user-specific bytes like PIN in a copy of the fixture). For the first commit, use a stripped copy of the analysis fixture (zero the PIN at 0x1D–0x20); document provenance in a header comment of the resources file.
- **Online mode + Store**: when running against real hardware and the user hits Store, we call `request_store_preset` which writes to device flash — a real hardware-mutating operation. Consider a confirmation dialog before store on real devices. Low priority for this plan (user asked for offline-first).
- **Preset name editing**: the picker's Store dialog has a name field, so name editing lands naturally. Inline name editing on the Home view stays out of scope.
