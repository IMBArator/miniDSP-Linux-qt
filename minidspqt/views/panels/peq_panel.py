"""PEQ settings panel for output channels.

Lays out 7 band columns of (Type, Freq, Gain, Q, Byp) below a summed
frequency-response graph, with a channel-bypass toggle in the title
row.

Each band's parameters are emitted *atomically per band* — the device
command (opcode 0x33) writes one full band at a time, so any change
in band *N* triggers a single ``peq_band_changed`` emit carrying all
five fields of band *N*.

Protocol raw ranges and conversions:

============  ==========  =================  ===========================
Parameter     Raw range   Display            Formula
============  ==========  =================  ===========================
Gain          0 -- 240    -12.0 .. +12.0 dB  dB = (raw - 120) / 10
Freq          0 -- 300    19.7 Hz .. 20 kHz  Hz = 19.70 * (20160/19.70)^(raw/300)
Q             0 -- 100    0.40 .. 128        Q  = 0.4 * 320^(raw/100)
Q (shelf/pass) 0 -- 35    0.40 .. 3.0        capped by app UI per analysis/protocol.md
Type          0 -- 6      Peak / shelves /   PEQ_TYPE_* constants
                          passes / allpasses
Bypass        bool        per-band & per-channel
============  ==========  =================  ===========================

Q range note
------------
The device firmware accepts the full raw 0–100 Q for any filter type,
but the official editor restricts shelf and pass filters to raw 0–35
(Q ≤ 3.0).  Higher Q on a shelf or pass produces a resonant bump that
is rarely musically useful, so we mirror the official UI here and
refit the Q knob's range whenever the type combo changes.  Peak and
allpass filters keep the full Q range.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from minidsp.protocol import (
    PEQ_TYPE_ALLPASS1,
    PEQ_TYPE_ALLPASS2,
    PEQ_TYPE_HIGH_PASS,
    PEQ_TYPE_HIGH_SHELF,
    PEQ_TYPE_LOW_PASS,
    PEQ_TYPE_LOW_SHELF,
    PEQ_TYPE_PEAK,
    freq_hz_to_raw,
    freq_raw_to_hz,
    peq_gain_to_raw,
    peq_q_to_raw,
    peq_raw_to_gain,
    peq_raw_to_q,
)

from ...model import PEQBand
from ...widgets import FreqResponseGraph, ParamKnob, ToggleButton
from ...widgets.freq_response_graph import CrossoverData
from ._slave_lock import apply_link_state, install_link_banner
from ...defaults import default_peq_bands, default_peq_channel_bypass

NUM_BANDS = 7

PEQ_TYPE_NAMES = (
    "Peak",
    "Low Shelf",
    "High Shelf",
    "Low Pass",
    "High Pass",
    "AP1",
    "AP2",
)

# Maximum Q raw value per filter type.  Shelves and pass filters are capped
# at raw 35 (Q ≈ 3.0) — the official editor does this and higher Q on those
# types produces a resonant bump that is rarely useful.  Peak and the two
# allpass forms keep the full range.
_Q_RAW_MAX_BY_TYPE = {
    PEQ_TYPE_PEAK: 100,
    PEQ_TYPE_LOW_SHELF: 35,
    PEQ_TYPE_HIGH_SHELF: 35,
    PEQ_TYPE_LOW_PASS: 35,
    PEQ_TYPE_HIGH_PASS: 35,
    PEQ_TYPE_ALLPASS1: 100,
    PEQ_TYPE_ALLPASS2: 100,
}


def _q_max_for_type(filter_type: int) -> int:
    return _Q_RAW_MAX_BY_TYPE.get(filter_type, 100)


def _fmt_freq(raw: int) -> str:
    # 1-decimal Hz under 1 kHz so values like raw=118 render as "300.8 Hz"
    # rather than rounding to "301 Hz" — matches the original t.racks editor.
    hz = freq_raw_to_hz(raw)
    return f"{hz:.1f} Hz" if hz < 1000 else f"{hz / 1000:.2f} kHz"


def _parse_freq(text: str) -> int:
    t = text.lower().strip()
    mult = 1.0
    if t.endswith("khz"):
        mult = 1000.0
        t = t.removesuffix("khz").strip()
    elif t.endswith("hz"):
        t = t.removesuffix("hz").strip()
    hz = float(t) * mult
    return freq_hz_to_raw(hz)


def _fmt_gain(raw: int) -> str:
    return f"{peq_raw_to_gain(raw):+.1f} dB"


def _parse_gain(text: str) -> int:
    db = float(text.lower().removesuffix("db").strip())
    return max(0, min(240, peq_gain_to_raw(db)))


def _fmt_q(raw: int) -> str:
    q = peq_raw_to_q(raw)
    return f"{q:.2f}" if q < 10 else f"{q:.1f}"


def _parse_q(text: str) -> int:
    q = float(text.strip())
    return max(0, min(100, peq_q_to_raw(q)))


class PEQPanel(QWidget):
    """7-band PEQ controls + summed response graph for one output channel.

    A 5-row × 7-column grid (Type / Bypass / Freq / Gain / Q per band)
    sits below the shared ``FreqResponseGraph``. Per-type Q ranges
    follow the official editor — shelves and pass filters cap Q at
    3.0; peak and the two allpass forms allow the full range.

    Signals:
        peq_band_changed (int, int, int, int, int, bool): One band
            update — ``(band, gain_raw, freq_raw, q_raw,
            filter_type, bypass)``. Emitted atomically when any
            per-band control changes.
        peq_channel_bypass_changed (bool): The channel-wide PEQ
            bypass toggle.
        reset_requested (): Emitted after the user confirms the
            "Reset" header button.
    """

    peq_band_changed = Signal(int, int, int, int, int, bool)
    peq_channel_bypass_changed = Signal(bool)
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the panel seeded with the F00 factory PEQ values.

        Args:
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self._suppress_emit = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._link_banner = install_link_banner(root)

        root.addLayout(self._build_header())

        self._graph = FreqResponseGraph(feature="peq")
        self._graph.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._graph.band_dragged.connect(self._on_marker_dragged)
        self._graph.band_q_changed.connect(self._on_marker_q_changed)
        self._graph.band_bypass_toggled.connect(self._on_marker_bypass_toggled)
        root.addWidget(self._graph, stretch=1)

        self._type_combos: list[QComboBox] = []
        self._freq_knobs: list[ParamKnob] = []
        self._gain_knobs: list[ParamKnob] = []
        self._q_knobs: list[ParamKnob] = []
        self._bypass_toggles: list[ToggleButton] = []

        root.addLayout(self._build_band_grid())

    # ------------------------------------------------------------------ #
    # Layout
    # ------------------------------------------------------------------ #

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        title = QLabel("PEQ Settings")
        title.setObjectName("panelTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(title)

        row.addStretch(1)

        self._channel_bypass = ToggleButton()
        self._channel_bypass.setText("Bypass")
        self._channel_bypass.setMinimumWidth(72)
        self._channel_bypass.toggled.connect(self._on_channel_bypass_toggled)
        row.addWidget(self._channel_bypass)

        self._reset_btn = QPushButton("Reset")
        self._reset_btn.setObjectName("resetButton")
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        row.addWidget(self._reset_btn)

        return row

    def _build_band_grid(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        grid.setContentsMargins(0, 0, 0, 0)

        # Column 0 holds the row labels and must stay at the width of the
        # widest label.  Without explicit stretch factors QGridLayout splits
        # any extra width across *all* columns, which makes column 0 too
        # wide and pushes the right-aligned label inward.  Pin column 0 to
        # zero stretch and let the 7 band columns share the extra space.
        grid.setColumnStretch(0, 0)
        for col in range(1, NUM_BANDS + 1):
            grid.setColumnStretch(col, 1)

        # Column 0: row labels for the three knob rows.  The Type and
        # Bypass rows are unlabeled — the combo and the "Byp" button text
        # are self-explanatory.
        for row, text in ((2, "Freq"), (3, "Gain"), (4, "Q")):
            row_label = QLabel(text)
            row_label.setObjectName("paramLabel")
            row_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            grid.addWidget(row_label, row, 0)

        factory_bands = default_peq_bands()

        for band in range(NUM_BANDS):
            col = band + 1  # column 0 is reserved for row labels
            header = QLabel(f"B{band + 1}")
            header.setObjectName("paramLabel")
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(header, 0, col)

            type_combo = QComboBox()
            type_combo.addItems(PEQ_TYPE_NAMES)
            type_combo.setFixedWidth(84)
            type_combo.currentIndexChanged.connect(
                lambda _idx, b=band: self._on_type_changed(b)
            )
            grid.addWidget(type_combo, 1, col, alignment=Qt.AlignmentFlag.AlignHCenter)
            self._type_combos.append(type_combo)

            freq_knob = ParamKnob(
                minimum=0,
                maximum=300,
                default=factory_bands[band][1],
                formatter=_fmt_freq,
                parser=_parse_freq,
            )
            freq_knob.valueChanged.connect(lambda _v, b=band: self._on_band_changed(b))
            grid.addWidget(freq_knob, 2, col, alignment=Qt.AlignmentFlag.AlignHCenter)
            self._freq_knobs.append(freq_knob)

            gain_knob = ParamKnob(
                minimum=0,
                maximum=240,
                default=factory_bands[band][0],
                formatter=_fmt_gain,
                parser=_parse_gain,
            )
            gain_knob.valueChanged.connect(lambda _v, b=band: self._on_band_changed(b))
            grid.addWidget(gain_knob, 3, col, alignment=Qt.AlignmentFlag.AlignHCenter)
            self._gain_knobs.append(gain_knob)

            q_knob = ParamKnob(
                minimum=0,
                maximum=100,
                default=factory_bands[band][2],
                formatter=_fmt_q,
                parser=_parse_q,
            )
            q_knob.valueChanged.connect(lambda _v, b=band: self._on_band_changed(b))
            grid.addWidget(q_knob, 4, col, alignment=Qt.AlignmentFlag.AlignHCenter)
            self._q_knobs.append(q_knob)

            bypass = ToggleButton()
            bypass.setText("Byp")
            bypass.setMinimumWidth(48)
            bypass.toggled.connect(lambda _c, b=band: self._on_band_changed(b))
            grid.addWidget(bypass, 5, col, alignment=Qt.AlignmentFlag.AlignHCenter)
            self._bypass_toggles.append(bypass)

        return grid

    # ------------------------------------------------------------------ #
    # Signal plumbing
    # ------------------------------------------------------------------ #

    def _read_band(self, band: int) -> PEQBand:
        return PEQBand(
            gain_raw=self._gain_knobs[band].value(),
            freq_raw=self._freq_knobs[band].value(),
            q_raw=self._q_knobs[band].value(),
            filter_type=self._type_combos[band].currentIndex(),
            bypass=self._bypass_toggles[band].isChecked(),
        )

    def _all_bands(self) -> list[PEQBand]:
        return [self._read_band(b) for b in range(NUM_BANDS)]

    def is_peq_active(self) -> bool:
        """True if any band has non-zero gain and is not bypassed.

        Mirrors :attr:`OutputChannelState.peq_active` but reads from the
        live widget state — useful right after a knob/toggle edit before
        the canonical state has been written back.
        """
        if self._channel_bypass.isChecked():
            return False
        return any(
            self._gain_knobs[b].value() != 120
            and not self._bypass_toggles[b].isChecked()
            for b in range(NUM_BANDS)
        )

    def _on_band_changed(self, band: int) -> None:
        if self._suppress_emit:
            return
        b = self._read_band(band)
        self.peq_band_changed.emit(
            band, b.gain_raw, b.freq_raw, b.q_raw, b.filter_type, b.bypass
        )
        self._graph.set_bands(self._all_bands(), self._channel_bypass.isChecked())

    def _on_marker_dragged(self, band: int, freq_raw: int, gain_raw: int) -> None:
        """Apply a graph-marker drag to band ``band``'s freq/gain knobs.

        The graph emits raw frequency and gain as the user drags a
        marker; we push them into the knobs silently and then fire a
        single :meth:`_on_band_changed` so exactly one
        ``peq_band_changed`` is emitted (and the graph refreshed) per
        drag step — reusing the normal knob-edit path.

        Args:
            band: Band index 0–6.
            freq_raw: New raw frequency (0–300) from the x-axis.
            gain_raw: New raw gain (0–240); equals the band's current
                gain for filter types whose marker is pinned at 0 dB.
        """
        # Slave channels show the graph read-only; ignore drags there.
        if not self._freq_knobs[band].isEnabled():
            return
        self._freq_knobs[band].setValueSilently(freq_raw)
        self._gain_knobs[band].setValueSilently(gain_raw)
        self._on_band_changed(band)

    def _on_marker_q_changed(self, band: int, delta_raw: int) -> None:
        """Apply a wheel-over-marker Q change to band ``band``.

        The graph emits a signed raw-Q delta per wheel notch; we add it
        to the band's Q knob. ``setValue`` clamps to the knob's current
        per-filter-type range and its ``valueChanged`` drives
        :meth:`_on_band_changed`, so exactly one ``peq_band_changed`` is
        emitted (and the curve refreshed) per notch.

        Args:
            band: Band index 0–6.
            delta_raw: Signed change to add to the raw Q value.
        """
        knob = self._q_knobs[band]
        if not knob.isEnabled():  # slave-locked / read-only
            return
        knob.setValue(knob.value() + delta_raw)

    def _on_marker_bypass_toggled(self, band: int) -> None:
        """Flip band ``band``'s per-band bypass from a marker double-click.

        Toggling the bypass button fires its ``toggled`` signal, which is
        already wired to :meth:`_on_band_changed` for the atomic emit and
        graph refresh.

        Args:
            band: Band index 0–6.
        """
        toggle = self._bypass_toggles[band]
        if not toggle.isEnabled():  # slave-locked / read-only
            return
        toggle.setChecked(not toggle.isChecked())

    def _on_type_changed(self, band: int) -> None:
        # Refit the Q knob's range first; if the new range clamps the
        # current Q value, ParamKnob.setRange emits valueChanged → we
        # suppress that intermediate emit so only one peq_band_changed
        # fires for the user's combo edit (carrying the clamped Q).
        prev = self._suppress_emit
        self._suppress_emit = True
        try:
            self._apply_q_range(band)
        finally:
            self._suppress_emit = prev
        self._on_band_changed(band)

    def _apply_q_range(self, band: int) -> None:
        ftype = self._type_combos[band].currentIndex()
        q_max = _q_max_for_type(ftype)
        knob = self._q_knobs[band]
        if knob._maximum != q_max:
            knob.setRange(0, q_max)

    def _on_channel_bypass_toggled(self, checked: bool) -> None:
        if self._suppress_emit:
            return
        self.peq_channel_bypass_changed.emit(checked)
        self._graph.set_bands(self._all_bands(), checked)

    def _on_reset_clicked(self) -> None:
        if (
            QMessageBox.question(
                self,
                "Reset PEQ",
                "Reset PEQ to factory defaults for this channel?",
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.reset_requested.emit()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def reset_to_defaults(self) -> None:
        """Reset all 7 bands plus channel bypass to F00 factory values."""
        bands = [
            PEQBand(gain_raw=g, freq_raw=f, q_raw=q, filter_type=t, bypass=b)
            for g, f, q, t, b in default_peq_bands()
        ]
        self.set_bands_silently(bands, default_peq_channel_bypass())

    def set_band_silently(
        self,
        band: int,
        gain_raw: int,
        freq_raw: int,
        q_raw: int,
        filter_type: int,
        bypass: bool,
    ) -> None:
        """Apply device-driven state to one band without emitting signals.

        Sets the filter type *before* the Q value so the per-type
        Q range is in place when the Q knob clamps the incoming
        value — otherwise loading e.g. ``(LowShelf, Q=80)`` would
        briefly accept Q=80 then truncate on the next type change.

        Args:
            band: Band index 0–6.
            gain_raw: Raw gain (120 = 0 dB).
            freq_raw: Raw frequency value.
            q_raw: Raw Q value (clamped to the type's allowed range).
            filter_type: Filter-type index into ``PEQ_TYPE_NAMES``.
            bypass: Per-band bypass flag.
        """
        prev = self._suppress_emit
        self._suppress_emit = True
        try:
            self._gain_knobs[band].setValueSilently(gain_raw)
            self._freq_knobs[band].setValueSilently(freq_raw)
            # Set the type *first* so the Q knob's max is in place before we
            # clamp the incoming q_raw. Otherwise loading e.g. (LowShelf, Q=80)
            # would briefly accept Q=80 then truncate on the next type change.
            combo = self._type_combos[band]
            combo.blockSignals(True)
            combo.setCurrentIndex(
                max(0, min(len(PEQ_TYPE_NAMES) - 1, int(filter_type)))
            )
            combo.blockSignals(False)
            self._apply_q_range(band)
            self._q_knobs[band].setValueSilently(q_raw)
            byp = self._bypass_toggles[band]
            byp.blockSignals(True)
            byp.setChecked(bool(bypass))
            byp.blockSignals(False)
        finally:
            self._suppress_emit = prev

    def set_channel_bypass_silently(self, bypass: bool) -> None:
        """Update the channel-wide bypass toggle without emitting signals."""
        prev = self._suppress_emit
        self._suppress_emit = True
        try:
            self._channel_bypass.blockSignals(True)
            self._channel_bypass.setChecked(bool(bypass))
            self._channel_bypass.blockSignals(False)
        finally:
            self._suppress_emit = prev

    def set_bands_silently(self, bands: list[PEQBand], channel_bypass: bool) -> None:
        """Replace all 7 bands and the channel-bypass flag at once.

        Args:
            bands: Up to 7 ``PEQBand`` instances; missing entries
                are filled with neutral defaults (0 dB peak filter
                at the freq-knob midpoint, unbypassed).
            channel_bypass: New value for the per-channel PEQ
                bypass toggle.
        """
        prev = self._suppress_emit
        self._suppress_emit = True
        try:
            for band in range(NUM_BANDS):
                if band < len(bands):
                    b = bands[band]
                    self.set_band_silently(
                        band,
                        b.gain_raw,
                        b.freq_raw,
                        b.q_raw,
                        b.filter_type,
                        b.bypass,
                    )
                else:
                    self.set_band_silently(band, 120, 170, 16, 0, False)
            self.set_channel_bypass_silently(channel_bypass)
        finally:
            self._suppress_emit = prev
        self._graph.set_bands(self._all_bands(), channel_bypass)

    def set_crossover(self, xo: CrossoverData) -> None:
        """Forward the channel's crossover state into the shared graph."""
        self._graph.set_crossover(xo)

    def set_linked_slave(self, is_slave: bool, master_name: str = "") -> None:
        """Lock the panel when displaying a slave channel's PEQ.

        Disables every per-band control plus the channel-bypass
        toggle. The summed response graph stays visible (read-only by
        nature) so the user still sees what the slave is doing.

        Args:
            is_slave: True if the displayed channel is a slave in a
                link group.
            master_name: Display name of the master, used inside the
                banner text.
        """
        interactive: list[QWidget] = [self._channel_bypass, self._reset_btn]
        interactive.extend(self._type_combos)
        interactive.extend(self._freq_knobs)
        interactive.extend(self._gain_knobs)
        interactive.extend(self._q_knobs)
        interactive.extend(self._bypass_toggles)
        apply_link_state(self._link_banner, is_slave, master_name, interactive)
