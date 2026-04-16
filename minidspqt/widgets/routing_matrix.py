"""4x4 routing matrix visualization (display-only for now).

Inputs are on the left, outputs on the right. A route is active when
output `o` has bit `1 << i` set in its `routing_mask`. Active routes
are drawn in accent colour; inactive are dim.

Editing (click-to-toggle) is planned for a later phase.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

NUM = 4


class RoutingMatrix(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._routing: list[int] = [1 << i for i in range(NUM)]  # 1:1 default
        self.setMinimumSize(60, 200)

    def set_routing(self, masks: list[int]) -> None:
        if len(masks) != NUM:
            return
        self._routing = list(masks)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter()
        if not p.begin(self):
            return
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()

            pad_y = 10
            slot_h = (h - 2 * pad_y) / NUM
            x_in = 10.0
            x_out = w - 10.0

            in_points: list[QPointF] = []
            out_points: list[QPointF] = []
            for i in range(NUM):
                y = pad_y + slot_h * (i + 0.5)
                in_points.append(QPointF(x_in, y))
                out_points.append(QPointF(x_out, y))

            # Inactive routes first (so active overlay on top)
            p.setPen(QPen(QColor(70, 70, 74), 1))
            for o in range(NUM):
                for i in range(NUM):
                    if not (self._routing[o] & (1 << i)):
                        p.drawLine(in_points[i], out_points[o])

            p.setPen(QPen(QColor(80, 170, 230), 2))
            for o in range(NUM):
                for i in range(NUM):
                    if self._routing[o] & (1 << i):
                        p.drawLine(in_points[i], out_points[o])

            # End-caps
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(200, 200, 200))
            for pt in in_points + out_points:
                p.drawEllipse(pt, 4.0, 4.0)
        finally:
            p.end()
