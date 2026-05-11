"""DelayPanel — signal emission, silent setters, parsing, slave lock."""

from __future__ import annotations

import pytest

from minidspqt.views.panels.delay_panel import (
    DelayPanel,
    _fmt_delay,
    _parse_delay,
)


@pytest.fixture
def panel(qtbot):
    p = DelayPanel()
    qtbot.addWidget(p)
    return p


# ------------------------------------------------------------------ #
# Format / parse helpers
# ------------------------------------------------------------------ #


class TestFormatDelay:
    def test_zero(self):
        assert _fmt_delay(0) == "0.000 ms"

    def test_exact_ms(self):
        # 480 samples / 48 kHz = exactly 10.000 ms
        assert _fmt_delay(480) == "10.000 ms"

    def test_sub_ms_resolution(self):
        # 1 sample / 48 kHz = 0.02083… ms -> 0.021 ms at 3 dp
        assert _fmt_delay(1) == "0.021 ms"

    def test_round_trip_ms(self):
        # 601 samples / 48 kHz = 12.52083… ms -> 12.521 ms at 3 dp
        assert _fmt_delay(601) == "12.521 ms"

    def test_max(self):
        # 32640 samples / 48 = 680.000 ms
        assert _fmt_delay(32640) == "680.000 ms"


class TestParseDelay:
    def test_ms_with_suffix(self):
        # 12.5 ms = 600 samples exactly
        assert _parse_delay("12.5 ms") == 600

    def test_ms_no_suffix_treated_as_ms(self):
        assert _parse_delay("10") == 480  # 10 ms

    def test_samples_explicit(self):
        assert _parse_delay("601 samples") == 601
        assert _parse_delay("601 sample") == 601
        assert _parse_delay("601 sa") == 601

    def test_clamps_below_zero(self):
        assert _parse_delay("-5 ms") == 0

    def test_clamps_above_max(self):
        assert _parse_delay("9999 ms") == 32640
        assert _parse_delay("99999 samples") == 32640


# ------------------------------------------------------------------ #
# Silent setter
# ------------------------------------------------------------------ #


class TestSilentSetter:
    def test_set_delays_silently_does_not_emit(self, panel, qtbot):
        with qtbot.assertNotEmitted(panel.delay_changed):
            panel.set_delays_silently([10, 20, 30, 40])

    def test_silent_setter_populates_graph(self, panel):
        panel.set_delays_silently([100, 200, 300, 400])
        assert panel._graph._samples == [100, 200, 300, 400]

    def test_silent_setter_updates_active_knob(self, panel):
        panel.set_active_channel(2, "Out3", 0)
        panel.set_delays_silently([10, 20, 999, 40])
        # Active row is index 2 -> knob mirrors the third value.
        assert panel._knob.value() == 999

    def test_silent_setter_wrong_length_is_no_op(self, panel, qtbot):
        panel.set_delays_silently([10, 20])  # only 2 entries
        assert panel._graph._samples == [0, 0, 0, 0]


# ------------------------------------------------------------------ #
# set_active_channel
# ------------------------------------------------------------------ #


class TestSetActiveChannel:
    def test_updates_label_and_graph_row(self, panel):
        panel.set_active_channel(2, "Sub L", 600)
        assert panel._active_label.text() == "Sub L"
        assert panel._graph._active_row == 2

    def test_updates_knob_value_silently(self, panel, qtbot):
        with qtbot.assertNotEmitted(panel.delay_changed):
            panel.set_active_channel(1, "Out2", 480)
        assert panel._knob.value() == 480

    def test_writes_into_stored_samples(self, panel):
        panel.set_active_channel(3, "Out4", 1234)
        assert panel._graph._samples[3] == 1234


# ------------------------------------------------------------------ #
# Signal emission
# ------------------------------------------------------------------ #


def test_knob_change_emits_signal(panel, qtbot):
    panel.set_active_channel(0, "Out1", 0)
    with qtbot.waitSignal(panel.delay_changed, timeout=500) as sig:
        panel._knob.setValue(240)
    assert sig.args == [240]


def test_knob_change_updates_graph_synchronously(panel):
    panel.set_active_channel(1, "Out2", 0)
    panel._knob.setValue(960)
    # The active row's bar should follow the drag without waiting for a
    # round-trip through the model.
    assert panel._graph._samples[1] == 960


def test_knob_change_only_touches_active_row(panel):
    panel.set_delays_silently([100, 200, 300, 400])
    panel.set_active_channel(2, "Out3", 300)
    panel._knob.setValue(500)
    assert panel._graph._samples == [100, 200, 500, 400]


# ------------------------------------------------------------------ #
# Slave lock
# ------------------------------------------------------------------ #


def test_slave_lock_disables_knob_only(panel):
    panel.set_linked_slave(True, "Out1")
    assert panel._knob.isEnabled() is False
    # Graph stays enabled — it's read-only context.
    assert panel._graph.isEnabled() is True
    assert not panel._link_banner.isHidden()
    assert "Out1" in panel._link_banner.text()


def test_unlock_re_enables_knob(panel):
    panel.set_linked_slave(True, "Out1")
    panel.set_linked_slave(False, "")
    assert panel._knob.isEnabled() is True
    assert panel._link_banner.isHidden()


# ------------------------------------------------------------------ #
# Channel names propagation
# ------------------------------------------------------------------ #


def test_set_channel_names_forwards_to_graph(panel):
    panel.set_channel_names(["Sub L", "Sub R", "Top L", "Top R"])
    assert panel._graph._names == ["Sub L", "Sub R", "Top L", "Top R"]
