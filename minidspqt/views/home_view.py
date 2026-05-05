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
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from minidsp.protocol import CHANNEL_NAMES

from ..model import DeviceState
from ..scale import s, apply_scale_recursive
from ..ui.ui_home import Ui_Home
from ..widgets import GainKnob, LedIndicator, LevelMeter, ToggleButton

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
        self._is_output = is_output

        root = QVBoxLayout(self)
        root.setContentsMargins(s(8), s(6), s(8), s(6))
        root.setSpacing(s(4))

        self._title_btn = QPushButton(title)
        self._title_btn.setFlat(True)
        self._title_btn.clicked.connect(self._on_title_clicked)
        root.addWidget(self._title_btn)

        meter_row = QHBoxLayout()
        meter_row.setSpacing(0)

        self._knob = GainKnob()
        meter_row.addWidget(self._knob)

        self._separator = QFrame()
        self._separator.setFrameShape(QFrame.Shape.VLine)
        meter_row.addWidget(self._separator)
        meter_row.addSpacing(s(4))

        meter_col = QVBoxLayout()
        meter_col.setSpacing(s(1))

        self._meter = LevelMeter()
        self._meter.setMinimumWidth(s(20))
        meter_col.addWidget(self._meter, stretch=1)

        self._db_label = QLabel("\u2014 dB")
        self._db_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._limiter_label: QLabel | None = None
        self._limiter_led: LedIndicator | None = None
        db_row = QHBoxLayout()
        db_row.setSpacing(s(4))
        db_row.setContentsMargins(0, 0, 0, 0)
        db_row.addWidget(self._db_label, stretch=1)
        if is_output:
            self._limiter_label = QLabel("Lim")
            self._limiter_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            db_row.addWidget(self._limiter_label)
            self._limiter_led = LedIndicator()
            db_row.addWidget(self._limiter_led)
        meter_col.addLayout(db_row)

        meter_row.addLayout(meter_col, stretch=1)

        root.addLayout(meter_row)

        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(s(4))
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

        self.apply_scale()

    # --- Programmatic state sync (no signals emitted) ---

    def set_title(self, title: str) -> None:
        self._title_btn.setText(title)

    def _on_title_clicked(self) -> None:
        current = self._title_btn.text()
        new_name, ok = QInputDialog.getText(
            self, "Channel Name", "Name (max 8 chars):",
            text=current,
        )
        if ok and new_name != current:
            new_name = new_name[:8]
            self._title_btn.setText(new_name)
            self.name_changed.emit(new_name)

    def set_gain_silent(self, raw: int) -> None:
        self._knob.setValueSilently(raw)

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
            self._link_label.setText("\U0001F517")
            self._link_label.setToolTip(f"Linked to {master_name}" if master_name else "Linked")
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

    def apply_scale(self) -> None:
        bw = s(1)
        cr = s(6)
        self.setStyleSheet(
            "ChannelStrip { background-color: #2d2d31;"
            f" border: {bw}px solid #3a3a3e;"
            f" border-radius: {cr}px;"
            " }"
            " QLabel { background: transparent; }"
            " QPushButton { background: transparent; }"
        )

        tb_bw = s(1)
        tb_cr = s(10)
        tb_px = s(2)
        tb_py = s(12)
        tb_fs = s(11)
        self._title_btn.setStyleSheet(
            "QPushButton {"
            " background-color: #3a3a3e;"
            " color: #cccccc;"
            f" border: {tb_bw}px solid #55555a;"
            f" border-radius: {tb_cr}px;"
            f" padding: {tb_px}px {tb_py}px;"
            " font-weight: 600;"
            f" font-size: {tb_fs}px;"
            " text-align: center;"
            "}"
            "QPushButton:hover { background-color: #4a4a4e; }"
            "QPushButton:pressed { background-color: #55555a; }"
        )
        self._title_btn.setFixedHeight(s(22))

        self._knob.setFixedSize(s(64), s(76))

        sep_w = max(1, s(1))
        self._separator.setStyleSheet(
            "QFrame { color: #3a3a3e;"
            f" max-width: {sep_w}px;"
            " }"
        )

        db_fs = s(11)
        self._db_label.setFixedHeight(s(16))
        self._db_label.setStyleSheet(
            "QLabel { color: #999999;"
            f" font-size: {db_fs}px;"
            " font-family: monospace;"
            " background: transparent;"
            " }"
        )

        if self._limiter_label is not None:
            lim_fs = s(9)
            self._limiter_label.setStyleSheet(
                "QLabel { color: #777;"
                f" font-size: {lim_fs}px;"
                " background: transparent;"
                " }"
            )

        link_fs = s(14)
        self._link_label.setStyleSheet(
            "QLabel { color: #66aaff;"
            f" font-size: {link_fs}px;"
            " font-weight: 600;"
            " background: transparent;"
            " }"
        )


class HomeView(QWidget, Ui_Home):
    # (channel, value) — channel is the unified index: 0..3 inputs, 4..7 outputs
    gain_changed = Signal(int, int)
    mute_changed = Signal(int, bool)
    phase_changed = Signal(int, bool)
    gate_toggled = Signal(int, bool)
    output_feature_toggled = Signal(int, str, bool)
    name_changed = Signal(int, str)
    route_changed = Signal(int, int)
    recall_clicked = Signal()
    store_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setupUi(self)

        from PySide6.QtWidgets import QLayout
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

        self.apply_scale()

    def apply_scale(self) -> None:
        from PySide6.QtWidgets import QLayout
        br = s(1)
        cr = s(4)
        pad = s(4)
        pad_x = s(8)
        self.rootLayout.setContentsMargins(s(10), s(10), s(10), s(10))
        self.rootLayout.setSpacing(s(8))
        self.titleLabel.setStyleSheet(
            f"font-size: {s(16)}pt; font-weight: 600;"
        )
        self.connectionLabel.setMinimumSize(s(110), s(28))
        self.connectionLabel.setStyleSheet(
            f"background-color: #8a2020; color: white; border-radius: {cr}px;"
            f" padding: {pad}px {pad_x}px; font-weight: 600;"
            f" font-size: {s(12)}px;"
        )
        mb_sz = s(28)
        self.menuButton.setMinimumSize(mb_sz, mb_sz)
        self.menuButton.setMaximumSize(mb_sz, mb_sz)
        self.menuButton.setStyleSheet(
            "QPushButton {"
            f" border: {br}px solid #55555a;"
            f" border-radius: {s(3)}px;"
            f" background-color: #3a3a3e; color: #dddddd; font-size: {s(14)}pt;"
            " }"
            " QPushButton:hover { background-color: #48484d; }"
            " QPushButton::menu-indicator { width: 0px; }"
        )
        self.routingMatrix.setMinimumWidth(s(160))
        self.routingMatrix.setMaximumWidth(s(240))
        self.presetLabel.setStyleSheet(
            f"padding: {pad}px {pad_x}px; background-color: #2a2a2e;"
            f" border-radius: {cr}px;"
            f" font-size: {s(12)}px;"
        )
        btn_style = (
            "QPushButton {"
            f" border: {br}px solid #55555a;"
            f" border-radius: {cr}px;"
            f" padding: {pad}px {pad_x}px;"
            " background-color: #3a3a3e; color: #dddddd;"
            f" font-size: {s(12)}px;"
            " font-weight: 600;"
            "}"
            "QPushButton:hover { background-color: #48484d; }"
            "QPushButton:pressed { background-color: #55555a; }"
        )
        self.storeButton.setStyleSheet(btn_style)
        self.recallButton.setStyleSheet(btn_style)
        self.inputsLayout.setSpacing(s(6))
        self.outputsLayout.setSpacing(s(6))
        for lay in (self.inputsLayout, self.outputsLayout, self.rootLayout):
            lay.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        apply_scale_recursive(self)

    # --- Signal plumbing ---

    def _connect_input(self, idx: int, strip: ChannelStrip) -> None:
        strip.gain_changed.connect(lambda raw, ch=idx: self.gain_changed.emit(ch, raw))
        strip.name_changed.connect(lambda name, ch=idx: self.name_changed.emit(ch, name))

        def _on_toggle(feature: str, checked: bool, ch: int = idx) -> None:
            if feature == "mute":
                self.mute_changed.emit(ch, checked)
            elif feature == "phase":
                self.phase_changed.emit(ch, checked)
            elif feature == "gate":
                self.gate_toggled.emit(ch, checked)

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

    def show_preview_banner(self, filename: str) -> None:
        self.titleLabel.setText(f"Preview — {filename}")
        self.connectionLabel.setText("Preview")
        self._set_connection_style("#8a6d20")

    def set_offline_mode(self) -> None:
        self.titleLabel.setText("Home")
        self.connectionLabel.setText("Offline")
        self._set_connection_style("#8a6d20")
        for strip in self._input_strips + self._output_strips:
            strip.set_enabled_state(True)
        if self._state:
            self._apply_link_state(self._state)

    def set_connected(self, connected: bool) -> None:
        self.titleLabel.setText("Home")
        if connected:
            self.connectionLabel.setText("Connected")
            self._set_connection_style("#2fa84a")
        else:
            self.connectionLabel.setText("Disconnected")
            self._set_connection_style("#8a2020")
            for strip in self._input_strips + self._output_strips:
                strip.set_enabled_state(False)
            return

        for strip in self._input_strips + self._output_strips:
            strip.set_enabled_state(True)
        if self._state:
            self._apply_link_state(self._state)

    def _set_connection_style(self, bg: str) -> None:
        cr = s(4)
        pad = s(4)
        pad_x = s(8)
        self.connectionLabel.setStyleSheet(
            f"background-color: {bg}; color: white; border-radius: {cr}px;"
            f" padding: {pad}px {pad_x}px; font-weight: 600;"
            f" font-size: {s(12)}px;"
        )

    def _apply_link_state(self, state: DeviceState) -> None:
        strips = self._all_strips()
        for i in range(4):
            master_name = self._master_title(state, i, strips)
            self._input_strips[i].set_linked_slave(state.is_linked_slave(i), master_name)
            master_name = self._master_title(state, i + 4, strips)
            self._output_strips[i].set_linked_slave(state.is_linked_slave(i + 4), master_name)

    @staticmethod
    def _master_title(state: DeviceState, channel: int, strips: list[ChannelStrip]) -> str:
        info = state.link_info[channel] if channel < len(state.link_info) else {}
        master_ch = info.get("master")
        if master_ch is not None and 0 <= master_ch < len(strips):
            return strips[master_ch]._title_btn.text()
        return ""

    @property
    def _state(self) -> DeviceState | None:
        return self._cached_state

    _cached_state: DeviceState | None = None
