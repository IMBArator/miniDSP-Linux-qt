"""PEQPanel — atomic per-band emit, silent setters, channel-bypass behaviour.

The panel emits ``peq_band_changed`` per band (because the device command
0x33 is per-band) and ``peq_channel_bypass_changed`` once for the channel
toggle.  Silent setters used to load device state must never re-emit.
"""

from __future__ import annotations

import pytest

from minidspqt.model import PEQBand
from minidspqt.views.detail_view import DetailView
from minidspqt.views.panels import PEQPanel


@pytest.fixture
def panel(qtbot):
    p = PEQPanel()
    qtbot.addWidget(p)
    return p


def _default_bands() -> list[PEQBand]:
    return [
        PEQBand(gain_raw=120, freq_raw=170, q_raw=16, filter_type=0, bypass=False)
        for _ in range(7)
    ]


class TestSilentSetters:
    def test_set_bands_silently_does_not_emit(self, panel, qtbot):
        with qtbot.assertNotEmitted(panel.peq_band_changed):
            with qtbot.assertNotEmitted(panel.peq_channel_bypass_changed):
                panel.set_bands_silently(_default_bands(), False)

    def test_silent_setter_updates_widgets(self, panel):
        bands = [
            PEQBand(
                gain_raw=120 + b * 5,
                freq_raw=100 + b * 10,
                q_raw=20,
                filter_type=b % 7,
                bypass=(b == 3),
            )
            for b in range(7)
        ]
        panel.set_bands_silently(bands, True)
        assert panel._gain_knobs[2].value() == 130
        assert panel._freq_knobs[2].value() == 120
        assert panel._type_combos[5].currentIndex() == 5
        assert panel._bypass_toggles[3].isChecked() is True
        assert panel._channel_bypass.isChecked() is True

    def test_silent_setter_does_not_break_subsequent_emits(self, panel, qtbot):
        panel.set_bands_silently(_default_bands(), False)
        with qtbot.waitSignal(panel.peq_band_changed, timeout=500) as sig:
            panel._gain_knobs[2].setValue(150)
        assert sig.args[0] == 2
        assert sig.args[1] == 150


class TestAtomicEmit:
    def test_one_knob_change_emits_full_band(self, panel, qtbot):
        panel.set_bands_silently(_default_bands(), False)
        with qtbot.waitSignal(panel.peq_band_changed, timeout=500) as sig:
            panel._freq_knobs[3].setValue(200)
        band, gain, freq, q, ftype, bypass = sig.args
        assert band == 3
        assert freq == 200
        assert gain == 120  # untouched default
        assert q == 16
        assert ftype == 0
        assert bypass is False

    def test_combo_change_emits_band(self, panel, qtbot):
        panel.set_bands_silently(_default_bands(), False)
        with qtbot.waitSignal(panel.peq_band_changed, timeout=500) as sig:
            panel._type_combos[1].setCurrentIndex(2)
        assert sig.args[0] == 1
        assert sig.args[4] == 2

    def test_band_bypass_toggle_emits_band(self, panel, qtbot):
        panel.set_bands_silently(_default_bands(), False)
        with qtbot.waitSignal(panel.peq_band_changed, timeout=500) as sig:
            panel._bypass_toggles[5].setChecked(True)
        assert sig.args[0] == 5
        assert sig.args[5] is True


class TestChannelBypass:
    def test_channel_toggle_emits_only_channel_signal(self, panel, qtbot):
        panel.set_bands_silently(_default_bands(), False)
        with qtbot.waitSignal(panel.peq_channel_bypass_changed, timeout=500) as sig:
            with qtbot.assertNotEmitted(panel.peq_band_changed):
                panel._channel_bypass.setChecked(True)
        assert sig.args[0] is True


class TestFeatureAvailability:
    @pytest.fixture
    def detail(self, qtbot):
        d = DetailView()
        qtbot.addWidget(d)
        return d

    def test_gate_available_for_input_only(self, detail):
        assert detail._feature_available("Gate", True) is True
        assert detail._feature_available("Gate", False) is False

    def test_peq_available_for_output_only(self, detail):
        assert detail._feature_available("PEQ", True) is False
        assert detail._feature_available("PEQ", False) is True

    def test_output_features_available_for_output_only(self, detail):
        assert detail._feature_available("Xover", False) is True
        assert detail._feature_available("Xover", True) is False
        assert detail._feature_available("Comp", False) is True
        assert detail._feature_available("Comp", True) is False
        assert detail._feature_available("Delay", False) is True
        assert detail._feature_available("Delay", True) is False

    def test_unknown_feature_unavailable(self, detail):
        assert detail._feature_available("Bogus", True) is False
        assert detail._feature_available("Bogus", False) is False


class TestPEQActive:
    """The output strip's PEQ button reflects whether any band is shaping signal."""

    def test_state_property_default_inactive(self):
        from minidspqt.model import OutputChannelState, PEQBand

        state = OutputChannelState(
            peqs=[PEQBand(gain_raw=120) for _ in range(7)], peq_channel_bypass=False
        )
        assert state.peq_active is False

    def test_state_property_active_when_one_band_has_gain(self):
        from minidspqt.model import OutputChannelState, PEQBand

        bands = [PEQBand(gain_raw=120) for _ in range(7)]
        bands[3] = PEQBand(gain_raw=160, bypass=False)  # +4 dB
        state = OutputChannelState(peqs=bands)
        assert state.peq_active is True

    def test_state_property_inactive_when_band_bypassed(self):
        from minidspqt.model import OutputChannelState, PEQBand

        bands = [PEQBand(gain_raw=120) for _ in range(7)]
        bands[3] = PEQBand(gain_raw=160, bypass=True)
        state = OutputChannelState(peqs=bands)
        assert state.peq_active is False

    def test_state_property_inactive_when_channel_bypassed(self):
        from minidspqt.model import OutputChannelState, PEQBand

        bands = [PEQBand(gain_raw=160, bypass=False) for _ in range(7)]
        state = OutputChannelState(peqs=bands, peq_channel_bypass=True)
        assert state.peq_active is False

    def test_panel_is_peq_active_reads_widgets(self, panel):
        panel.set_bands_silently(_default_bands(), False)
        assert panel.is_peq_active() is False

        panel._gain_knobs[2].setValueSilently(150)
        assert panel.is_peq_active() is True

        panel._bypass_toggles[2].blockSignals(True)
        panel._bypass_toggles[2].setChecked(True)
        panel._bypass_toggles[2].blockSignals(False)
        assert panel.is_peq_active() is False

    def test_strip_property_set_via_set_peq_active(self, qtbot):
        from minidspqt.views.channel_strip import OutputChannelStrip

        strip = OutputChannelStrip("Out1")
        qtbot.addWidget(strip)
        peq_btn = strip._toggles["peq"]

        assert peq_btn.property("peq_active") in (None, False)
        strip.set_peq_active(True)
        assert peq_btn.property("peq_active") is True
        strip.set_peq_active(False)
        assert peq_btn.property("peq_active") is False


class TestPerTypeQRange:
    """Shelf and pass filters cap Q at raw 35 (Q ≈ 3.0); Peak and Allpass keep
    the full raw 0..100 range, per analysis/protocol.md and the official editor.
    """

    def test_default_peak_uses_full_q_range(self, panel):
        # Default type is Peak (index 0); Q knob max should be 100.
        assert panel._q_knobs[0]._maximum == 100

    @pytest.mark.parametrize(
        "type_index, expected_max",
        [
            (0, 100),  # Peak
            (1, 35),  # Low Shelf
            (2, 35),  # High Shelf
            (3, 35),  # Low Pass
            (4, 35),  # High Pass
            (5, 100),  # Allpass 1st
            (6, 100),  # Allpass 2nd
        ],
    )
    def test_q_max_per_type(self, panel, type_index, expected_max):
        panel._type_combos[2].setCurrentIndex(type_index)
        assert panel._q_knobs[2]._maximum == expected_max

    def test_changing_type_to_shelf_clamps_high_q_value(self, panel, qtbot):
        # Set Q=80 with Peak type — allowed.
        panel._q_knobs[1].setValueSilently(80)
        assert panel._q_knobs[1].value() == 80

        # Switch to Low Shelf — Q must clamp to 35 and emit one band-change.
        with qtbot.waitSignal(panel.peq_band_changed, timeout=500) as sig:
            panel._type_combos[1].setCurrentIndex(1)
        band, gain, freq, q, ftype, bypass = sig.args
        assert band == 1
        assert ftype == 1
        assert q == 35
        assert panel._q_knobs[1].value() == 35

    def test_changing_back_to_peak_does_not_restore_clamped_q(self, panel):
        # Q clamping is one-way: dropping from Peak Q=80 to Shelf clamps to 35;
        # going back to Peak leaves Q at 35 (we don't remember the old value).
        panel._q_knobs[3].setValueSilently(80)
        panel._type_combos[3].setCurrentIndex(1)  # Low Shelf → Q=35
        assert panel._q_knobs[3].value() == 35
        panel._type_combos[3].setCurrentIndex(0)  # Peak again
        assert panel._q_knobs[3]._maximum == 100
        assert panel._q_knobs[3].value() == 35  # not magically restored

    def test_silent_setter_clamps_q_for_shelf(self, panel):
        from minidspqt.model import PEQBand

        bands = [
            PEQBand(gain_raw=120, freq_raw=170, q_raw=20, filter_type=0)
            for _ in range(7)
        ]
        # Out-of-range Q for a Low Shelf should be clamped to 35 on load.
        bands[2] = PEQBand(gain_raw=160, freq_raw=180, q_raw=80, filter_type=1)
        panel.set_bands_silently(bands, False)
        assert panel._type_combos[2].currentIndex() == 1
        assert panel._q_knobs[2]._maximum == 35
        assert panel._q_knobs[2].value() == 35


class TestOutputStripPEQNavigation:
    """The output strip's PEQ button is wired as a momentary nav button."""

    def test_peq_click_auto_unchecks_and_emits(self, qtbot):
        from minidspqt.views.channel_strip import OutputChannelStrip

        strip = OutputChannelStrip("Out1")
        qtbot.addWidget(strip)
        peq_btn = strip._toggles["peq"]

        with qtbot.waitSignal(strip.toggle_changed, timeout=500) as sig:
            peq_btn.click()

        assert sig.args == ["peq", True]
        assert peq_btn.isChecked() is False  # auto-unchecks


class TestMainWindowIntegration:
    """End-to-end: home view PEQ click navigates to the PEQ detail panel."""

    @pytest.fixture
    def window(self, qtbot):
        from minidspqt.model import DeviceState
        from minidspqt.views.main_window import MainWindow
        from tests.conftest import _make_preset_cfg

        # Build offline (so the menu's Save action is enabled and a VirtualDSP
        # is bootstrapped) but seed the state synchronously rather than waiting
        # for the DeviceThread's config_loaded signal — keeps the test fast.
        w = MainWindow(offline=True)
        qtbot.addWidget(w)
        # Stop the worker AND drain queued signals — see the sibling
        # comment in test_channel_linking_sync.py's fixture.
        w._thread.request_stop()
        w._thread.wait(2000)
        qtbot.wait(50)
        cfg = _make_preset_cfg()
        w._state = DeviceState.from_config(cfg)
        w._home_view.apply_state(w._state)
        yield w

    def test_home_peq_click_navigates_to_peq_panel(self, window, qtbot):
        # Click PEQ on Out1 in the home view.
        out_strip = window._home_view._output_strips[0]
        peq_btn = out_strip._toggles["peq"]
        peq_btn.click()

        # Detail view should be the active stack page, on channel 4 (Out1),
        # and the PEQ panel should be the visible feature panel.
        assert window._stack.currentWidget() is window._detail_view
        assert window._detail_view.channel == 4
        assert window._detail_view._feature_name == "PEQ"
        assert (
            window._detail_view._content_stack.currentWidget()
            is window._detail_view.peq_panel
        )

    def test_peq_band_change_calls_thread(self, window, qtbot, monkeypatch):
        captured: list[tuple] = []
        monkeypatch.setattr(
            window._thread,
            "request_peq_band",
            lambda *args: captured.append(args),
        )
        window._show_detail(4)
        window._detail_view.show_feature(4, "PEQ")
        window._detail_view.peq_panel._gain_knobs[2].setValue(150)

        assert len(captured) == 1
        ch, band, gain, freq, q, ftype, bypass = captured[0]
        assert ch == 4
        assert band == 2
        assert gain == 150

    def test_band_edit_lights_up_strip_peq_active(self, window, qtbot):
        window._show_detail(4)
        window._detail_view.show_feature(4, "PEQ")
        out_idx = 0
        home_btn = window._home_view._output_strips[out_idx]._toggles["peq"]
        detail_btn = window._detail_view._output_strip._toggles["peq"]
        assert home_btn.property("peq_active") in (None, False)

        # Lift band 0 gain — the strip should now read as active.
        window._detail_view.peq_panel._gain_knobs[0].setValue(150)
        assert window._state.outputs[out_idx].peq_active is True
        assert home_btn.property("peq_active") is True
        assert detail_btn.property("peq_active") is True

        # Bypass that band — the strip should drop back to inactive.
        window._detail_view.peq_panel._bypass_toggles[0].setChecked(True)
        assert window._state.outputs[out_idx].peq_active is False
        assert home_btn.property("peq_active") is False
        assert detail_btn.property("peq_active") is False

    def test_channel_bypass_drops_peq_active(self, window, qtbot):
        window._show_detail(4)
        window._detail_view.show_feature(4, "PEQ")
        # Make a band non-trivial first.
        window._detail_view.peq_panel._gain_knobs[2].setValue(140)
        out_idx = 0
        home_btn = window._home_view._output_strips[out_idx]._toggles["peq"]
        assert home_btn.property("peq_active") is True

        window._detail_view.peq_panel._channel_bypass.setChecked(True)
        assert window._state.outputs[out_idx].peq_channel_bypass is True
        assert home_btn.property("peq_active") is False

    def test_switching_to_input_shows_placeholder(self, window, qtbot):
        # Open PEQ for Out1.
        window._show_detail(4)
        window._detail_view.show_feature(4, "PEQ")
        assert window._detail_view._feature_name == "PEQ"

        # Now navigate to InA via the in-detail nav buttons.
        window._detail_view._on_input_nav(0)

        # PEQ is not valid for an input, so feature_name resets to Gate
        # and the gate panel is shown.
        assert window._detail_view._feature_name == "Gate"
        assert (
            window._detail_view._content_stack.currentWidget()
            is window._detail_view.gate_panel
        )
