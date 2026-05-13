"""CompressorGraph — curve math and parameter binding."""

from __future__ import annotations

import math

import pytest

from minidsp.protocol import comp_threshold_to_db
from minidspqt.widgets.compressor_graph import COMP_RATIO_VALUES, CompressorGraph


@pytest.fixture
def graph(qtbot):
    g = CompressorGraph()
    qtbot.addWidget(g)
    return g


# ------------------------------------------------------------------ #
# Parameter binding
# ------------------------------------------------------------------ #


def test_default_state_is_identity(graph):
    """Defaults (threshold +20 dB, ratio 1:1.0, knee 0) collapse to identity."""
    assert graph._threshold_db == pytest.approx(20.0)
    assert graph._ratio == pytest.approx(1.0)
    assert graph._knee_db == pytest.approx(0.0)


def test_set_params_stores_threshold_db(graph):
    graph.set_params(threshold_raw=120, ratio_raw=0, knee_raw=0)
    assert graph._threshold_db == pytest.approx(comp_threshold_to_db(120))


def test_set_params_stores_numeric_ratio(graph):
    graph.set_params(threshold_raw=150, ratio_raw=5, knee_raw=0)  # 1:2.0
    assert graph._ratio == pytest.approx(2.0)


def test_limit_ratio_is_infinite(graph):
    graph.set_params(threshold_raw=150, ratio_raw=15, knee_raw=0)
    assert math.isinf(graph._ratio)


def test_set_params_clamps_out_of_range_ratio(graph):
    """Defensive clamp so a corrupt config can't crash the painter."""
    graph.set_params(threshold_raw=120, ratio_raw=99, knee_raw=0)
    assert graph._ratio == COMP_RATIO_VALUES[15]


# ------------------------------------------------------------------ #
# Static transfer function
# ------------------------------------------------------------------ #


class TestCurveMath:
    def test_baseline_below_threshold_is_identity(self, graph):
        """For inputs well below threshold, output equals input."""
        graph.set_params(
            threshold_raw=160, ratio_raw=9, knee_raw=0
        )  # thr=-10, ratio=4.0
        for x in (-90.0, -60.0, -30.0, -15.0):
            assert graph._curve_db(x) == pytest.approx(x)

    def test_slope_above_threshold_for_hard_knee(self, graph):
        """ratio 1:2.0, hard knee: 10 dB above threshold maps to 5 dB above."""
        graph.set_params(threshold_raw=160, ratio_raw=5, knee_raw=0)
        thr = comp_threshold_to_db(160)
        assert graph._curve_db(thr + 10) == pytest.approx(thr + 5.0)

    def test_continuous_at_threshold_hard_knee(self, graph):
        graph.set_params(threshold_raw=160, ratio_raw=5, knee_raw=0)
        thr = comp_threshold_to_db(160)
        assert graph._curve_db(thr) == pytest.approx(thr)
        # Just above threshold continues with the 1/2 slope, no jump.
        eps = 1e-6
        assert graph._curve_db(thr + eps) == pytest.approx(thr + eps / 2.0)

    def test_limit_ratio_clamps_above_threshold(self, graph):
        """Limit (ratio=∞, hard knee): output never exceeds threshold."""
        graph.set_params(threshold_raw=160, ratio_raw=15, knee_raw=0)
        thr = comp_threshold_to_db(160)
        assert graph._curve_db(thr + 0.1) == pytest.approx(thr)
        assert graph._curve_db(thr + 20.0) == pytest.approx(thr)
        # And still identity below.
        assert graph._curve_db(thr - 20.0) == pytest.approx(thr - 20.0)

    def test_soft_knee_smooths_at_boundary(self, graph):
        """Inside the knee window the curve is neither identity nor fully compressed."""
        graph.set_params(threshold_raw=160, ratio_raw=5, knee_raw=8)
        thr = comp_threshold_to_db(160)
        # Exactly at threshold the soft-knee curve sits below the identity
        # line (we've already started compressing) but above the
        # hard-knee curve at the same point.
        y = graph._curve_db(thr)
        assert y < thr
        # And the knee transitions are smooth: at the low edge, output ==
        # input (identity); at the high edge, output matches the linear
        # compressed region.
        assert graph._curve_db(thr - 4.0) == pytest.approx(thr - 4.0)
        assert graph._curve_db(thr + 4.0) == pytest.approx(thr + 4.0 / 2.0)
