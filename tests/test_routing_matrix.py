"""RoutingMatrix — drag-to-connect, double-click-to-disconnect, signal emission."""

from __future__ import annotations

import pytest

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from minidspqt.widgets.routing_matrix import (
    _point_to_segment_dist,
    RoutingMatrix,
)


def _mouse_event(
    etype,
    pos: QPointF,
    button=Qt.MouseButton.LeftButton,
    modifiers=Qt.KeyboardModifier.NoModifier,
) -> QMouseEvent:
    return QMouseEvent(etype, pos, pos, button, button, modifiers)


class TestPointToSegmentDist:
    def test_point_on_segment(self):
        a, b = QPointF(0, 0), QPointF(100, 0)
        assert _point_to_segment_dist(QPointF(50, 0), a, b) == pytest.approx(0)

    def test_point_perpendicular(self):
        a, b = QPointF(0, 0), QPointF(100, 0)
        assert _point_to_segment_dist(QPointF(50, 30), a, b) == pytest.approx(30)

    def test_point_beyond_end(self):
        a, b = QPointF(0, 0), QPointF(100, 0)
        assert _point_to_segment_dist(QPointF(150, 0), a, b) == pytest.approx(50)

    def test_point_before_start(self):
        a, b = QPointF(0, 0), QPointF(100, 0)
        assert _point_to_segment_dist(QPointF(-20, 0), a, b) == pytest.approx(20)

    def test_degenerate_segment(self):
        a = b = QPointF(50, 50)
        assert _point_to_segment_dist(QPointF(50, 60), a, b) == pytest.approx(10)


class TestRoutingMatrixSignals:
    def test_drag_emits_routing_changed(self, qtbot):
        widget = RoutingMatrix()
        widget.resize(200, 400)
        qtbot.addWidget(widget)
        widget.show()

        widget.set_routing([0x01, 0x02, 0x04, 0x08])

        ins, outs = widget._node_positions()

        with qtbot.waitSignal(widget.routing_changed, timeout=1000) as sig:
            qtbot.mousePress(
                widget,
                Qt.MouseButton.LeftButton,
                pos=ins[0].toPoint(),
            )
            qtbot.mouseRelease(
                widget,
                Qt.MouseButton.LeftButton,
                pos=outs[1].toPoint(),
            )

        assert sig.args == [1, 0x03]

    def test_drag_same_connection_no_signal(self, qtbot):
        widget = RoutingMatrix()
        widget.resize(200, 400)
        qtbot.addWidget(widget)
        widget.show()

        widget.set_routing([0x01, 0x02, 0x04, 0x08])

        ins, outs = widget._node_positions()

        with qtbot.assertNotEmitted(widget.routing_changed, wait=200):
            qtbot.mousePress(
                widget,
                Qt.MouseButton.LeftButton,
                pos=ins[0].toPoint(),
            )
            qtbot.mouseRelease(
                widget,
                Qt.MouseButton.LeftButton,
                pos=outs[0].toPoint(),
            )

    def test_double_click_disconnects_route(self, qtbot):
        widget = RoutingMatrix()
        widget.resize(200, 400)
        qtbot.addWidget(widget)
        widget.show()

        widget.set_routing([0x03, 0x02, 0x04, 0x08])

        ins, outs = widget._node_positions()

        mid_x = (ins[0].x() + outs[0].x()) / 2
        click_pos = QPointF(mid_x, ins[0].y())

        with qtbot.waitSignal(widget.routing_changed, timeout=1000) as sig:
            QApplication.sendEvent(
                widget,
                _mouse_event(
                    QMouseEvent.Type.MouseButtonDblClick,
                    click_pos,
                ),
            )

        assert sig.args == [0, 0x02]

    def test_double_click_no_route_no_signal(self, qtbot):
        widget = RoutingMatrix()
        widget.resize(200, 400)
        qtbot.addWidget(widget)
        widget.show()

        widget.set_routing([0x01, 0x00, 0x04, 0x08])

        ins, outs = widget._node_positions()

        mid_x = (ins[1].x() + outs[1].x()) / 2
        click_pos = QPointF(mid_x, ins[1].y())

        QApplication.sendEvent(
            widget,
            _mouse_event(
                QMouseEvent.Type.MouseButtonDblClick,
                click_pos,
            ),
        )
        qtbot.wait(100)
        assert widget._masks[1] == 0x00

    def test_drag_updates_internal_masks(self, qtbot):
        widget = RoutingMatrix()
        widget.resize(200, 400)
        qtbot.addWidget(widget)
        widget.show()

        widget.set_routing([0x01, 0x02, 0x04, 0x08])

        ins, outs = widget._node_positions()

        with qtbot.waitSignal(widget.routing_changed, timeout=1000):
            qtbot.mousePress(
                widget,
                Qt.MouseButton.LeftButton,
                pos=ins[0].toPoint(),
            )
            qtbot.mouseRelease(
                widget,
                Qt.MouseButton.LeftButton,
                pos=outs[1].toPoint(),
            )

        assert widget._masks[1] == 0x03


class TestRoutingMatrixHitDetection:
    def test_hit_node_on_point(self):
        widget = RoutingMatrix()
        widget.resize(200, 400)
        ins, outs = widget._node_positions()

        assert widget._hit_node(ins[0], ins) == 0
        assert widget._hit_node(ins[3], ins) == 3
        assert widget._hit_node(outs[2], outs) == 2

    def test_hit_node_miss(self):
        widget = RoutingMatrix()
        widget.resize(200, 400)
        ins, outs = widget._node_positions()

        mid = QPointF((ins[0].x() + outs[0].x()) / 2, ins[0].y())
        assert widget._hit_node(mid, ins) == -1

    def test_hit_connection_finds_nearest(self):
        widget = RoutingMatrix()
        widget.resize(200, 400)
        widget.set_routing([0x03, 0x02, 0x04, 0x08])

        ins, outs = widget._node_positions()

        mid_x = (ins[0].x() + outs[0].x()) / 2
        result = widget._hit_connection(QPointF(mid_x, ins[0].y()), ins, outs)
        assert result is not None
        input_idx, output_idx = result
        assert output_idx == 0
        assert input_idx == 0
