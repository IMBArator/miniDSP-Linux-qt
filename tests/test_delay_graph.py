"""DelayGraph — state setters and clamping."""

from __future__ import annotations

import pytest

from minidspqt.widgets.delay_graph import DelayGraph


@pytest.fixture
def graph(qtbot):
    g = DelayGraph()
    qtbot.addWidget(g)
    return g


# ------------------------------------------------------------------ #
# Defaults
# ------------------------------------------------------------------ #


def test_default_state(graph):
    assert graph._samples == [0, 0, 0, 0]
    assert graph._active_row == 0
    assert graph._names == ["Out1", "Out2", "Out3", "Out4"]


# ------------------------------------------------------------------ #
# set_delays
# ------------------------------------------------------------------ #


def test_set_delays_stores_values(graph):
    graph.set_delays([10, 20, 30, 40])
    assert graph._samples == [10, 20, 30, 40]


def test_set_delays_clamps_out_of_range(graph):
    """Defensive clamp: a corrupt config can't blow up the painter."""
    graph.set_delays([-5, 99999, 600, 0])
    assert graph._samples == [0, 32640, 600, 0]


def test_set_delays_wrong_length_is_no_op(graph):
    graph.set_delays([100, 200])  # only 2 entries
    assert graph._samples == [0, 0, 0, 0]


def test_set_delays_idempotent(graph):
    graph.set_delays([100, 200, 300, 400])
    before = list(graph._samples)
    graph.set_delays([100, 200, 300, 400])
    assert graph._samples == before


# ------------------------------------------------------------------ #
# set_active_row
# ------------------------------------------------------------------ #


def test_set_active_row(graph):
    graph.set_active_row(2)
    assert graph._active_row == 2


def test_set_active_row_clamps(graph):
    graph.set_active_row(99)
    assert graph._active_row == 3
    graph.set_active_row(-1)
    assert graph._active_row == 0


# ------------------------------------------------------------------ #
# set_channel_names
# ------------------------------------------------------------------ #


def test_set_channel_names(graph):
    graph.set_channel_names(["Sub L", "Sub R", "Top L", "Top R"])
    assert graph._names == ["Sub L", "Sub R", "Top L", "Top R"]


def test_set_channel_names_wrong_length_is_no_op(graph):
    graph.set_channel_names(["A", "B"])
    assert graph._names == ["Out1", "Out2", "Out3", "Out4"]


# ------------------------------------------------------------------ #
# Dynamic axis range
# ------------------------------------------------------------------ #


class TestAxisRange:
    def test_all_zero_uses_minimum_range(self, graph):
        graph.set_delays([0, 0, 0, 0])
        assert graph._current_axis_max_ms() == pytest.approx(20.0)

    def test_axis_snaps_up_to_next_20ms(self, graph):
        graph.set_delays([0, 0, 0, 48 * 5])      # 5 ms → 20 ms axis
        assert graph._current_axis_max_ms() == pytest.approx(20.0)
        graph.set_delays([0, 0, 0, 48 * 21])     # 21 ms → 40 ms axis
        assert graph._current_axis_max_ms() == pytest.approx(40.0)
        graph.set_delays([0, 0, 0, 48 * 40])     # exactly 40 ms → 40 ms axis
        assert graph._current_axis_max_ms() == pytest.approx(40.0)

    def test_axis_respects_largest_channel(self, graph):
        # A single large value drives the whole axis.
        graph.set_delays([48 * 100, 48 * 5, 48 * 5, 48 * 5])
        assert graph._current_axis_max_ms() == pytest.approx(100.0)

    def test_protocol_max_clamps_to_680(self, graph):
        graph.set_delays([32640, 0, 0, 0])
        assert graph._current_axis_max_ms() == pytest.approx(680.0)

    def test_axis_shrinks_when_max_drops(self, graph):
        graph.set_delays([48 * 200, 0, 0, 0])
        assert graph._current_axis_max_ms() == pytest.approx(200.0)
        graph.set_delays([0, 0, 0, 48 * 5])
        assert graph._current_axis_max_ms() == pytest.approx(20.0)


class TestGridTicks:
    def test_low_range_uses_20ms_step(self, graph):
        assert graph._grid_ticks_ms(100.0) == (
            0.0, 20.0, 40.0, 60.0, 80.0, 100.0,
        )

    def test_high_range_uses_100ms_step(self, graph):
        assert graph._grid_ticks_ms(400.0) == (
            0.0, 100.0, 200.0, 300.0, 400.0,
        )

    def test_always_anchors_at_endpoints(self, graph):
        for upper in (20.0, 60.0, 120.0, 680.0):
            ticks = graph._grid_ticks_ms(upper)
            assert ticks[0] == pytest.approx(0.0)
            assert ticks[-1] == pytest.approx(upper)

    def test_boundary_collapse_avoids_crowded_labels(self, graph):
        # At upper=120 with the 100 ms step, the would-be 100 ms label
        # sits inside half a step of the endpoint, so it's absorbed into
        # the 120 ms endpoint — only 0 and 120 are labelled.
        assert graph._grid_ticks_ms(120.0) == (0.0, 120.0)
