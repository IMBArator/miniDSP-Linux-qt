"""Home view: 4 input strips + routing matrix + 4 output strips.

Per-channel strips are built programmatically and inserted into the
`inputsLayout` / `outputsLayout` containers.  Each strip emits signals;
the MainWindow routes them to DeviceThread.request_* methods.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from minidsp.protocol import CHANNEL_NAMES

from ..model import DeviceState
from .channel_strip import (
    ChannelStrip,
    InputChannelStrip,
    OutputChannelStrip,
    apply_input_strip_state,
    apply_output_strip_state,
)

NUM_CHANNELS = 4


class HomeView(QWidget):
    gain_changed = Signal(int, int)
    mute_changed = Signal(int, bool)
    phase_changed = Signal(int, bool)
    gate_clicked = Signal(int)
    output_feature_toggled = Signal(int, str, bool)
    name_changed = Signal(int, str)
    route_changed = Signal(int, int)
    recall_clicked = Signal()
    store_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

        for lay in (self.inputsLayout, self.outputsLayout, self.rootLayout):
            lay.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        self._input_strips: list[InputChannelStrip] = []
        self._output_strips: list[OutputChannelStrip] = []

        for i in range(NUM_CHANNELS):
            strip = InputChannelStrip(CHANNEL_NAMES[i])
            self._input_strips.append(strip)
            self.inputsLayout.addWidget(strip)
            self._connect_input(i, strip)

        for i in range(NUM_CHANNELS):
            strip = OutputChannelStrip(CHANNEL_NAMES[i + 4])
            self._output_strips.append(strip)
            self.outputsLayout.addWidget(strip)
            self._connect_output(i, strip)

        self.routingMatrix.set_strips(self._input_strips, self._output_strips)

        self.routingMatrix.routing_changed.connect(self.route_changed)

        self.set_connected(False)

        self.recallButton.clicked.connect(self.recall_clicked)
        self.storeButton.clicked.connect(self.store_clicked)

    # --- UI construction ---

    def _build_ui(self) -> None:
        self.setObjectName("Home")
        self.resize(980, 640)
        self.setWindowTitle("Home")

        self.rootLayout = QVBoxLayout(self)
        self.rootLayout.setContentsMargins(10, 10, 10, 10)
        self.rootLayout.setSpacing(8)

        header = QHBoxLayout()
        header.addItem(
            QSpacerItem(
                40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
        )

        self.titleLabel = QLabel("Home")
        self.titleLabel.setObjectName("titleLabel")
        self.titleLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.titleLabel)

        header.addItem(
            QSpacerItem(
                40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
        )

        self.connectionLabel = QLabel("Disconnected")
        self.connectionLabel.setObjectName("connectionLabel")
        self.connectionLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.connectionLabel.setMinimumSize(110, 28)
        self._set_connection_state("disconnected")
        header.addWidget(self.connectionLabel)

        self.menuButton = QPushButton("\u2261")
        self.menuButton.setObjectName("menuButton")
        self.menuButton.setFixedSize(28, 28)
        header.addWidget(self.menuButton)

        self.rootLayout.addLayout(header)

        center = QHBoxLayout()
        center.setSpacing(8)

        inputs_container = QWidget()
        self.inputsLayout = QVBoxLayout(inputs_container)
        self.inputsLayout.setContentsMargins(0, 0, 0, 0)
        self.inputsLayout.setSpacing(6)
        center.addWidget(inputs_container)

        from ..widgets import RoutingMatrix

        self.routingMatrix = RoutingMatrix()
        self.routingMatrix.setMinimumWidth(160)
        self.routingMatrix.setMaximumWidth(240)
        center.addWidget(self.routingMatrix)

        outputs_container = QWidget()
        self.outputsLayout = QVBoxLayout(outputs_container)
        self.outputsLayout.setContentsMargins(0, 0, 0, 0)
        self.outputsLayout.setSpacing(6)
        center.addWidget(outputs_container)

        self.rootLayout.addLayout(center)

        footer = QHBoxLayout()

        self.presetLabel = QLabel("Preset: \u2014")
        self.presetLabel.setObjectName("presetLabel")
        footer.addWidget(self.presetLabel)

        footer.addItem(
            QSpacerItem(
                40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
        )

        self.storeButton = QPushButton("Store")
        footer.addWidget(self.storeButton)

        self.recallButton = QPushButton("Recall")
        footer.addWidget(self.recallButton)

        self.rootLayout.addLayout(footer)

    # --- Signal plumbing ---

    def _connect_input(self, idx: int, strip: InputChannelStrip) -> None:
        strip.gain_changed.connect(lambda raw, ch=idx: self.gain_changed.emit(ch, raw))
        strip.name_changed.connect(
            lambda name, ch=idx: self.name_changed.emit(ch, name)
        )
        strip.gate_clicked.connect(lambda ch=idx: self.gate_clicked.emit(ch))

        def _on_toggle(feature: str, checked: bool, ch: int = idx) -> None:
            if feature == "mute":
                self.mute_changed.emit(ch, checked)
            elif feature == "phase":
                self.phase_changed.emit(ch, checked)

        strip.toggle_changed.connect(_on_toggle)

    def _connect_output(self, idx: int, strip: OutputChannelStrip) -> None:
        unified_ch = idx + 4
        strip.gain_changed.connect(
            lambda raw, ch=unified_ch: self.gain_changed.emit(ch, raw)
        )
        strip.name_changed.connect(
            lambda name, ch=unified_ch: self.name_changed.emit(ch, name)
        )

        def _on_toggle(feature: str, checked: bool, ch: int = unified_ch) -> None:
            if feature == "mute":
                self.mute_changed.emit(ch, checked)
            elif feature == "phase":
                self.phase_changed.emit(ch, checked)
            else:
                self.output_feature_toggled.emit(ch, feature, checked)

        strip.toggle_changed.connect(_on_toggle)

    # --- State application ---

    def apply_state(self, state: DeviceState) -> None:
        self._cached_state = state
        strips = self._all_strips()
        for i, ch_state in enumerate(state.inputs):
            apply_input_strip_state(
                self._input_strips[i],
                i,
                ch_state,
                self._master_title(state, i, strips),
                state.is_linked_slave(i),
            )

        for i, ch_state in enumerate(state.outputs):
            apply_output_strip_state(
                self._output_strips[i],
                i + 4,
                ch_state,
                self._master_title(state, i + 4, strips),
                state.is_linked_slave(i + 4),
            )

        self.routingMatrix.set_routing([ch.routing_mask for ch in state.outputs])

        slot = state.active_slot
        if slot is not None and state.preset_names:
            label = f"U{slot:02d}" if slot > 0 else "F00"
            name = ""
            if slot > 0:
                idx = slot - 1
                if idx < len(state.preset_names):
                    name = state.preset_names[idx]
            self.presetLabel.setText(
                f"Preset: {label} \u2014 {name}" if name else f"Preset: {label}"
            )
        else:
            self.presetLabel.setText("Preset: \u2014")

    def update_levels(self, payload: dict) -> None:
        inputs = payload.get("inputs", [])
        outputs = payload.get("outputs", [])
        limiter_mask = payload.get("limiter_mask", 0)
        for i in range(NUM_CHANNELS):
            if i < len(inputs):
                self._input_strips[i].update_level(inputs[i])
            if i < len(outputs):
                self._output_strips[i].update_level(outputs[i])
            self._output_strips[i].set_limiter_active(bool(limiter_mask & (1 << i)))

    @property
    def menu_button(self):
        return self.menuButton

    def _all_strips(self) -> list[ChannelStrip]:
        return self._input_strips + self._output_strips

    def _set_connection_state(self, state: str) -> None:
        self.connectionLabel.setProperty("state", state)
        self.connectionLabel.style().unpolish(self.connectionLabel)
        self.connectionLabel.style().polish(self.connectionLabel)

    def show_preview_banner(self, filename: str) -> None:
        self.titleLabel.setText(f"Preview \u2014 {filename}")
        self.connectionLabel.setText("Preview")
        self._set_connection_state("preview")

    def set_offline_mode(self) -> None:
        self.titleLabel.setText("Home")
        self.connectionLabel.setText("Offline")
        self._set_connection_state("offline")
        for strip in self._input_strips + self._output_strips:
            strip.set_enabled_state(True)
        if self._state:
            self._apply_link_state(self._state)

    def set_connected(self, connected: bool) -> None:
        self.titleLabel.setText("Home")
        if connected:
            self.connectionLabel.setText("Connected")
            self._set_connection_state("connected")
        else:
            self.connectionLabel.setText("Disconnected")
            self._set_connection_state("disconnected")
            for strip in self._input_strips + self._output_strips:
                strip.set_enabled_state(False)
            return

        for strip in self._input_strips + self._output_strips:
            strip.set_enabled_state(True)
        if self._state:
            self._apply_link_state(self._state)

    def _apply_link_state(self, state: DeviceState) -> None:
        strips = self._all_strips()
        for i in range(4):
            master_name = self._master_title(state, i, strips)
            self._input_strips[i].set_linked_slave(
                state.is_linked_slave(i), master_name
            )
            master_name = self._master_title(state, i + 4, strips)
            self._output_strips[i].set_linked_slave(
                state.is_linked_slave(i + 4), master_name
            )

    @staticmethod
    def _master_title(
        state: DeviceState, channel: int, strips: list[ChannelStrip]
    ) -> str:
        info = state.link_info[channel] if channel < len(state.link_info) else {}
        master_ch = info.get("master")
        if master_ch is not None and 0 <= master_ch < len(strips):
            return strips[master_ch]._title_btn.text()
        return ""

    @property
    def _state(self) -> DeviceState | None:
        return self._cached_state

    _cached_state: DeviceState | None = None
