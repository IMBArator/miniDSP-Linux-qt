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
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..model import DeviceState
from ..ui.ui_home import Ui_Home
from ..widgets import GainKnob, LevelMeter, ToggleButton

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

    Emits generic `gain_changed(raw)` and `toggle_changed(feature, checked)`
    signals; HomeView translates them to per-channel input_*/output_* signals.
    """

    gain_changed = Signal(int)
    toggle_changed = Signal(str, bool)

    def __init__(
        self,
        title: str,
        is_output: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "ChannelStrip { background-color: #2d2d31; border: 1px solid #3a3a3e;"
            " border-radius: 6px; } QLabel { background: transparent; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        self._title_label = QLabel(title)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setStyleSheet(
            "QLabel {"
            " background-color: #3a3a3e;"
            " color: #cccccc;"
            " border: 1px solid #55555a;"
            " border-radius: 10px;"
            " padding: 2px 12px;"
            " font-weight: 600;"
            " font-size: 11px;"
            "}"
        )
        self._title_label.setFixedHeight(22)
        root.addWidget(self._title_label)

        self._knob = GainKnob()
        self._knob.setFixedSize(64, 76)
        root.addWidget(self._knob, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._meter = LevelMeter()
        self._meter.setFixedHeight(16)
        root.addWidget(self._meter)

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
        toggle_row.addStretch(1)
        root.addLayout(toggle_row)

        self._knob.valueChanged.connect(self.gain_changed)

    # --- Programmatic state sync (no signals emitted) ---

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

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
        self._knob.setEnabled(enabled)
        for btn in self._toggles.values():
            btn.setEnabled(enabled)
        if not enabled:
            self._meter.reset()

    @property
    def meter(self) -> LevelMeter:
        return self._meter


class HomeView(QWidget, Ui_Home):
    # (channel, value) — channel is the unified index: 0..3 inputs, 4..7 outputs
    gain_changed = Signal(int, int)
    mute_changed = Signal(int, bool)
    phase_changed = Signal(int, bool)
    gate_toggled = Signal(int, bool)
    output_feature_toggled = Signal(int, str, bool)
    recall_clicked = Signal()
    store_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setupUi(self)

        self._input_strips: list[ChannelStrip] = []
        self._output_strips: list[ChannelStrip] = []

        for i in range(NUM_CHANNELS):
            strip = ChannelStrip(f"In {chr(ord('A') + i)}", is_output=False)
            self._input_strips.append(strip)
            self.inputsLayout.addWidget(strip)
            self._connect_input(i, strip)

        for i in range(NUM_CHANNELS):
            strip = ChannelStrip(f"Out {i + 1}", is_output=True)
            self._output_strips.append(strip)
            self.outputsLayout.addWidget(strip)
            self._connect_output(i, strip)

        self.set_connected(False)

        self.recallButton.clicked.connect(self.recall_clicked)
        self.storeButton.clicked.connect(self.store_clicked)

    # --- Signal plumbing ---

    def _connect_input(self, idx: int, strip: ChannelStrip) -> None:
        strip.gain_changed.connect(lambda raw, ch=idx: self.gain_changed.emit(ch, raw))

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
        for i, ch_state in enumerate(state.inputs):
            strip = self._input_strips[i]
            strip.set_title(ch_state.name or f"In {chr(ord('A') + i)}")
            strip.set_gain_silent(ch_state.gain_raw)
            strip.set_toggle_silent("mute", ch_state.muted)
            strip.set_toggle_silent("phase", ch_state.phase_inverted)
            strip.set_toggle_silent(
                "gate", False
            )  # gate has no single "on" bit in config

        for i, ch_state in enumerate(state.outputs):
            strip = self._output_strips[i]
            strip.set_title(ch_state.name or f"Out {i + 1}")
            strip.set_gain_silent(ch_state.gain_raw)
            strip.set_toggle_silent("mute", ch_state.muted)
            strip.set_toggle_silent("phase", ch_state.phase_inverted)

        self.routingMatrix.set_routing([ch.routing_mask for ch in state.outputs])

        slot = state.active_slot
        if slot is not None and state.preset_names:
            label = f"U{slot:02d}" if slot > 0 else "F00"
            name = ""
            if slot > 0 and slot < len(state.preset_names):
                name = state.preset_names[slot]
            self.presetLabel.setText(
                f"Preset: {label} \u2014 {name}" if name else f"Preset: {label}"
            )
        else:
            self.presetLabel.setText("Preset: —")

    def update_levels(self, payload: dict) -> None:
        inputs = payload.get("inputs", [])
        outputs = payload.get("outputs", [])
        for i in range(NUM_CHANNELS):
            if i < len(inputs):
                self._input_strips[i].meter.set_level(inputs[i])
            if i < len(outputs):
                self._output_strips[i].meter.set_level(outputs[i])

    @property
    def menu_button(self):
        return self.menuButton

    def show_preview_banner(self, filename: str) -> None:
        self.titleLabel.setText(f"Preview — {filename}")
        self.connectionLabel.setText("Preview")
        self.connectionLabel.setStyleSheet(
            "background-color: #8a6d20; color: white; border-radius: 4px;"
            " padding: 4px 8px; font-weight: 600;"
        )

    def set_offline_mode(self) -> None:
        self.titleLabel.setText("Home")
        self.connectionLabel.setText("Offline")
        self.connectionLabel.setStyleSheet(
            "background-color: #8a6d20; color: white; border-radius: 4px;"
            " padding: 4px 8px; font-weight: 600;"
        )
        for strip in self._input_strips + self._output_strips:
            strip.set_enabled_state(True)

    def set_connected(self, connected: bool) -> None:
        self.titleLabel.setText("Home")
        if connected:
            self.connectionLabel.setText("Connected")
            self.connectionLabel.setStyleSheet(
                "background-color: #2fa84a; color: white; border-radius: 4px;"
                " padding: 4px 8px; font-weight: 600;"
            )
        else:
            self.connectionLabel.setText("Disconnected")
            self.connectionLabel.setStyleSheet(
                "background-color: #8a2020; color: white; border-radius: 4px;"
                " padding: 4px 8px; font-weight: 600;"
            )
            for strip in self._input_strips + self._output_strips:
                strip.set_enabled_state(False)
            return

        for strip in self._input_strips + self._output_strips:
            strip.set_enabled_state(True)
