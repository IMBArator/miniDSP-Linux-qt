"""Crossover settings panel for output channels.

Lays out Hi-Pass and Lo-Pass rows, each with frequency knob, slope
combo, and bypass toggle, below a summed frequency-response graph
showing both crossover and PEQ contributions.

Protocol encoding (shared by hipass 0x32 and lopass 0x31):

============  ==========  ===================  ===========================
Parameter     Raw range   Display              Formula
============  ==========  ===================  ===========================
Frequency     0 -- 300    19.7 Hz .. 20 kHz    Hz = 19.70 * (20160/19.70)^(raw/300)
Slope         0 -- 10     Off / BW 6 .. LR 24  See SLOPE_NAMES
============  ==========  ===================  ===========================

Slope = 0 means bypassed.  The device **forgets** the slope on bypass
so the panel tracks the last-active slope and re-sends it on un-bypass.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from minidsp.protocol import SLOPE_NAMES, freq_raw_to_hz

from ...widgets import FreqResponseGraph, ParamKnob, ToggleButton
from ...widgets.freq_response_graph import CrossoverData
from ._slave_lock import apply_link_state, install_link_banner
from ...defaults import default_crossover_state

_SLOPE_ITEMS = [SLOPE_NAMES[i] for i in sorted(SLOPE_NAMES) if i != 0]

_DEFAULT_SLOPE = 10  # LR-24, device default when slope is lost after bypass


def _fmt_freq(raw: int) -> str:
    hz = freq_raw_to_hz(raw)
    return f"{hz:.1f} Hz" if hz < 1000 else f"{hz / 1000:.2f} kHz"


def _parse_freq(text: str) -> int:
    import math

    t = text.lower().strip()
    mult = 1.0
    if t.endswith("khz"):
        mult = 1000.0
        t = t.removesuffix("khz").strip()
    elif t.endswith("hz"):
        t = t.removesuffix("hz").strip()
    hz = float(t) * mult
    if hz <= 0:
        return 0
    raw = round(300.0 * math.log(hz / 19.70) / math.log(20160.0 / 19.70))
    return max(0, min(300, raw))


class XoverPanel(QWidget):
    """Crossover controls + shared frequency-response graph for one output.

    Two rows (Hi-Pass and Lo-Pass), each with a frequency knob, slope
    selector and bypass toggle. The bypass toggle is independent of
    the slope selector (matching the manufacturer software): toggling
    bypass remembers the previous slope so the user can flick the
    filter on and off without losing their choice.

    Signals:
        xover_changed (int, int, int, int): ``(hipass_freq,
            hipass_slope, lopass_freq, lopass_slope)`` raw values.
            Slope of 0 means the filter is bypassed.
        reset_requested (): Emitted after the user confirms the
            "Reset" header button.
    """

    xover_changed = Signal(int, int, int, int)
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the panel seeded with the F00 factory crossover values.

        Args:
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self._suppress_emit = False
        self._hp_last_slope: int = 10
        self._lp_last_slope: int = 10

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._link_banner = install_link_banner(root)

        header = QHBoxLayout()
        title = QLabel("Xover Settings")
        title.setObjectName("panelTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(title)
        header.addStretch()
        self._reset_btn = QPushButton("Reset")
        self._reset_btn.setObjectName("resetButton")
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        header.addWidget(self._reset_btn)
        root.addLayout(header)

        self._graph = FreqResponseGraph(feature="xover")
        self._graph.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self._graph, stretch=1)

        factory_defaults = default_crossover_state()
        root.addLayout(self._build_filter_row("Hi-Pass", "hp", factory_defaults[0]))
        root.addLayout(self._build_filter_row("Lo-Pass", "lp", factory_defaults[2]))

    def _build_filter_row(self, label: str, prefix: str, default_freq: int) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        lbl = QLabel(label)
        lbl.setObjectName("paramLabel")
        lbl.setFixedWidth(56)
        row.addWidget(lbl)

        freq_knob = ParamKnob(
            minimum=0,
            maximum=300,
            default=default_freq,
            formatter=_fmt_freq,
            parser=_parse_freq,
        )
        freq_knob.valueChanged.connect(lambda _v: self._on_param_changed())
        row.addWidget(freq_knob)
        setattr(self, f"_{prefix}_freq", freq_knob)

        slope_combo = QComboBox()
        slope_combo.addItems(_SLOPE_ITEMS)
        slope_combo.setCurrentIndex(_DEFAULT_SLOPE - 1)
        slope_combo.setFixedWidth(80)
        slope_combo.currentIndexChanged.connect(lambda _i: self._on_param_changed())
        row.addWidget(slope_combo)
        setattr(self, f"_{prefix}_slope", slope_combo)

        bypass_btn = ToggleButton()
        bypass_btn.setText("Byp")
        bypass_btn.setMinimumWidth(48)
        bypass_btn.toggled.connect(lambda _c: self._on_param_changed())
        row.addWidget(bypass_btn)
        setattr(self, f"_{prefix}_bypass", bypass_btn)

        row.addStretch(1)
        return row

    def _on_reset_clicked(self) -> None:
        if (
            QMessageBox.question(
                self,
                "Reset Xover",
                "Reset Xover to factory defaults for this channel?",
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.reset_requested.emit()

    def _read_state(self) -> CrossoverData:
        hp_bypassed = self._hp_bypass.isChecked()
        hp_slope = 0 if hp_bypassed else (self._hp_slope.currentIndex() + 1)

        lp_bypassed = self._lp_bypass.isChecked()
        lp_slope = 0 if lp_bypassed else (self._lp_slope.currentIndex() + 1)

        return CrossoverData(
            hipass_freq=self._hp_freq.value(),
            hipass_slope=hp_slope,
            lopass_freq=self._lp_freq.value(),
            lopass_slope=lp_slope,
        )

    def _on_param_changed(self) -> None:
        if self._suppress_emit:
            return

        self._hp_last_slope = self._hp_slope.currentIndex() + 1
        self._lp_last_slope = self._lp_slope.currentIndex() + 1

        xo = self._read_state()
        self._graph.set_crossover(xo)
        self.xover_changed.emit(
            xo.hipass_freq, xo.hipass_slope, xo.lopass_freq, xo.lopass_slope
        )

    def is_xover_active(self) -> bool:
        """True if either hi-pass or lo-pass has a non-zero slope (not bypassed)."""
        xo = self._read_state()
        return xo.hipass_slope != 0 or xo.lopass_slope != 0

    def reset_to_defaults(self) -> None:
        """Reset hi-pass and lo-pass to F00 factory values without emitting signals."""
        self.set_params_silently(*default_crossover_state())

    def set_params_silently(
        self,
        hipass_freq: int,
        hipass_slope: int,
        lopass_freq: int,
        lopass_slope: int,
    ) -> None:
        """Apply device-driven crossover state without emitting signals.

        Args:
            hipass_freq: Raw hi-pass frequency value.
            hipass_slope: Raw hi-pass slope index, or 0 for bypass.
                A 0 here also hides the bypass-vs-slope distinction:
                the slope combo holds onto whichever value it had
                last so toggling bypass off restores it.
            lopass_freq: Raw lo-pass frequency value.
            lopass_slope: Raw lo-pass slope index, or 0 for bypass.
        """
        prev = self._suppress_emit
        self._suppress_emit = True
        try:
            hp_bypassed = hipass_slope == 0
            hp_display = hipass_slope if hipass_slope != 0 else _DEFAULT_SLOPE
            self._hp_last_slope = hp_display

            self._hp_freq.setValueSilently(hipass_freq)
            self._hp_slope.blockSignals(True)
            self._hp_slope.setCurrentIndex(hp_display - 1)
            self._hp_slope.blockSignals(False)
            self._hp_bypass.blockSignals(True)
            self._hp_bypass.setChecked(hp_bypassed)
            self._hp_bypass.blockSignals(False)

            lp_bypassed = lopass_slope == 0
            lp_display = lopass_slope if lopass_slope != 0 else _DEFAULT_SLOPE
            self._lp_last_slope = lp_display

            self._lp_freq.setValueSilently(lopass_freq)
            self._lp_slope.blockSignals(True)
            self._lp_slope.setCurrentIndex(lp_display - 1)
            self._lp_slope.blockSignals(False)
            self._lp_bypass.blockSignals(True)
            self._lp_bypass.setChecked(lp_bypassed)
            self._lp_bypass.blockSignals(False)
        finally:
            self._suppress_emit = prev
        self._graph.set_crossover(self._read_state())

    def set_bands(self, bands, channel_bypass: bool) -> None:
        """Forward the channel's PEQ bands into the shared graph.

        Args:
            bands: Up to 7 ``PEQBand`` instances.
            channel_bypass: Channel-wide PEQ bypass flag.
        """
        self._graph.set_bands(bands, channel_bypass)

    def set_linked_slave(self, is_slave: bool, master_name: str = "") -> None:
        """Lock the panel when displaying a slave channel's crossover.

        Disables both Hi-Pass and Lo-Pass rows (freq knob, slope
        combo, bypass toggle). The summed response graph stays
        visible so the user still sees what the slave is doing.

        Args:
            is_slave: True if the displayed channel is a slave in a
                link group.
            master_name: Display name of the master, used inside the
                banner text.
        """
        apply_link_state(
            self._link_banner,
            is_slave,
            master_name,
            [
                self._hp_freq,
                self._hp_slope,
                self._hp_bypass,
                self._lp_freq,
                self._lp_slope,
                self._lp_bypass,
                self._reset_btn,
            ],
        )
