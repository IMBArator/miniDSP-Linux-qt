"""Main window: owns the DeviceThread, DeviceState, and view stack."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
)

from ..device_thread import DeviceThread
from ..model import DeviceState
from ..unt_loader import UntParseError, load_unt, load_unt_all_slots
from ..unt_writer import save_unt
from ..virtual_dsp import VirtualDSP
from .home_view import HomeView
from .preset_picker import PresetPickerDialog

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, *, dsp_instance=None, offline: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("DSP 4x4 Mini")
        self.setMinimumSize(960, 560)
        self._offline = offline

        self._state = DeviceState()

        self._stack = QStackedWidget()
        self._home_view = HomeView()
        self._stack.addWidget(self._home_view)
        self.setCentralWidget(self._stack)

        if dsp_instance is not None:
            factory = type(dsp_instance)
        else:
            from minidsp.device import DSPmini
            factory = DSPmini

        self._thread = DeviceThread(
            dsp_factory=factory, dsp_instance=dsp_instance, parent=self,
        )
        self._thread.levels_updated.connect(self._home_view.update_levels)
        self._thread.connection_changed.connect(self._on_connection_changed)
        self._thread.config_loaded.connect(self._on_config_loaded)

        self._home_view.gain_changed.connect(self._on_gain_changed)
        self._home_view.mute_changed.connect(self._on_mute_changed)
        self._home_view.phase_changed.connect(self._on_phase_changed)
        self._home_view.gate_toggled.connect(self._on_gate_toggled)
        self._home_view.recall_clicked.connect(self._on_recall)
        self._home_view.store_clicked.connect(self._on_store)

        self._thread.start()

        menu = QMenu(self)
        menu.addAction("Load .unt file\u2026").triggered.connect(self._on_load_unt)
        self._save_action = menu.addAction("Save .unt file\u2026")
        self._save_action.triggered.connect(self._on_save_unt)
        self._save_action.setEnabled(False)
        btn = self._home_view.menu_button
        btn.setMenu(menu)
        btn.setStyleSheet(btn.styleSheet() + " QPushButton::menu-indicator { width: 0; }")

        if offline:
            self._home_view.set_offline_mode()
            self._save_action.setEnabled(True)

    @property
    def _virtual_dsp(self) -> VirtualDSP | None:
        inst = self._thread._dsp_instance
        return inst if isinstance(inst, VirtualDSP) else None

    # --- DeviceThread -> UI ---

    def _on_connection_changed(self, connected: bool) -> None:
        self._state.connected = connected
        if self._offline:
            return
        self._home_view.set_connected(connected)

    def _on_config_loaded(self, cfg: dict) -> None:
        log.info(
            "config_loaded: keys=%s active_slot=%s preset_names=%d entries",
            sorted(cfg.keys()), cfg.get("active_slot"), len(cfg.get("preset_names", [])),
        )
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
        self._home_view.apply_state(self._state)

    def _on_load_unt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load .unt preset", "",
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
            self._home_view.apply_state(self._state)
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
        self._home_view.apply_state(self._state)
        self._home_view.show_preview_banner(Path(path).name)

    def _on_save_unt(self) -> None:
        vdsp = self._virtual_dsp
        if vdsp is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save .unt preset", "",
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
            self, display_names, active_in_list, "recall",
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
            self, display_names, active_in_list, "store", current_name,
        )
        if dlg.exec() == QDialog.Accepted:
            slot = dlg.chosen_slot
            reply = QMessageBox.question(
                self, "Store Preset",
                f"Store the current configuration to slot U{slot:02d} \"{dlg.chosen_name}\"?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._thread.request_store_preset(slot, dlg.chosen_name)
            names = self._state.preset_names
            idx = slot - 1
            if 0 <= idx < len(names):
                names[idx] = dlg.chosen_name
            self._home_view.apply_state(self._state)

    # --- UI -> DeviceThread ---

    def _on_gain_changed(self, channel: int, raw: int) -> None:
        self._update_channel_field(channel, "gain_raw", raw)
        self._thread.request_gain(channel, raw)
        for slave in self._state.get_linked_slaves(channel):
            self._update_channel_field(slave, "gain_raw", raw)
            self._thread.request_gain(slave, raw)
            self._apply_strip_gain(slave, raw)

    def _on_mute_changed(self, channel: int, muted: bool) -> None:
        self._update_channel_field(channel, "muted", muted)
        self._thread.request_mute(channel, muted)
        for slave in self._state.get_linked_slaves(channel):
            self._update_channel_field(slave, "muted", muted)
            self._thread.request_mute(slave, muted)
            self._apply_strip_toggle(slave, "mute", muted)

    def _on_phase_changed(self, channel: int, inverted: bool) -> None:
        self._update_channel_field(channel, "phase_inverted", inverted)
        self._thread.request_phase(channel, inverted)
        for slave in self._state.get_linked_slaves(channel):
            self._update_channel_field(slave, "phase_inverted", inverted)
            self._thread.request_phase(slave, inverted)
            self._apply_strip_toggle(slave, "phase", inverted)

    def _on_gate_toggled(self, channel: int, enabled: bool) -> None:
        log.info("Gate toggle ch=%d checked=%s (detail view not yet wired)",
                 channel, enabled)

    def _apply_strip_gain(self, channel: int, raw: int) -> None:
        strips = self._home_view._all_strips()
        if 0 <= channel < len(strips):
            strips[channel].set_gain_silent(raw)

    def _apply_strip_toggle(self, channel: int, feature: str, checked: bool) -> None:
        strips = self._home_view._all_strips()
        if 0 <= channel < len(strips):
            strips[channel].set_toggle_silent(feature, checked)

    def _update_channel_field(self, channel: int, field: str, value) -> None:
        if not self._state.inputs and not self._state.outputs:
            return
        if channel < 4 and channel < len(self._state.inputs):
            setattr(self._state.inputs[channel], field, value)
        elif channel >= 4 and (channel - 4) < len(self._state.outputs):
            setattr(self._state.outputs[channel - 4], field, value)

    # --- Lifecycle ---

    def closeEvent(self, event) -> None:
        self._thread.request_stop()
        self._thread.wait(2000)
        event.accept()
