"""Main window: owns the DeviceThread, DeviceState, and view stack."""

from __future__ import annotations

import copy
import logging
from pathlib import Path

from PySide6.QtGui import QActionGroup, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
)

from ..blank_seed import seed_virtual_dsp_from_blank
from ..device_thread import DeviceThread
from ..model import (
    CompressorState,
    CrossoverState,
    DeviceState,
    GateState,
    PEQBand,
    TestToneState,
)
from ..theme import theme_manager
from ..unt_loader import UntParseError, load_unt, load_unt_all_slots
from ..unt_writer import save_unt
from ..virtual_dsp import VirtualDSP
from .channel_linking_dialog import ChannelLinkingDialog
from .copy_channel_dialog import CopyChannelDialog
from .detail_view import DetailView
from .device_pin_dialog import SetPinDialog, UnlockPinDialog
from .home_view import HomeView
from .preset_picker import PresetPickerDialog
from .test_tone_dialog import TestToneDialog

log = logging.getLogger(__name__)


def _logo_path() -> Path:
    try:
        import importlib.resources as ir

        ref = ir.files("minidspqt.resources").joinpath("logo.svg")
        return Path(str(ref))
    except Exception:
        return Path()


class MainWindow(QMainWindow):
    """Top-level application window: owns the worker thread and the views.

    The window stitches together every other widget — home view,
    detail view, menus, the device worker thread, every dialog. Its
    job is mostly **signal routing**: forward UI signals to
    ``DeviceThread.request_*`` calls, and forward ``DeviceThread``
    signals (``config_loaded`` / ``levels_updated`` /
    ``pin_required`` / ``pin_result`` / ``connection_changed``)
    back into the views. State lives in a single ``DeviceState``
    mirror that ``MainWindow`` mutates on each device-driven update.
    """

    def __init__(self, *, dsp_instance: object | None = None, offline: bool = False) -> None:
        """Build the main window and start the device worker thread.

        Args:
            dsp_instance: Pre-built DSP object passed straight through
                to ``DeviceThread`` — required for offline mode (an
                in-RAM ``VirtualDSP``) and for tests (a ``FakeDSPmini``).
                When ``None`` and ``offline`` is also False, the
                worker uses the real ``DSPmini`` factory.
            offline: True selects offline UX (no auto-reconnect, no
                "Connected" indicator) and provides a defensive
                ``VirtualDSP`` if ``dsp_instance`` is ``None`` — see
                the comment inline for why.
        """
        super().__init__()
        self.setWindowTitle("DSP 4x4 Mini")
        self.setMinimumWidth(960)
        logo = _logo_path()
        if logo.exists():
            self.setWindowIcon(QIcon(str(logo)))
        self._offline = offline

        self._state = DeviceState()
        # Most-recent raw config dict from the worker. Cached deep-copy so a
        # later online → offline switch can seed the new VirtualDSP with the
        # device's last-known state without re-querying the worker.
        self._last_config: dict | None = None

        self._stack = QStackedWidget()
        self._home_view = HomeView()
        self._detail_view = DetailView()
        self._stack.addWidget(self._home_view)
        self._stack.addWidget(self._detail_view)
        self.setCentralWidget(self._stack)

        if dsp_instance is None and offline:
            # Defensive default: ``offline=True`` without an explicit
            # instance should NEVER mean "talk to real hardware".
            # ``app.py`` always supplies a VirtualDSP when offline, but
            # tests sometimes pass ``offline=True`` alone — without this
            # branch the worker would happily probe a real DSPmini and
            # trip the unlock dialog if one is plugged in and locked.
            dsp_instance = VirtualDSP()

        self._unlock_dialog: UnlockPinDialog | None = None
        self._create_and_start_thread(dsp_instance)

        self._home_view.gain_changed.connect(self._on_gain_changed)
        self._home_view.mute_changed.connect(self._on_mute_changed)
        self._home_view.phase_changed.connect(self._on_phase_changed)
        self._home_view.gate_clicked.connect(self._show_detail)
        self._home_view.output_feature_toggled.connect(self._on_output_feature_toggled)
        self._home_view.name_changed.connect(self._on_name_changed)
        self._home_view.route_changed.connect(self._on_route_changed)
        self._home_view.recall_clicked.connect(self._on_recall)
        self._home_view.store_clicked.connect(self._on_store)

        self._detail_view.back_clicked.connect(self._on_detail_back)
        self._detail_view.gain_changed.connect(self._on_gain_changed)
        self._detail_view.mute_changed.connect(self._on_mute_changed)
        self._detail_view.phase_changed.connect(self._on_phase_changed)
        self._detail_view.gate_clicked.connect(self._on_detail_gate_clicked)
        self._detail_view.gate_params_changed.connect(self._on_detail_gate_params)
        self._detail_view.name_changed.connect(self._on_name_changed)
        self._detail_view.output_feature_toggled.connect(
            self._on_output_feature_toggled
        )
        self._detail_view.peq_band_changed.connect(self._on_detail_peq_band)
        self._detail_view.peq_channel_bypass_changed.connect(
            self._on_detail_peq_channel_bypass
        )
        self._detail_view.xover_changed.connect(self._on_detail_xover_changed)
        self._detail_view.compressor_changed.connect(self._on_detail_compressor_changed)
        self._detail_view.delay_changed.connect(self._on_detail_delay_changed)

        menu = QMenu(self)
        menu.addAction("Load .unt file\u2026").triggered.connect(self._on_load_unt)
        self._save_action = menu.addAction("Save .unt file\u2026")
        self._save_action.triggered.connect(self._on_save_unt)
        self._save_action.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Channel linking\u2026").triggered.connect(
            self._on_channel_linking
        )
        self._linking_dialog: ChannelLinkingDialog | None = None
        menu.addAction("Copy channel settings\u2026").triggered.connect(
            self._on_copy_requested
        )
        self._copy_dialog: CopyChannelDialog | None = None
        menu.addAction("Test tone\u2026").triggered.connect(self._on_test_tone)
        self._test_tone_dialog: TestToneDialog | None = None
        menu.addSeparator()
        self._set_pin_action = menu.addAction("Set device PIN\u2026")
        self._set_pin_action.triggered.connect(self._on_set_pin)
        # Only meaningful while the device is connected (no-op on VirtualDSP
        # in offline mode would still work, but we gate it the same way for
        # consistency).
        self._set_pin_action.setEnabled(False)
        self._reconnect_action = menu.addAction("Reconnect")
        self._reconnect_action.triggered.connect(self._on_reconnect)
        # Reconnect is only useful when we've stopped \u2014 i.e. NOT connected.
        # Hidden until disconnected.
        self._reconnect_action.setEnabled(False)
        self._build_connection_mode_menu(menu)
        menu.addSeparator()
        self._build_theme_menu(menu)
        menu.addSeparator()
        menu.addAction("About").triggered.connect(self._on_about)
        btn = self._home_view.menu_button
        btn.setMenu(menu)

        self._detail_view.menu_button.setMenu(menu)

        if offline:
            self._home_view.set_offline_mode()
            self._detail_view.set_offline_mode()
            self._save_action.setEnabled(True)

    @property
    def _virtual_dsp(self) -> VirtualDSP | None:
        inst = self._thread._dsp_instance
        return inst if isinstance(inst, VirtualDSP) else None

    # --- DeviceThread -> UI ---

    def _on_levels_updated(self, payload: dict) -> None:
        self._home_view.update_levels(payload)
        if self._stack.currentIndex() == 1:
            self._detail_view.update_levels(payload)

    def _on_connection_changed(self, connected: bool) -> None:
        self._state.connected = connected
        # Set device PIN is a device-only action; it follows the worker's
        # connection state even in offline mode (where VirtualDSP toggles
        # _open during the set-PIN → relock cycle).
        self._set_pin_action.setEnabled(connected)
        # Reconnect is the inverse: only useful when we're not connected
        # (e.g. after the user cancelled the unlock prompt).
        self._reconnect_action.setEnabled(not connected)
        if self._offline:
            return
        self._home_view.set_connected(connected)
        self._detail_view.set_connected(connected)

    def _on_config_loaded(self, cfg: dict) -> None:
        log.info(
            "config_loaded: keys=%s active_slot=%s preset_names=%d entries",
            sorted(cfg.keys()),
            cfg.get("active_slot"),
            len(cfg.get("preset_names", [])),
        )
        # Cache a deep copy so a later online → offline switch can seed a
        # VirtualDSP with the device's last-known state. Deep copy because
        # downstream consumers (DeviceState.from_config) don't mutate today
        # but might tomorrow — this is cheap insurance.
        self._last_config = copy.deepcopy(cfg)
        old_names = list(self._state.preset_names)
        try:
            self._state = DeviceState.from_config(cfg)
        except Exception:
            log.exception("Failed to parse config dict")
            return
        if not self._state.preset_names and old_names:
            self._state.preset_names = old_names
        log.info(
            "config_loaded: state updated, slot=%s gains=%s",
            self._state.active_slot,
            [ch.gain_raw for ch in self._state.inputs + self._state.outputs],
        )
        self._apply_state_to_views()
        self._sync_linking_dialog()
        self._sync_test_tone_dialog()

    def _sync_linking_dialog(self) -> None:
        """Refresh the channel-linking dialog if it's currently open.

        Called wherever ``self._state`` is replaced (config reload, .unt
        load) so the dialog reflects the authoritative state — crucial
        after _apply_channel_links so any silent device rejection snaps
        the radios back instead of showing stale optimistic state.
        """
        if self._linking_dialog is not None and self._linking_dialog.isVisible():
            self._linking_dialog.refresh(self._state)

    def _sync_test_tone_dialog(self) -> None:
        """Refresh the test-tone dialog if it's currently open.

        Same contract as :meth:`_sync_linking_dialog`: snap the dialog to
        the device's authoritative state after every config reload so
        the panic button's enabled state and the freq spin-box reflect
        what the generator is actually doing.
        """
        if self._test_tone_dialog is not None and self._test_tone_dialog.isVisible():
            self._test_tone_dialog.refresh(self._state)

    def _on_load_unt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load .unt preset",
            "",
            "miniDSP preset (*.unt);;All files (*)",
        )
        if not path:
            return

        vdsp = self._virtual_dsp
        if vdsp is not None:
            try:
                slots, active_slot, names, raw = load_unt_all_slots(path)
            except (UntParseError, OSError) as e:
                QMessageBox.critical(self, "Cannot load .unt file", str(e))
                return
            vdsp.load_from_unt_bytes(raw, slots, active_slot, names)
            cfg = vdsp.read_config()
            try:
                self._state = DeviceState.from_config(cfg)
            except Exception:
                log.exception("Failed to parse config from loaded .unt")
                return
            self._apply_state_to_views()
            self._sync_linking_dialog()
            self._save_action.setEnabled(True)
            return

        try:
            cfg, active_slot, names = load_unt(path)
        except (UntParseError, OSError) as e:
            QMessageBox.critical(self, "Cannot load .unt file", str(e))
            return
        cfg["active_slot"] = active_slot
        cfg["preset_names"] = names
        self._state = DeviceState.from_config(cfg)
        self._state.connected = False
        self._home_view.set_connected(False)
        self._apply_state_to_views()
        self._sync_linking_dialog()
        self._sync_test_tone_dialog()
        self._home_view.show_preview_banner(Path(path).name)

    def _on_save_unt(self) -> None:
        vdsp = self._virtual_dsp
        if vdsp is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save .unt preset",
            "",
            "miniDSP preset (*.unt);;All files (*)",
        )
        if not path:
            return
        slots_0based, active_0based, template = vdsp.export_to_unt_args()
        slot_names = self._state.preset_names
        try:
            save_unt(path, slots_0based, slot_names, active_0based, template)
        except Exception as e:
            QMessageBox.critical(self, "Cannot save .unt file", str(e))

    # --- Recall / Store ---

    def _preset_display_names(self) -> list[str]:
        return self._state.preset_names

    def _on_recall(self) -> None:
        display_names = self._preset_display_names()
        active = self._state.active_slot if self._state.active_slot is not None else 1
        active_in_list = active  # F00=row 0, U01=row 1, … (matches chosen_slot)
        dlg = PresetPickerDialog(
            self,
            display_names,
            active_in_list,
            "recall",
        )
        if dlg.exec() == QDialog.Accepted:
            slot = dlg.chosen_slot
            self._thread.request_load_preset(slot)

    def _on_store(self) -> None:
        display_names = self._preset_display_names()
        active = self._state.active_slot if self._state.active_slot is not None else 1
        active_in_list = active
        current_name = ""
        names_30 = display_names
        if 1 <= active <= 30:
            idx = active - 1
            if idx < len(names_30):
                current_name = names_30[idx]

        dlg = PresetPickerDialog(
            self,
            display_names,
            active_in_list,
            "store",
            current_name,
        )
        if dlg.exec() == QDialog.Accepted:
            slot = dlg.chosen_slot
            reply = QMessageBox.question(
                self,
                "Store Preset",
                f'Store the current configuration to slot U{slot:02d} "{dlg.chosen_name}"?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._thread.request_store_preset(slot, dlg.chosen_name)
            self._thread.request_read_config()
            names = self._state.preset_names
            idx = slot - 1
            if 0 <= idx < len(names):
                names[idx] = dlg.chosen_name
            self._apply_state_to_views()

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About DSP 4x4 Mini",
            "<h3>DSP 4x4 Mini</h3>"
            "<p>Qt graphical interface for the t.racks DSP 4x4 Mini.</p>"
            '<p><a href="https://github.com/IMBArator/miniDSP-Linux-qt">'
            "github.com/IMBArator/miniDSP-Linux-qt</a></p>"
            "<p>Licensed under the "
            '<a href="https://www.gnu.org/licenses/gpl-3.0.en.html">'
            "GNU General Public License v3.0</a>.</p>"
            "<hr>"
            "<p>This application uses <b>PySide6</b> (Qt for Python), "
            "licensed under the "
            '<a href="https://www.gnu.org/licenses/lgpl-3.0.en.html">'
            "GNU Lesser General Public License v3</a>. "
            "PySide6 is dynamically linked; users may replace the library "
            "with a modified version.</p>",
        )

    # --- UI -> DeviceThread ---

    def _on_gain_changed(self, channel: int, raw: int) -> None:
        for ch in self._state.set_field_with_links(channel, "gain_raw", raw):
            self._thread.request_gain(ch, raw)
            if ch != channel:
                self._apply_strip_gain(ch, raw)

    def _on_mute_changed(self, channel: int, muted: bool) -> None:
        for ch in self._state.set_field_with_links(channel, "muted", muted):
            self._thread.request_mute(ch, muted)
            if ch != channel:
                self._apply_strip_toggle(ch, "mute", muted)

    def _on_phase_changed(self, channel: int, inverted: bool) -> None:
        for ch in self._state.set_field_with_links(channel, "phase_inverted", inverted):
            self._thread.request_phase(ch, inverted)
            if ch != channel:
                self._apply_strip_toggle(ch, "phase", inverted)

    def _show_detail(self, channel: int) -> None:
        self._detail_view.set_channel(channel, self._state)
        self._stack.setCurrentIndex(1)

    def _on_detail_back(self) -> None:
        self._stack.setCurrentIndex(0)

    def _on_detail_gate_clicked(self, channel: int) -> None:
        pass

    def _on_detail_gate_params(
        self, channel: int, attack: int, release: int, hold: int, threshold: int
    ) -> None:
        def _mutate(obj) -> None:
            obj.gate = GateState(
                attack=attack, release=release, hold=hold, threshold=threshold
            )

        affected = self._state.mutate_with_links(channel, _mutate)
        for ch in affected:
            self._thread.request_gate(ch, attack, release, hold, threshold)
        self._refresh_active_states(affected)

    def _on_output_feature_toggled(
        self, channel: int, feature: str, checked: bool
    ) -> None:
        # Output feature buttons (xover/peq/comp/delay) are navigation buttons.
        # The strip auto-unchecks PEQ; only act on the press (checked=True).
        if not checked:
            return
        feature_titles = {
            "peq": "PEQ",
            "xover": "Xover",
            "comp": "Comp",
            "delay": "Delay",
        }
        title = feature_titles.get(feature)
        if title is None:
            log.info(
                "Output feature ch=%d feature=%s checked=%s (no panel yet)",
                channel,
                feature,
                checked,
            )
            return
        self._show_detail(channel)
        self._detail_view.show_feature(channel, title)

    def _on_detail_peq_band(
        self,
        channel: int,
        band: int,
        gain_raw: int,
        freq_raw: int,
        q_raw: int,
        filter_type: int,
        bypass: bool,
    ) -> None:
        new_band = PEQBand(
            gain_raw=gain_raw,
            freq_raw=freq_raw,
            q_raw=q_raw,
            filter_type=filter_type,
            bypass=bypass,
        )

        def _mutate(obj) -> None:
            while len(obj.peqs) <= band:
                obj.peqs.append(PEQBand())
            obj.peqs[band] = PEQBand(
                gain_raw=new_band.gain_raw,
                freq_raw=new_band.freq_raw,
                q_raw=new_band.q_raw,
                filter_type=new_band.filter_type,
                bypass=new_band.bypass,
            )

        affected = self._state.mutate_with_links(channel, _mutate)
        for ch in affected:
            self._thread.request_peq_band(
                ch, band, gain_raw, freq_raw, q_raw, filter_type, bypass
            )
        self._refresh_active_states(affected)

    def _on_detail_peq_channel_bypass(self, channel: int, bypass: bool) -> None:
        affected = self._state.mutate_with_links(
            channel, lambda obj: setattr(obj, "peq_channel_bypass", bypass)
        )
        for ch in affected:
            self._thread.request_peq_channel_bypass(ch, bypass)
        self._refresh_active_states(affected)

    def _on_detail_xover_changed(
        self, channel: int, hp_freq: int, hp_slope: int, lp_freq: int, lp_slope: int
    ) -> None:
        def _mutate(obj) -> None:
            obj.crossover = CrossoverState(
                hipass_freq=hp_freq,
                hipass_slope=hp_slope,
                lopass_freq=lp_freq,
                lopass_slope=lp_slope,
            )

        affected = self._state.mutate_with_links(channel, _mutate)
        # slope=0 IS the bypass command on the device side (protocol §0x31/0x32).
        # Skipping it leaves the device's last-active slope intact, so a restart
        # would re-load the old slope and the channel would still be filtering —
        # always push the value through so bypass is honoured.
        for ch in affected:
            self._thread.request_hipass(ch, hp_freq, hp_slope)
            self._thread.request_lopass(ch, lp_freq, lp_slope)
        self._refresh_active_states(affected)

    def _on_detail_compressor_changed(
        self,
        channel: int,
        ratio: int,
        knee: int,
        attack: int,
        release: int,
        threshold: int,
    ) -> None:
        """Scaffolded handler for the future compressor panel.

        No UI emits this signal yet, but the linked fan-out + device
        request pattern is wired so the panel only needs to connect a
        signal when it lands.
        """

        def _mutate(obj) -> None:
            obj.compressor = CompressorState(
                ratio=ratio,
                knee=knee,
                attack=attack,
                release=release,
                threshold=threshold,
            )

        affected = self._state.mutate_with_links(channel, _mutate)
        for ch in affected:
            self._thread.request_compressor(ch, ratio, knee, attack, release, threshold)
        self._refresh_active_states(affected)

    def _on_detail_delay_changed(self, channel: int, samples: int) -> None:
        """Scaffolded handler for the future delay panel."""
        affected = self._state.mutate_with_links(
            channel, lambda obj: setattr(obj, "delay_samples", samples)
        )
        for ch in affected:
            self._thread.request_delay(ch, samples)
        self._refresh_active_states(affected)

    def _on_name_changed(self, channel: int, name: str) -> None:
        self._state.set_field(channel, "name", name)
        self._thread.request_channel_name(channel, name)
        strips = self._home_view._all_strips()
        if 0 <= channel < len(strips):
            strips[channel].set_title(name)

    def _on_route_changed(self, output_idx: int, input_mask: int) -> None:
        if output_idx < 0 or output_idx >= len(self._state.outputs):
            return
        self._state.outputs[output_idx].routing_mask = input_mask
        self._thread.request_matrix_route(0x04 + output_idx, input_mask)

    def _apply_strip_gain(self, channel: int, raw: int) -> None:
        strips = self._home_view._all_strips()
        if 0 <= channel < len(strips):
            strips[channel].set_gain_silent(raw)

    def _apply_strip_toggle(self, channel: int, feature: str, checked: bool) -> None:
        strips = self._home_view._all_strips()
        if 0 <= channel < len(strips):
            strips[channel].set_toggle_silent(feature, checked)

    def _apply_state_to_views(self) -> None:
        """Push the current :class:`DeviceState` to both views.

        The detail view's ``apply_state`` is a no-op if no channel is
        currently shown, so this is safe to call after every state
        replacement (config load, .unt load, preset store).
        """
        self._home_view.apply_state(self._state)
        self._detail_view.apply_state(self._state)

    def _refresh_active_states(self, channels: list[int]) -> None:
        """Re-derive Gate/PEQ/Xover active styling for the given channels.

        Cheaper than a full ``_apply_state_to_views`` and crucially does
        not call ``set_*_silent`` on knobs/toggles — that would interrupt
        the user mid-drag if their edit was the trigger. Only the
        coloured indicator changes here. The detail view's displayed
        strip + panels are updated too when one of ``channels`` is the
        currently shown channel, so slave panels reflect the master's
        new values immediately.
        """
        for ch in channels:
            if 0 <= ch < 4 and ch < len(self._state.inputs):
                in_state = self._state.inputs[ch]
                self._home_view._input_strips[ch].set_gate_active(
                    in_state.gate.threshold > 0
                )
            elif 4 <= ch < 8 and (ch - 4) < len(self._state.outputs):
                out_state = self._state.outputs[ch - 4]
                strip = self._home_view._output_strips[ch - 4]
                strip.set_peq_active(out_state.peq_active)
                strip.set_xover_active(out_state.xover_active)
                strip.set_comp_active(out_state.comp_active)
                strip.set_delay_active(out_state.delay_active)

        if self._stack.currentIndex() == 1 and self._detail_view.channel in channels:
            self._detail_view.apply_state(self._state)
        elif (
            self._stack.currentIndex() == 1
            and self._detail_view.channel >= 4
            and any(4 <= ch < 8 for ch in channels)
        ):
            # An output delay (or other output field) changed for a channel
            # other than the one displayed.  The Delay panel's overview graph
            # shows all four rows, so refresh it explicitly even though the
            # main strip/panels don't need a full re-render.
            self._detail_view.refresh_delay_panel_state()

    # --- Device PIN / unlock ---

    def _show_unlock_dialog(self) -> None:
        """Worker says the device is locked; pop a non-blocking modal dialog.

        Must be non-blocking (``open()``, not ``exec()``) because the
        worker is parked in ``_handle_locked`` waiting on its PIN queue —
        a modal that blocks the UI thread would also block ``submit_pin``
        signals from ever reaching it.
        """
        if self._unlock_dialog is not None and self._unlock_dialog.isVisible():
            return
        self._unlock_dialog = UnlockPinDialog(self)
        self._unlock_dialog.pinEntered.connect(self._thread.submit_pin)
        self._unlock_dialog.cancelled.connect(self._thread.cancel_pin_entry)
        # If the user closes the dialog any other way (Esc, window close)
        # the worker is still parked — treat that as a cancel.
        self._unlock_dialog.rejected.connect(self._on_unlock_dialog_rejected)
        self._unlock_dialog.open()

    def _on_unlock_dialog_rejected(self) -> None:
        # If the dialog was rejected without a prior pin_result(_, 0),
        # the worker is still waiting — push the cancel sentinel.  Safe
        # to call even after exhaustion: the queue.put just gets drained
        # on the next prompt.
        self._thread.cancel_pin_entry()

    def _on_pin_result(self, success: bool, attempts_left: int) -> None:
        if self._unlock_dialog is None:
            return
        self._unlock_dialog.on_pin_result(success, attempts_left)

    def _on_set_pin(self) -> None:
        dialog = SetPinDialog(self)
        dialog.pinChosen.connect(self._thread.request_set_pin)
        dialog.exec()

    def _on_reconnect(self) -> None:
        """Re-arm the worker after a user-initiated stop.

        Reached via the menu after the user cancelled the unlock prompt,
        exhausted attempts, or set a new PIN. We block briefly for the
        previous run() to wind down (it may still be emitting
        connection_changed under us) before restart().
        """
        if self._thread.isRunning():
            # Already running — nothing to do. Should be visually
            # impossible because the menu item is disabled while
            # connected, but defensive against signal-ordering races.
            return
        # wait() returns immediately if the thread already finished;
        # otherwise it gives the run() coroutine a moment to exit.
        self._thread.wait(500)
        self._thread.restart()

    # --- Channel linking ---

    def _on_channel_linking(self) -> None:
        """Open the channel-linking dialog (creating it on first use)."""
        if self._linking_dialog is None:
            self._linking_dialog = ChannelLinkingDialog(self, self._state)
            self._linking_dialog.applyRequested.connect(self._apply_channel_links)
        else:
            self._linking_dialog.refresh(self._state)
        self._linking_dialog.show()
        self._linking_dialog.raise_()
        self._linking_dialog.activateWindow()

    # --- Copy channel settings ---

    def _on_copy_requested(self) -> None:
        """Open the copy-settings dialog."""
        dialog = CopyChannelDialog(self._state, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            source, targets, groups = dialog.result_data
            changes = self._state.copy_params(source, targets, groups)
            if not changes:
                return

            for change in changes:
                ch = change["channel"]
                cmd_type = change["cmd_type"]
                value = change["value"]

                if cmd_type == "GAIN":
                    self._thread.request_gain(ch, value)
                elif cmd_type == "MUTE":
                    self._thread.request_mute(ch, value)
                elif cmd_type == "PHASE":
                    self._thread.request_phase(ch, value)
                elif cmd_type == "GATE":
                    attack, release, hold, threshold = value
                    self._thread.request_gate(ch, attack, release, hold, threshold)
                elif cmd_type == "HIPASS":
                    freq_raw, slope = value
                    self._thread.request_hipass(ch, freq_raw, slope)
                elif cmd_type == "LOPASS":
                    freq_raw, slope = value
                    self._thread.request_lopass(ch, freq_raw, slope)
                elif cmd_type == "COMPRESSOR":
                    ratio, knee, attack, release, threshold = value
                    self._thread.request_compressor(
                        ch, ratio, knee, attack, release, threshold
                    )
                elif cmd_type == "DELAY":
                    self._thread.request_delay(ch, value)
                elif cmd_type == "PEQ_BAND":
                    band_idx = change["band"]
                    gain_raw, freq_raw, q_raw, filter_type, bypass = value
                    self._thread.request_peq_band(
                        ch, band_idx, gain_raw, freq_raw, q_raw, filter_type, bypass
                    )
                elif cmd_type == "PEQ_CHANNEL_BYPASS":
                    self._thread.request_peq_channel_bypass(ch, value)
                elif cmd_type == "MATRIX_ROUTE":
                    self._thread.request_matrix_route(ch, value)
                elif cmd_type == "CHANNEL_NAME":
                    self._thread.request_channel_name(ch, value)

            # Trigger a config reload to refresh UI with copied values
            self._thread.request_read_config()

    def _apply_channel_links(self, new_flags: list[int]) -> None:
        """Push link changes to the device and trigger a config reload.

        Sequencing matches the protocol contract:
          1. For every *new* slave (non-zero → zero transition), declare the
             pair via prepare_link before any set_channel_link is sent.
          2. Send set_channel_link for every channel whose flags changed
             (master + slaves both need updating).
          3. Request a fresh read_config so the UI reflects what the device
             actually committed (handles silent rejections).
        """
        old_flags = self._state._link_flags_list()
        if new_flags == old_flags:
            return  # nothing changed — don't churn the device

        # Step 1: prepare_link for any new slave pair, per group.
        for group_start in (0, 4):
            new_master = self._find_new_master(old_flags, new_flags, group_start)
            if new_master is None:
                continue
            new_master_unified = group_start + new_master
            for i in range(4):
                ch = group_start + i
                # A "new slave" is a channel whose new flags are 0x00 and
                # whose old flags weren't (or whose master changed).
                was_slave = old_flags[ch] == 0x00
                is_slave = new_flags[ch] == 0x00
                if is_slave and not was_slave:
                    self._thread.request_prepare_link(new_master_unified, ch)

        # Step 2: send set_channel_link for every channel whose flags changed.
        for ch in range(8):
            if new_flags[ch] != old_flags[ch]:
                self._thread.request_channel_link(ch, new_flags[ch])

        # Step 3: refresh from the device so the UI snaps to the truth.
        self._thread.request_read_config()

    # --- Test tone ---

    def _on_test_tone(self) -> None:
        """Open the test-tone dialog (creating it on first use)."""
        if self._test_tone_dialog is None:
            self._test_tone_dialog = TestToneDialog(self, self._state)
            self._test_tone_dialog.applyRequested.connect(self._apply_test_tone)
            self._test_tone_dialog.disableRequested.connect(self._disable_test_tone)
        else:
            self._test_tone_dialog.refresh(self._state)
        self._test_tone_dialog.show()
        self._test_tone_dialog.raise_()
        self._test_tone_dialog.activateWindow()

    def _apply_test_tone(self, mode: int, freq_index: int) -> None:
        """Write a new tone-generator setting to the device.

        Updates local state immediately so the dialog's stop button arms
        (or disarms) without waiting for a config round-trip.
        """
        self._state.test_tone = TestToneState(mode=mode, sine_freq_index=freq_index)
        self._thread.request_test_tone(mode, freq_index)
        self._sync_test_tone_dialog()

    def _disable_test_tone(self) -> None:
        """Hard-stop the generator. Preserves the last sine freq index.

        The device retains the sine freq in config even when mode=Off, so
        sending the current freq alongside TONE_OFF keeps it sticky for
        the next time the user picks Sine.
        """
        keep_freq = self._state.test_tone.sine_freq_index
        self._state.test_tone = TestToneState(mode=0, sine_freq_index=keep_freq)
        self._thread.request_test_tone(0, keep_freq)

    @staticmethod
    def _find_new_master(
        old_flags: list[int], new_flags: list[int], group_start: int
    ) -> int | None:
        """Return the within-group master index for the new state, or None.

        Used to look up which channel needs the prepare_link partner. The
        master is the unique channel in the group whose new flags have
        more than one bit set.
        """
        for i in range(4):
            ch = group_start + i
            f = new_flags[ch]
            if f and (f & (f - 1)) != 0:
                # f has more than one bit set → this is a master.
                return i
        return None

    # --- Theme menu ---

    def _build_theme_menu(self, parent_menu: QMenu) -> None:
        """Add a "Theme" submenu with System / Light / Dark choices.

        The choice is persisted via QSettings inside the theme manager, so
        the next launch reflects whatever the user picked here.
        """
        theme_menu = parent_menu.addMenu("Theme")
        group = QActionGroup(self)
        group.setExclusive(True)

        def _add(label: str, pref: str) -> None:
            act = theme_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(theme_manager.preference == pref)
            act.triggered.connect(
                lambda _checked, p=pref: theme_manager.set_user_preference(p)
            )
            group.addAction(act)

        _add("System", "system")
        _add("Light", "light")
        _add("Dark", "dark")

    # --- Connection mode menu / runtime switch ---

    def _build_connection_mode_menu(self, parent_menu: QMenu) -> None:
        """Add a "Connection mode" submenu with Connected / Offline radios.

        Mirrors :meth:`_build_theme_menu`'s exclusive-radio pattern. The
        choice is **session-only** — re-launching the app without
        ``--offline`` returns to connected mode.

        Args:
            parent_menu: The hamburger menu the submenu should be appended
                to. The radio actions are stored on ``self`` so later code
                (e.g. :meth:`_sync_mode_actions`) can update their checked
                state without re-traversing the menu.
        """
        mode_menu = parent_menu.addMenu("Connection mode")
        group = QActionGroup(self)
        group.setExclusive(True)

        self._mode_action_online = mode_menu.addAction("Connected (USB)")
        self._mode_action_online.setCheckable(True)
        self._mode_action_online.setChecked(not self._offline)
        self._mode_action_online.triggered.connect(
            lambda _checked: self._on_mode_chosen(offline=False)
        )
        group.addAction(self._mode_action_online)

        self._mode_action_offline = mode_menu.addAction("Offline")
        self._mode_action_offline.setCheckable(True)
        self._mode_action_offline.setChecked(self._offline)
        self._mode_action_offline.triggered.connect(
            lambda _checked: self._on_mode_chosen(offline=True)
        )
        group.addAction(self._mode_action_offline)

    def _sync_mode_actions(self) -> None:
        """Push ``self._offline`` to the menu radios.

        Called after a successful switch and whenever the user cancels a
        switch — without this the radio would visually flip to the
        cancelled choice and lie about the active mode.
        """
        self._mode_action_online.setChecked(not self._offline)
        self._mode_action_offline.setChecked(self._offline)

    def _on_mode_chosen(self, *, offline: bool) -> None:
        """Switch between online and offline at runtime.

        Tears down the current worker, rebuilds it against the right DSP
        source (``DSPmini`` factory or a freshly seeded ``VirtualDSP``), and
        snaps the views to the new mode. Online → offline keeps the live
        device state (via ``VirtualDSP.seed_from_config``); offline → online
        warns first because unsaved edits are discarded.

        Args:
            offline: Target mode. ``True`` switches to the in-RAM
                ``VirtualDSP``; ``False`` reconnects to the real USB
                device via the ``DSPmini`` factory. A no-op when the
                target equals ``self._offline``.
        """
        if offline == self._offline:
            return

        # 1. Offline → Online: warn before discarding offline edits.
        if self._offline and not offline:
            reply = QMessageBox.question(
                self,
                "Switch to Connected mode?",
                "Unsaved offline edits will be discarded when switching to "
                "the live device. Save your .unt file first if you want to "
                "keep them.\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                # Restore the radio so it doesn't visually lie about the
                # active mode after the user cancelled.
                self._sync_mode_actions()
                return

        # 2. Close any open transient dialogs — they hold references to the
        #    old thread or to ``self._state`` and would emit/show stale data
        #    after the swap.
        for dlg_attr in ("_unlock_dialog", "_linking_dialog", "_test_tone_dialog"):
            dlg = getattr(self, dlg_attr, None)
            if dlg is not None and dlg.isVisible():
                if hasattr(dlg, "reject"):
                    dlg.reject()
                else:
                    dlg.close()
            setattr(self, dlg_attr, None)

        # 3. Disconnect every signal from the old thread BEFORE stopping it.
        #    Without this, signals already queued on the UI thread could
        #    fire into _on_connection_changed / _on_levels_updated after
        #    we've flipped self._offline and mis-update the chip.
        for sig, slot in (
            (self._thread.levels_updated, self._on_levels_updated),
            (self._thread.connection_changed, self._on_connection_changed),
            (self._thread.config_loaded, self._on_config_loaded),
            (self._thread.pin_required, self._show_unlock_dialog),
            (self._thread.pin_result, self._on_pin_result),
        ):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                # Already disconnected or never connected — fine.
                pass

        # 4. Stop the current worker. Even when parked in _handle_locked,
        #    request_stop pushes _CANCEL_PIN to unblock it.
        self._thread.request_stop()
        self._thread.wait(2000)
        old_thread = self._thread
        old_thread.setParent(None)
        old_thread.deleteLater()

        # 5. Build the new DSP instance.
        if offline:
            new_instance: VirtualDSP | None = VirtualDSP()
            if self._last_config is not None:
                new_instance.seed_from_config(self._last_config)
            else:
                # Cold switch with no live config ever seen (e.g. device
                # unplugged at launch). Fall back to the bundled blank.unt
                # so the strips have sane defaults to edit.
                seed_virtual_dsp_from_blank(new_instance)
        else:
            new_instance = None  # → DSPmini factory path

        # 6. Update flag BEFORE creating the new thread so the first signal
        #    that arrives lands on a consistent self._offline.
        self._offline = offline
        if not offline:
            # Drop the offline-mode config so a subsequent switch back to
            # offline doesn't re-seed from a stale offline snapshot. The
            # views keep showing whatever they had (with strips disabled
            # via set_connected(False) below) until the real device
            # answers — matching the existing disconnect UX.
            self._last_config = None

        self._create_and_start_thread(new_instance)

        if offline:
            # Push the freshly seeded config through the normal pipeline so
            # the views snap to the new state immediately — the worker will
            # re-emit the same thing shortly, but this removes visual lag.
            assert new_instance is not None
            self._on_config_loaded(new_instance.read_config())
            self._home_view.set_offline_mode()
            self._detail_view.set_offline_mode()
        else:
            self._home_view.set_connected(False)
            self._detail_view.set_connected(False)

        self._save_action.setEnabled(offline)
        if offline:
            # Reconnect is meaningless against VirtualDSP (it doesn't drop).
            self._reconnect_action.setEnabled(False)
        self._sync_mode_actions()

    def _create_and_start_thread(self, dsp_instance: object | None) -> None:
        """Build a fresh :class:`DeviceThread`, wire every signal, and start.

        Single source of truth for thread construction — used both at startup
        and on every runtime mode switch. ``dsp_instance=None`` selects the
        real ``DSPmini`` factory; passing a ``VirtualDSP`` (or test fake)
        pins that instance across reconnects so its in-RAM state survives
        the worker's close/open cycle.

        Args:
            dsp_instance: Pre-built DSP object to pin across reconnects, or
                ``None`` to use the real ``DSPmini`` factory. Must already
                be seeded with the desired state — this method does not
                populate it.
        """
        if dsp_instance is not None:
            factory = type(dsp_instance)
        else:
            from minidsp.device import DSPmini

            factory = DSPmini

        self._thread = DeviceThread(
            dsp_factory=factory,
            dsp_instance=dsp_instance,
            parent=self,
        )
        self._thread.levels_updated.connect(self._on_levels_updated)
        self._thread.connection_changed.connect(self._on_connection_changed)
        self._thread.config_loaded.connect(self._on_config_loaded)
        self._thread.pin_required.connect(self._show_unlock_dialog)
        self._thread.pin_result.connect(self._on_pin_result)
        self._thread.start()

    # --- Lifecycle ---

    def closeEvent(self, event) -> None:
        """Stop the worker thread (waiting up to 2 s) before closing.

        Without this hook the QThread would outlive the QApplication
        and emit signals into already-destroyed widgets on shutdown.
        """
        self._thread.request_stop()
        self._thread.wait(2000)
        event.accept()
