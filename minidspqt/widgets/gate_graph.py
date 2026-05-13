"""Noise gate transfer function graph: dB input vs dB output.

Draws a dark-themed plot showing the gate characteristic as an L-shaped
curve.  Below the threshold the output sits at the noise floor (-90 dB);
above the threshold the output follows the input at unity gain (1:1 line).

Only the *threshold* parameter changes the visual — attack, hold and
release are time-domain parameters that do not affect the static transfer
function.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from minidsp.protocol import gate_threshold_to_db

from ..theme import theme_manager

_DB_MIN = -90.0
_DB_MAX = 0.0
_DB_RANGE = _DB_MAX - _DB_MIN

_OUTER_PADDING = 10
_OUTER_PADDING_LEFT = 4  # tighter than other sides: y-labels are right-aligned
# and naturally drift toward the rect, leaving extra
# whitespace on the widget-edge side of the text.
_LABEL_GAP = 4
_X_LABEL_HEIGHT = 12
_Y_LABEL_WIDTH = 24

_MARGIN_TOP = _OUTER_PADDING
_MARGIN_RIGHT = _OUTER_PADDING
_MARGIN_BOTTOM = _OUTER_PADDING + _LABEL_GAP + _X_LABEL_HEIGHT
_MARGIN_LEFT = _OUTER_PADDING_LEFT + _LABEL_GAP + _Y_LABEL_WIDTH

_GRID_INTERVAL = 15.0
_CURVE_WIDTH = 2.5


class GateGraph(QWidget):
    """Gate transfer function graph driven by a raw threshold value."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._threshold_db: float = -89.5
        self.setMinimumHeight(140)
        self.setSizePolicy(
            self.sizePolicy().horizontalPolicy(),
            self.sizePolicy().verticalPolicy(),
        )
        theme_manager.themeChanged.connect(self.update)

    def set_threshold(self, raw: int) -> None:
        db = gate_threshold_to_db(raw)
        if db != self._threshold_db:
            self._threshold_db = db
            self.update()

    def set_threshold_db(self, db: float) -> None:
        if db != self._threshold_db:
            self._threshold_db = db
            self.update()

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
            self._draw_closed_fill(p, rect)
            self._draw_open_fill(p, rect)
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
        db = _DB_MIN + _GRID_INTERVAL
        while db < _DB_MAX:
            x = self._db_to_x(db)
            y = self._db_to_y(db)
            p.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
            p.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            db += _GRID_INTERVAL

    def _draw_axis_labels(self, p: QPainter, rect: QRectF) -> None:
        font = QFont(p.font())
        font.setPixelSize(10)
        p.setFont(font)
        p.setPen(QPen(theme_manager.current.graph_label))

        db = _DB_MIN
        while db <= _DB_MAX + 0.1:
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
            db += _GRID_INTERVAL

    def _draw_ref_diagonal(self, p: QPainter, rect: QRectF) -> None:
        pen = QPen(theme_manager.current.graph_ref, 1, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(
            int(rect.left()),
            int(rect.bottom()),
            int(rect.right()),
            int(rect.top()),
        )

    def _draw_closed_fill(self, p: QPainter, rect: QRectF) -> None:
        poly = QPolygonF()
        poly.append(rect.bottomLeft())
        poly.append(rect.bottomRight())
        poly.append(rect.topRight())
        poly.append(self._db_to_xy(rect, self._threshold_db, self._threshold_db))
        poly.append(self._db_to_xy(rect, self._threshold_db, _DB_MIN))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme_manager.current.gate_closed_fill)
        p.drawPolygon(poly)

    def _draw_open_fill(self, p: QPainter, rect: QRectF) -> None:
        thr_db = self._threshold_db
        poly = QPolygonF()
        poly.append(self._db_to_xy(rect, thr_db, _DB_MIN))
        poly.append(self._db_to_xy(rect, thr_db, thr_db))
        poly.append(self._db_to_xy(rect, _DB_MAX, _DB_MAX))
        poly.append(self._db_to_xy(rect, _DB_MAX, _DB_MIN))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme_manager.current.gate_open_fill)
        p.drawPolygon(poly)

    def _draw_curve(self, p: QPainter, rect: QRectF) -> None:
        thr_db = self._threshold_db
        pen = QPen(theme_manager.current.graph_curve_gate, _CURVE_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)

        poly = QPolygonF()
        poly.append(self._db_to_xy(rect, _DB_MIN, _DB_MIN))
        poly.append(self._db_to_xy(rect, thr_db, _DB_MIN))
        poly.append(self._db_to_xy(rect, thr_db, thr_db))
        poly.append(self._db_to_xy(rect, _DB_MAX, _DB_MAX))

        p.setBrush(Qt.BrushStyle.NoBrush)
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
        label = f"{self._threshold_db:.1f} dB"
        p.drawText(int(x) + 4, int(rect.top()) + 12, label)

    def _db_to_xy(self, rect: QRectF, db_x: float, db_y: float) -> QPointF:
        return QPointF(self._db_to_x(db_x), self._db_to_y(db_y))
