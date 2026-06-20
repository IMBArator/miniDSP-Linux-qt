"""Combined frequency-response graph: crossover + PEQ summed on one curve.

Draws a single summed magnitude response from optional crossover
hi-pass / lo-pass filters and up to 7 parametric EQ bands, plus
numbered markers for each PEQ band and triangular markers for
active crossover cutoff frequencies. Optional faint "overlay" curves
(see :meth:`FreqResponseGraph.set_overlays`) show other output
channels' responses behind the active curve for comparison.

Biquad coefficients are computed locally from the raw protocol values
via the standard Audio EQ Cookbook (RBJ).  Crossover filters use
cascaded 2nd-order sections matching the miniDSP slope types
(Butterworth, Bessel, Linkwitz-Riley).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

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
    peq_raw_to_gain,
    peq_raw_to_q,
)

from ..model import PEQBand
from ..theme import theme_manager

_FS_HZ = 48_000.0  # device internal sample rate (per protocol manual)

_F_MIN = 10.0
_F_MAX = 25_000.0
_LOG_F_MIN = math.log10(_F_MIN)
_LOG_F_MAX = math.log10(_F_MAX)
_LOG_F_RANGE = _LOG_F_MAX - _LOG_F_MIN

_DB_MAX = 18.0
_DB_MIN = -18.0
_DB_RANGE = _DB_MAX - _DB_MIN

_OUTER_PADDING = 10
_OUTER_PADDING_LEFT = 4
_LABEL_GAP = 4
_X_LABEL_HEIGHT = 12
_Y_LABEL_WIDTH = 28

_MARGIN_TOP = _OUTER_PADDING
_MARGIN_RIGHT = _OUTER_PADDING
_MARGIN_BOTTOM = _OUTER_PADDING + _LABEL_GAP + _X_LABEL_HEIGHT
_MARGIN_LEFT = _OUTER_PADDING_LEFT + _LABEL_GAP + _Y_LABEL_WIDTH

_DB_GRID_LINES = (-18.0, -12.0, -6.0, 0.0, 6.0, 12.0, 18.0)
_DB_LABELS = (-18.0, -12.0, -6.0, 0.0, 6.0, 12.0, 18.0)
_FREQ_MARKERS = (20, 50, 100, 200, 500, 1_000, 2_000, 5_000, 10_000, 20_000)

_CURVE_WIDTH = 2.0
_NUM_SAMPLES = 256

# Filter types whose marker carries the band's gain on the y-axis. For every
# other type the static response is gain-independent, so the marker is pinned
# at 0 dB and dragging only moves it horizontally (frequency).
_GAIN_BEARING_TYPES = (PEQ_TYPE_PEAK, PEQ_TYPE_LOW_SHELF, PEQ_TYPE_HIGH_SHELF)

# Raw PEQ gain spans ±12 dB (raw 0–240) even though the plot y-axis spans ±18,
# so a drag must clamp dB to this before encoding or the marker would keep
# climbing into dead axis space above +12 dB.
_PEQ_GAIN_DB_LIMIT = 12.0

# PEQ markers are drawn with radius 7; allow a slightly larger grab radius so
# they are easy to catch (mirrors RoutingMatrix's NODE_RADIUS + 4 generosity).
_MARKER_RADIUS = 7.0
_MARKER_HIT_RADIUS = 11.0

# Raw-Q change per wheel notch over a marker; Ctrl gives a coarser step.
_Q_WHEEL_STEP = 1
_Q_WHEEL_STEP_CTRL = 5

# Bessel Q values per order (per-section Q for cascaded 2nd-order stages).
# Bessel poles are not Butterworth-equivalent; the Q values come from
# the Bessel polynomial coefficients normalised for each stage.
_BESSEL_Q = {
    2: [0.5774],
    3: [0.6910, 0.5774],
    4: [0.8055, 0.5219],
}

# Butterworth Q values per section (Q = 1 / (2 * cos(pole_angle))).
_BUTTERWORTH_Q = {
    2: [0.7071],
    3: [1.0000, 0.5774],
    4: [0.5412, 1.3066],
}


@dataclass
class CrossoverData:
    """Plain-data carrier for crossover values passed to the graph.

    Mirrors the fields of ``CrossoverState`` but is a separate type so
    widget code stays decoupled from the model layer; either dataclass
    can be converted to the other field-for-field. ``hipass_slope`` /
    ``lopass_slope`` of 0 means "no filter on this half".
    """

    hipass_freq: int = 0
    hipass_slope: int = 0
    lopass_freq: int = 0
    lopass_slope: int = 0


def _crossover_biquads(xo: CrossoverData) -> list[tuple[float, ...]]:
    """Return biquad coefficient tuples for the crossover filters."""
    sections: list[tuple[float, ...]] = []
    if xo.hipass_slope != 0:
        sections.extend(
            _slope_to_biquads(xo.hipass_freq, xo.hipass_slope, is_highpass=True)
        )
    if xo.lopass_slope != 0:
        sections.extend(
            _slope_to_biquads(xo.lopass_freq, xo.lopass_slope, is_highpass=False)
        )
    return sections


def _slope_to_biquads(
    freq_raw: int, slope: int, is_highpass: bool
) -> list[tuple[float, ...]]:
    from minidsp.protocol import (
        SLOPE_BL6,
        SLOPE_BL12,
        SLOPE_BL18,
        SLOPE_BL24,
        SLOPE_BW6,
        SLOPE_BW12,
        SLOPE_BW18,
        SLOPE_BW24,
        SLOPE_LR12,
        SLOPE_LR24,
    )

    f0 = max(1.0, freq_raw_to_hz(freq_raw))
    result: list[tuple[float, ...]] = []

    if slope == SLOPE_BW6:
        result.append(_first_order_coeffs(f0, is_highpass))
    elif slope == SLOPE_BL6:
        result.append(_first_order_coeffs(f0, is_highpass))
    elif slope == SLOPE_BW12:
        for q in _BUTTERWORTH_Q[2]:
            result.append(_second_order_coeffs(f0, q, is_highpass))
    elif slope == SLOPE_BL12:
        for q in _BESSEL_Q[2]:
            result.append(_second_order_coeffs(f0, q, is_highpass))
    elif slope == SLOPE_LR12:
        for _ in range(2):
            for q in _BUTTERWORTH_Q[2]:
                result.append(_second_order_coeffs(f0, q, is_highpass))
    elif slope == SLOPE_BW18:
        for q in _BUTTERWORTH_Q[3]:
            result.append(_second_order_coeffs(f0, q, is_highpass))
    elif slope == SLOPE_BL18:
        for q in _BESSEL_Q[3]:
            result.append(_second_order_coeffs(f0, q, is_highpass))
    elif slope == SLOPE_BW24:
        for q in _BUTTERWORTH_Q[4]:
            result.append(_second_order_coeffs(f0, q, is_highpass))
    elif slope == SLOPE_BL24:
        for q in _BESSEL_Q[4]:
            result.append(_second_order_coeffs(f0, q, is_highpass))
    elif slope == SLOPE_LR24:
        for _ in range(2):
            for q in _BUTTERWORTH_Q[4]:
                result.append(_second_order_coeffs(f0, q, is_highpass))

    return result


def _first_order_coeffs(f0: float, is_highpass: bool) -> tuple[float, ...]:
    omega0 = 2.0 * math.pi * f0 / _FS_HZ
    tan_half = math.tan(omega0 / 2.0)
    a1 = (tan_half - 1.0) / (tan_half + 1.0)
    if is_highpass:
        b0 = 1.0 / (tan_half + 1.0)
        b1 = -b0
    else:
        b0 = tan_half / (tan_half + 1.0)
        b1 = b0
    return (b0, b1, 0.0, 1.0, a1, 0.0)


def _second_order_coeffs(f0: float, q: float, is_highpass: bool) -> tuple[float, ...]:
    omega0 = 2.0 * math.pi * f0 / _FS_HZ
    cos_w0 = math.cos(omega0)
    sin_w0 = math.sin(omega0)
    alpha = sin_w0 / (2.0 * q)

    if is_highpass:
        b0 = (1.0 + cos_w0) / 2.0
        b1 = -(1.0 + cos_w0)
        b2 = (1.0 + cos_w0) / 2.0
    else:
        b0 = (1.0 - cos_w0) / 2.0
        b1 = 1.0 - cos_w0
        b2 = (1.0 - cos_w0) / 2.0

    a0 = 1.0 + alpha
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha

    return (b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0)


class FreqResponseGraph(QWidget):
    """Combined crossover + PEQ frequency-response graph for one channel.

    Used by both the PEQ panel and the crossover panel. The summed
    magnitude response includes every PEQ band (skipping bypassed
    ones) cascaded with the hi-pass and lo-pass biquad sections of
    the channel's crossover. The active curve colour follows the
    panel feature (``"peq"`` for the PEQ panel, ``"xover"`` for the
    crossover panel) so the two views are visually distinct.

    PEQ bands appear as numbered circular markers; crossover corner
    frequencies appear as triangular markers.

    When built with ``feature="peq"`` the PEQ markers are draggable:
    grabbing one and moving it emits :attr:`band_dragged` with the new
    raw frequency (and gain, for gain-bearing filter types). The host
    panel owns the canonical band state, so it applies the change to
    its knobs and feeds the updated bands back via :meth:`set_bands`.

    When built with ``feature="xover"`` the crossover markers (HP/LP
    triangles) are draggable the same way: dragging one horizontally
    sets that filter's cutoff frequency, scrolling the wheel over it
    steps the slope one notch, and double-clicking toggles bypass
    (which works on dim bypassed markers too, so they can be
    re-enabled). The host panel owns the canonical state and applies
    each gesture via :meth:`set_crossover` / its own control setters.

    Signals:
        band_dragged (int, int, int): ``(band_index, freq_raw,
            gain_raw)`` emitted continuously while a marker is dragged.
            For non-gain-bearing filter types ``gain_raw`` is the band's
            unchanged current value.
        band_q_changed (int, int): ``(band_index, delta_raw)`` emitted
            when the wheel is scrolled over an active marker; the host
            applies the signed raw-Q delta to the band's Q control.
        band_bypass_toggled (int): ``(band_index)`` emitted on a
            double-click of a marker (incl. bypassed ones) so the host
            flips that band's per-band bypass.
        xover_freq_dragged (str, int): ``(which, freq_raw)`` emitted
            continuously while an HP/LP marker is dragged. ``which`` is
            ``"hp"`` or ``"lp"``. The host applies the new cutoff to the
            matching freq knob.
        xover_slope_stepped (str, int): ``(which, delta_notches)``
            emitted when the wheel is scrolled over an active marker.
            The host applies the signed delta to the matching slope
            combo, clamped to its range.
        xover_bypass_toggled (str): ``(which)`` emitted on a
            double-click of a marker (incl. dim bypassed ones) so the
            host flips that filter's bypass toggle.
    """

    band_dragged = Signal(int, int, int)
    band_q_changed = Signal(int, int)  # (band_index, delta_raw) — wheel over marker
    band_bypass_toggled = Signal(int)  # (band_index) — double-click marker

    xover_freq_dragged = Signal(str, int)  # (which, freq_raw) — drag marker
    xover_slope_stepped = Signal(str, int)  # (which, delta_notches) — wheel over marker
    xover_bypass_toggled = Signal(str)  # (which) — double-click marker

    def __init__(self, parent: QWidget | None = None, *, feature: str = "peq") -> None:
        """Build an empty graph with the given feature accent.

        Args:
            parent: Qt parent widget.
            feature: ``"peq"`` or ``"xover"`` — picks the curve
                palette and gates marker dragging. PEQ graphs respond
                to the numbered PEQ markers; xover graphs respond to
                the HP/LP triangles.
        """
        super().__init__(parent)
        self._feature = feature
        self._bands: list[PEQBand] = []
        self._channel_bypass: bool = False
        self._crossover: CrossoverData = CrossoverData()
        # "Show other outputs" overlays: each entry is
        # (output_index, bands, channel_bypass, crossover). Drawn behind the
        # active curve in the per-output ``theme.graph_overlay`` colour.
        self._overlays: list[tuple[int, list[PEQBand], bool, CrossoverData]] = []
        self._drag_band: int = -1  # index of the marker being dragged, or -1
        self._drag_xover: str | None = None  # "hp"/"lp" being dragged, or None
        self.setMinimumHeight(160)
        # Hover-cursor feedback needs move events even when no button is held.
        if feature in ("peq", "xover"):
            self.setMouseTracking(True)
        theme_manager.themeChanged.connect(self.update)

    def set_bands(self, bands: list[PEQBand], channel_bypass: bool) -> None:
        """Replace the PEQ band list and repaint.

        Args:
            bands: Up to 7 ``PEQBand`` instances; order drives the
                numbered marker labels.
            channel_bypass: When True the PEQ contribution is hidden
                from the curve and the bypassed-marker palette is
                used for the band markers.
        """
        self._bands = list(bands)
        self._channel_bypass = bool(channel_bypass)
        self.update()

    def set_crossover(self, xo: CrossoverData) -> None:
        """Replace the crossover state and repaint."""
        self._crossover = xo
        self.update()

    def set_data(
        self,
        bands: list[PEQBand],
        channel_bypass: bool,
        xo: CrossoverData,
    ) -> None:
        """Replace bands and crossover at once with a single repaint.

        Same args as ``set_bands`` plus ``set_crossover``; use this
        when both inputs change together (e.g. switching the panel
        to a different channel) to avoid a flicker between the two
        single-setter updates.
        """
        self._bands = list(bands)
        self._channel_bypass = bool(channel_bypass)
        self._crossover = xo
        self.update()

    def set_overlays(
        self,
        overlays: list[tuple[int, list[PEQBand], bool, CrossoverData]],
    ) -> None:
        """Replace the set of "other output" overlay curves and repaint.

        These are sibling output channels shown faintly behind the active
        curve for comparison; they carry no markers and never affect the
        active curve. Pass an empty list to clear all overlays.

        Args:
            overlays: One entry per curve to draw, each a tuple of
                ``(output_index, bands, channel_bypass, crossover)``. The
                ``output_index`` (0–3) selects the overlay colour from
                ``theme.graph_overlay`` so a given output keeps a stable
                colour regardless of which channel is displayed. ``bands``,
                ``channel_bypass`` and ``crossover`` are that output's PEQ
                and crossover state, rendered with the same math as the
                active curve.
        """
        self._overlays = list(overlays)
        self.update()

    def _plot_rect(self) -> QRectF:
        return QRectF(
            _MARGIN_LEFT,
            _MARGIN_TOP,
            self.width() - _MARGIN_LEFT - _MARGIN_RIGHT,
            self.height() - _MARGIN_TOP - _MARGIN_BOTTOM,
        )

    def _hz_to_x(self, hz: float) -> float:
        r = self._plot_rect()
        frac = (math.log10(max(_F_MIN, min(_F_MAX, hz))) - _LOG_F_MIN) / _LOG_F_RANGE
        return r.left() + frac * r.width()

    def _db_to_y(self, db: float) -> float:
        r = self._plot_rect()
        frac = (db - _DB_MIN) / _DB_RANGE
        return r.bottom() - frac * r.height()

    def _x_to_hz(self, x: float) -> float:
        """Inverse of :meth:`_hz_to_x`; clamps ``x`` to the plot rect."""
        r = self._plot_rect()
        x = max(r.left(), min(r.right(), x))
        frac = (x - r.left()) / r.width() if r.width() else 0.0
        return 10.0 ** (_LOG_F_MIN + frac * _LOG_F_RANGE)

    def _y_to_db(self, y: float) -> float:
        """Inverse of :meth:`_db_to_y`; clamps ``y`` to the plot rect."""
        r = self._plot_rect()
        y = max(r.top(), min(r.bottom(), y))
        frac = (r.bottom() - y) / r.height() if r.height() else 0.0
        return _DB_MIN + frac * _DB_RANGE

    @staticmethod
    def _marker_y_db(band: PEQBand) -> float:
        """dB position of ``band``'s marker on the y-axis.

        Gain-bearing types sit at their (axis-clamped) gain; every other
        type sits at 0 dB. Single source of truth shared by the painter
        and the hit-test so they never disagree.
        """
        if band.filter_type in _GAIN_BEARING_TYPES:
            return max(_DB_MIN, min(_DB_MAX, peq_raw_to_gain(band.gain_raw)))
        return 0.0

    def _curve_color(self, theme) -> tuple[QColor, QColor]:
        """Return (active, bypassed) curve colours for the graph's feature."""
        if self._feature == "xover":
            return theme.graph_curve_xover, theme.graph_curve_xover_bypassed
        return theme.graph_curve_peq, theme.graph_curve_peq_bypassed

    def paintEvent(self, event) -> None:
        p = QPainter()
        if not p.begin(self):
            return
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()
            rect = self._plot_rect()
            theme = theme_manager.current

            p.fillRect(0, 0, w, h, theme.graph_bg)
            self._draw_grid(p, rect)
            self._draw_axis_labels(p, rect)
            self._draw_zero_line(p, rect)
            self._draw_overlays(p, rect)
            self._draw_curve(p, rect)
            self._draw_xover_markers(p, rect)
            self._draw_peq_markers(p, rect)

            p.setPen(QPen(theme.graph_border, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect)
        finally:
            p.end()

    def _draw_grid(self, p: QPainter, rect: QRectF) -> None:
        pen = QPen(theme_manager.current.graph_grid, 1, Qt.PenStyle.DotLine)
        p.setPen(pen)
        for f in _FREQ_MARKERS:
            x = self._hz_to_x(f)
            p.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
        for db in _DB_GRID_LINES:
            y = self._db_to_y(db)
            p.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))

    def _draw_zero_line(self, p: QPainter, rect: QRectF) -> None:
        pen = QPen(theme_manager.current.graph_ref, 1, Qt.PenStyle.DashLine)
        p.setPen(pen)
        y = self._db_to_y(0.0)
        p.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))

    def _draw_axis_labels(self, p: QPainter, rect: QRectF) -> None:
        font = QFont(p.font())
        font.setPixelSize(10)
        p.setFont(font)
        p.setPen(QPen(theme_manager.current.graph_label))
        for f in _FREQ_MARKERS:
            x = self._hz_to_x(f)
            label = f"{int(f)}" if f < 1000 else f"{int(f / 1000)}k"
            p.drawText(
                int(x) - _Y_LABEL_WIDTH // 2,
                int(rect.bottom()) + _LABEL_GAP,
                _Y_LABEL_WIDTH,
                _X_LABEL_HEIGHT,
                Qt.AlignmentFlag.AlignCenter,
                label,
            )
        for db in _DB_LABELS:
            y = self._db_to_y(db)
            label = f"{db:+.0f}" if db != 0 else "0"
            p.drawText(
                int(rect.left()) - (_LABEL_GAP + _Y_LABEL_WIDTH),
                int(y) - _X_LABEL_HEIGHT // 2,
                _Y_LABEL_WIDTH,
                _X_LABEL_HEIGHT,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )

    @staticmethod
    def _response_coeffs(
        bands: list[PEQBand],
        channel_bypass: bool,
        crossover: CrossoverData,
    ) -> list[tuple[float, ...]]:
        """Collect the cascaded biquad sections for one channel's response.

        Mirrors how the active curve is built: each non-bypassed PEQ band
        contributes a section (unless the whole channel is bypassed), plus
        the crossover hi-/lo-pass sections.

        Args:
            bands: The channel's PEQ bands.
            channel_bypass: When True the PEQ bands are skipped entirely.
            crossover: The channel's crossover state.

        Returns:
            A list of biquad coefficient tuples (possibly empty).
        """
        coeffs: list[tuple[float, ...]] = []
        if not channel_bypass:
            for b in bands:
                if not b.bypass:
                    coeffs.append(_biquad_coeffs_from_band(b))
        coeffs.extend(_crossover_biquads(crossover))
        return coeffs

    def _response_polyline(
        self,
        bands: list[PEQBand],
        channel_bypass: bool,
        crossover: CrossoverData,
        rect: QRectF,
    ) -> QPolygonF | None:
        """Sample one channel's magnitude response into a screen-space polyline.

        Shared by the active curve and the overlay curves so they stay
        pixel-identical. Returns ``None`` when the channel has no active
        sections (fully bypassed / flat), letting the caller decide how to
        render — the active curve draws a flat reference line, overlays skip.

        Args:
            bands: The channel's PEQ bands.
            channel_bypass: Channel-wide PEQ bypass flag.
            crossover: The channel's crossover state.
            rect: The plot rectangle to map samples into.

        Returns:
            A :class:`QPolygonF` of ``_NUM_SAMPLES`` points, or ``None`` if
            the response is flat (no sections).
        """
        coeffs = self._response_coeffs(bands, channel_bypass, crossover)
        if not coeffs:
            return None
        poly = QPolygonF()
        for i in range(_NUM_SAMPLES):
            frac = i / (_NUM_SAMPLES - 1)
            db = 0.0
            omega = (
                2.0 * math.pi * (10.0 ** (_LOG_F_MIN + frac * _LOG_F_RANGE)) / _FS_HZ
            )
            for c in coeffs:
                db += _biquad_magnitude_db(c, omega)
            x = rect.left() + frac * rect.width()
            y = self._db_to_y(db)
            poly.append(QPointF(x, y))
        return poly

    def _draw_overlays(self, p: QPainter, rect: QRectF) -> None:
        """Draw the "other output" overlay curves behind the active curve.

        Each overlay is rendered in its per-output ``theme.graph_overlay``
        colour. Flat (fully bypassed) overlays are skipped so they don't
        clutter the plot with a redundant 0 dB line.
        """
        if not self._overlays:
            return
        theme = theme_manager.current
        p.save()
        p.setClipRect(rect)
        for output_index, bands, channel_bypass, crossover in self._overlays:
            poly = self._response_polyline(bands, channel_bypass, crossover, rect)
            if poly is None:
                continue
            pen = QPen(theme.graph_overlay[output_index % 4], _CURVE_WIDTH)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(poly)
        p.restore()

    def _draw_curve(self, p: QPainter, rect: QRectF) -> None:
        theme = theme_manager.current
        curve_color, bypassed_color = self._curve_color(theme)
        poly = self._response_polyline(
            self._bands, self._channel_bypass, self._crossover, rect
        )
        if poly is None:
            # No active sections — draw a flat 0 dB reference in the
            # bypassed colour so the user still sees the (flat) response.
            pen = QPen(bypassed_color, _CURVE_WIDTH)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            y = self._db_to_y(0.0)
            p.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            return

        p.save()
        p.setClipRect(rect)
        pen = QPen(curve_color, _CURVE_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(poly)
        p.restore()

    def _draw_xover_markers(self, p: QPainter, rect: QRectF) -> None:
        xo = self._crossover
        theme = theme_manager.current
        for freq_raw, slope, label in [
            (xo.hipass_freq, xo.hipass_slope, "HP"),
            (xo.lopass_freq, xo.lopass_slope, "LP"),
        ]:
            f_hz = freq_raw_to_hz(freq_raw)
            if f_hz <= 0:
                continue
            x = self._hz_to_x(f_hz)
            if not (rect.left() - 1 <= x <= rect.right() + 1):
                continue
            y = self._db_to_y(0.0)

            # ``slope == 0`` means bypassed (no curve contribution), but the
            # cutoff frequency is still retained by the device — draw a dim
            # marker so the user can see / re-grab it (e.g. double-click to
            # re-enable). Active halves keep the bright xover accent.
            tri_color = (
                theme.graph_marker_bypassed if slope == 0 else theme.graph_curve_xover
            )
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tri_color)
            tri = QPolygonF()
            tri.append(QPointF(x, y - 8))
            tri.append(QPointF(x - 6, y + 4))
            tri.append(QPointF(x + 6, y + 4))
            p.drawPolygon(tri)

            font = QFont(p.font())
            font.setPixelSize(8)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QPen(theme.graph_xover_label_text))
            p.drawText(
                QRectF(x - 12, y + 4, 24, 12),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )

    def _draw_peq_markers(self, p: QPainter, rect: QRectF) -> None:
        font = QFont(p.font())
        font.setPixelSize(9)
        font.setBold(True)
        p.setFont(font)
        theme = theme_manager.current

        for idx, band in enumerate(self._bands):
            f_hz = freq_raw_to_hz(band.freq_raw)
            if f_hz <= 0:
                continue
            x = self._hz_to_x(f_hz)
            if not (rect.left() - 1 <= x <= rect.right() + 1):
                continue
            y = self._db_to_y(self._marker_y_db(band))

            color = (
                theme.graph_marker_bypassed
                if (band.bypass or self._channel_bypass)
                else theme.graph_curve_peq
            )
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(QPointF(x, y), _MARKER_RADIUS, _MARKER_RADIUS)

            p.setPen(QPen(theme.graph_marker_text))
            p.drawText(
                QRectF(x - 8, y - 7, 16, 14),
                Qt.AlignmentFlag.AlignCenter,
                str(idx + 1),
            )

    # ------------------------------------------------------------------ #
    # PEQ marker dragging (feature == "peq" only)
    # ------------------------------------------------------------------ #

    def _hit_band(self, pos: QPointF, *, include_bypassed: bool = False) -> int:
        """Return the index of the PEQ marker nearest ``pos``.

        Considers PEQ markers only when this graph hosts the PEQ
        feature. When markers overlap the nearest centre wins; ties
        resolve to the higher index, which is the one drawn on top.
        Returns ``-1`` when nothing is in reach.

        Args:
            pos: Cursor position in widget coordinates.
            include_bypassed: When True, per-band bypassed markers are
                also hittable (used by double-click-to-toggle so a dim
                marker can be re-enabled). Channel-wide bypass always
                blocks. Drag/wheel pass False, so they tune active
                markers only.

        Returns:
            Band index in range ``0..len(bands)-1`` or ``-1``.
        """
        if self._feature != "peq" or self._channel_bypass:
            return -1
        rect = self._plot_rect()
        best = -1
        best_dist = _MARKER_HIT_RADIUS
        for idx, band in enumerate(self._bands):
            if band.bypass and not include_bypassed:
                continue
            f_hz = freq_raw_to_hz(band.freq_raw)
            if f_hz <= 0:
                continue
            x = self._hz_to_x(f_hz)
            if not (rect.left() - 1 <= x <= rect.right() + 1):
                continue
            y = self._db_to_y(self._marker_y_db(band))
            dist = QLineF(pos, QPointF(x, y)).length()
            if dist <= best_dist:  # "<=" so later (topmost) markers win ties
                best_dist = dist
                best = idx
        return best

    def _hit_xover(
        self, pos: QPointF, *, include_bypassed: bool = False
    ) -> str | None:
        """Return the HP/LP marker nearest ``pos``, or None.

        Crossover markers are considered only when this graph hosts the
        xover feature. The HP and LP triangles share a single 0 dB
        y-coordinate, so ties resolve to whichever half was checked
        later in the loop (LP) — in practice they sit at different
        frequencies and never overlap.

        Args:
            pos: Cursor position in widget coordinates.
            include_bypassed: When True, dim bypassed markers
                (``slope == 0``) are also hittable — used by
                double-click-to-toggle so a bypassed filter can be
                re-enabled. Drag/wheel pass False so they tune active
                halves only.

        Returns:
            ``"hp"`` / ``"lp"`` or ``None``.
        """
        if self._feature != "xover":
            return None
        rect = self._plot_rect()
        xo = self._crossover
        best: str | None = None
        best_dist = _MARKER_HIT_RADIUS
        for which, freq_raw, slope in (
            ("hp", xo.hipass_freq, xo.hipass_slope),
            ("lp", xo.lopass_freq, xo.lopass_slope),
        ):
            if slope == 0 and not include_bypassed:
                continue
            f_hz = freq_raw_to_hz(freq_raw)
            if f_hz <= 0:
                continue
            x = self._hz_to_x(f_hz)
            if not (rect.left() - 1 <= x <= rect.right() + 1):
                continue
            y = self._db_to_y(0.0)
            dist = QLineF(pos, QPointF(x, y)).length()
            if dist <= best_dist:  # "<=" so LP wins a tie (matches draw order)
                best_dist = dist
                best = which
        return best

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        if self._feature == "peq":
            hit = self._hit_band(QPointF(event.position()))
            if hit >= 0:
                self._drag_band = hit
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
        elif self._feature == "xover":
            which = self._hit_xover(QPointF(event.position()))
            if which is not None:
                self._drag_xover = which
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = QPointF(event.position())
        if self._feature == "peq":
            if self._drag_band >= 0:
                self._apply_drag(self._drag_band, pos)
                event.accept()
                return
            # Not dragging: offer a grab cursor when hovering a draggable marker.
            over = self._hit_band(pos) >= 0
            self.setCursor(
                Qt.CursorShape.OpenHandCursor if over else Qt.CursorShape.ArrowCursor
            )
            super().mouseMoveEvent(event)
            return
        if self._feature == "xover":
            if self._drag_xover is not None:
                self._apply_xover_drag(self._drag_xover, pos)
                event.accept()
                return
            over = self._hit_xover(pos) is not None
            self.setCursor(
                Qt.CursorShape.OpenHandCursor if over else Qt.CursorShape.ArrowCursor
            )
            super().mouseMoveEvent(event)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._drag_band >= 0:
                self._drag_band = -1
                over = self._hit_band(QPointF(event.position())) >= 0
                self.setCursor(
                    Qt.CursorShape.OpenHandCursor
                    if over
                    else Qt.CursorShape.ArrowCursor
                )
                event.accept()
                return
            if self._drag_xover is not None:
                self._drag_xover = None
                over = self._hit_xover(QPointF(event.position())) is not None
                self.setCursor(
                    Qt.CursorShape.OpenHandCursor
                    if over
                    else Qt.CursorShape.ArrowCursor
                )
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        if self._drag_band < 0 and self._drag_xover is None:
            self.unsetCursor()
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:
        if self._feature == "peq":
            notches = event.angleDelta().y() // 120
            if not notches:
                super().wheelEvent(event)
                return
            idx = self._hit_band(QPointF(event.position()))
            if idx < 0:
                # Not over an active marker — leave the event for anyone above us.
                super().wheelEvent(event)
                return
            fast = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            delta = notches * (_Q_WHEEL_STEP_CTRL if fast else _Q_WHEEL_STEP)
            self.band_q_changed.emit(idx, delta)
            event.accept()
            return
        if self._feature == "xover":
            notches = event.angleDelta().y() // 120
            if not notches:
                super().wheelEvent(event)
                return
            which = self._hit_xover(QPointF(event.position()))
            if which is None:
                # Not over an active marker — leave the event for anyone above us.
                super().wheelEvent(event)
                return
            self.xover_slope_stepped.emit(which, notches)
            event.accept()
            return
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        if self._feature == "peq":
            # include_bypassed so a dim (bypassed) marker can be re-enabled.
            idx = self._hit_band(QPointF(event.position()), include_bypassed=True)
            if idx >= 0:
                self.band_bypass_toggled.emit(idx)
                event.accept()
                return
        elif self._feature == "xover":
            # include_bypassed so a dim (bypassed) marker can be re-enabled.
            which = self._hit_xover(QPointF(event.position()), include_bypassed=True)
            if which is not None:
                self.xover_bypass_toggled.emit(which)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def _apply_drag(self, idx: int, pos: QPointF) -> None:
        """Map ``pos`` to raw freq/gain for band ``idx`` and emit the change.

        The band's local copy is updated for instant visual feedback; the
        host panel re-feeds canonical state via :meth:`set_bands` when it
        handles the emitted :attr:`band_dragged`.
        """
        band = self._bands[idx]
        freq_raw = freq_hz_to_raw(self._x_to_hz(pos.x()))
        if band.filter_type in _GAIN_BEARING_TYPES:
            db = max(
                -_PEQ_GAIN_DB_LIMIT, min(_PEQ_GAIN_DB_LIMIT, self._y_to_db(pos.y()))
            )
            gain_raw = peq_gain_to_raw(db)
        else:
            gain_raw = band.gain_raw  # pinned at 0 dB; preserve existing gain
        self._bands[idx] = PEQBand(
            gain_raw=gain_raw,
            freq_raw=freq_raw,
            q_raw=band.q_raw,
            filter_type=band.filter_type,
            bypass=band.bypass,
        )
        self.update()
        self.band_dragged.emit(idx, freq_raw, gain_raw)

    def _apply_xover_drag(self, which: str, pos: QPointF) -> None:
        """Map ``pos.x()`` to a raw cutoff for half ``which`` and emit the change.

        Crossover markers sit at 0 dB, so only the horizontal position
        is mapped — vertical movement is ignored. The local
        ``_crossover`` copy is rebuilt with the new cutoff for instant
        visual feedback; the host panel re-feeds canonical state via
        :meth:`set_crossover` when it handles the emitted
        :attr:`xover_freq_dragged`.

        Args:
            which: ``"hp"`` or ``"lp"`` — which filter's cutoff to set.
            pos: Cursor position in widget coordinates; ``pos.x()`` is
                inverse-mapped through :meth:`_x_to_hz` and clamped to
                the plot rect.
        """
        freq = freq_hz_to_raw(self._x_to_hz(pos.x()))
        xo = self._crossover
        if which == "hp":
            self._crossover = CrossoverData(
                hipass_freq=freq,
                hipass_slope=xo.hipass_slope,
                lopass_freq=xo.lopass_freq,
                lopass_slope=xo.lopass_slope,
            )
        else:
            self._crossover = CrossoverData(
                hipass_freq=xo.hipass_freq,
                hipass_slope=xo.hipass_slope,
                lopass_freq=freq,
                lopass_slope=xo.lopass_slope,
            )
        self.update()
        self.xover_freq_dragged.emit(which, freq)


def _biquad_coeffs_from_band(band: PEQBand) -> tuple[float, ...]:
    f0 = freq_raw_to_hz(band.freq_raw)
    if f0 <= 0:
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    f0 = max(1.0, min(_FS_HZ * 0.49, f0))
    q = max(0.1, peq_raw_to_q(band.q_raw))
    gain_db = peq_raw_to_gain(band.gain_raw)
    return _peq_coeffs(band.filter_type, f0, q, gain_db)


def _peq_coeffs(
    filter_type: int, f0: float, q: float, gain_db: float
) -> tuple[float, ...]:
    omega0 = 2.0 * math.pi * f0 / _FS_HZ
    cos_w0 = math.cos(omega0)
    sin_w0 = math.sin(omega0)
    alpha = sin_w0 / (2.0 * q)

    if filter_type == PEQ_TYPE_PEAK:
        a_amp = 10.0 ** (gain_db / 40.0)
        b0 = 1 + alpha * a_amp
        b1 = -2 * cos_w0
        b2 = 1 - alpha * a_amp
        a0 = 1 + alpha / a_amp
        a1 = -2 * cos_w0
        a2 = 1 - alpha / a_amp
    elif filter_type == PEQ_TYPE_LOW_SHELF:
        a_amp = 10.0 ** (gain_db / 40.0)
        sqrt_a = math.sqrt(a_amp)
        b0 = a_amp * ((a_amp + 1) - (a_amp - 1) * cos_w0 + 2 * sqrt_a * alpha)
        b1 = 2 * a_amp * ((a_amp - 1) - (a_amp + 1) * cos_w0)
        b2 = a_amp * ((a_amp + 1) - (a_amp - 1) * cos_w0 - 2 * sqrt_a * alpha)
        a0 = (a_amp + 1) + (a_amp - 1) * cos_w0 + 2 * sqrt_a * alpha
        a1 = -2 * ((a_amp - 1) + (a_amp + 1) * cos_w0)
        a2 = (a_amp + 1) + (a_amp - 1) * cos_w0 - 2 * sqrt_a * alpha
    elif filter_type == PEQ_TYPE_HIGH_SHELF:
        a_amp = 10.0 ** (gain_db / 40.0)
        sqrt_a = math.sqrt(a_amp)
        b0 = a_amp * ((a_amp + 1) + (a_amp - 1) * cos_w0 + 2 * sqrt_a * alpha)
        b1 = -2 * a_amp * ((a_amp - 1) + (a_amp + 1) * cos_w0)
        b2 = a_amp * ((a_amp + 1) + (a_amp - 1) * cos_w0 - 2 * sqrt_a * alpha)
        a0 = (a_amp + 1) - (a_amp - 1) * cos_w0 + 2 * sqrt_a * alpha
        a1 = 2 * ((a_amp - 1) - (a_amp + 1) * cos_w0)
        a2 = (a_amp + 1) - (a_amp - 1) * cos_w0 - 2 * sqrt_a * alpha
    elif filter_type == PEQ_TYPE_LOW_PASS:
        b0 = (1 - cos_w0) / 2
        b1 = 1 - cos_w0
        b2 = (1 - cos_w0) / 2
        a0 = 1 + alpha
        a1 = -2 * cos_w0
        a2 = 1 - alpha
    elif filter_type == PEQ_TYPE_HIGH_PASS:
        b0 = (1 + cos_w0) / 2
        b1 = -(1 + cos_w0)
        b2 = (1 + cos_w0) / 2
        a0 = 1 + alpha
        a1 = -2 * cos_w0
        a2 = 1 - alpha
    elif filter_type == PEQ_TYPE_ALLPASS2:
        b0 = 1 - alpha
        b1 = -2 * cos_w0
        b2 = 1 + alpha
        a0 = 1 + alpha
        a1 = -2 * cos_w0
        a2 = 1 - alpha
    elif filter_type == PEQ_TYPE_ALLPASS1:
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    else:
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    return (b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0)


def _biquad_magnitude_db(coeffs: tuple[float, ...], omega: float) -> float:
    b0, b1, b2, a0, a1, a2 = coeffs
    cos_w = math.cos(omega)
    sin_w = math.sin(omega)
    cos_2w = math.cos(2 * omega)
    sin_2w = math.sin(2 * omega)

    num_re = b0 + b1 * cos_w + b2 * cos_2w
    num_im = -(b1 * sin_w + b2 * sin_2w)
    den_re = a0 + a1 * cos_w + a2 * cos_2w
    den_im = -(a1 * sin_w + a2 * sin_2w)

    num_sq = num_re * num_re + num_im * num_im
    den_sq = den_re * den_re + den_im * den_im
    if den_sq <= 0 or num_sq <= 0:
        return 0.0
    return 10.0 * math.log10(num_sq / den_sq)
