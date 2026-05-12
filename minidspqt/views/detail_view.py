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
from ..defaults import (
    default_compressor_state,
    default_crossover_state,
    default_delay_samples,
    default_gate_state,
    default_peq_bands,
    default_peq_channel_bypass,
)
from .channel_strip import (
    ChannelStrip,
    InputChannelStrip,
    OutputChannelStrip,
    apply_input_strip_state,
    apply_output_strip_state,
)
from .panels import (
    CompressorPanel,
    DelayPanel,
    GatePanel,
    PEQPanel,
    PlaceholderPanel,
    XoverPanel,
)
from ..widgets.freq_response_graph import CrossoverData

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
    peq_band_changed = Signal(int, int, int, int, int, int, bool)
    peq_channel_bypass_changed = Signal(int, bool)
    xover_changed = Signal(int, int, int, int, int)
    compressor_changed = Signal(int, int, int, int, int, int)
    delay_changed = Signal(int, int)
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
        self._peq_panel = PEQPanel()
        self._xover_panel = XoverPanel()
        self._compressor_panel = CompressorPanel()
        self._delay_panel = DelayPanel()
        self._placeholder_panel = PlaceholderPanel()
        self._content_stack.addWidget(self._gate_panel)
        self._content_stack.addWidget(self._peq_panel)
        self._content_stack.addWidget(self._xover_panel)
        self._content_stack.addWidget(self._compressor_panel)
        self._content_stack.addWidget(self._delay_panel)
        self._content_stack.addWidget(self._placeholder_panel)
        content_row.addWidget(self._content_stack, stretch=1)

        self._right_meters = RoutedMetersPanel()
        self._right_meters.hide()
        content_row.addWidget(self._right_meters)

        root.addLayout(content_row, stretch=1)

        self._gate_panel.gate_params_changed.connect(self._on_gate_params)
        self._gate_panel.reset_requested.connect(self._on_gate_reset)
        self._peq_panel.peq_band_changed.connect(self._on_peq_band)
        self._peq_panel.peq_channel_bypass_changed.connect(
            self._on_peq_channel_bypass
        )
        self._peq_panel.reset_requested.connect(self._on_peq_reset)
        self._xover_panel.xover_changed.connect(self._on_xover_changed)
        self._xover_panel.reset_requested.connect(self._on_xover_reset)
        self._compressor_panel.compressor_params_changed.connect(
            self._on_compressor_params
        )
        self._compressor_panel.reset_requested.connect(self._on_compressor_reset)
        self._delay_panel.delay_changed.connect(self._on_delay_changed)
        self._delay_panel.reset_requested.connect(self._on_delay_reset)

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

        self._render_displayed_channel(state)

        # Reset _feature_name only if it doesn't apply to the new channel type;
        # otherwise preserve cross-channel navigation context (e.g. user was on
        # PEQ for Out1, clicks Out2 \u2192 still on PEQ).
        if not self._feature_available(self._feature_name, self._is_input):
            self._feature_name = "Gate" if self._is_input else "PEQ"

        self._show_feature_panel()

        ch_state = self._current_channel_state(state)
        ch_name = ch_state.name or CHANNEL_NAMES[channel] if ch_state else CHANNEL_NAMES[channel]
        self._title_label.setText(f"{self._feature_name} \u2014 {ch_name}")

    def apply_state(self, state: DeviceState) -> None:
        """Re-render the currently displayed channel from ``state``.

        Used after any change that may have mutated the displayed channel
        externally \u2014 e.g. a master edit propagating to a slave shown here,
        a fresh ``read_config`` after channel-linking changes, or a
        loaded .unt preset. Cheaper than ``set_channel`` because it
        preserves the current feature selection and nav state.
        """
        self._cached_state = state
        self._update_nav_labels(state)
        self._update_routed_meters(state)
        self._render_displayed_channel(state)

    def _current_channel_state(self, state: DeviceState):
        ch = self._channel
        if ch < 4 and ch < len(state.inputs):
            return state.inputs[ch]
        if ch >= 4 and (ch - 4) < len(state.outputs):
            return state.outputs[ch - 4]
        return None

    def _render_displayed_channel(self, state: DeviceState) -> None:
        """Apply the strip + panels for the current channel from ``state``.

        Shared by :meth:`set_channel` and :meth:`apply_state` so a single
        code path drives both initial display and refresh-on-master-edit.
        """
        ch = self._channel
        ch_state = self._current_channel_state(state)
        if ch_state is None:
            return
        is_slave = state.is_linked_slave(ch)
        master_name = self._master_title(state, ch)
        strip = self._strip

        if self._is_input:
            apply_input_strip_state(strip, ch, ch_state, master_name, is_slave)
            self._gate_panel.set_params_silently(
                ch_state.gate.attack,
                ch_state.gate.release,
                ch_state.gate.hold,
                ch_state.gate.threshold,
            )
        else:
            apply_output_strip_state(strip, ch, ch_state, master_name, is_slave)
            self._peq_panel.set_bands_silently(
                ch_state.peqs, ch_state.peq_channel_bypass
            )
            xo = ch_state.crossover
            self._xover_panel.set_params_silently(
                xo.hipass_freq, xo.hipass_slope, xo.lopass_freq, xo.lopass_slope
            )
            self._peq_panel.set_crossover(CrossoverData(
                xo.hipass_freq, xo.hipass_slope, xo.lopass_freq, xo.lopass_slope
            ))
            self._xover_panel.set_bands(ch_state.peqs, ch_state.peq_channel_bypass)
            c = ch_state.compressor
            self._compressor_panel.set_params_silently(
                c.ratio, c.knee, c.attack, c.release, c.threshold,
            )
            self._push_delay_state(state)

        self._apply_slave_lock(is_slave, master_name)

    def _push_delay_state(self, state: DeviceState) -> None:
        """Populate the Delay panel's overview graph + active row.

        Called from :meth:`_render_displayed_channel` and from
        :meth:`refresh_delay_panel_state`; both share the same body so the
        panel can be updated either on full re-render or on a model-only
        fan-out refresh without re-running unrelated panel work.
        """
        out_idx = self._channel - 4
        if out_idx < 0 or out_idx >= len(state.outputs):
            return
        names = [
            (state.outputs[i].name or CHANNEL_NAMES[4 + i])
            for i in range(min(4, len(state.outputs)))
        ]
        # Pad if the state has fewer than 4 outputs (defensive — the device
        # always exposes 4, but this keeps the API safe in tests).
        while len(names) < 4:
            names.append(CHANNEL_NAMES[4 + len(names)])
        samples = [s.delay_samples for s in state.outputs[:4]]
        while len(samples) < 4:
            samples.append(0)
        self._delay_panel.set_channel_names(names)
        self._delay_panel.set_delays_silently(samples)
        self._delay_panel.set_active_channel(
            out_idx, names[out_idx], samples[out_idx]
        )

    def refresh_delay_panel_state(self) -> None:
        """Re-push delay values from the cached state into the panel.

        MainWindow calls this after a delay edit fans out via
        ``mutate_with_links`` so the graph's non-active rows reflect the
        new slave values even though the user only moved the master's
        knob.  No-op if no state is cached or the displayed channel is
        not an output.
        """
        if self._cached_state is None or self._is_input:
            return
        self._push_delay_state(self._cached_state)

    def _apply_slave_lock(self, is_slave: bool, master_name: str) -> None:
        """Propagate slave-lock state to every feature panel.

        Each panel hides the banner and re-enables its controls when
        ``is_slave`` is False, so masters and standalone channels look
        normal even after this method runs.
        """
        for panel in (
            self._gate_panel,
            self._peq_panel,
            self._xover_panel,
            self._compressor_panel,
            self._delay_panel,
        ):
            panel.set_linked_slave(is_slave, master_name)

    @staticmethod
    def _master_title(state: DeviceState, channel: int) -> str:
        """Resolve the display name of ``channel``'s master, or "".

        Mirrors :meth:`HomeView._master_title` but works from the raw
        state instead of a pre-built strip list \u2014 DetailView only has
        one strip at a time so no list lookup is needed.
        """
        if channel >= len(state.link_info):
            return ""
        info = state.link_info[channel]
        master_ch = info.get("master")
        if master_ch is None:
            return ""
        if master_ch < 4 and master_ch < len(state.inputs):
            ch_state = state.inputs[master_ch]
        elif master_ch >= 4 and (master_ch - 4) < len(state.outputs):
            ch_state = state.outputs[master_ch - 4]
        else:
            return ""
        return ch_state.name or CHANNEL_NAMES[master_ch]

    def update_levels(self, payload: dict) -> None:
        inputs = payload.get("inputs", [])
        outputs = payload.get("outputs", [])
        limiter_mask = payload.get("limiter_mask", 0)
        ch = self._channel
        if ch < 4 and ch < len(inputs):
            self._strip.update_level(inputs[ch])
        elif ch >= 4 and (ch - 4) < len(outputs):
            self._strip.update_level(outputs[ch - 4])
            self._output_strip.set_limiter_active(
                bool(limiter_mask & (1 << (ch - 4)))
            )

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
    def peq_panel(self) -> PEQPanel:
        return self._peq_panel

    @property
    def xover_panel(self) -> XoverPanel:
        return self._xover_panel

    @property
    def channel(self) -> int:
        return self._channel

    def show_feature(self, channel: int, feature_name: str) -> None:
        """Switch the detail view to ``channel`` and ``feature_name``.

        Called by MainWindow when an output's feature nav button is hit
        on either the home view or the detail view.
        """
        if self._cached_state is not None and channel != self._channel:
            self.set_channel(channel, self._cached_state)
        self._feature_name = feature_name
        self._show_feature_panel()
        ch_name = self._strip._title_btn.text()
        self._title_label.setText(f"{feature_name} — {ch_name}")

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
        self._feature_name = "Gate"
        self._show_feature_panel()
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

    def _on_peq_band(
        self,
        band: int,
        gain_raw: int,
        freq_raw: int,
        q_raw: int,
        filter_type: int,
        bypass: bool,
    ) -> None:
        if not self._is_input:
            self._output_strip.set_peq_active(self._peq_panel.is_peq_active())
            self._xover_panel.set_bands(self._peq_panel._all_bands(), self._peq_panel._channel_bypass.isChecked())
        self.peq_band_changed.emit(
            self._channel, band, gain_raw, freq_raw, q_raw, filter_type, bypass
        )

    def _on_peq_channel_bypass(self, bypass: bool) -> None:
        if not self._is_input:
            self._output_strip.set_peq_active(self._peq_panel.is_peq_active())
        self.peq_channel_bypass_changed.emit(self._channel, bypass)

    def _on_gate_params(self, attack: int, release: int, hold: int, threshold: int) -> None:
        if self._is_input:
            self._input_strip.set_gate_active(threshold > 0)
        self.gate_params_changed.emit(
            self._channel, attack, release, hold, threshold
        )

    def _on_xover_changed(
        self, hp_freq: int, hp_slope: int, lp_freq: int, lp_slope: int
    ) -> None:
        if not self._is_input:
            active = hp_slope != 0 or lp_slope != 0
            self._output_strip.set_xover_active(active)
            self._peq_panel.set_crossover(CrossoverData(
                hp_freq, hp_slope, lp_freq, lp_slope
            ))
        self.xover_changed.emit(self._channel, hp_freq, hp_slope, lp_freq, lp_slope)

    def _on_compressor_params(
        self,
        ratio: int,
        knee: int,
        attack: int,
        release: int,
        threshold: int,
    ) -> None:
        if not self._is_input:
            self._output_strip.set_comp_active(ratio > 0)
        self.compressor_changed.emit(
            self._channel, ratio, knee, attack, release, threshold
        )

    def _on_delay_changed(self, samples: int) -> None:
        # Light the output strip's Delay LED immediately for snappy feedback;
        # the model fan-out in MainWindow refreshes everything else.
        if not self._is_input:
            self._output_strip.set_delay_active(samples > 0)
        self.delay_changed.emit(self._channel, samples)

    def _on_gate_reset(self) -> None:
        self._gate_panel.reset_to_defaults()
        attack, release, hold, threshold = default_gate_state()
        if self._is_input:
            self._input_strip.set_gate_active(threshold > 0)
        self.gate_params_changed.emit(self._channel, attack, release, hold, threshold)

    def _on_compressor_reset(self) -> None:
        self._compressor_panel.reset_to_defaults()
        ratio, knee, attack, release, threshold = default_compressor_state()
        if not self._is_input:
            self._output_strip.set_comp_active(ratio > 0)
        self.compressor_changed.emit(self._channel, ratio, knee, attack, release, threshold)

    def _on_xover_reset(self) -> None:
        self._xover_panel.reset_to_defaults()
        hp_freq, hp_slope, lp_freq, lp_slope = default_crossover_state()
        if not self._is_input:
            self._output_strip.set_xover_active(hp_slope != 0 or lp_slope != 0)
            self._peq_panel.set_crossover(CrossoverData(hp_freq, hp_slope, lp_freq, lp_slope))
        self.xover_changed.emit(self._channel, hp_freq, hp_slope, lp_freq, lp_slope)

    def _on_delay_reset(self) -> None:
        self._delay_panel.reset_to_defaults()
        samples = default_delay_samples()
        if not self._is_input:
            self._output_strip.set_delay_active(samples > 0)
        self.delay_changed.emit(self._channel, samples)

    def _on_peq_reset(self) -> None:
        self._peq_panel.reset_to_defaults()
        if not self._is_input:
            self._output_strip.set_peq_active(self._peq_panel.is_peq_active())
            self._xover_panel.set_bands(
                self._peq_panel._all_bands(),
                self._peq_panel._channel_bypass.isChecked(),
            )
        for band, (gain_raw, freq_raw, q_raw, filter_type, bypass) in enumerate(default_peq_bands()):
            self.peq_band_changed.emit(
                self._channel, band, gain_raw, freq_raw, q_raw, filter_type, bypass
            )
        self.peq_channel_bypass_changed.emit(self._channel, default_peq_channel_bypass())

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _feature_available(feature: str, is_input: bool) -> bool:
        if feature == "Gate":
            return is_input
        if feature in ("PEQ", "Xover", "Comp", "Delay"):
            return not is_input
        return False

    def _show_feature_panel(self) -> None:
        if self._feature_available(self._feature_name, self._is_input):
            if self._feature_name == "Gate":
                self._content_stack.setCurrentWidget(self._gate_panel)
                return
            if self._feature_name == "PEQ":
                self._content_stack.setCurrentWidget(self._peq_panel)
                return
            if self._feature_name == "Xover":
                self._content_stack.setCurrentWidget(self._xover_panel)
                return
            if self._feature_name == "Comp":
                self._content_stack.setCurrentWidget(self._compressor_panel)
                return
            if self._feature_name == "Delay":
                self._content_stack.setCurrentWidget(self._delay_panel)
                return
        self._placeholder_panel.set_message(
            f"{self._feature_name} is not available for this channel."
        )
        self._content_stack.setCurrentWidget(self._placeholder_panel)

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
