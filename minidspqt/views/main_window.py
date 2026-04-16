"""Main window: owns the DeviceThread, DeviceState, and view stack."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QMainWindow, QStackedWidget

from ..device_thread import DeviceThread
from ..model import DeviceState
from .home_view import HomeView

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DSP 4x4 Mini")
        self.setMinimumSize(960, 560)

        self._state = DeviceState()

        self._stack = QStackedWidget()
        self._home_view = HomeView()
        self._stack.addWidget(self._home_view)
        self.setCentralWidget(self._stack)

        self._thread = DeviceThread(parent=self)
        self._thread.levels_updated.connect(self._home_view.update_levels)
        self._thread.connection_changed.connect(self._on_connection_changed)
        self._thread.config_loaded.connect(self._on_config_loaded)

        self._home_view.gain_changed.connect(self._on_gain_changed)
        self._home_view.mute_changed.connect(self._on_mute_changed)
        self._home_view.phase_changed.connect(self._on_phase_changed)
        self._home_view.gate_toggled.connect(self._on_gate_toggled)

        self._thread.start()

    # --- DeviceThread -> UI ---

    def _on_connection_changed(self, connected: bool) -> None:
        self._state.connected = connected
        self._home_view.set_connected(connected)

    def _on_config_loaded(self, cfg: dict) -> None:
        try:
            self._state = DeviceState.from_config(cfg)
        except Exception:
            log.exception("Failed to parse config dict")
            return
        self._home_view.apply_state(self._state)

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
