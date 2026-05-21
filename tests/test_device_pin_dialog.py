"""Dialog interaction tests for UnlockPinDialog and SetPinDialog."""

from __future__ import annotations

import pytest

from minidspqt.views.device_pin_dialog import SetPinDialog, UnlockPinDialog


@pytest.fixture
def unlock_dlg(qtbot):
    dlg = UnlockPinDialog(None)
    qtbot.addWidget(dlg)
    return dlg


@pytest.fixture
def set_dlg(qtbot):
    dlg = SetPinDialog(None)
    qtbot.addWidget(dlg)
    return dlg


# --- UnlockPinDialog ---


class TestUnlockPinDialog:
    def test_unlock_button_disabled_until_4_digits(self, unlock_dlg):
        assert not unlock_dlg._unlock_btn.isEnabled()
        unlock_dlg._pin_edit.setText("12")
        assert not unlock_dlg._unlock_btn.isEnabled()
        unlock_dlg._pin_edit.setText("1234")
        assert unlock_dlg._unlock_btn.isEnabled()

    def test_validator_accepts_printable_ascii(self, unlock_dlg, qtbot):
        # The protocol uses 4 raw bytes; any printable ASCII goes through.
        qtbot.keyClicks(unlock_dlg._pin_edit, "ab12")
        assert unlock_dlg._pin_edit.text() == "ab12"

    def test_max_length_caps_at_4(self, unlock_dlg, qtbot):
        qtbot.keyClicks(unlock_dlg._pin_edit, "abcdef")
        assert unlock_dlg._pin_edit.text() == "abcd"

    def test_pin_entered_signal_carries_typed_pin(self, unlock_dlg, qtbot):
        unlock_dlg._pin_edit.setText("Ab1!")
        with qtbot.waitSignal(unlock_dlg.pinEntered, timeout=500) as caught:
            unlock_dlg._unlock_btn.click()
        assert caught.args == ["Ab1!"]

    def test_double_trigger_only_emits_once(self, unlock_dlg):
        """Regression: pressing Enter on the line-edit AND the default-
        button click both reach _on_accept for a single user action.
        Without the in-flight guard this submits the PIN twice and burns
        two of the three allowed worker attempts on one keystroke — the
        dialog then closes after only two visible tries. The guard keeps
        the second call inert until the worker answers."""
        emissions: list[str] = []
        unlock_dlg.pinEntered.connect(emissions.append)
        unlock_dlg._pin_edit.setText("1234")

        # Simulate the double-trigger: returnPressed fires _on_accept,
        # then the QDialogButtonBox.accepted of the default Ok button
        # fires it again before we hear back from the worker.
        unlock_dlg._on_accept()
        unlock_dlg._on_accept()

        assert emissions == ["1234"]

    def test_unlock_re_enables_after_pin_result(self, unlock_dlg):
        """After the worker reports back (wrong PIN, attempts remaining),
        the dialog must be ready to accept the next attempt — that means
        the in-flight gate is cleared so the next _on_accept goes through."""
        unlock_dlg._pin_edit.setText("1234")
        unlock_dlg._on_accept()  # in-flight = True
        unlock_dlg.on_pin_result(False, 2)  # worker answered: wrong
        assert unlock_dlg._submitting is False
        # And a fresh 4-char entry re-arms the button.
        unlock_dlg._pin_edit.setText("5678")
        assert unlock_dlg._unlock_btn.isEnabled()

    def test_wrong_pin_with_attempts_left_keeps_open(self, unlock_dlg):
        # We track the `finished` signal instead of calling show() and
        # asserting isVisible() — that avoids popping a real window onto
        # the user's desktop during the test run.
        finished: list[int] = []
        unlock_dlg.finished.connect(finished.append)

        unlock_dlg._pin_edit.setText("0000")
        unlock_dlg.on_pin_result(False, 2)

        assert finished == []  # dialog did NOT close
        assert not unlock_dlg._error_label.isHidden()
        assert "2" in unlock_dlg._error_label.text()
        # Input cleared & ready for next attempt.
        assert unlock_dlg._pin_edit.text() == ""

    def test_wrong_pin_zero_attempts_closes(self, unlock_dlg):
        finished: list[int] = []
        unlock_dlg.finished.connect(finished.append)
        unlock_dlg.on_pin_result(False, 0)
        assert finished == [unlock_dlg.DialogCode.Rejected]

    def test_correct_pin_accepts(self, unlock_dlg):
        finished: list[int] = []
        unlock_dlg.finished.connect(finished.append)
        unlock_dlg.on_pin_result(True, 2)
        assert finished == [unlock_dlg.DialogCode.Accepted]

    def test_cancel_emits_cancelled(self, unlock_dlg, qtbot):
        from PySide6.QtWidgets import QDialogButtonBox

        cancel_btn = None
        for btn_box in unlock_dlg.findChildren(QDialogButtonBox):
            cancel_btn = btn_box.button(QDialogButtonBox.StandardButton.Cancel)
            if cancel_btn is not None:
                break
        assert cancel_btn is not None

        with qtbot.waitSignal(unlock_dlg.cancelled, timeout=500):
            cancel_btn.click()


# --- SetPinDialog ---


class TestSetPinDialog:
    def test_set_btn_disabled_initially(self, set_dlg):
        assert not set_dlg._set_btn.isEnabled()

    def test_mismatch_shows_error_and_keeps_btn_disabled(self, set_dlg):
        set_dlg._pin_edit.setText("1234")
        set_dlg._confirm_edit.setText("5678")
        assert not set_dlg._set_btn.isEnabled()
        assert not set_dlg._error_label.isHidden()

    def test_match_enables_and_hides_error(self, set_dlg):
        set_dlg._pin_edit.setText("1234")
        set_dlg._confirm_edit.setText("1234")
        assert set_dlg._set_btn.isEnabled()
        assert set_dlg._error_label.isHidden()

    def test_pin_chosen_emits_on_accept(self, set_dlg, qtbot):
        set_dlg._pin_edit.setText("9999")
        set_dlg._confirm_edit.setText("9999")
        with qtbot.waitSignal(set_dlg.pinChosen, timeout=500) as caught:
            set_dlg._set_btn.click()
        assert caught.args == ["9999"]

    def test_partial_input_keeps_btn_disabled(self, set_dlg):
        set_dlg._pin_edit.setText("12")
        set_dlg._confirm_edit.setText("12")
        # PINs match but aren't 4 digits — still disabled.
        assert not set_dlg._set_btn.isEnabled()
