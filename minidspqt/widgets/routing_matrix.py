"""4x4 routing matrix with drag-to-connect and double-click-to-disconnect.

Inputs are on the left, outputs on the right. A route is active when
output ``o`` has bit ``1 << i`` set in its ``routing_mask``.

Interactions
------------
- **Drag** from an input node to an output node to *add* that input to the
  output's routing (OR the bit into the mask).
- **Double-click** near an existing connection line to *remove* that
  specific input→output pair (clear the bit).
"""

from __future__ import annotations

from PySide6.QtCore import QLineF, QPointF, Qt, Signal
from PySide6.QtGui import QCursor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..theme import theme_manager

NUM = 4

NODE_RADIUS = 7.0
LINE_HIT_TOLERANCE = 8.0
PAD_X = 12.0


def _point_to_segment_dist(p: QPointF, a: QPointF, b: QPointF) -> float:
    dx = b.x() - a.x()
    dy = b.y() - a.y()
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-9:
        return QLineF(p, a).length()
    t = max(0.0, min(1.0, ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / len_sq))
    proj = QPointF(a.x() + t * dx, a.y() + t * dy)
    return QLineF(p, proj).length()


class RoutingMatrix(QWidget):
    """Interactive 4-input × 4-output routing matrix.

    Renders connection lines between input nodes (left) and output
    nodes (right) at the vertical positions of their respective
    channel strips, so the user reads each connection straight across
    a row in the home view. Drag an input node to an output to
    create a connection; double-click an existing connection to
    remove it.

    Signals:
        routing_changed (int, int): Emitted on every routing edit
            with ``(output_index, new_mask)`` — the caller writes
            ``new_mask`` to the device via ``cmd_matrix_route``.
    """

    routing_changed = Signal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build a matrix seeded with the identity routing (i → i).

        Args:
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self._masks: list[int] = [1 << i for i in range(NUM)]
        self.setMinimumSize(80, 200)
        self.setMouseTracking(True)

        self._input_strips: list[QWidget] = []
        self._output_strips: list[QWidget] = []

        self._dragging: bool = False
        self._drag_input: int = -1
        self._drag_pos: QPointF = QPointF()
        self._hover_output: int = -1
        self._hover_input: int = -1
        theme_manager.themeChanged.connect(self.update)

    def set_routing(self, masks: list[int]) -> None:
        """Replace all four output routing masks and repaint.

        Args:
            masks: Exactly 4 4-bit input bitmasks (one per output).
                Wrong-length lists are ignored. Bit ``i`` in the mask
                for output ``j`` means "input ``i`` is routed to
                output ``j``".
        """
        if len(masks) != NUM:
            return
        self._masks = list(masks)
        self.update()

    def set_strips(self, inputs: list[QWidget], outputs: list[QWidget]) -> None:
        """Tell the matrix which channel strip widgets to align with.

        The matrix reads each strip's screen position on every
        ``paintEvent`` and centres its endpoints on the strip
        midline — this keeps the connection lines aligned with the
        home-view rows even when the user resizes the window or
        scrolls.

        Args:
            inputs: Up to 4 input-strip widgets.
            outputs: Up to 4 output-strip widgets.
        """
        self._input_strips = list(inputs)
        self._output_strips = list(outputs)

    # ---- geometry helpers ----

    def _strip_y(self, strip: QWidget) -> float | None:
        if strip is None or not strip.isVisible():
            return None
        center = strip.rect().center()
        global_pt = strip.mapToGlobal(center)
        local_pt = self.mapFromGlobal(global_pt)
        return float(local_pt.y())

    def _node_positions(self) -> tuple[list[QPointF], list[QPointF]]:
        w, h = self.width(), self.height()
        x_in = PAD_X
        x_out = w - PAD_X

        ins: list[QPointF] = []
        outs: list[QPointF] = []

        for i in range(NUM):
            y_in = (
                self._strip_y(self._input_strips[i])
                if i < len(self._input_strips)
                else None
            )
            y_out = (
                self._strip_y(self._output_strips[i])
                if i < len(self._output_strips)
                else None
            )

            if y_in is None:
                y_in = h / (NUM + 1) * (i + 1)
            if y_out is None:
                y_out = h / (NUM + 1) * (i + 1)

            ins.append(QPointF(x_in, y_in))
            outs.append(QPointF(x_out, y_out))

        return ins, outs

    def _hit_node(self, pos: QPointF, nodes: list[QPointF]) -> int:
        for i, pt in enumerate(nodes):
            if QLineF(pos, pt).length() <= NODE_RADIUS + 4:
                return i
        return -1

    def _hit_connection(
        self, pos: QPointF, ins: list[QPointF], outs: list[QPointF]
    ) -> tuple[int, int] | None:
        best_dist = LINE_HIT_TOLERANCE
        best: tuple[int, int] | None = None
        for o in range(NUM):
            for i in range(NUM):
                if self._masks[o] & (1 << i):
                    d = _point_to_segment_dist(pos, ins[i], outs[o])
                    if d < best_dist:
                        best_dist = d
                        best = (i, o)
        return best

    # ---- painting ----

    def paintEvent(self, event) -> None:
        p = QPainter()
        if not p.begin(self):
            return
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            ins, outs = self._node_positions()
            theme = theme_manager.current

            for o in range(NUM):
                if self._hover_output == o:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(theme.matrix_highlight)
                    p.drawEllipse(outs[o], NODE_RADIUS + 10, NODE_RADIUS + 10)

            pen_active = QPen(theme.matrix_active, 2.5)
            for o in range(NUM):
                for i in range(NUM):
                    if self._masks[o] & (1 << i):
                        p.setPen(pen_active)
                        p.drawLine(ins[i], outs[o])

            if self._dragging and 0 <= self._drag_input < NUM:
                pen_drag = QPen(theme.matrix_drag, 2, Qt.PenStyle.DashLine)
                p.setPen(pen_drag)
                p.drawLine(ins[self._drag_input], self._drag_pos)

            p.setPen(Qt.PenStyle.NoPen)
            for i in range(NUM):
                fill = (
                    theme.matrix_active
                    if self._hover_input == i
                    else theme.matrix_node_fill
                )
                p.setBrush(fill)
                p.drawEllipse(ins[i], NODE_RADIUS, NODE_RADIUS)
            for o in range(NUM):
                fill = (
                    theme.matrix_active
                    if self._hover_output == o
                    else theme.matrix_node_fill
                )
                p.setBrush(fill)
                p.drawEllipse(outs[o], NODE_RADIUS, NODE_RADIUS)
        finally:
            p.end()

    # ---- mouse events ----

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        ins, outs = self._node_positions()
        hit = self._hit_node(QPointF(event.position()), ins)
        if hit >= 0:
            self._dragging = True
            self._drag_input = hit
            self._drag_pos = QPointF(event.position())
            self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = QPointF(event.position())
        ins, outs = self._node_positions()

        if self._dragging:
            self._drag_pos = pos
            self._hover_output = self._hit_node(pos, outs)
            self.update()
            return

        prev_in = self._hover_input
        prev_out = self._hover_output
        self._hover_input = self._hit_node(pos, ins)
        self._hover_output = self._hit_node(pos, outs)
        near_node = self._hover_input >= 0 or self._hover_output >= 0

        on_line = False
        if not near_node:
            on_line = self._hit_connection(pos, ins, outs) is not None

        if near_node or on_line:
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        if self._hover_input != prev_in or self._hover_output != prev_out:
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if not self._dragging:
            return
        self._dragging = False
        pos = QPointF(event.position())
        ins, outs = self._node_positions()
        hit_out = self._hit_node(pos, outs)

        if hit_out >= 0 and 0 <= self._drag_input < NUM:
            bit = 1 << self._drag_input
            new_mask = self._masks[hit_out] | bit
            if new_mask != self._masks[hit_out]:
                self._masks[hit_out] = new_mask
                self.routing_changed.emit(hit_out, new_mask)
                self.update()

        self._drag_input = -1
        self._hover_output = -1
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        pos = QPointF(event.position())
        ins, outs = self._node_positions()

        hit = self._hit_connection(pos, ins, outs)
        if hit is not None:
            input_idx, output_idx = hit
            bit = 1 << input_idx
            new_mask = self._masks[output_idx] & ~bit
            if new_mask != self._masks[output_idx]:
                self._masks[output_idx] = new_mask
                self.routing_changed.emit(output_idx, new_mask)
                self.update()

    def leaveEvent(self, event) -> None:
        self._hover_input = -1
        self._hover_output = -1
        if not self._dragging:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.update()
