"""FreqResponseGraph — "show other outputs" overlay rendering.

Covers the overlay primitives added for the cross-channel comparison
feature: ``set_overlays`` storage, the shared ``_response_polyline`` /
``_response_coeffs`` helpers (reused by both the active curve and the
overlays), and that overlay colours are keyed by output index.
"""

from __future__ import annotations

import pytest

from minidspqt.model import PEQBand
from minidspqt.theme import theme_manager
from minidspqt.widgets.freq_response_graph import (
    CrossoverData,
    FreqResponseGraph,
    _NUM_SAMPLES,
)


@pytest.fixture
def graph(qtbot):
    g = FreqResponseGraph(feature="peq")
    qtbot.addWidget(g)
    g.resize(400, 200)
    return g


def _active_band() -> PEQBand:
    # +4 dB peak at ~1 kHz, not bypassed → a non-flat response.
    return PEQBand(gain_raw=160, freq_raw=170, q_raw=30, filter_type=0, bypass=False)


class TestSetOverlays:
    def test_set_overlays_stores_entries(self, graph):
        entry = (1, [_active_band()], False, CrossoverData())
        graph.set_overlays([entry])
        assert graph._overlays == [entry]

    def test_set_overlays_clears_with_empty_list(self, graph):
        graph.set_overlays([(1, [_active_band()], False, CrossoverData())])
        graph.set_overlays([])
        assert graph._overlays == []

    def test_set_overlays_copies_input_list(self, graph):
        src = [(1, [_active_band()], False, CrossoverData())]
        graph.set_overlays(src)
        src.clear()
        assert len(graph._overlays) == 1


class TestResponsePolyline:
    def test_active_band_yields_full_polyline(self, graph):
        rect = graph._plot_rect()
        poly = graph._response_polyline([_active_band()], False, CrossoverData(), rect)
        assert poly is not None
        assert poly.count() == _NUM_SAMPLES

    def test_channel_bypass_without_crossover_is_flat(self, graph):
        # Channel-bypassed PEQ with no crossover → no sections → None
        # (overlays skip these; the active curve draws a flat reference).
        rect = graph._plot_rect()
        poly = graph._response_polyline([_active_band()], True, CrossoverData(), rect)
        assert poly is None

    def test_all_bands_bypassed_is_flat(self, graph):
        rect = graph._plot_rect()
        band = _active_band()
        band.bypass = True
        poly = graph._response_polyline([band], False, CrossoverData(), rect)
        assert poly is None

    def test_crossover_alone_yields_polyline_even_when_peq_bypassed(self, graph):
        # A channel-bypassed PEQ still shows its crossover roll-off.
        rect = graph._plot_rect()
        xo = CrossoverData(hipass_freq=120, hipass_slope=4, lopass_freq=0, lopass_slope=0)
        poly = graph._response_polyline([_active_band()], True, xo, rect)
        assert poly is not None
        assert poly.count() == _NUM_SAMPLES


class TestOverlayColour:
    def test_overlay_palette_has_four_distinct_colours(self):
        palette = theme_manager.current.graph_overlay
        assert len(palette) == 4
        names = {c.name() for c in palette}
        assert len(names) == 4  # all distinct
