"""Main window: owns the DeviceThread, DeviceState, and view stack."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMainWindow, QMenu, QMessageBox, QStackedWidget

from ..device_thread import DeviceThread
from ..model import DeviceState
from ..unt_loader import UntParseError, load_unt
from ..virtual_dsp import VirtualDSP
from .home_view import HomeView

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

    # --- DeviceThread -> UI ---

    def _on_connection_changed(self, connected: bool) -> None:
        self._state.connected = connected
        if self._offline:
            return
        self._home_view.set_connected(connected)

    def _on_config_loaded(self, cfg: dict) -> None:
        try:
            self._state = DeviceState.from_config(cfg)
        except Exception:
            log.exception("Failed to parse config dict")
            return
        self._home_view.apply_state(self._state)

    def _on_load_unt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load .unt preset", "",
            "miniDSP preset (*.unt);;All files (*)",
        )
        if not path:
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
        pass  # implemented in commit 3

    # --- UI -> DeviceThread ---

    def _on_gain_changed(self, channel: int, raw: int) -> None:
        self._update_channel_field(channel, "gain_raw", raw)
        self._thread.request_gain(channel, raw)

    def _on_mute_changed(self, channel: int, muted: bool) -> None:
        self._update_channel_field(channel, "muted", muted)
        self._thread.request_mute(channel, muted)

    def _on_phase_changed(self, channel: int, inverted: bool) -> None:
        self._update_channel_field(channel, "phase_inverted", inverted)
        self._thread.request_phase(channel, inverted)

    def _on_gate_toggled(self, channel: int, enabled: bool) -> None:
        # The gate has no simple on/off opcode; toggling is handled by
        # writing zero-threshold params in Detail View. This stub just
        # keeps the button responsive until Detail View lands.
        log.info("Gate toggle ch=%d checked=%s (detail view not yet wired)",
                 channel, enabled)

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
