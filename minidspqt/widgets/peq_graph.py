"""PEQ frequency-response graph: log Hz vs dB.

Draws the summed magnitude response of up to 7 parametric EQ bands
plus a numbered marker for each band.  Visual conventions (background
colour, grid, label palette, margin layout) match :class:`GateGraph`
so the two detail-view feature panels feel like one family.

Coefficients per band are computed locally from the raw protocol
values via the standard Audio EQ Cookbook biquad formulas (RBJ),
evaluated at the device's 48 kHz internal sample rate (see the
0x38 delay opcode in analysis/protocol.md, which encodes samples
at 48 kHz).  Using the wrong rate skews the bilinear-transform
warping near the top of the audio band, so high-frequency PEQ
bands would render with shifted resonance peaks.
"""

from __future__ import annotations

import math

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

# Visible frequency range.  We extend a touch beyond the labelled markers
# on both ends so the first/last grid line doesn't sit flush against the
# plot border (which would clip its label and look cramped).  The lower
# bound is one decade below 100 Hz (i.e. 10 Hz) since log10(0) is
# undefined; the upper bound is ~25 kHz so the 20 kHz marker has breathing
# room on the right.
_F_MIN = 10.0
_F_MAX = 25_000.0
_LOG_F_MIN = math.log10(_F_MIN)
_LOG_F_MAX = math.log10(_F_MAX)
_LOG_F_RANGE = _LOG_F_MAX - _LOG_F_MIN

# Y-axis dB range.  Device clamps gain to ±12 dB so ±18 gives 6 dB of
# headroom for visible high-Q peaks without clipping the chart border.
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

# dB gridlines: every 5 dB but skipping 0 (drawn separately as the
# dashed reference) and skipping the ±18 edges so they don't clip the
# plot border.
_DB_GRID_LINES = (-18.0, -12.0, -6.0, 0.0, 6.0, 12.0, 18.0)
_DB_LABELS = (-18.0, -12.0, -6.0, 0.0, 6.0, 12.0, 18.0)

# Explicit list of frequency markers (1-2-5 within each audio decade).
# The plot extends past these on both sides — the very edges have no
# marker so the first and last visible labels (20 Hz and 20 kHz) sit
# inside the plot rather than clipping its border.
_FREQ_MARKERS = (20, 50, 100, 200, 500, 1_000, 2_000, 5_000, 10_000, 20_000)

_CURVE_WIDTH = 2.0
_NUM_SAMPLES = 256


class PEQGraph(QWidget):
    """Frequency-response graph for one channel's 7 PEQ bands."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bands: list[PEQBand] = []
        self._channel_bypass: bool = False
        self.setMinimumHeight(160)
        # Repaint when the active theme flips (system or user toggle).
        theme_manager.themeChanged.connect(self.update)

    def set_bands(self, bands: list[PEQBand], channel_bypass: bool) -> None:
        self._bands = list(bands)
        self._channel_bypass = bool(channel_bypass)
        self.update()

    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #

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
            self._draw_markers(p, rect)

            p.setPen(QPen(theme.graph_border, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect)
        finally:
            p.end()

    # ------------------------------------------------------------------ #
    # Grid & axes
    # ------------------------------------------------------------------ #

    def _draw_grid(self, p: QPainter, rect: QRectF) -> None:
        pen = QPen(theme_manager.current.graph_grid, 1, Qt.PenStyle.DotLine)
        p.setPen(pen)

        # Vertical: one gridline per labelled marker.  No edge gridlines —
        # the plot border itself frames the chart.
        for f in _FREQ_MARKERS:
            x = self._hz_to_x(f)
            p.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))

        # Horizontal: explicit 5 dB grid lines.
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

    # ------------------------------------------------------------------ #
    # Summed response curve
    # ------------------------------------------------------------------ #

    def _draw_curve(self, p: QPainter, rect: QRectF) -> None:
        theme = theme_manager.current
        if self._channel_bypass:
            pen = QPen(theme.graph_curve_peq_bypassed, _CURVE_WIDTH)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            y = self._db_to_y(0.0)
            p.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            return

        # Sample on a log-spaced frequency grid and accumulate dB contributions.
        active_bands = [b for b in self._bands if not b.bypass]
        coeffs = [_biquad_coeffs_from_band(b) for b in active_bands]

        poly = QPolygonF()
        for i in range(_NUM_SAMPLES):
            frac = i / (_NUM_SAMPLES - 1)
            log_f = _LOG_F_MIN + frac * _LOG_F_RANGE
            f = 10.0 ** log_f
            db = 0.0
            omega = 2.0 * math.pi * f / _FS_HZ
            for c in coeffs:
                db += _biquad_magnitude_db(c, omega)
            x = rect.left() + frac * rect.width()
            y = self._db_to_y(max(_DB_MIN, min(_DB_MAX, db)))
            poly.append(QPointF(x, y))

        pen = QPen(theme.graph_curve_peq, _CURVE_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(poly)

    # ------------------------------------------------------------------ #
    # Per-band markers
    # ------------------------------------------------------------------ #

    def _draw_markers(self, p: QPainter, rect: QRectF) -> None:
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
            # Marker y: at the band's gain for peak/shelf bands, at 0 dB for
            # filters where gain doesn't contribute to the static response.
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
                else theme.graph_curve_peq
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


# ---------------------------------------------------------------------- #
# Biquad math (Audio EQ Cookbook)
# ---------------------------------------------------------------------- #


def _biquad_coeffs_from_band(band: PEQBand) -> tuple[float, ...]:
    f0 = freq_raw_to_hz(band.freq_raw)
    if f0 <= 0:
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    f0 = max(1.0, min(_FS_HZ * 0.49, f0))
    q = max(0.1, peq_raw_to_q(band.q_raw))
    gain_db = peq_raw_to_gain(band.gain_raw)
    return _coeffs(band.filter_type, f0, q, gain_db)


def _coeffs(
    filter_type: int, f0: float, q: float, gain_db: float
) -> tuple[float, ...]:
    """Return ``(b0, b1, b2, a0, a1, a2)`` in normalised-by-a0 form."""
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
        # 1st-order allpass: magnitude is unity at all frequencies.
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    else:
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    return (b0, b1, b2, a0, a1, a2)


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
