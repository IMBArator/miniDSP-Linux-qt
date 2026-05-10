"""Combined frequency-response graph: crossover + PEQ summed on one curve.

Draws a single summed magnitude response from optional crossover
hi-pass / lo-pass filters and up to 7 parametric EQ bands, plus
numbered markers for each PEQ band and triangular markers for
active crossover cutoff frequencies.

Biquad coefficients are computed locally from the raw protocol values
via the standard Audio EQ Cookbook (RBJ).  Crossover filters use
cascaded 2nd-order sections matching the miniDSP slope types
(Butterworth, Bessel, Linkwitz-Riley).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from minidsp.protocol import (
    PEQ_TYPE_ALLPASS1,
    PEQ_TYPE_ALLPASS2,
    PEQ_TYPE_HIGH_PASS,
    PEQ_TYPE_HIGH_SHELF,
    PEQ_TYPE_LOW_PASS,
    PEQ_TYPE_LOW_SHELF,
    PEQ_TYPE_PEAK,
    freq_raw_to_hz,
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
    hipass_freq: int = 0
    hipass_slope: int = 0
    lopass_freq: int = 0
    lopass_slope: int = 0


def _crossover_biquads(xo: CrossoverData) -> list[tuple[float, ...]]:
    """Return biquad coefficient tuples for the crossover filters."""
    sections: list[tuple[float, ...]] = []
    if xo.hipass_slope != 0:
        sections.extend(_slope_to_biquads(xo.hipass_freq, xo.hipass_slope, is_highpass=True))
    if xo.lopass_slope != 0:
        sections.extend(_slope_to_biquads(xo.lopass_freq, xo.lopass_slope, is_highpass=False))
    return sections


def _slope_to_biquads(freq_raw: int, slope: int, is_highpass: bool) -> list[tuple[float, ...]]:
    from minidsp.protocol import (
        SLOPE_BL6, SLOPE_BL12, SLOPE_BL18, SLOPE_BL24,
        SLOPE_BW6, SLOPE_BW12, SLOPE_BW18, SLOPE_BW24,
        SLOPE_LR12, SLOPE_LR24,
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
    """Combined crossover + PEQ frequency-response graph for one channel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bands: list[PEQBand] = []
        self._channel_bypass: bool = False
        self._crossover: CrossoverData = CrossoverData()
        self.setMinimumHeight(160)
        theme_manager.themeChanged.connect(self.update)

    def set_bands(self, bands: list[PEQBand], channel_bypass: bool) -> None:
        self._bands = list(bands)
        self._channel_bypass = bool(channel_bypass)
        self.update()

    def set_crossover(self, xo: CrossoverData) -> None:
        self._crossover = xo
        self.update()

    def set_data(
        self,
        bands: list[PEQBand],
        channel_bypass: bool,
        xo: CrossoverData,
    ) -> None:
        self._bands = list(bands)
        self._channel_bypass = bool(channel_bypass)
        self._crossover = xo
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

    def _draw_curve(self, p: QPainter, rect: QRectF) -> None:
        theme = theme_manager.current
        if self._channel_bypass and self._crossover.hipass_slope == 0 and self._crossover.lopass_slope == 0:
            pen = QPen(theme.graph_curve_bypassed, _CURVE_WIDTH)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            y = self._db_to_y(0.0)
            p.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            return

        all_coeffs: list[tuple[float, ...]] = []
        if not self._channel_bypass:
            for b in self._bands:
                if not b.bypass:
                    all_coeffs.append(_biquad_coeffs_from_band(b))
        all_coeffs.extend(_crossover_biquads(self._crossover))

        if not all_coeffs:
            pen = QPen(theme.graph_curve_bypassed, _CURVE_WIDTH)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            y = self._db_to_y(0.0)
            p.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            return

        poly = QPolygonF()
        for i in range(_NUM_SAMPLES):
            frac = i / (_NUM_SAMPLES - 1)
            db = 0.0
            omega = 2.0 * math.pi * (10.0 ** (_LOG_F_MIN + frac * _LOG_F_RANGE)) / _FS_HZ
            for c in all_coeffs:
                db += _biquad_magnitude_db(c, omega)
            x = rect.left() + frac * rect.width()
            y = self._db_to_y(max(_DB_MIN, min(_DB_MAX, db)))
            poly.append(QPointF(x, y))

        pen = QPen(theme.graph_curve, _CURVE_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(poly)

    def _draw_xover_markers(self, p: QPainter, rect: QRectF) -> None:
        xo = self._crossover
        theme = theme_manager.current
        for freq_raw, slope, label in [
            (xo.hipass_freq, xo.hipass_slope, "HP"),
            (xo.lopass_freq, xo.lopass_slope, "LP"),
        ]:
            if slope == 0:
                continue
            f_hz = freq_raw_to_hz(freq_raw)
            if f_hz <= 0:
                continue
            x = self._hz_to_x(f_hz)
            if not (rect.left() - 1 <= x <= rect.right() + 1):
                continue
            y = self._db_to_y(0.0)

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.graph_xover_marker)
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
            if band.filter_type in (
                PEQ_TYPE_PEAK,
                PEQ_TYPE_LOW_SHELF,
                PEQ_TYPE_HIGH_SHELF,
            ):
                gain_db = peq_raw_to_gain(band.gain_raw)
                y_db = max(_DB_MIN, min(_DB_MAX, gain_db))
            else:
                y_db = 0.0
            y = self._db_to_y(y_db)

            color = (
                theme.graph_marker_bypassed
                if (band.bypass or self._channel_bypass)
                else theme.graph_marker_active
            )
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(QPointF(x, y), 7.0, 7.0)

            p.setPen(QPen(theme.graph_marker_text))
            p.drawText(
                QRectF(x - 8, y - 7, 16, 14),
                Qt.AlignmentFlag.AlignCenter,
                str(idx + 1),
            )


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
