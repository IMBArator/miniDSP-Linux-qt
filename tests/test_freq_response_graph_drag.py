"""Draggable markers on FreqResponseGraph — PEQ bands + crossover halves.

Covers the coordinate inverses, marker hit-testing (incl. overlap
tie-break and bypassed/locked exclusion), and the drag → ``band_dragged``
mapping for both gain-bearing (peak/shelf) and gain-pinned (pass/allpass)
PEQ filter types, plus clamping at the plot edges. The crossover variant
of the same widget mirrors the gestures: drag → ``xover_freq_dragged``,
wheel → ``xover_slope_stepped``, double-click → ``xover_bypass_toggled``;
its tests live in the second half of the file.
"""

from __future__ import annotations

import pytest

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent

from minidsp.protocol import (
    PEQ_TYPE_HIGH_PASS,
    PEQ_TYPE_PEAK,
    SLOPE_BW24,
    freq_hz_to_raw,
    freq_raw_to_hz,
    peq_gain_to_raw,
)

from minidspqt.model import PEQBand
from minidspqt.widgets.freq_response_graph import CrossoverData, FreqResponseGraph


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


def _double_click(pos: QPointF) -> QMouseEvent:
    return QMouseEvent(
        QMouseEvent.Type.MouseButtonDblClick,
        pos,
        pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _wheel(pos: QPointF, notches: int = 1, ctrl: bool = False) -> QWheelEvent:
    mod = (
        Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
    )
    delta = QPoint(0, 120 * notches)
    return QWheelEvent(
        pos,
        pos,
        delta,
        delta,
        Qt.MouseButton.NoButton,
        mod,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )


def _band(
    filter_type=PEQ_TYPE_PEAK, gain_raw=120, freq_raw=150, bypass=False
) -> PEQBand:
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


def _xover_marker_pos(graph: FreqResponseGraph, which: str) -> QPointF:
    """Centre of the HP/LP triangle for the graph's current crossover."""
    xo = graph._crossover
    freq_raw = xo.hipass_freq if which == "hp" else xo.lopass_freq
    return QPointF(graph._hz_to_x(freq_raw_to_hz(freq_raw)), graph._db_to_y(0.0))


@pytest.fixture
def graph(qtbot) -> FreqResponseGraph:
    g = FreqResponseGraph(feature="peq")
    qtbot.addWidget(g)
    g.resize(600, 320)
    g.show()
    qtbot.waitExposed(g)
    return g


@pytest.fixture
def xover_graph(qtbot) -> FreqResponseGraph:
    """Feature="xover" graph with active HP and LP halves."""
    g = FreqResponseGraph(feature="xover")
    qtbot.addWidget(g)
    g.resize(600, 320)
    g.show()
    qtbot.waitExposed(g)
    g.set_crossover(
        CrossoverData(
            hipass_freq=100,
            hipass_slope=SLOPE_BW24,
            lopass_freq=200,
            lopass_slope=SLOPE_BW24,
        )
    )
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


class TestWheelQ:
    def test_wheel_up_over_marker_emits_positive_delta(self, graph, qtbot):
        b = _band()
        graph.set_bands([b], channel_bypass=False)
        with qtbot.waitSignal(graph.band_q_changed, timeout=1000) as sig:
            graph.wheelEvent(_wheel(_marker_pos(graph, b), notches=1))
        assert sig.args == [0, 1]

    def test_wheel_down_emits_negative_delta(self, graph, qtbot):
        b = _band()
        graph.set_bands([b], channel_bypass=False)
        with qtbot.waitSignal(graph.band_q_changed, timeout=1000) as sig:
            graph.wheelEvent(_wheel(_marker_pos(graph, b), notches=-1))
        assert sig.args == [0, -1]

    def test_ctrl_wheel_uses_coarse_step(self, graph, qtbot):
        b = _band()
        graph.set_bands([b], channel_bypass=False)
        with qtbot.waitSignal(graph.band_q_changed, timeout=1000) as sig:
            graph.wheelEvent(_wheel(_marker_pos(graph, b), notches=1, ctrl=True))
        assert sig.args == [0, 5]

    def test_wheel_off_marker_is_ignored_and_silent(self, graph, qtbot):
        graph.set_bands([_band()], channel_bypass=False)
        ev = _wheel(QPointF(5, 5), notches=1)
        with qtbot.assertNotEmitted(graph.band_q_changed):
            graph.wheelEvent(ev)
        # Left unaccepted so it can propagate to a parent.
        assert not ev.isAccepted()

    def test_wheel_over_bypassed_marker_silent(self, graph, qtbot):
        b = _band(bypass=True)
        graph.set_bands([b], channel_bypass=False)
        with qtbot.assertNotEmitted(graph.band_q_changed):
            graph.wheelEvent(_wheel(_marker_pos(graph, b), notches=1))


class TestDoubleClickBypass:
    def test_double_click_active_marker_toggles(self, graph, qtbot):
        b = _band(bypass=False)
        graph.set_bands([b], channel_bypass=False)
        with qtbot.waitSignal(graph.band_bypass_toggled, timeout=1000) as sig:
            graph.mouseDoubleClickEvent(_double_click(_marker_pos(graph, b)))
        assert sig.args == [0]

    def test_double_click_bypassed_marker_toggles(self, graph, qtbot):
        # A dim/bypassed marker must still be reachable so it can be re-enabled.
        b = _band(bypass=True)
        graph.set_bands([b], channel_bypass=False)
        with qtbot.waitSignal(graph.band_bypass_toggled, timeout=1000) as sig:
            graph.mouseDoubleClickEvent(_double_click(_marker_pos(graph, b)))
        assert sig.args == [0]

    def test_double_click_empty_area_silent(self, graph, qtbot):
        graph.set_bands([_band()], channel_bypass=False)
        with qtbot.assertNotEmitted(graph.band_bypass_toggled):
            graph.mouseDoubleClickEvent(_double_click(QPointF(5, 5)))


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

    def test_xover_graph_ignores_wheel_and_double_click(self, qtbot):
        g = FreqResponseGraph(feature="xover")
        qtbot.addWidget(g)
        g.resize(600, 320)
        g.show()
        qtbot.waitExposed(g)
        b = _band()
        g.set_bands([b], channel_bypass=False)
        start = _marker_pos(g, b)

        with qtbot.assertNotEmitted(g.band_q_changed):
            with qtbot.assertNotEmitted(g.band_bypass_toggled):
                g.wheelEvent(_wheel(start, notches=1))
                g.mouseDoubleClickEvent(_double_click(start))


# ------------------------------------------------------------------ #
# Crossover marker dragging (feature == "xover")
# ------------------------------------------------------------------ #


class TestXoverHitTesting:
    def test_hits_hp_marker(self, xover_graph):
        assert xover_graph._hit_xover(_xover_marker_pos(xover_graph, "hp")) == "hp"

    def test_hits_lp_marker(self, xover_graph):
        assert xover_graph._hit_xover(_xover_marker_pos(xover_graph, "lp")) == "lp"

    def test_miss_returns_none(self, xover_graph):
        assert xover_graph._hit_xover(QPointF(5, 5)) is None

    def test_bypassed_half_not_hittable_unless_flagged(self, qtbot):
        # HP bypassed (slope=0), LP active. Drag/wheel must not pick the HP
        # half; double-click may, via include_bypassed=True.
        g = FreqResponseGraph(feature="xover")
        qtbot.addWidget(g)
        g.resize(600, 320)
        g.show()
        qtbot.waitExposed(g)
        g.set_crossover(
            CrossoverData(
                hipass_freq=100,
                hipass_slope=0,
                lopass_freq=200,
                lopass_slope=SLOPE_BW24,
            )
        )
        hp_pos = _xover_marker_pos(g, "hp")
        assert g._hit_xover(hp_pos) is None
        # Closer to LP than to HP, so the active half still wins by distance.
        assert g._hit_xover(hp_pos, include_bypassed=True) == "hp"


class TestXoverDragMapping:
    def test_drag_hp_emits_freq(self, xover_graph, qtbot):
        start = _xover_marker_pos(xover_graph, "hp")
        target = QPointF(start.x() + 80, start.y() - 30)  # vertical ignored

        xover_graph.mousePressEvent(_press(start))
        with qtbot.waitSignal(xover_graph.xover_freq_dragged, timeout=1000) as sig:
            xover_graph.mouseMoveEvent(_move(target))

        which, freq_raw = sig.args
        assert which == "hp"
        assert freq_raw == freq_hz_to_raw(xover_graph._x_to_hz(target.x()))
        # Local crossover is rebuilt for instant feedback.
        assert xover_graph._crossover.hipass_freq == freq_raw
        assert freq_raw > 100  # moved right → higher cutoff

    def test_drag_lp_emits_freq(self, xover_graph, qtbot):
        start = _xover_marker_pos(xover_graph, "lp")
        target = QPointF(start.x() - 80, start.y())

        xover_graph.mousePressEvent(_press(start))
        with qtbot.waitSignal(xover_graph.xover_freq_dragged, timeout=1000) as sig:
            xover_graph.mouseMoveEvent(_move(target))

        which, freq_raw = sig.args
        assert which == "lp"
        assert freq_raw == freq_hz_to_raw(xover_graph._x_to_hz(target.x()))
        assert xover_graph._crossover.lopass_freq == freq_raw
        assert freq_raw < 200  # moved left → lower cutoff

    def test_freq_clamps_at_edges(self, xover_graph, qtbot):
        start = _xover_marker_pos(xover_graph, "hp")

        xover_graph.mousePressEvent(_press(start))
        with qtbot.waitSignal(xover_graph.xover_freq_dragged) as sig_left:
            xover_graph.mouseMoveEvent(_move(QPointF(-100, start.y())))
        assert sig_left.args == ["hp", 0]

        with qtbot.waitSignal(xover_graph.xover_freq_dragged) as sig_right:
            xover_graph.mouseMoveEvent(_move(QPointF(5000, start.y())))
        assert sig_right.args == ["hp", 300]

    def test_release_ends_drag(self, xover_graph):
        start = _xover_marker_pos(xover_graph, "hp")
        xover_graph.mousePressEvent(_press(start))
        assert xover_graph._drag_xover == "hp"
        xover_graph.mouseReleaseEvent(_release(start))
        assert xover_graph._drag_xover is None


class TestXoverWheelSlope:
    def test_wheel_up_over_hp_emits_positive(self, xover_graph, qtbot):
        with qtbot.waitSignal(xover_graph.xover_slope_stepped, timeout=1000) as sig:
            xover_graph.wheelEvent(_wheel(_xover_marker_pos(xover_graph, "hp"), 1))
        assert sig.args == ["hp", 1]

    def test_wheel_down_over_lp_emits_negative(self, xover_graph, qtbot):
        with qtbot.waitSignal(xover_graph.xover_slope_stepped, timeout=1000) as sig:
            xover_graph.wheelEvent(_wheel(_xover_marker_pos(xover_graph, "lp"), -1))
        assert sig.args == ["lp", -1]

    def test_wheel_off_marker_is_ignored_and_silent(self, xover_graph, qtbot):
        ev = _wheel(QPointF(5, 5), notches=1)
        with qtbot.assertNotEmitted(xover_graph.xover_slope_stepped):
            xover_graph.wheelEvent(ev)
        assert not ev.isAccepted()

    def test_wheel_over_bypassed_marker_silent(self, qtbot):
        g = FreqResponseGraph(feature="xover")
        qtbot.addWidget(g)
        g.resize(600, 320)
        g.show()
        qtbot.waitExposed(g)
        g.set_crossover(
            CrossoverData(
                hipass_freq=100,
                hipass_slope=0,
                lopass_freq=200,
                lopass_slope=SLOPE_BW24,
            )
        )
        with qtbot.assertNotEmitted(g.xover_slope_stepped):
            g.wheelEvent(_wheel(_xover_marker_pos(g, "hp"), notches=1))


class TestXoverDoubleClickBypass:
    def test_double_click_active_hp_marker_toggles(self, xover_graph, qtbot):
        with qtbot.waitSignal(xover_graph.xover_bypass_toggled, timeout=1000) as sig:
            xover_graph.mouseDoubleClickEvent(
                _double_click(_xover_marker_pos(xover_graph, "hp"))
            )
        assert sig.args == ["hp"]

    def test_double_click_bypassed_marker_toggles(self, qtbot):
        # A dim/bypassed marker must still be reachable so it can be re-enabled.
        g = FreqResponseGraph(feature="xover")
        qtbot.addWidget(g)
        g.resize(600, 320)
        g.show()
        qtbot.waitExposed(g)
        g.set_crossover(
            CrossoverData(
                hipass_freq=100,
                hipass_slope=0,
                lopass_freq=200,
                lopass_slope=SLOPE_BW24,
            )
        )
        with qtbot.waitSignal(g.xover_bypass_toggled, timeout=1000) as sig:
            g.mouseDoubleClickEvent(_double_click(_xover_marker_pos(g, "hp")))
        assert sig.args == ["hp"]

    def test_double_click_empty_area_silent(self, xover_graph, qtbot):
        with qtbot.assertNotEmitted(xover_graph.xover_bypass_toggled):
            xover_graph.mouseDoubleClickEvent(_double_click(QPointF(5, 5)))


class TestPeqGraphEmitsNoXoverSignals:
    """The xover_* signals must stay silent on a feature='peq' graph."""

    def test_peq_graph_emits_no_xover_signals(self, graph, qtbot):
        # The PEQ-graph fixture has feature='peq' and no crossover data, so
        # none of the xover gestures can find a marker; but they must also
        # not emit even if crossover data is somehow fed in.
        graph.set_crossover(
            CrossoverData(hipass_freq=100, hipass_slope=SLOPE_BW24, lopass_freq=200, lopass_slope=SLOPE_BW24)
        )
        pos = _xover_marker_pos(graph, "hp")
        with qtbot.assertNotEmitted(graph.xover_freq_dragged):
            with qtbot.assertNotEmitted(graph.xover_slope_stepped):
                with qtbot.assertNotEmitted(graph.xover_bypass_toggled):
                    graph.mousePressEvent(_press(pos))
                    graph.mouseMoveEvent(_move(QPointF(pos.x() + 50, pos.y())))
                    graph.mouseReleaseEvent(_release(pos))
                    graph.wheelEvent(_wheel(pos, notches=1))
                    graph.mouseDoubleClickEvent(_double_click(pos))
        assert graph._drag_xover is None
