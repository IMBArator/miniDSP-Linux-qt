"""CompressorPanel — silent setters, signal emission, ratio combo,
slave lock, and graph wiring."""

from __future__ import annotations

import pytest

from minidsp.protocol import COMP_RATIO_NAMES, comp_threshold_to_db
from minidspqt.views.panels import CompressorPanel


@pytest.fixture
def panel(qtbot):
    p = CompressorPanel()
    qtbot.addWidget(p)
    return p


# ------------------------------------------------------------------ #
# Ratio combo
# ------------------------------------------------------------------ #


def test_ratio_combo_lists_all_16_names(panel):
    """All 16 protocol ratio names must appear in order."""
    assert panel._ratio_combo.count() == 16
    for raw in range(16):
        assert panel._ratio_combo.itemText(raw) == COMP_RATIO_NAMES[raw]


# ------------------------------------------------------------------ #
# Silent setter
# ------------------------------------------------------------------ #


class TestSilentSetter:
    def test_set_params_silently_does_not_emit(self, panel, qtbot):
        with qtbot.assertNotEmitted(panel.compressor_params_changed):
            panel.set_params_silently(
                ratio=5, knee=4, attack=49, release=499, threshold=180
            )

    def test_silent_setter_updates_widgets(self, panel):
        panel.set_params_silently(
            ratio=9, knee=6, attack=100, release=1000, threshold=120
        )
        assert panel._ratio_combo.currentIndex() == 9
        assert panel._knob_knee.value() == 6
        assert panel._knob_attack.value() == 100
        assert panel._knob_release.value() == 1000
        assert panel._knob_threshold.value() == 120

    def test_silent_setter_does_not_break_subsequent_emits(self, panel, qtbot):
        panel.set_params_silently(
            ratio=2, knee=0, attack=49, release=499, threshold=220
        )
        with qtbot.waitSignal(
            panel.compressor_params_changed, timeout=500
        ) as sig:
            panel._knob_threshold.setValue(120)
        ratio, knee, attack, release, threshold = sig.args
        assert (ratio, knee, attack, release, threshold) == (
            2, 0, 49, 499, 120,
        )


# ------------------------------------------------------------------ #
# Signal emission
# ------------------------------------------------------------------ #


class TestSignalEmission:
    def test_threshold_change_emits_all_five_values(self, panel, qtbot):
        panel.set_params_silently(
            ratio=4, knee=2, attack=60, release=400, threshold=200
        )
        with qtbot.waitSignal(
            panel.compressor_params_changed, timeout=500
        ) as sig:
            panel._knob_threshold.setValue(150)
        assert sig.args == [4, 2, 60, 400, 150]

    def test_ratio_combo_change_emits(self, panel, qtbot):
        panel.set_params_silently(
            ratio=0, knee=0, attack=49, release=499, threshold=220
        )
        with qtbot.waitSignal(
            panel.compressor_params_changed, timeout=500
        ) as sig:
            panel._ratio_combo.setCurrentIndex(7)
        assert sig.args == [7, 0, 49, 499, 220]

    def test_knee_attack_release_each_emit(self, panel, qtbot):
        panel.set_params_silently(
            ratio=3, knee=0, attack=49, release=499, threshold=180
        )
        with qtbot.waitSignal(
            panel.compressor_params_changed, timeout=500
        ) as sig:
            panel._knob_knee.setValue(8)
        assert sig.args == [3, 8, 49, 499, 180]

        with qtbot.waitSignal(
            panel.compressor_params_changed, timeout=500
        ) as sig:
            panel._knob_attack.setValue(120)
        assert sig.args == [3, 8, 120, 499, 180]

        with qtbot.waitSignal(
            panel.compressor_params_changed, timeout=500
        ) as sig:
            panel._knob_release.setValue(2000)
        assert sig.args == [3, 8, 120, 2000, 180]


# ------------------------------------------------------------------ #
# Graph wiring
# ------------------------------------------------------------------ #


def test_graph_threshold_reflects_knob(panel):
    panel._knob_threshold.setValue(150)
    # raw 150 → -15 dB
    assert panel._graph._threshold_db == pytest.approx(
        comp_threshold_to_db(150)
    )


def test_graph_knee_reflects_knob(panel):
    panel._knob_knee.setValue(6)
    assert panel._graph._knee_db == pytest.approx(6.0)


def test_graph_ratio_reflects_combo(panel):
    panel._ratio_combo.setCurrentIndex(5)  # 1:2.0
    assert panel._graph._ratio == pytest.approx(2.0)


def test_graph_limit_ratio_is_infinite(panel):
    panel._ratio_combo.setCurrentIndex(15)  # Limit
    import math

    assert math.isinf(panel._graph._ratio)


# ------------------------------------------------------------------ #
# Slave lock
# ------------------------------------------------------------------ #


def test_slave_lock_disables_all_controls(panel):
    panel.set_linked_slave(True, "Out1")
    assert panel._knob_threshold.isEnabled() is False
    assert panel._ratio_combo.isEnabled() is False
    assert panel._knob_knee.isEnabled() is False
    assert panel._knob_attack.isEnabled() is False
    assert panel._knob_release.isEnabled() is False
    assert not panel._link_banner.isHidden()
    assert "Out1" in panel._link_banner.text()


def test_unlock_re_enables_controls(panel):
    panel.set_linked_slave(True, "Out1")
    panel.set_linked_slave(False, "")
    assert panel._knob_threshold.isEnabled() is True
    assert panel._ratio_combo.isEnabled() is True
    assert panel._knob_knee.isEnabled() is True
    assert panel._knob_attack.isEnabled() is True
    assert panel._knob_release.isEnabled() is True
    assert panel._link_banner.isHidden()
