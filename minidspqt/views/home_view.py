"""Home view: 4 input strips + routing matrix + 4 output strips.

Per-channel strips are built programmatically and inserted into the
`inputsLayout` / `outputsLayout` containers defined in `home.ui`. Each
strip emits signals prefixed with `input_` or `output_`; the MainWindow
routes them to DeviceThread.request_* methods.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
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
from ..widgets import GainKnob, LedIndicator, LevelMeter, RoutingMatrix, ToggleButton

NUM_CHANNELS = 4

INPUT_TOGGLES = [("Gate", "gate"), ("Phase", "phase"), ("Mute", "mute")]
OUTPUT_TOGGLES = [
    ("Xover", "xover"),
    ("PEQ", "peq"),
    ("Comp", "comp"),
    ("Phase", "phase"),
    ("Delay", "delay"),
    ("Mute", "mute"),
]


class ChannelStrip(QFrame):
    """A single input or output channel row.

    Emits generic `gain_changed(raw)`, `toggle_changed(feature, checked)`
    and `name_changed(name)` signals; HomeView translates them to per-channel
    input_*/output_* signals.
    """

    gain_changed = Signal(int)
    toggle_changed = Signal(str, bool)
    name_changed = Signal(str)

    def __init__(
        self,
        title: str,
        is_output: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        self._title_btn = QPushButton(title)
        self._title_btn.setObjectName("channelTitle")
        self._title_btn.setFixedHeight(22)
        self._title_btn.setFlat(True)
        self._title_btn.clicked.connect(self._on_title_clicked)
        root.addWidget(self._title_btn)

        meter_row = QHBoxLayout()
        meter_row.setSpacing(0)

        self._knob = GainKnob()
        self._knob.setFixedSize(64, 76)
        meter_row.addWidget(self._knob)

        separator = QFrame()
        separator.setObjectName("channelSeparator")
        separator.setFrameShape(QFrame.Shape.VLine)
        meter_row.addWidget(separator)
        meter_row.addSpacing(4)

        meter_col = QVBoxLayout()
        meter_col.setSpacing(1)

        self._meter = LevelMeter()
        self._meter.setMinimumWidth(20)
        meter_col.addWidget(self._meter, stretch=1)

        self._db_label = QLabel("\u2014 dB")
        self._db_label.setObjectName("channelDbLabel")
        self._db_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._db_label.setFixedHeight(16)

        self._limiter_led: LedIndicator | None = None
        db_row = QHBoxLayout()
        db_row.setSpacing(4)
        db_row.setContentsMargins(0, 0, 0, 0)
        db_row.addWidget(self._db_label, stretch=1)
        if is_output:
            limiter_label = QLabel("Lim")
            limiter_label.setObjectName("channelLimLabel")
            limiter_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            db_row.addWidget(limiter_label)
            self._limiter_led = LedIndicator()
            db_row.addWidget(self._limiter_led)
        meter_col.addLayout(db_row)

        meter_row.addLayout(meter_col, stretch=1)

        root.addLayout(meter_row)

        # Toggle row
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(4)
        self._toggles: dict[str, ToggleButton] = {}
        specs = OUTPUT_TOGGLES if is_output else INPUT_TOGGLES
        for label, feature in specs:
            btn = ToggleButton()
            btn.setText(label)
            btn.setFeature(feature)
            btn.toggled.connect(
                lambda checked, f=feature: self.toggle_changed.emit(f, checked)
            )
            toggle_row.addWidget(btn)
            self._toggles[feature] = btn

        self._link_label = QLabel("")
        self._link_label.setObjectName("channelLinkLabel")
        self._link_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._link_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self._link_label.hide()
        self._is_linked_slave = False

        toggle_row.addStretch(1)
        toggle_row.addWidget(self._link_label)
        root.addLayout(toggle_row)

        root.setSizeConstraint(root.SizeConstraint.SetMinimumSize)

        self._knob.valueChanged.connect(self.gain_changed)

    # --- Programmatic state sync (no signals emitted) ---

    def set_title(self, title: str) -> None:
        self._title_btn.setText(title)

    def _on_title_clicked(self) -> None:
        current = self._title_btn.text()
        new_name, ok = QInputDialog.getText(
            self,
            "Channel Name",
            "Name (max 8 chars):",
            text=current,
        )
        if ok and new_name != current:
            new_name = new_name[:8]
            self._title_btn.setText(new_name)
            self.name_changed.emit(new_name)

    def set_gain_silent(self, raw: int) -> None:
        self._knob.setValueSilently(raw)

    def set_gate_active(self, active: bool) -> None:
        btn = self._toggles.get("gate")
        if btn is None:
            return
        btn.setProperty("gate_active", active)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def set_toggle_silent(self, feature: str, checked: bool) -> None:
        btn = self._toggles.get(feature)
        if btn is None:
            return
        was = btn.blockSignals(True)
        btn.setChecked(checked)
        btn.blockSignals(was)

    def set_enabled_state(self, enabled: bool) -> None:
        if enabled and self._is_linked_slave:
            return
        self._knob.setEnabled(enabled)
        for btn in self._toggles.values():
            btn.setEnabled(enabled)
        if not enabled:
            self._meter.reset()
            self._db_label.setText("\u2014 dB")
            if self._limiter_led is not None:
                self._limiter_led.set_active(False)

    def set_limiter_active(self, active: bool) -> None:
        if self._limiter_led is not None:
            self._limiter_led.set_active(active)

    def set_linked_slave(self, is_slave: bool, master_name: str = "") -> None:
        self._is_linked_slave = is_slave
        self._knob.setEnabled(not is_slave)
        for btn in self._toggles.values():
            btn.setEnabled(not is_slave)
        if is_slave:
            self._link_label.setText("\U0001f517")
            self._link_label.setToolTip(
                f"Linked to {master_name}" if master_name else "Linked"
            )
            self._link_label.show()
        else:
            self._link_label.setToolTip("")
            self._link_label.hide()

    @property
    def meter(self) -> LevelMeter:
        return self._meter

    def update_level(self, value: int) -> None:
        self._meter.set_level(value)
        db = self._meter.display_db
        if db == float("-inf"):
            self._db_label.setText("\u2014 dB")
        else:
            self._db_label.setText(f"{db:+.1f} dB")


class HomeView(QWidget):
    # (channel, value) — channel is the unified index: 0..3 inputs, 4..7 outputs
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

        self._input_strips: list[ChannelStrip] = []
        self._output_strips: list[ChannelStrip] = []

        for i in range(NUM_CHANNELS):
            strip = ChannelStrip(CHANNEL_NAMES[i], is_output=False)
            self._input_strips.append(strip)
            self.inputsLayout.addWidget(strip)
            self._connect_input(i, strip)

        for i in range(NUM_CHANNELS):
            strip = ChannelStrip(CHANNEL_NAMES[i + 4], is_output=True)
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

        # Header: spacer | title | spacer | connection badge | menu button
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

        self.menuButton = QPushButton("≡")
        self.menuButton.setObjectName("menuButton")
        self.menuButton.setFixedSize(28, 28)
        header.addWidget(self.menuButton)

        self.rootLayout.addLayout(header)

        # Center: inputs column | routing matrix | outputs column
        center = QHBoxLayout()
        center.setSpacing(8)

        inputs_container = QWidget()
        self.inputsLayout = QVBoxLayout(inputs_container)
        self.inputsLayout.setContentsMargins(0, 0, 0, 0)
        self.inputsLayout.setSpacing(6)
        center.addWidget(inputs_container)

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

        # Footer: preset label | spacer | store | recall
        footer = QHBoxLayout()

        self.presetLabel = QLabel("Preset: —")
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

    def _connect_input(self, idx: int, strip: ChannelStrip) -> None:
        strip.gain_changed.connect(lambda raw, ch=idx: self.gain_changed.emit(ch, raw))
        strip.name_changed.connect(
            lambda name, ch=idx: self.name_changed.emit(ch, name)
        )

        def _on_toggle(feature: str, checked: bool, ch: int = idx) -> None:
            if feature == "mute":
                self.mute_changed.emit(ch, checked)
            elif feature == "phase":
                self.phase_changed.emit(ch, checked)
            elif feature == "gate":
                strip.set_toggle_silent("gate", False)
                self.gate_clicked.emit(ch)

        strip.toggle_changed.connect(_on_toggle)

    def _connect_output(self, idx: int, strip: ChannelStrip) -> None:
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
                # xover/peq/comp/delay — detail-view stubs, emit a generic event
                self.output_feature_toggled.emit(ch, feature, checked)

        strip.toggle_changed.connect(_on_toggle)

    # --- State application ---

    def apply_state(self, state: DeviceState) -> None:
        self._cached_state = state
        strips = self._all_strips()
        for i, ch_state in enumerate(state.inputs):
            strip = self._input_strips[i]
            strip.set_title(ch_state.name or CHANNEL_NAMES[i])
            strip.set_gain_silent(ch_state.gain_raw)
            strip.set_toggle_silent("mute", ch_state.muted)
            strip.set_toggle_silent("phase", ch_state.phase_inverted)
            strip.set_toggle_silent("gate", False)
            strip.set_gate_active(ch_state.gate.threshold > 0)
            master_name = self._master_title(state, i, strips)
            strip.set_linked_slave(state.is_linked_slave(i), master_name)

        for i, ch_state in enumerate(state.outputs):
            strip = self._output_strips[i]
            strip.set_title(ch_state.name or CHANNEL_NAMES[i + 4])
            strip.set_gain_silent(ch_state.gain_raw)
            strip.set_toggle_silent("mute", ch_state.muted)
            strip.set_toggle_silent("phase", ch_state.phase_inverted)
            master_name = self._master_title(state, i + 4, strips)
            strip.set_linked_slave(state.is_linked_slave(i + 4), master_name)

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
            self.presetLabel.setText("Preset: —")

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
        # Drives the QSS selector QLabel#connectionLabel[state="..."]; valid
        # values: disconnected, connected, offline, preview.
        self.connectionLabel.setProperty("state", state)
        self.connectionLabel.style().unpolish(self.connectionLabel)
        self.connectionLabel.style().polish(self.connectionLabel)

    def show_preview_banner(self, filename: str) -> None:
        self.titleLabel.setText(f"Preview — {filename}")
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
