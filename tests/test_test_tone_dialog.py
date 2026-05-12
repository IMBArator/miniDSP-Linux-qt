"""TestToneDialog — initial state, apply emission, panic-button behaviour."""

from __future__ import annotations

import pytest

from minidsp.protocol import (
    SINE_FREQ_1KHZ,
    SINE_FREQ_20HZ,
    TONE_OFF,
    TONE_PINK,
    TONE_SINE,
    TONE_WHITE,
)

from minidspqt.model import DeviceState, TestToneState
from minidspqt.views.test_tone_dialog import TestToneDialog, _FREQ_LABELS


def _state(mode: int = TONE_OFF, freq_index: int = 0) -> DeviceState:
    """Build a minimal DeviceState carrying a specific tone configuration.

    We don't go through DeviceState.from_config here — the dialog only
    reads state.test_tone, so a hand-built dataclass is enough.
    """
    s = DeviceState()
    s.test_tone = TestToneState(mode=mode, sine_freq_index=freq_index)
    return s


@pytest.fixture
def dialog(qtbot):
    dlg = TestToneDialog(None, _state())
    qtbot.addWidget(dlg)
    return dlg


class TestInitialState:
    def test_31_freq_labels(self):
        # Sanity: the device exposes 31 ISO 1/3-octave steps.
        assert len(_FREQ_LABELS) == 31

    def test_off_state_radio_and_freq(self, dialog):
        assert dialog.current_mode() == TONE_OFF
        assert dialog.current_freq_index() == 0
        assert dialog._wave_radios[0].isChecked()  # Off radio

    def test_sine_state_reflects_freq(self, qtbot):
        dlg = TestToneDialog(None, _state(TONE_SINE, SINE_FREQ_1KHZ))
        qtbot.addWidget(dlg)
        assert dlg.current_mode() == TONE_SINE
        assert dlg.current_freq_index() == SINE_FREQ_1KHZ
        assert dlg._freq_label.text() == _FREQ_LABELS[SINE_FREQ_1KHZ]

    def test_freq_spin_disabled_unless_sine(self, dialog):
        # Off: spin disabled.
        assert not dialog._freq_spin.isEnabled()
        # Switch to Sine → spin enabled.
        dialog._wave_radios[3].setChecked(True)  # index 3 == Sine
        assert dialog._freq_spin.isEnabled()
        # Back to Off → spin disabled again.
        dialog._wave_radios[0].setChecked(True)
        assert not dialog._freq_spin.isEnabled()

    def test_stop_button_disabled_when_off(self, dialog):
        assert not dialog._stop_btn.isEnabled()

    def test_stop_button_stays_disabled_when_non_off_selected_but_not_applied(
        self, dialog
    ):
        # Selecting a non-Off radio alone must NOT arm the stop button —
        # the tone isn't running until Apply is clicked.
        dialog._wave_radios[1].setChecked(True)  # Pink selected
        assert not dialog._stop_btn.isEnabled()

    def test_stop_button_enabled_after_refresh_with_active_mode(self, qtbot):
        # Only refresh() (i.e. applied state) arms the button.
        for mode in (TONE_PINK, TONE_WHITE, TONE_SINE):
            dlg = TestToneDialog(None, _state(mode))
            qtbot.addWidget(dlg)
            assert dlg._stop_btn.isEnabled(), f"mode={mode}"


class TestApply:
    def test_apply_emits_mode_and_freq(self, dialog, qtbot):
        # Pick Sine + 1 kHz.
        dialog._wave_radios[3].setChecked(True)
        dialog._freq_spin.setValue(SINE_FREQ_1KHZ)

        with qtbot.waitSignal(dialog.applyRequested, timeout=500) as caught:
            dialog._on_apply_clicked()

        assert caught.args == [TONE_SINE, SINE_FREQ_1KHZ]

    def test_apply_keeps_dialog_visible(self, dialog, qtbot):
        # Mirror Channel Linking: Apply must NOT close the dialog.
        dialog.show()
        assert dialog.isVisible()
        with qtbot.waitSignal(dialog.applyRequested):
            dialog._on_apply_clicked()
        assert dialog.isVisible()

    def test_apply_off_mode_still_sends_freq(self, dialog, qtbot):
        # Even in Off mode, the current freq spin value rides along — the
        # device persists it so the next Sine session resumes where the
        # user left off.
        dialog._wave_radios[3].setChecked(True)
        dialog._freq_spin.setValue(SINE_FREQ_1KHZ)
        dialog._wave_radios[0].setChecked(True)  # back to Off

        with qtbot.waitSignal(dialog.applyRequested) as caught:
            dialog._on_apply_clicked()

        assert caught.args == [TONE_OFF, SINE_FREQ_1KHZ]


class TestPanicButton:
    def test_disable_emits_signal(self, qtbot):
        dlg = TestToneDialog(None, _state(TONE_PINK))
        qtbot.addWidget(dlg)
        with qtbot.waitSignal(dlg.disableRequested, timeout=500):
            dlg._stop_btn.click()

    def test_disable_flips_radio_to_off(self, qtbot):
        dlg = TestToneDialog(None, _state(TONE_SINE, SINE_FREQ_1KHZ))
        qtbot.addWidget(dlg)
        assert dlg.current_mode() == TONE_SINE

        dlg._stop_btn.click()

        assert dlg.current_mode() == TONE_OFF
        # Stop button itself should now be disabled (nothing to silence).
        assert not dlg._stop_btn.isEnabled()

    def test_disable_does_not_emit_applyrequested(self, qtbot):
        # The panic button is a separate channel; the main window's
        # disable handler does the device write, not Apply.
        dlg = TestToneDialog(None, _state(TONE_PINK))
        qtbot.addWidget(dlg)

        received: list = []
        dlg.applyRequested.connect(lambda *a: received.append(a))
        dlg._stop_btn.click()
        # Pump events so any pending signal fires.
        qtbot.wait(20)
        assert received == []


class TestRefresh:
    def test_refresh_snaps_back_to_device_state(self, dialog):
        # Optimistically flip to Sine + 1 kHz...
        dialog._wave_radios[3].setChecked(True)
        dialog._freq_spin.setValue(SINE_FREQ_1KHZ)
        # ...then the device says "actually I'm Pink at 20 Hz".
        dialog.refresh(_state(TONE_PINK, SINE_FREQ_20HZ))

        assert dialog.current_mode() == TONE_PINK
        assert dialog.current_freq_index() == SINE_FREQ_20HZ
        # Sine wasn't picked → freq spin disabled.
        assert not dialog._freq_spin.isEnabled()

    def test_refresh_clamps_out_of_range_freq(self, dialog):
        # The device should never report this, but be defensive — a
        # corrupted config byte shouldn't crash the dialog.
        dialog.refresh(_state(TONE_SINE, 99))
        assert dialog.current_freq_index() == len(_FREQ_LABELS) - 1

    def test_refresh_does_not_emit_apply(self, dialog, qtbot):
        # Refreshing must not trigger spurious applyRequested via toggle
        # callbacks — that would create a feedback loop with the main
        # window's config-loaded → sync_test_tone_dialog chain.
        received: list = []
        dialog.applyRequested.connect(lambda *a: received.append(a))
        dialog.refresh(_state(TONE_SINE, SINE_FREQ_1KHZ))
        qtbot.wait(20)
        assert received == []
