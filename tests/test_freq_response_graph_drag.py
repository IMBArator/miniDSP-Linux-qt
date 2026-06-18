"""Draggable PEQ markers on FreqResponseGraph.

Covers the coordinate inverses, marker hit-testing (incl. overlap
tie-break and bypassed/locked exclusion), and the drag → ``band_dragged``
mapping for both gain-bearing (peak/shelf) and gain-pinned (pass/allpass)
filter types, plus clamping at the plot edges. The crossover variant of
the same widget must stay non-interactive.
"""

from __future__ import annotations

import pytest

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

from minidsp.protocol import (
    PEQ_TYPE_HIGH_PASS,
    PEQ_TYPE_PEAK,
    freq_hz_to_raw,
    freq_raw_to_hz,
    peq_gain_to_raw,
)

from minidspqt.model import PEQBand
from minidspqt.widgets.freq_response_graph import FreqResponseGraph


def _press(pos: QPointF) -> QMouseEvent:
    return QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        pos,
        pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _move(pos: QPointF) -> QMouseEvent:
    return QMouseEvent(
        QMouseEvent.Type.MouseMove,
        pos,
        pos,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _release(pos: QPointF) -> QMouseEvent:
    return QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        pos,
        pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _band(filter_type=PEQ_TYPE_PEAK, gain_raw=120, freq_raw=150, bypass=False) -> PEQBand:
    return PEQBand(
        gain_raw=gain_raw,
        freq_raw=freq_raw,
        q_raw=16,
        filter_type=filter_type,
        bypass=bypass,
    )


def _marker_pos(graph: FreqResponseGraph, band: PEQBand) -> QPointF:
    x = graph._hz_to_x(freq_raw_to_hz(band.freq_raw))
    y = graph._db_to_y(graph._marker_y_db(band))
    return QPointF(x, y)


@pytest.fixture
def graph(qtbot) -> FreqResponseGraph:
    g = FreqResponseGraph(feature="peq")
    qtbot.addWidget(g)
    g.resize(600, 320)
    g.show()
    qtbot.waitExposed(g)
    return g


class TestCoordinateInverses:
    def test_x_to_hz_roundtrips(self, graph):
        for raw in (0, 60, 150, 240, 300):
            hz = freq_raw_to_hz(raw)
            assert graph._x_to_hz(graph._hz_to_x(hz)) == pytest.approx(hz, rel=1e-6)

    def test_y_to_db_roundtrips(self, graph):
        for db in (-18.0, -6.0, 0.0, 6.0, 12.0):
            assert graph._y_to_db(graph._db_to_y(db)) == pytest.approx(db, abs=1e-6)

    def test_inverses_clamp_outside_plot(self, graph):
        # Far above/left of the plot clamps to the axis extremes.
        assert graph._y_to_db(-1000) == pytest.approx(18.0, abs=1e-6)  # top of axis
        assert graph._x_to_hz(-1000) == pytest.approx(10.0, rel=1e-6)  # _F_MIN


class TestHitTesting:
    def test_hits_marker_centre(self, graph):
        b = _band()
        graph.set_bands([b], channel_bypass=False)
        assert graph._hit_band(_marker_pos(graph, b)) == 0

    def test_miss_returns_minus_one(self, graph):
        graph.set_bands([_band()], channel_bypass=False)
        assert graph._hit_band(QPointF(5, 5)) == -1

    def test_overlap_prefers_higher_index(self, graph):
        # Two bands at the same freq+gain: the later-drawn (higher) index wins.
        b0 = _band(freq_raw=150, gain_raw=160)
        b1 = _band(freq_raw=150, gain_raw=160)
        graph.set_bands([b0, b1], channel_bypass=False)
        assert graph._hit_band(_marker_pos(graph, b1)) == 1

    def test_bypassed_band_not_hittable(self, graph):
        b = _band(bypass=True)
        graph.set_bands([b], channel_bypass=False)
        assert graph._hit_band(_marker_pos(graph, b)) == -1

    def test_channel_bypass_blocks_all(self, graph):
        b = _band()
        graph.set_bands([b], channel_bypass=True)
        assert graph._hit_band(_marker_pos(graph, b)) == -1


class TestDragMapping:
    def test_drag_peak_emits_freq_and_gain(self, graph, qtbot):
        b = _band(filter_type=PEQ_TYPE_PEAK, freq_raw=150, gain_raw=120)
        graph.set_bands([b], channel_bypass=False)
        start = _marker_pos(graph, b)
        target = QPointF(start.x() + 80, start.y() - 30)  # higher freq, more gain

        graph.mousePressEvent(_press(start))
        with qtbot.waitSignal(graph.band_dragged, timeout=1000) as sig:
            graph.mouseMoveEvent(_move(target))

        idx, freq_raw, gain_raw = sig.args
        assert idx == 0
        assert freq_raw == freq_hz_to_raw(graph._x_to_hz(target.x()))
        assert gain_raw == peq_gain_to_raw(graph._y_to_db(target.y()))
        # Moving right raises freq, moving up raises gain.
        assert freq_raw > b.freq_raw
        assert gain_raw > b.gain_raw

    def test_drag_pass_type_changes_freq_only(self, graph, qtbot):
        b = _band(filter_type=PEQ_TYPE_HIGH_PASS, freq_raw=150, gain_raw=200)
        graph.set_bands([b], channel_bypass=False)
        # Marker is pinned at 0 dB for a high-pass regardless of stored gain.
        assert graph._marker_y_db(b) == 0.0
        start = _marker_pos(graph, b)
        target = QPointF(start.x() + 60, start.y() - 50)  # try to move it up too

        graph.mousePressEvent(_press(start))
        with qtbot.waitSignal(graph.band_dragged, timeout=1000) as sig:
            graph.mouseMoveEvent(_move(target))

        idx, freq_raw, gain_raw = sig.args
        assert freq_raw == freq_hz_to_raw(graph._x_to_hz(target.x()))
        assert gain_raw == b.gain_raw  # gain untouched, not zeroed

    def test_gain_clamps_at_plus_12(self, graph, qtbot):
        b = _band(filter_type=PEQ_TYPE_PEAK, freq_raw=150, gain_raw=120)
        graph.set_bands([b], channel_bypass=False)
        start = _marker_pos(graph, b)
        # Drag well above the +12 dB line (top of the plot, where axis = +18).
        graph.mousePressEvent(_press(start))
        with qtbot.waitSignal(graph.band_dragged, timeout=1000) as sig:
            graph.mouseMoveEvent(_move(QPointF(start.x(), -50)))
        assert sig.args[2] == 240  # raw for +12 dB, not the +18 axis edge

    def test_freq_clamps_at_edges(self, graph, qtbot):
        b = _band(freq_raw=150)
        graph.set_bands([b], channel_bypass=False)
        start = _marker_pos(graph, b)

        graph.mousePressEvent(_press(start))
        with qtbot.waitSignal(graph.band_dragged) as sig_left:
            graph.mouseMoveEvent(_move(QPointF(-100, start.y())))
        assert sig_left.args[1] == 0

        with qtbot.waitSignal(graph.band_dragged) as sig_right:
            graph.mouseMoveEvent(_move(QPointF(5000, start.y())))
        assert sig_right.args[1] == 300

    def test_release_ends_drag(self, graph):
        b = _band()
        graph.set_bands([b], channel_bypass=False)
        start = _marker_pos(graph, b)
        graph.mousePressEvent(_press(start))
        assert graph._drag_band == 0
        graph.mouseReleaseEvent(_release(start))
        assert graph._drag_band == -1


class TestCrossoverIsInert:
    def test_xover_graph_emits_nothing_on_drag(self, qtbot):
        g = FreqResponseGraph(feature="xover")
        qtbot.addWidget(g)
        g.resize(600, 320)
        g.show()
        qtbot.waitExposed(g)
        b = _band()
        g.set_bands([b], channel_bypass=False)
        start = _marker_pos(g, b)

        assert g._hit_band(start) == -1
        with qtbot.assertNotEmitted(g.band_dragged):
            g.mousePressEvent(_press(start))
            g.mouseMoveEvent(_move(QPointF(start.x() + 50, start.y())))
        assert g._drag_band == -1
