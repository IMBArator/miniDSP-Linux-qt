"""Main window: owns the DeviceThread, DeviceState, and view stack."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QIcon
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
from .detail_view import DetailView
from .home_view import HomeView
from .preset_picker import PresetPickerDialog

log = logging.getLogger(__name__)


def _logo_path() -> Path:
    try:
        import importlib.resources as ir

        ref = ir.files("minidspqt.resources").joinpath("logo.svg")
        return Path(str(ref))
    except Exception:
        return Path()


class MainWindow(QMainWindow):
    def __init__(self, *, dsp_instance=None, offline: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("DSP 4x4 Mini")
        self.setMinimumWidth(960)
        logo = _logo_path()
        if logo.exists():
            self.setWindowIcon(QIcon(str(logo)))
        self._offline = offline

        self._state = DeviceState()

        self._stack = QStackedWidget()
        self._home_view = HomeView()
        self._detail_view = DetailView()
        self._stack.addWidget(self._home_view)
        self._stack.addWidget(self._detail_view)
        self.setCentralWidget(self._stack)

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

        self._home_view.gain_changed.connect(self._on_gain_changed)
        self._home_view.mute_changed.connect(self._on_mute_changed)
        self._home_view.phase_changed.connect(self._on_phase_changed)
        self._home_view.gate_clicked.connect(self._show_detail)
        self._home_view.name_changed.connect(self._on_name_changed)
        self._home_view.route_changed.connect(self._on_route_changed)
        self._home_view.recall_clicked.connect(self._on_recall)
        self._home_view.store_clicked.connect(self._on_store)

        self._detail_view.back_clicked.connect(self._on_detail_back)
        self._detail_view.gain_changed.connect(self._on_gain_changed)
        self._detail_view.mute_changed.connect(self._on_mute_changed)
        self._detail_view.phase_changed.connect(self._on_phase_changed)
        self._detail_view.gate_enable_changed.connect(self._on_detail_gate_enable)
        self._detail_view.gate_params_changed.connect(self._on_detail_gate_params)
        self._detail_view.name_changed.connect(self._on_name_changed)
        self._detail_view.output_feature_toggled.connect(
            self._on_detail_output_feature
        )

        self._thread.start()

        menu = QMenu(self)
        menu.addAction("Load .unt file\u2026").triggered.connect(self._on_load_unt)
        self._save_action = menu.addAction("Save .unt file\u2026")
        self._save_action.triggered.connect(self._on_save_unt)
        self._save_action.setEnabled(False)
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
            names = self._state.preset_names
            idx = slot - 1
            if 0 <= idx < len(names):
                names[idx] = dlg.chosen_name
            self._home_view.apply_state(self._state)

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

    def _on_detail_gate_enable(self, channel: int, enabled: bool) -> None:
        log.info("Gate enable ch=%d enabled=%s", channel, enabled)

    def _on_detail_gate_params(
        self, channel: int, attack: int, release: int, hold: int, threshold: int
    ) -> None:
        if 0 <= channel < 4 and channel < len(self._state.inputs):
            gate = self._state.inputs[channel].gate
            gate.attack = attack
            gate.release = release
            gate.hold = hold
            gate.threshold = threshold
        self._thread.request_gate(channel, attack, release, hold, threshold)
        self._home_view._input_strips[channel].set_gate_active(threshold > 0)

    def _on_detail_output_feature(
        self, channel: int, feature: str, checked: bool
    ) -> None:
        log.info(
            "Output feature ch=%d feature=%s checked=%s", channel, feature, checked
        )

    def _on_name_changed(self, channel: int, name: str) -> None:
        self._state.set_field(channel, "name", name)
        self._thread.request_channel_name(channel, name)

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

    # --- Lifecycle ---

    def closeEvent(self, event) -> None:
        self._thread.request_stop()
        self._thread.wait(2000)
        event.accept()
