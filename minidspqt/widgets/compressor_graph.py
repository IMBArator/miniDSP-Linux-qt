"""Compressor transfer-function graph: input dB vs output dB.

Draws the static compression curve from the current
``(threshold, ratio, knee)`` triple.  The reference 45-degree line shows
identity (no compression); the compression curve follows it below the
threshold-minus-half-knee point and then bends toward the slope
``1/ratio`` for inputs above the threshold-plus-half-knee point.  The
transition between the two regions is smoothed quadratically across the
knee width so a non-zero knee value visibly rounds the elbow.

Only the static parameters (threshold, ratio, knee) affect the visual.
Attack and release are time-domain — they do not change the steady-state
transfer function and so do not need to be reflected here.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from minidsp.protocol import comp_threshold_to_db

from ..theme import theme_manager

_DB_MIN = -90.0
_DB_MAX = 20.0
_DB_RANGE = _DB_MAX - _DB_MIN

_OUTER_PADDING = 10
_OUTER_PADDING_LEFT = 4
_LABEL_GAP = 4
_X_LABEL_HEIGHT = 12
_Y_LABEL_WIDTH = 24

_MARGIN_TOP = _OUTER_PADDING
# Right margin fits half a centred axis label so the "+20" tick at the
# right edge does not get clipped by the widget border.
_MARGIN_RIGHT = _OUTER_PADDING + _Y_LABEL_WIDTH // 2
_MARGIN_BOTTOM = _OUTER_PADDING + _LABEL_GAP + _X_LABEL_HEIGHT
_MARGIN_LEFT = _OUTER_PADDING_LEFT + _LABEL_GAP + _Y_LABEL_WIDTH

# Grid ticks are anchored to multiples of 20 dB so the labels include the
# meaningful reference points (-20, 0, +20). Drawing a line on either
# endpoint would duplicate the plot border, so they're labelled but not
# drawn in the grid pass.
_GRID_TICKS_DB: tuple[float, ...] = (-80.0, -60.0, -40.0, -20.0, 0.0)
_AXIS_LABELS_DB: tuple[float, ...] = (
    -90.0, -80.0, -60.0, -40.0, -20.0, 0.0, 20.0,
)

_CURVE_WIDTH = 2.5
_CURVE_STEPS = 110  # one sample per dB across the −90..+20 plot

# Numeric ratios, indexed by raw value 0..15.  Parallels
# ``minidsp.protocol.COMP_RATIO_NAMES``.  ``math.inf`` marks the hard
# limiter (raw 0x0F).
COMP_RATIO_VALUES: tuple[float, ...] = (
    1.0, 1.1, 1.3, 1.5, 1.7, 2.0, 2.5, 3.0,
    3.5, 4.0, 5.0, 6.0, 8.0, 10.0, 20.0, math.inf,
)


class CompressorGraph(QWidget):
    """Compressor transfer-function graph driven by raw parameter values."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._threshold_db: float = comp_threshold_to_db(220)  # +20 dB default
        self._ratio: float = 1.0
        self._knee_db: float = 0.0
        self.setMinimumHeight(140)
        theme_manager.themeChanged.connect(self.update)

    def set_params(self, threshold_raw: int, ratio_raw: int, knee_raw: int) -> None:
        thr = comp_threshold_to_db(threshold_raw)
        ratio = COMP_RATIO_VALUES[max(0, min(15, ratio_raw))]
        knee = float(max(0, min(12, knee_raw)))
        if (thr, ratio, knee) != (self._threshold_db, self._ratio, self._knee_db):
            self._threshold_db = thr
            self._ratio = ratio
            self._knee_db = knee
            self.update()

    def _curve_db(self, x_db: float) -> float:
        """Static compressor transfer function for an input level in dB."""
        thr = self._threshold_db
        knee = self._knee_db
        ratio = self._ratio
        half = knee / 2.0

        if x_db <= thr - half:
            return x_db
        if x_db >= thr + half:
            if math.isinf(ratio):
                return thr
            return thr + (x_db - thr) / ratio

        # Knee region: quadratic interpolation that matches identity at the
        # low boundary and the compressed slope at the high boundary while
        # keeping the derivative continuous on both sides.
        if knee == 0:
            return thr  # only reachable when knee=0 and x_db == thr
        if math.isinf(ratio):
            slope = -1.0  # 1/ratio − 1 with ratio = ∞
        else:
            slope = 1.0 / ratio - 1.0
        d = x_db - thr + half
        return x_db + slope * d * d / (2.0 * knee)

    # ------------------------------------------------------------------ #

    def _plot_rect(self) -> QRectF:
        return QRectF(
            _MARGIN_LEFT,
            _MARGIN_TOP,
            self.width() - _MARGIN_LEFT - _MARGIN_RIGHT,
            self.height() - _MARGIN_TOP - _MARGIN_BOTTOM,
        )

    def _db_to_x(self, db: float) -> float:
        r = self._plot_rect()
        frac = (db - _DB_MIN) / _DB_RANGE
        return r.left() + frac * r.width()

    def _db_to_y(self, db: float) -> float:
        r = self._plot_rect()
        frac = (db - _DB_MIN) / _DB_RANGE
        return r.bottom() - frac * r.height()

    def _db_to_xy(self, db_x: float, db_y: float) -> QPointF:
        return QPointF(self._db_to_x(db_x), self._db_to_y(db_y))

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
            self._draw_ref_diagonal(p, rect)
            self._draw_curve(p, rect)
            self._draw_threshold_marker(p, rect)

            p.setPen(QPen(theme.graph_border, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect)
        finally:
            p.end()

    def _draw_grid(self, p: QPainter, rect: QRectF) -> None:
        pen = QPen(theme_manager.current.graph_grid, 1, Qt.PenStyle.DotLine)
        p.setPen(pen)
        for db in _GRID_TICKS_DB:
            x = self._db_to_x(db)
            y = self._db_to_y(db)
            p.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
            p.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))

    def _draw_axis_labels(self, p: QPainter, rect: QRectF) -> None:
        font = QFont(p.font())
        font.setPixelSize(10)
        p.setFont(font)
        p.setPen(QPen(theme_manager.current.graph_label))

        for db in _AXIS_LABELS_DB:
            x = self._db_to_x(db)
            y = self._db_to_y(db)
            label = f"{db:.0f}"
            p.drawText(
                int(x) - _Y_LABEL_WIDTH // 2,
                int(rect.bottom()) + _LABEL_GAP,
                _Y_LABEL_WIDTH,
                _X_LABEL_HEIGHT,
                Qt.AlignmentFlag.AlignCenter,
                label,
            )
            p.drawText(
                int(rect.left()) - (_LABEL_GAP + _Y_LABEL_WIDTH),
                int(y) - _X_LABEL_HEIGHT // 2,
                _Y_LABEL_WIDTH,
                _X_LABEL_HEIGHT,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )

    def _draw_ref_diagonal(self, p: QPainter, rect: QRectF) -> None:
        pen = QPen(theme_manager.current.graph_ref, 1, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(
            int(rect.left()),
            int(rect.bottom()),
            int(rect.right()),
            int(rect.top()),
        )

    def _draw_curve(self, p: QPainter, rect: QRectF) -> None:
        pen = QPen(theme_manager.current.graph_curve_comp, _CURVE_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        poly = QPolygonF()
        for i in range(_CURVE_STEPS + 1):
            x_db = _DB_MIN + i * _DB_RANGE / _CURVE_STEPS
            y_db = self._curve_db(x_db)
            y_db = max(_DB_MIN, min(_DB_MAX, y_db))
            poly.append(self._db_to_xy(x_db, y_db))
        p.drawPolyline(poly)

    def _draw_threshold_marker(self, p: QPainter, rect: QRectF) -> None:
        theme = theme_manager.current
        x = self._db_to_x(self._threshold_db)
        pen = QPen(theme.gate_threshold_line, 1, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))

        font = QFont(p.font())
        font.setPixelSize(10)
        p.setFont(font)
        p.setPen(QPen(theme.gate_threshold_text))
        label = f"{self._threshold_db:+.1f} dB"
        p.drawText(int(x) + 4, int(rect.top()) + 12, label)
