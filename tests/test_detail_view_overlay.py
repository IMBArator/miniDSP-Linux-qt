"""DetailView — feeds sibling-output overlay sources to both output graphs.

Selecting an output channel should push the *other three* outputs to the PEQ
and Xover panels' overlay controls (so they can be overlaid for comparison),
and re-applying state should refresh a checked overlay's data live.
"""

from __future__ import annotations

import pytest

from minidspqt.model import (
    CrossoverState,
    DeviceState,
    InputChannelState,
    OutputChannelState,
    PEQBand,
)
from minidspqt.views.detail_view import DetailView


@pytest.fixture
def detail(qtbot):
    d = DetailView()
    qtbot.addWidget(d)
    return d


def _state(out0_gain=160) -> DeviceState:
    inputs = [InputChannelState(name=f"In{i}") for i in range(4)]
    outputs = []
    for i in range(4):
        outputs.append(
            OutputChannelState(
                name=f"Out{i + 1}",
                peqs=[
                    PEQBand(
                        gain_raw=(out0_gain if i == 0 else 120),
                        freq_raw=170,
                        q_raw=30,
                        filter_type=0,
                    )
                ],
                crossover=CrossoverState(),
            )
        )
    return DeviceState(connected=True, inputs=inputs, outputs=outputs)


class TestOverlaySourcePush:
    def test_selecting_output_pushes_three_siblings(self, detail):
        detail.set_channel(4, _state())  # Out1 (output index 0)
        overlay = detail.peq_panel._overlay
        assert overlay._active_idx == 0
        assert set(overlay._sources.keys()) == {1, 2, 3}
        assert overlay._checks[0].isHidden()

    def test_both_panels_receive_sources(self, detail):
        detail.set_channel(5, _state())  # Out2 (output index 1)
        assert detail.peq_panel._overlay._active_idx == 1
        assert detail.xover_panel._overlay._active_idx == 1
        assert set(detail.xover_panel._overlay._sources.keys()) == {0, 2, 3}

    def test_sibling_names_propagate(self, detail):
        detail.set_channel(4, _state())
        # Box for output index 1 should be labelled "Out2".
        assert detail.peq_panel._overlay._checks[1].text() == "Out2"

    def test_checked_overlay_tracks_live_edit(self, detail):
        detail.set_channel(4, _state(out0_gain=160))  # viewing Out1
        # Overlay output index 1 (Out2)…
        detail.peq_panel._overlay._checks[1].setChecked(True)
        graph = detail.peq_panel._graph
        assert graph._overlays[0][0] == 1
        # Edit Out2's band and re-apply → overlay data refreshes (same active).
        st = _state()
        st.outputs[1].peqs[0].gain_raw = 200
        detail.apply_state(st)
        assert detail.peq_panel._overlay._checks[1].isChecked()
        assert graph._overlays[0][1][0].gain_raw == 200
