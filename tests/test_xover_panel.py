"""XoverPanel — silent setters, signal emission, bypass behaviour, and
crossover-related model state / strip indicator tests.

Includes coverage of the direct-manipulation graph slots
(``_on_marker_dragged`` / ``_on_marker_slope_stepped`` /
``_on_marker_bypass_toggled``) that bridge marker gestures on the shared
:class:`FreqResponseGraph` to the panel's row widgets.
"""

from __future__ import annotations

import math

import pytest

from minidsp.protocol import SLOPE_BW24, SLOPE_BW6, SLOPE_LR24
from minidspqt.model import CrossoverState, OutputChannelState
from minidspqt.views.panels import XoverPanel
from minidspqt.widgets.freq_response_graph import (
    CrossoverData,
    FreqResponseGraph,
    _biquad_magnitude_db,
    _crossover_biquads,
    _FS_HZ,
)


@pytest.fixture
def panel(qtbot):
    p = XoverPanel()
    qtbot.addWidget(p)
    return p


# ------------------------------------------------------------------ #
# Silent setter
# ------------------------------------------------------------------ #


class TestSilentSetter:
    def test_set_params_silently_does_not_emit(self, panel, qtbot):
        with qtbot.assertNotEmitted(panel.xover_changed):
            panel.set_params_silently(100, SLOPE_BW24, 200, SLOPE_BW24)

    def test_silent_setter_updates_widgets(self, panel):
        panel.set_params_silently(150, SLOPE_BW24, 250, 0)
        assert panel._hp_freq.value() == 150
        assert panel._hp_slope.currentIndex() == SLOPE_BW24 - 1
        assert panel._hp_bypass.isChecked() is False
        assert panel._lp_freq.value() == 250
        assert panel._lp_slope.currentIndex() == 9  # default LR-24 when bypassed
        assert panel._lp_bypass.isChecked() is True

    def test_silent_setter_does_not_break_subsequent_emits(self, panel, qtbot):
        panel.set_params_silently(100, SLOPE_BW24, 200, SLOPE_BW24)
        with qtbot.waitSignal(panel.xover_changed, timeout=500) as sig:
            panel._hp_freq.setValue(120)
        hp_freq, hp_slope, lp_freq, lp_slope = sig.args
        assert hp_freq == 120
        assert hp_slope == SLOPE_BW24


# ------------------------------------------------------------------ #
# Signal emission
# ------------------------------------------------------------------ #


class TestSignalEmission:
    def test_freq_knob_change_emits(self, panel, qtbot):
        panel.set_params_silently(100, SLOPE_BW24, 200, SLOPE_BW24)
        with qtbot.waitSignal(panel.xover_changed, timeout=500) as sig:
            panel._lp_freq.setValue(180)
        hp_freq, hp_slope, lp_freq, lp_slope = sig.args
        assert lp_freq == 180
        assert hp_freq == 100

    def test_slope_combo_change_emits(self, panel, qtbot):
        panel.set_params_silently(100, 3, 200, 3)  # BW 12
        with qtbot.waitSignal(panel.xover_changed, timeout=500) as sig:
            panel._hp_slope.setCurrentIndex(SLOPE_BW24 - 1)  # switch to BW 24
        hp_freq, hp_slope, lp_freq, lp_slope = sig.args
        assert hp_slope == SLOPE_BW24

    def test_unbypass_activates_slope(self, panel, qtbot):
        panel.set_params_silently(100, SLOPE_BW24, 200, 0)
        with qtbot.waitSignal(panel.xover_changed, timeout=500) as sig:
            panel._hp_bypass.setChecked(True)
        assert sig.args[1] == 0  # bypassed

        with qtbot.waitSignal(panel.xover_changed, timeout=500) as sig2:
            panel._hp_bypass.setChecked(False)
        assert sig2.args[1] == SLOPE_BW24  # re-activated with stored slope

    def test_bypassed_load_shows_default_slope(self, panel):
        panel.set_params_silently(100, 0, 200, 0)
        assert panel._hp_bypass.isChecked() is True
        assert panel._hp_slope.currentIndex() == 9  # LR-24 default
        assert panel._hp_last_slope == 10


# ------------------------------------------------------------------ #
# Bypass
# ------------------------------------------------------------------ #


class TestBypass:
    def test_bypass_toggle_sends_slope_zero(self, panel, qtbot):
        panel.set_params_silently(100, SLOPE_BW24, 200, SLOPE_BW24)
        with qtbot.waitSignal(panel.xover_changed, timeout=500) as sig:
            panel._hp_bypass.setChecked(True)
        hp_freq, hp_slope, lp_freq, lp_slope = sig.args
        assert hp_slope == 0

    def test_is_xover_active_false_when_both_bypassed(self, panel):
        panel.set_params_silently(100, 0, 200, 0)
        assert panel.is_xover_active() is False

    def test_is_xover_active_true_when_hp_active(self, panel):
        panel.set_params_silently(100, SLOPE_BW24, 200, 0)
        assert panel.is_xover_active() is True

    def test_is_xover_active_true_when_lp_active(self, panel):
        panel.set_params_silently(100, 0, 200, SLOPE_BW24)
        assert panel.is_xover_active() is True


# ------------------------------------------------------------------ #
# Model: xover_active property
# ------------------------------------------------------------------ #


class TestXoverActiveProperty:
    def test_default_inactive(self):
        state = OutputChannelState()
        assert state.xover_active is False

    def test_active_when_hipass(self):
        state = OutputChannelState(crossover=CrossoverState(hipass_slope=SLOPE_BW24))
        assert state.xover_active is True

    def test_active_when_lopass(self):
        state = OutputChannelState(crossover=CrossoverState(lopass_slope=SLOPE_BW24))
        assert state.xover_active is True

    def test_inactive_when_both_bypassed(self):
        state = OutputChannelState(
            crossover=CrossoverState(hipass_slope=0, lopass_slope=0)
        )
        assert state.xover_active is False


# ------------------------------------------------------------------ #
# Strip: xover_active indicator
# ------------------------------------------------------------------ #


class TestStripIndicator:
    def test_set_xover_active(self, qtbot):
        from minidspqt.views.channel_strip import OutputChannelStrip

        strip = OutputChannelStrip("Out1")
        qtbot.addWidget(strip)
        btn = strip._toggles["xover"]

        assert btn.property("xover_active") in (None, False)
        strip.set_xover_active(True)
        assert btn.property("xover_active") is True
        strip.set_xover_active(False)
        assert btn.property("xover_active") is False

    def test_xover_button_auto_unchecks(self, qtbot):
        from minidspqt.views.channel_strip import OutputChannelStrip

        strip = OutputChannelStrip("Out1")
        qtbot.addWidget(strip)
        btn = strip._toggles["xover"]

        events = []
        strip.toggle_changed.connect(lambda f, c: events.append((f, c)))
        btn.setChecked(True)
        assert events == [("xover", True)]
        assert btn.isChecked() is False


# ------------------------------------------------------------------ #
# Crossover biquad math
# ------------------------------------------------------------------ #


class TestCrossoverBiquads:
    def test_bypassed_returns_empty(self):
        xo = CrossoverData(hipass_slope=0, lopass_slope=0)
        assert _crossover_biquads(xo) == []

    def test_hipass_only(self):
        xo = CrossoverData(hipass_freq=150, hipass_slope=SLOPE_BW24, lopass_slope=0)
        biquads = _crossover_biquads(xo)
        assert len(biquads) == 2  # BW24 = 2 cascaded 2nd-order

    def test_lopass_only(self):
        from minidsp.protocol import SLOPE_BW12

        xo = CrossoverData(hipass_slope=0, lopass_freq=200, lopass_slope=SLOPE_BW12)
        biquads = _crossover_biquads(xo)
        assert len(biquads) == 1  # BW12 = 1 biquad

    def test_both_active(self):
        from minidsp.protocol import SLOPE_LR24

        xo = CrossoverData(
            hipass_freq=100,
            hipass_slope=SLOPE_BW24,
            lopass_freq=200,
            lopass_slope=SLOPE_LR24,
        )
        biquads = _crossover_biquads(xo)
        assert len(biquads) == 6  # BW24=2 + LR24=4

    def test_hipass_attenuates_low_freq(self):
        biquads = _crossover_biquads(
            CrossoverData(hipass_freq=150, hipass_slope=SLOPE_BW24, lopass_slope=0)
        )
        omega_low = 2.0 * math.pi * 20.0 / _FS_HZ
        db = sum(_biquad_magnitude_db(c, omega_low) for c in biquads)
        assert db < -20  # well below cutoff

    def test_hipass_passes_high_freq(self):
        biquads = _crossover_biquads(
            CrossoverData(hipass_freq=150, hipass_slope=SLOPE_BW24, lopass_slope=0)
        )
        omega_high = 2.0 * math.pi * 10000.0 / _FS_HZ
        db = sum(_biquad_magnitude_db(c, omega_high) for c in biquads)
        assert abs(db) < 0.5  # near unity

    def test_lopass_attenuates_high_freq(self):
        biquads = _crossover_biquads(
            CrossoverData(hipass_slope=0, lopass_freq=150, lopass_slope=SLOPE_BW24)
        )
        omega_high = 2.0 * math.pi * 10000.0 / _FS_HZ
        db = sum(_biquad_magnitude_db(c, omega_high) for c in biquads)
        assert db < -20

    def test_lopass_passes_low_freq(self):
        biquads = _crossover_biquads(
            CrossoverData(hipass_slope=0, lopass_freq=150, lopass_slope=SLOPE_BW24)
        )
        omega_low = 2.0 * math.pi * 20.0 / _FS_HZ
        db = sum(_biquad_magnitude_db(c, omega_low) for c in biquads)
        assert abs(db) < 0.5


# ------------------------------------------------------------------ #
# FreqResponseGraph: set_data / set_crossover / set_bands
# ------------------------------------------------------------------ #


class TestFreqResponseGraph:
    def test_set_crossover_stores_data(self, qtbot):
        g = FreqResponseGraph()
        qtbot.addWidget(g)
        xo = CrossoverData(hipass_freq=100, hipass_slope=SLOPE_BW24)
        g.set_crossover(xo)
        assert g._crossover.hipass_freq == 100
        assert g._crossover.hipass_slope == SLOPE_BW24

    def test_set_bands_stores_data(self, qtbot):
        from minidspqt.model import PEQBand

        g = FreqResponseGraph()
        qtbot.addWidget(g)
        bands = [PEQBand(gain_raw=130)]
        g.set_bands(bands, False)
        assert len(g._bands) == 1
        assert g._channel_bypass is False

    def test_set_data_stores_all(self, qtbot):
        from minidspqt.model import PEQBand

        g = FreqResponseGraph()
        qtbot.addWidget(g)
        bands = [PEQBand(gain_raw=140)]
        xo = CrossoverData(lopass_freq=200, lopass_slope=SLOPE_BW24)
        g.set_data(bands, True, xo)
        assert len(g._bands) == 1
        assert g._channel_bypass is True
        assert g._crossover.lopass_freq == 200


# ------------------------------------------------------------------ #
# Graph-driven slots (_on_marker_*)
# ------------------------------------------------------------------ #


class TestMarkerDraggedSlot:
    def test_hp_drag_sets_knob_and_emits_once(self, panel, qtbot):
        panel.set_params_silently(100, SLOPE_BW24, 200, SLOPE_BW24)
        with qtbot.waitSignal(panel.xover_changed, timeout=500) as sig:
            panel._on_marker_dragged("hp", 150)
        assert panel._hp_freq.value() == 150
        hp_freq, hp_slope, lp_freq, lp_slope = sig.args
        assert hp_freq == 150
        assert hp_slope == SLOPE_BW24  # slope untouched
        assert lp_freq == 200
        assert lp_slope == SLOPE_BW24

    def test_lp_drag_sets_knob_and_emits_once(self, panel, qtbot):
        panel.set_params_silently(100, SLOPE_BW24, 200, SLOPE_BW24)
        with qtbot.waitSignal(panel.xover_changed, timeout=500) as sig:
            panel._on_marker_dragged("lp", 180)
        assert panel._lp_freq.value() == 180
        hp_freq, hp_slope, lp_freq, lp_slope = sig.args
        assert lp_freq == 180
        assert hp_freq == 100

    def test_drag_syncs_graph(self, panel):
        panel.set_params_silently(100, SLOPE_BW24, 200, SLOPE_BW24)
        panel._on_marker_dragged("hp", 175)
        assert panel._graph._crossover.hipass_freq == 175


class TestMarkerSlopeSteppedSlot:
    def test_hp_slope_up_advances_combo_and_emit(self, panel, qtbot):
        panel.set_params_silently(100, SLOPE_BW24, 200, SLOPE_BW24)
        # BW24 = slope 8 → combo index 7; +1 → index 8 = BL24 = slope 9.
        with qtbot.waitSignal(panel.xover_changed, timeout=500) as sig:
            panel._on_marker_slope_stepped("hp", +1)
        assert panel._hp_slope.currentIndex() == 8
        assert sig.args[1] == 9

    def test_lp_slope_down_advances_combo_and_emit(self, panel, qtbot):
        panel.set_params_silently(100, SLOPE_BW24, 200, SLOPE_BW24)
        # BW24 = index 7; -1 → index 6 = BL18 = slope 7.
        with qtbot.waitSignal(panel.xover_changed, timeout=500) as sig:
            panel._on_marker_slope_stepped("lp", -1)
        assert panel._lp_slope.currentIndex() == 6
        assert sig.args[3] == 7

    def test_clamp_at_index_zero_with_minus_one(self, panel, qtbot):
        panel.set_params_silently(100, SLOPE_BW6, 200, SLOPE_BW6)
        # BW6 = index 0; -1 clamps to 0 → no change → no emit.
        with qtbot.assertNotEmitted(panel.xover_changed):
            panel._on_marker_slope_stepped("hp", -1)
        assert panel._hp_slope.currentIndex() == 0

    def test_clamp_at_top_index_with_plus_one(self, panel, qtbot):
        panel.set_params_silently(100, SLOPE_LR24, 200, SLOPE_LR24)
        # LR24 = index 9 (top); +1 clamps to 9 → no change → no emit.
        with qtbot.assertNotEmitted(panel.xover_changed):
            panel._on_marker_slope_stepped("hp", +1)
        assert panel._hp_slope.currentIndex() == 9


class TestMarkerBypassToggledSlot:
    def test_first_call_bypasses(self, panel, qtbot):
        panel.set_params_silently(100, SLOPE_BW24, 200, SLOPE_BW24)
        with qtbot.waitSignal(panel.xover_changed, timeout=500) as sig:
            panel._on_marker_bypass_toggled("hp")
        assert panel._hp_bypass.isChecked() is True
        assert sig.args[1] == 0  # hp_slope now bypassed

    def test_second_call_restores_slope(self, panel, qtbot):
        panel.set_params_silently(100, SLOPE_BW24, 200, SLOPE_BW24)
        panel._on_marker_bypass_toggled("hp")  # bypass
        with qtbot.waitSignal(panel.xover_changed, timeout=500) as sig:
            panel._on_marker_bypass_toggled("hp")  # re-enable
        assert panel._hp_bypass.isChecked() is False
        # Combo kept its position while bypassed → BW24 restored.
        assert sig.args[1] == SLOPE_BW24


class TestMarkerSlotsSlaveLocked:
    """Slots must be no-ops on a linked-slave channel (read-only guard)."""

    def test_dragged_slot_noop_on_slave(self, panel, qtbot):
        panel.set_params_silently(100, SLOPE_BW24, 200, SLOPE_BW24)
        panel.set_linked_slave(True, "Out 1")
        assert panel._hp_freq.isEnabled() is False
        with qtbot.assertNotEmitted(panel.xover_changed):
            panel._on_marker_dragged("hp", 250)
        assert panel._hp_freq.value() == 100  # unchanged

    def test_slope_stepped_slot_noop_on_slave(self, panel, qtbot):
        panel.set_params_silently(100, SLOPE_BW24, 200, SLOPE_BW24)
        panel.set_linked_slave(True, "Out 1")
        with qtbot.assertNotEmitted(panel.xover_changed):
            panel._on_marker_slope_stepped("hp", +1)
        assert panel._hp_slope.currentIndex() == SLOPE_BW24 - 1  # unchanged

    def test_bypass_toggled_slot_noop_on_slave(self, panel, qtbot):
        panel.set_params_silently(100, SLOPE_BW24, 200, SLOPE_BW24)
        panel.set_linked_slave(True, "Out 1")
        with qtbot.assertNotEmitted(panel.xover_changed):
            panel._on_marker_bypass_toggled("hp")
        assert panel._hp_bypass.isChecked() is False  # unchanged
