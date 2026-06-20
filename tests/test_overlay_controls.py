"""OverlayControls — the shared "show other outputs" overlay checkboxes.

Verifies the controller that both the PEQ and Xover panels compose: it hides
the active output's box, shows/relabels the siblings, resets selections on a
channel switch, pushes the checked siblings to the graph, and keeps the boxes
interactive regardless of slave-lock (they are pure view toggles).
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QHBoxLayout, QWidget

from minidspqt.model import PEQBand
from minidspqt.views.panels._overlay_controls import install_overlay_controls
from minidspqt.widgets.freq_response_graph import CrossoverData, FreqResponseGraph


@pytest.fixture
def controls(qtbot):
    """An OverlayControls wired to a real graph, hosted in a shown widget.

    The host is shown so ``isHidden()`` reflects the per-box show/hide calls
    rather than the ancestor's visibility.
    """
    host = QWidget()
    layout = QHBoxLayout(host)
    graph = FreqResponseGraph(feature="peq")
    ctrl = install_overlay_controls(layout, graph)
    # Keep the host (parent of the checkboxes) alive for the test's lifetime;
    # qtbot tracks it for cleanup but we anchor it to the returned graph too.
    graph._keepalive_host = host
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)
    return ctrl, graph


def _band() -> PEQBand:
    return PEQBand(gain_raw=160, freq_raw=170, q_raw=30, filter_type=0, bypass=False)


def _sources_excluding(active_idx: int):
    names = ["Out1", "Out2", "Out3", "Out4"]
    return [
        (i, [_band()], False, CrossoverData(), names[i])
        for i in range(4)
        if i != active_idx
    ]


class TestVisibilityAndLabels:
    def test_active_box_hidden_others_shown(self, controls):
        ctrl, _ = controls
        ctrl.set_sources(0, _sources_excluding(0))
        assert ctrl._checks[0].isHidden()
        assert not ctrl._checks[1].isHidden()
        assert not ctrl._checks[2].isHidden()
        assert not ctrl._checks[3].isHidden()

    def test_sibling_boxes_relabelled(self, controls):
        ctrl, _ = controls
        ctrl.set_sources(0, _sources_excluding(0))
        assert ctrl._checks[1].text() == "Out2"
        assert ctrl._checks[3].text() == "Out4"

    def test_switching_active_relabels_and_hides_new_active(self, controls):
        ctrl, _ = controls
        ctrl.set_sources(0, _sources_excluding(0))
        ctrl.set_sources(2, _sources_excluding(2))
        assert ctrl._checks[2].isHidden()
        assert not ctrl._checks[0].isHidden()


class TestOverlayPush:
    def test_checking_box_pushes_that_source(self, controls):
        ctrl, graph = controls
        ctrl.set_sources(0, _sources_excluding(0))
        ctrl._checks[1].setChecked(True)
        assert len(graph._overlays) == 1
        assert graph._overlays[0][0] == 1  # output index

    def test_unchecking_removes_overlay(self, controls):
        ctrl, graph = controls
        ctrl.set_sources(0, _sources_excluding(0))
        ctrl._checks[1].setChecked(True)
        ctrl._checks[1].setChecked(False)
        assert graph._overlays == []

    def test_multiple_overlays(self, controls):
        ctrl, graph = controls
        ctrl.set_sources(0, _sources_excluding(0))
        ctrl._checks[1].setChecked(True)
        ctrl._checks[3].setChecked(True)
        assert {o[0] for o in graph._overlays} == {1, 3}

    def test_resource_refresh_updates_checked_overlay_data(self, controls):
        ctrl, graph = controls
        ctrl.set_sources(0, _sources_excluding(0))
        ctrl._checks[1].setChecked(True)
        # Re-push the SAME active index with edited band data for output 1.
        edited = PEQBand(gain_raw=200, freq_raw=200, q_raw=40, filter_type=0, bypass=False)
        ctrl.set_sources(
            0,
            [
                (1, [edited], False, CrossoverData(), "Out2"),
                (2, [_band()], False, CrossoverData(), "Out3"),
                (3, [_band()], False, CrossoverData(), "Out4"),
            ],
        )
        # Still checked (no switch) and now carries the edited band.
        assert ctrl._checks[1].isChecked()
        assert len(graph._overlays) == 1
        assert graph._overlays[0][1][0].gain_raw == 200


class TestResetOnSwitch:
    def test_switch_clears_selections(self, controls):
        ctrl, graph = controls
        ctrl.set_sources(0, _sources_excluding(0))
        ctrl._checks[1].setChecked(True)
        ctrl.set_sources(1, _sources_excluding(1))
        assert not any(cb.isChecked() for cb in ctrl._checks)
        assert graph._overlays == []

    def test_same_active_keeps_selection(self, controls):
        ctrl, graph = controls
        ctrl.set_sources(0, _sources_excluding(0))
        ctrl._checks[2].setChecked(True)
        ctrl.set_sources(0, _sources_excluding(0))
        assert ctrl._checks[2].isChecked()
        assert len(graph._overlays) == 1


class TestAlwaysInteractive:
    def test_boxes_enabled_by_default(self, controls):
        ctrl, _ = controls
        ctrl.set_sources(0, _sources_excluding(0))
        assert all(cb.isEnabled() for cb in ctrl._checks)
