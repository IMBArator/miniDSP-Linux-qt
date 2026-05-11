"""End-to-end tests for the master→slave parameter-sync feature.

Covers the gap that motivated the channel-linking-sync work: the device
emits no telemetry when its on-board "copy master to slave" logic runs,
so the UI mirror must replicate the fan-out itself on every live edit
*and* keep the detail view in sync with the model.

Tests in this file always seed a state where two pairs are linked:

  - In0 master, In1 slave (input pair)
  - Out0 master, Out1 + Out2 slaves (output triple)
"""

from __future__ import annotations

import copy

import pytest

from minidspqt.model import DeviceState


def _linked_cfg(preset_cfg: dict) -> dict:
    cfg = copy.deepcopy(preset_cfg)
    cfg["link_flags"][0] = 0x03  # In0 master incl. In1
    cfg["link_flags"][1] = 0x00  # In1 slave
    cfg["link_flags"][4] = 0x07  # Out0 master incl. Out1 + Out2
    cfg["link_flags"][5] = 0x00
    cfg["link_flags"][6] = 0x00
    return cfg


@pytest.fixture
def window(qtbot, preset_cfg):
    """A MainWindow with a linked-pair state already loaded.

    The DeviceThread is created but we won't drive any real I/O — tests
    monkeypatch ``request_*`` methods to capture what would be sent.
    """
    from minidspqt.views.main_window import MainWindow

    w = MainWindow(offline=True)
    qtbot.addWidget(w)
    w._state = DeviceState.from_config(_linked_cfg(preset_cfg))
    w._home_view.apply_state(w._state)
    yield w
    w._thread.request_stop()
    w._thread.wait(2000)


# ---------------------------------------------------------------------------
# MainWindow live-edit fan-out
# ---------------------------------------------------------------------------


def test_master_gate_edit_fans_out_to_device(window, monkeypatch):
    """Editing the master's gate should send request_gate for master + slaves."""
    calls: list[tuple] = []
    monkeypatch.setattr(window._thread, "request_gate", lambda *a: calls.append(a))

    window._on_detail_gate_params(0, attack=10, release=20, hold=30, threshold=120)

    assert {c[0] for c in calls} == {0, 1}
    for ch, attack, release, hold, threshold in calls:
        assert (attack, release, hold, threshold) == (10, 20, 30, 120)

    # And the model must reflect the same on both channels
    assert window._state.inputs[0].gate.threshold == 120
    assert window._state.inputs[1].gate.threshold == 120


def test_master_peq_band_edit_fans_out_to_device(window, monkeypatch):
    """A PEQ band edit on Out0 master must hit Out1 and Out2 too."""
    calls: list[tuple] = []
    monkeypatch.setattr(window._thread, "request_peq_band", lambda *a: calls.append(a))

    window._on_detail_peq_band(4, band=2, gain_raw=160, freq_raw=180, q_raw=25, filter_type=0, bypass=False)

    chans = sorted({c[0] for c in calls})
    assert chans == [4, 5, 6]
    # All three carry the same band payload
    for ch, band, gain_raw, freq_raw, q_raw, filter_type, bypass in calls:
        assert (band, gain_raw, freq_raw, q_raw, filter_type, bypass) == (
            2, 160, 180, 25, 0, False,
        )
    # Model mirrors
    for out_idx in (0, 1, 2):
        assert window._state.outputs[out_idx].peqs[2].gain_raw == 160


def test_master_peq_channel_bypass_fans_out(window, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(
        window._thread, "request_peq_channel_bypass", lambda *a: calls.append(a)
    )

    window._on_detail_peq_channel_bypass(4, bypass=True)

    assert sorted(c[0] for c in calls) == [4, 5, 6]
    for ch, bypass in calls:
        assert bypass is True
    for out_idx in (0, 1, 2):
        assert window._state.outputs[out_idx].peq_channel_bypass is True


def test_master_xover_edit_fans_out_to_device(window, monkeypatch):
    hp_calls: list[tuple] = []
    lp_calls: list[tuple] = []
    monkeypatch.setattr(window._thread, "request_hipass", lambda *a: hp_calls.append(a))
    monkeypatch.setattr(window._thread, "request_lopass", lambda *a: lp_calls.append(a))

    window._on_detail_xover_changed(4, hp_freq=120, hp_slope=4, lp_freq=200, lp_slope=6)

    assert sorted(c[0] for c in hp_calls) == [4, 5, 6]
    assert sorted(c[0] for c in lp_calls) == [4, 5, 6]
    for out_idx in (0, 1, 2):
        xo = window._state.outputs[out_idx].crossover
        assert (xo.hipass_freq, xo.hipass_slope, xo.lopass_freq, xo.lopass_slope) == (
            120, 4, 200, 6,
        )


def test_xover_bypass_is_sent_to_device(window, monkeypatch):
    """slope=0 is the on-device bypass command — it MUST be sent, not suppressed.

    Per protocol §0x31/0x32 the device interprets a 0x00 slope byte as
    "filter bypassed". Skipping the request leaves the device's previous
    slope intact, so a hardware restart would re-arm a crossover the user
    just disabled. Regression guard.
    """
    hp_calls: list[tuple] = []
    lp_calls: list[tuple] = []
    monkeypatch.setattr(window._thread, "request_hipass", lambda *a: hp_calls.append(a))
    monkeypatch.setattr(window._thread, "request_lopass", lambda *a: lp_calls.append(a))

    window._on_detail_xover_changed(4, hp_freq=0, hp_slope=0, lp_freq=300, lp_slope=0)

    assert sorted(c[0] for c in hp_calls) == [4, 5, 6]
    assert sorted(c[0] for c in lp_calls) == [4, 5, 6]
    for ch, freq, slope in hp_calls:
        assert slope == 0
    for ch, freq, slope in lp_calls:
        assert slope == 0


def test_active_state_propagates_to_slave_strips(window):
    """After a master edit the slaves' home-view strips must reflect new active flags."""
    # Drive a gate edit that lights the master's Gate indicator
    window._on_detail_gate_params(0, attack=10, release=20, hold=30, threshold=120)
    master_strip = window._home_view._input_strips[0]
    slave_strip = window._home_view._input_strips[1]
    assert master_strip._toggles["gate"].property("gate_active") is True
    assert slave_strip._toggles["gate"].property("gate_active") is True

    # And a PEQ edit that lights output strips
    window._on_detail_peq_band(4, band=0, gain_raw=200, freq_raw=150, q_raw=20, filter_type=0, bypass=False)
    for out_idx in (0, 1, 2):
        btn = window._home_view._output_strips[out_idx]._toggles["peq"]
        assert btn.property("peq_active") is True


# ---------------------------------------------------------------------------
# DetailView link awareness
# ---------------------------------------------------------------------------


def test_detail_view_shows_link_indicator_for_slave(window):
    """Opening detail view on a slave must reveal the link emoji + tooltip."""
    window._show_detail(1)  # In1 is a slave of In0
    strip = window._detail_view._input_strip
    assert not strip._link_label.isHidden()
    assert "InA" in strip._link_label.toolTip()


def test_detail_view_no_indicator_for_standalone(window):
    """Standalone channels (In2, In3) should not show the link indicator."""
    window._show_detail(2)
    strip = window._detail_view._input_strip
    assert strip._link_label.isHidden()


def test_detail_view_apply_state_refreshes_displayed_slave(window):
    """A master-side mutation must visibly update a slave shown in detail view.

    Reproduces the original bug: with the detail view showing the slave,
    a change to the master via the model would not reach the slave's
    strip or feature panel until the user navigated away and back.
    """
    window._show_detail(5)  # Out1 is a slave of Out0
    detail_strip = window._detail_view._output_strip

    # Mutate Out0 (master) directly in the model + refresh the slave.
    window._state.outputs[0].gain_raw = 222
    window._state.outputs[1].gain_raw = 222  # mirror as the live handler would
    window._detail_view.apply_state(window._state)

    assert detail_strip._knob.value() == 222


def test_detail_view_panels_disabled_for_slave(window):
    """Slave channels lock their feature panel inputs and show the banner."""
    window._show_detail(5)  # Out1 slave
    peq = window._detail_view._peq_panel
    xover = window._detail_view._xover_panel

    assert not peq._link_banner.isHidden()
    assert not xover._link_banner.isHidden()
    # Spot-check that the per-band controls and bypass toggle are disabled
    assert peq._channel_bypass.isEnabled() is False
    assert peq._gain_knobs[0].isEnabled() is False
    assert xover._hp_freq.isEnabled() is False


def test_detail_view_panels_enabled_for_master(window):
    """Master + standalone channels should leave panels editable."""
    window._show_detail(4)  # Out0 master
    peq = window._detail_view._peq_panel
    assert peq._link_banner.isHidden()
    assert peq._channel_bypass.isEnabled() is True
    assert peq._gain_knobs[0].isEnabled() is True


def test_detail_view_nav_to_slave_updates_link_indicator(window):
    """Navigating from master to slave inside detail view must flip the indicator."""
    window._show_detail(4)  # Out0 master
    out_strip = window._detail_view._output_strip
    assert out_strip._link_label.isHidden()

    # Simulate the user clicking the Out2 nav button
    window._detail_view._on_output_nav(2)  # Out2 (channel 6) is a slave

    assert not out_strip._link_label.isHidden()


# ---------------------------------------------------------------------------
# Compressor / Delay panels
# ---------------------------------------------------------------------------


def test_compressor_panel_available_on_output_detail(window):
    """Clicking 'Comp' on an output strip lands on the new placeholder panel."""
    window._on_output_feature_toggled(4, "comp", True)
    assert window._stack.currentWidget() is window._detail_view
    assert (
        window._detail_view._content_stack.currentWidget()
        is window._detail_view._compressor_panel
    )


def test_delay_panel_available_on_output_detail(window):
    window._on_output_feature_toggled(4, "delay", True)
    assert (
        window._detail_view._content_stack.currentWidget()
        is window._detail_view._delay_panel
    )


def test_compressor_handler_scaffolds_fan_out(window, monkeypatch):
    """The scaffolded compressor handler should still fan out per-channel."""
    calls: list[tuple] = []
    monkeypatch.setattr(window._thread, "request_compressor", lambda *a: calls.append(a))

    window._on_detail_compressor_changed(
        4, ratio=4, knee=2, attack=15, release=120, threshold=30
    )

    assert sorted(c[0] for c in calls) == [4, 5, 6]
    for out_idx in (0, 1, 2):
        assert window._state.outputs[out_idx].compressor.ratio == 4


def test_compressor_panel_edit_fans_out(window, monkeypatch):
    """Driving the real CompressorPanel must reach all linked channels.

    Verifies the end-to-end signal path:
      panel.compressor_params_changed
        → detail_view._on_compressor_params
        → detail_view.compressor_changed
        → main_window._on_detail_compressor_changed
        → thread.request_compressor / model mutate_with_links.
    """
    calls: list[tuple] = []
    monkeypatch.setattr(window._thread, "request_compressor", lambda *a: calls.append(a))

    window._show_detail(4)  # Out0 master
    panel = window._detail_view._compressor_panel
    panel.set_params_silently(ratio=0, knee=0, attack=49, release=499, threshold=220)
    panel._knob_threshold.setValue(150)  # any control change fires the signal

    assert sorted(c[0] for c in calls) == [4, 5, 6]
    for ch, ratio, knee, attack, release, threshold in calls:
        assert (ratio, knee, attack, release, threshold) == (0, 0, 49, 499, 150)
    for out_idx in (0, 1, 2):
        assert window._state.outputs[out_idx].compressor.threshold == 150


def test_compressor_active_propagates_to_slave_strips(window):
    """Setting ratio > 0 on a master must light the Comp button on every slave."""
    window._on_detail_compressor_changed(
        4, ratio=5, knee=0, attack=49, release=499, threshold=180
    )
    for out_idx in (0, 1, 2):
        btn = window._home_view._output_strips[out_idx]._toggles["comp"]
        assert btn.property("comp_active") is True

    # And clearing it darkens all three.
    window._on_detail_compressor_changed(
        4, ratio=0, knee=0, attack=49, release=499, threshold=220
    )
    for out_idx in (0, 1, 2):
        btn = window._home_view._output_strips[out_idx]._toggles["comp"]
        assert btn.property("comp_active") is False


def test_delay_handler_scaffolds_fan_out(window, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(window._thread, "request_delay", lambda *a: calls.append(a))

    window._on_detail_delay_changed(4, samples=96)

    assert sorted(c[0] for c in calls) == [4, 5, 6]
    for out_idx in (0, 1, 2):
        assert window._state.outputs[out_idx].delay_samples == 96
