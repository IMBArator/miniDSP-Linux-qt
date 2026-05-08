"""Channel detail view with feature panels and routed-channel level meters.

Layout (matching concept art ``miniDSP-detailView.excalidraw``)::

    +--------------------------------------------------------------------+
    | [<- Back]    "InA"                   [Connected]    [menu]         |
    +--------+-------------------------------------------+--------------+
    | [InA]  |                                           | [Out1]       |
    | [InB]  |  ChannelStrip (reused from home_view)     | [Out2]       |
    | [InC]  |                                           | [Out3]       |
    | [InD]  |                                           | [Out4]       |
    +--------+-------------------------------------------+--------------+
    |                          |                                        |
    |  Feature Panel           |  Routed-channel meters                |
    |  (Gate / Xover / ...)    |  (vertical LevelMeters for channels   |
    |                          |   connected via the routing matrix)    |
    |                          |                                        |
    +--------------------------+----------------------------------------+

For input channels the routed meters are on the **right** (showing outputs).
For output channels the routed meters are on the **left** (showing inputs).

The channel header reuses the :class:`ChannelStrip` widget from
:mod:`.home_view` so the look-and-feel is identical to the home screen.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from minidsp.protocol import CHANNEL_NAMES

from ..model import DeviceState
from ..widgets import LevelMeter
from .channel_strip import ChannelStrip, InputChannelStrip, OutputChannelStrip
from .panels import GatePanel

NUM_CHANNELS = 4


class RoutedMetersPanel(QWidget):
    """Vertical level meters for channels routed via the matrix."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(6)
        self._meters: list[tuple[int, QLabel, LevelMeter]] = []
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    def set_channels(self, channel_indices: list[int], names: dict[int, str] | None = None) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._meters.clear()

        for ch in channel_indices:
            col = QVBoxLayout()
            col.setSpacing(2)
            col.setAlignment(Qt.AlignmentFlag.AlignHCenter)

            lbl = QLabel((names or {}).get(ch, CHANNEL_NAMES[ch]))
            lbl.setObjectName("routedMeterLabel")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(lbl)

            meter = LevelMeter(vertical=True)
            meter.setFixedWidth(24)
            col.addWidget(meter, stretch=1)

            container = QWidget()
            container.setLayout(col)
            self._layout.addWidget(container)
            self._meters.append((ch, lbl, meter))

    def update_levels(self, payload: dict) -> None:
        inputs = payload.get("inputs", [])
        outputs = payload.get("outputs", [])
        for ch, _lbl, meter in self._meters:
            if ch < 4 and ch < len(inputs):
                meter.set_level(inputs[ch])
            elif ch >= 4 and (ch - 4) < len(outputs):
                meter.set_level(outputs[ch - 4])
            else:
                meter.reset()


class DetailView(QWidget):
    """Per-channel detail view with feature panels and routed meters.

    Signals
    -------
    back_clicked()
        User pressed the back button.
    gain_changed(int, int)
        ``(channel, raw)``
    mute_changed(int, bool)
        ``(channel, muted)``
    phase_changed(int, bool)
        ``(channel, inverted)``
    gate_enable_changed(int, bool)
        ``(channel, enabled)``
    gate_params_changed(int, int, int, int, int)
        ``(channel, attack, release, hold, threshold)``
    output_feature_toggled(int, str, bool)
        ``(channel, feature, checked)``
    name_changed(int, str)
        ``(channel, name)``
    """

    back_clicked = Signal()
    gain_changed = Signal(int, int)
    mute_changed = Signal(int, bool)
    phase_changed = Signal(int, bool)
    gate_clicked = Signal(int)
    gate_params_changed = Signal(int, int, int, int, int)
    output_feature_toggled = Signal(int, str, bool)
    name_changed = Signal(int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._channel: int = 0
        self._is_input: bool = True
        self._feature_name: str = "Gate"
        self._cached_state: DeviceState | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        root.addLayout(self._build_header())
        root.addLayout(self._build_channel_strip_row())

        content_row = QHBoxLayout()
        content_row.setSpacing(8)

        self._left_meters = RoutedMetersPanel()
        self._left_meters.hide()
        content_row.addWidget(self._left_meters)

        self._content_stack = QStackedWidget()
        self._gate_panel = GatePanel()
        self._content_stack.addWidget(self._gate_panel)
        content_row.addWidget(self._content_stack, stretch=1)

        self._right_meters = RoutedMetersPanel()
        self._right_meters.hide()
        content_row.addWidget(self._right_meters)

        root.addLayout(content_row, stretch=1)

        self._gate_panel.gate_params_changed.connect(self._on_gate_params)

    # ------------------------------------------------------------------ #
    # Header (identical chrome to HomeView)
    # ------------------------------------------------------------------ #

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()

        self._back_button = QPushButton("\u2190")
        self._back_button.setObjectName("menuButton")
        self._back_button.setFixedSize(28, 28)
        self._back_button.clicked.connect(self.back_clicked)
        header.addWidget(self._back_button)

        header.addItem(
            QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )

        self._title_label = QLabel("Detail View")
        self._title_label.setObjectName("titleLabel")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self._title_label)

        header.addItem(
            QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )

        self._connection_label = QLabel("Disconnected")
        self._connection_label.setObjectName("connectionLabel")
        self._connection_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._connection_label.setMinimumSize(110, 28)
        self._set_connection_state("disconnected")
        header.addWidget(self._connection_label)

        self._menu_button = QPushButton("\u2261")
        self._menu_button.setObjectName("menuButton")
        self._menu_button.setFixedSize(28, 28)
        header.addWidget(self._menu_button)

        return header

    # ------------------------------------------------------------------ #
    # Channel strip row: [input buttons] | [ChannelStrip] | [output buttons]
    # ------------------------------------------------------------------ #

    def _build_channel_strip_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._input_buttons: list[QPushButton] = []
        input_col = QVBoxLayout()
        input_col.setSpacing(4)
        for i in range(NUM_CHANNELS):
            btn = QPushButton(CHANNEL_NAMES[i])
            btn.setObjectName("channelNavButton")
            btn.setCheckable(True)
            btn.setFixedWidth(56)
            btn.clicked.connect(lambda checked, ch=i: self._on_input_nav(ch))
            input_col.addWidget(btn)
            self._input_buttons.append(btn)
        input_col.addStretch(1)
        input_container = QWidget()
        input_container.setLayout(input_col)
        row.addWidget(input_container)

        self._strip_stack = QStackedWidget()
        self._input_strip = InputChannelStrip("InA")
        self._output_strip = OutputChannelStrip("Out1")
        self._strip_stack.addWidget(self._input_strip)
        self._strip_stack.addWidget(self._output_strip)
        row.addWidget(self._strip_stack, stretch=1)

        self._output_buttons: list[QPushButton] = []
        output_col = QVBoxLayout()
        output_col.setSpacing(4)
        for i in range(NUM_CHANNELS):
            btn = QPushButton(CHANNEL_NAMES[i + 4])
            btn.setObjectName("channelNavButton")
            btn.setCheckable(True)
            btn.setFixedWidth(56)
            btn.clicked.connect(lambda checked, ch=i: self._on_output_nav(ch))
            output_col.addWidget(btn)
            self._output_buttons.append(btn)
        output_col.addStretch(1)
        output_container = QWidget()
        output_container.setLayout(output_col)
        row.addWidget(output_container)

        for strip in (self._input_strip, self._output_strip):
            strip.gain_changed.connect(self._on_strip_gain)
            strip.toggle_changed.connect(self._on_strip_toggle)
            strip.name_changed.connect(self._on_strip_name)

        self._input_strip.gate_clicked.connect(self._on_gate_nav)

        return row

    @property
    def _strip(self) -> ChannelStrip:
        return self._input_strip if self._is_input else self._output_strip

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def set_channel(self, channel: int, state: DeviceState) -> None:
        self._channel = channel
        self._is_input = channel < 4
        self._cached_state = state

        self._strip_stack.setCurrentIndex(0 if self._is_input else 1)
        self._update_nav_highlight()
        self._update_nav_labels(state)
        self._update_routed_meters(state)

        strip = self._strip
        if self._is_input:
            ch_state = state.inputs[channel]
            strip.set_gain_silent(ch_state.gain_raw)
            strip.set_toggle_silent("mute", ch_state.muted)
            strip.set_toggle_silent("phase", ch_state.phase_inverted)
            strip.set_toggle_silent("gate", False)
            strip.set_gate_active(ch_state.gate.threshold > 0)
            self._gate_panel.set_params_silently(
                ch_state.gate.attack,
                ch_state.gate.release,
                ch_state.gate.hold,
                ch_state.gate.threshold,
            )
            self._content_stack.setCurrentWidget(self._gate_panel)
        else:
            ch_state = state.outputs[channel - 4]
            strip.set_gain_silent(ch_state.gain_raw)
            strip.set_toggle_silent("mute", ch_state.muted)
            strip.set_toggle_silent("phase", ch_state.phase_inverted)
            for f in ("xover", "peq", "comp", "delay"):
                strip.set_toggle_silent(f, False)
            self._content_stack.setCurrentWidget(self._gate_panel)

        ch_name = ch_state.name or CHANNEL_NAMES[channel]
        strip.set_title(ch_name)
        self._feature_name = "Gate"
        self._title_label.setText(f"{self._feature_name} \u2014 {ch_name}")

    def update_levels(self, payload: dict) -> None:
        inputs = payload.get("inputs", [])
        outputs = payload.get("outputs", [])
        ch = self._channel
        if ch < 4 and ch < len(inputs):
            self._strip.update_level(inputs[ch])
        elif ch >= 4 and (ch - 4) < len(outputs):
            self._strip.update_level(outputs[ch - 4])

        self._left_meters.update_levels(payload)
        self._right_meters.update_levels(payload)

    def set_connected(self, connected: bool) -> None:
        if connected:
            self._connection_label.setText("Connected")
            self._set_connection_state("connected")
            for s in (self._input_strip, self._output_strip):
                s.set_enabled_state(True)
        else:
            self._connection_label.setText("Disconnected")
            self._set_connection_state("disconnected")
            for s in (self._input_strip, self._output_strip):
                s.set_enabled_state(False)

    def set_offline_mode(self) -> None:
        self._connection_label.setText("Offline")
        self._set_connection_state("offline")
        for s in (self._input_strip, self._output_strip):
            s.set_enabled_state(True)

    def show_preview_banner(self, filename: str) -> None:
        self._connection_label.setText("Preview")
        self._set_connection_state("preview")

    @property
    def menu_button(self) -> QPushButton:
        return self._menu_button

    @property
    def gate_panel(self) -> GatePanel:
        return self._gate_panel

    @property
    def channel(self) -> int:
        return self._channel

    # ------------------------------------------------------------------ #
    # Routed meters
    # ------------------------------------------------------------------ #

    def _update_routed_meters(self, state: DeviceState) -> None:
        self._left_meters.hide()
        self._right_meters.hide()

        names = self._channel_names(state)

        if self._is_input:
            routed = self._routed_outputs_for_input(state, self._channel)
            if routed:
                self._right_meters.set_channels(routed, names)
                self._right_meters.show()
        else:
            routed = self._routed_inputs_for_output(state, self._channel)
            if routed:
                self._left_meters.set_channels(routed, names)
                self._left_meters.show()

    @staticmethod
    def _routed_outputs_for_input(state: DeviceState, input_ch: int) -> list[int]:
        result = []
        bit = 1 << input_ch
        for out_idx in range(NUM_CHANNELS):
            if out_idx >= len(state.outputs):
                break
            if state.outputs[out_idx].routing_mask & bit:
                result.append(out_idx + 4)
        return result

    @staticmethod
    def _routed_inputs_for_output(state: DeviceState, output_ch: int) -> list[int]:
        out_idx = output_ch - 4
        if out_idx < 0 or out_idx >= len(state.outputs):
            return []
        mask = state.outputs[out_idx].routing_mask
        return [i for i in range(4) if mask & (1 << i)]

    # ------------------------------------------------------------------ #
    # Navigation
    # ------------------------------------------------------------------ #

    def _update_nav_highlight(self) -> None:
        for i, btn in enumerate(self._input_buttons):
            btn.setChecked(i == self._channel and self._is_input)
        for i, btn in enumerate(self._output_buttons):
            ch = i + 4
            btn.setChecked(ch == self._channel and not self._is_input)

    def _on_input_nav(self, ch: int) -> None:
        if self._cached_state is not None:
            self.set_channel(ch, self._cached_state)

    def _on_output_nav(self, idx: int) -> None:
        if self._cached_state is not None:
            self.set_channel(idx + 4, self._cached_state)

    # ------------------------------------------------------------------ #
    # Signal handlers
    # ------------------------------------------------------------------ #

    def _on_strip_gain(self, raw: int) -> None:
        self.gain_changed.emit(self._channel, raw)

    def _on_strip_toggle(self, feature: str, checked: bool) -> None:
        if feature == "mute":
            self.mute_changed.emit(self._channel, checked)
        elif feature == "phase":
            self.phase_changed.emit(self._channel, checked)
        else:
            self.output_feature_toggled.emit(self._channel, feature, checked)

    def _on_gate_nav(self) -> None:
        self._content_stack.setCurrentWidget(self._gate_panel)
        self._feature_name = "Gate"
        ch_name = self._strip._title_btn.text()
        self._title_label.setText(f"{self._feature_name} \u2014 {ch_name}")
        self.gate_clicked.emit(self._channel)

    def _on_strip_name(self, name: str) -> None:
        ch_name = name or CHANNEL_NAMES[self._channel]
        self._title_label.setText(f"{self._feature_name} \u2014 {ch_name}")
        if self._is_input:
            self._input_buttons[self._channel].setText(ch_name)
        else:
            self._output_buttons[self._channel - 4].setText(ch_name)
        self.name_changed.emit(self._channel, name)

    def _on_gate_params(self, attack: int, release: int, hold: int, threshold: int) -> None:
        if self._is_input:
            self._input_strip.set_gate_active(threshold > 0)
        self.gate_params_changed.emit(
            self._channel, attack, release, hold, threshold
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _set_connection_state(self, state: str) -> None:
        self._connection_label.setProperty("state", state)
        self._connection_label.style().unpolish(self._connection_label)
        self._connection_label.style().polish(self._connection_label)

    def _channel_names(self, state: DeviceState) -> dict[int, str]:
        names: dict[int, str] = {}
        for i, ch in enumerate(state.inputs):
            names[i] = ch.name or CHANNEL_NAMES[i]
        for i, ch in enumerate(state.outputs):
            names[i + 4] = ch.name or CHANNEL_NAMES[i + 4]
        return names

    def _update_nav_labels(self, state: DeviceState) -> None:
        for i in range(NUM_CHANNELS):
            self._input_buttons[i].setText(state.inputs[i].name or CHANNEL_NAMES[i])
            self._output_buttons[i].setText(
                state.outputs[i].name or CHANNEL_NAMES[i + 4]
            )
