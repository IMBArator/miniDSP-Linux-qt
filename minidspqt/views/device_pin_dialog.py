"""Modal PIN dialogs for the device-lock / PIN feature.

Two small QDialogs in one file:

* ``UnlockPinDialog`` — shown when the device reports it is locked
  (worker emits ``pin_required``). The user types the 4-character PIN;
  we emit ``pinEntered`` for the worker to try. On a wrong PIN the
  worker reports back via ``pin_result(False, attempts_left)`` and we
  re-prompt; on the last failed attempt the worker has already given
  up so we close.

* ``SetPinDialog`` — admin action to set a new device PIN. Two
  matching 4-character entries; ``pinChosen`` fires on Set. The device
  disconnects after applying the PIN, so the rest of the UX is the
  normal reconnect path, which then triggers the unlock dialog.

Both dialogs follow the modal QDialog pattern used elsewhere in the
codebase (e.g. ``ChannelLinkingDialog``): the dialog owns its widgets,
exposes signals back to the caller, and never touches the device
directly.
"""

from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

PIN_LENGTH = 4

# The protocol doc describes the PIN as "4 ASCII digit characters", but on
# the wire it's just 4 raw bytes — the device accepts any 4 printable
# ASCII chars (digits, letters, punctuation). Restrict to printable ASCII
# (0x20–0x7e) so the user can't accidentally enter control/non-ASCII
# characters that wouldn't survive the round-trip.
_PIN_REGEX = QRegularExpression(r"[\x20-\x7e]{0,4}")


def _make_pin_edit() -> QLineEdit:
    """Build a 4-character password QLineEdit accepting printable ASCII.

    Returns:
        A configured ``QLineEdit`` with a 4-char max length, password
        echo mode, and a regex validator restricting input to
        printable ASCII (0x20–0x7e) so the user can't accidentally
        type control / non-ASCII characters that wouldn't survive
        the round-trip.
    """
    edit = QLineEdit()
    edit.setMaxLength(PIN_LENGTH)
    edit.setEchoMode(QLineEdit.EchoMode.Password)
    edit.setValidator(QRegularExpressionValidator(_PIN_REGEX, edit))
    return edit


class UnlockPinDialog(QDialog):
    """Modal prompt asking the user for the device PIN.

    The worker drives retries: on a wrong PIN the dialog stays open
    with inline feedback ("N attempts remaining"); on exhaustion the
    worker has already disconnected, so the dialog just closes.

    Signals:
        pinEntered (str): User submitted a 4-character PIN. Caller
            forwards to ``DeviceThread.submit_pin``.
        cancelled (): User pressed Cancel. Caller forwards to
            ``DeviceThread.cancel_pin_entry``.
    """

    pinEntered = Signal(str)
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build a fresh unlock prompt.

        Args:
            parent: Qt parent window; the dialog is modal w.r.t. it.
        """
        super().__init__(parent)
        self.setWindowTitle("Unlock device")
        self.setModal(True)
        # Set while a PIN is in flight with the worker so accidental
        # double-triggers (Enter key firing returnPressed *and* the
        # default-button click) don't burn two of the three allowed
        # attempts on a single user action.
        self._submitting = False

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Enter the 4-character device PIN:"))

        self._pin_edit = _make_pin_edit()
        self._pin_edit.textChanged.connect(self._on_text_changed)
        self._pin_edit.returnPressed.connect(self._on_accept)
        layout.addWidget(self._pin_edit)

        self._error_label = QLabel("")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._unlock_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._unlock_btn.setText("Unlock")
        self._unlock_btn.setEnabled(False)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self._on_cancel)
        layout.addWidget(buttons)

    # --- Internal ---

    def _on_text_changed(self, text: str) -> None:
        # When in flight, don't re-enable just because text changed —
        # we're still waiting on a pin_result from the worker.
        if self._submitting:
            return
        self._unlock_btn.setEnabled(len(text) == PIN_LENGTH)

    def _on_accept(self) -> None:
        if self._submitting:
            return
        pin = self._pin_edit.text()
        if len(pin) != PIN_LENGTH:
            return
        self._submitting = True
        self._unlock_btn.setEnabled(False)
        self.pinEntered.emit(pin)

    def _on_cancel(self) -> None:
        self.cancelled.emit()
        self.reject()

    # --- Public slot ---

    def on_pin_result(self, success: bool, attempts_left: int) -> None:
        """Worker → UI feedback after a ``submit_pin`` round.

        Wired to ``DeviceThread.pin_result``. On success the dialog
        accepts and closes; otherwise it shows inline feedback and
        clears the field so the user can retry.

        Args:
            success: True if the device accepted the PIN.
            attempts_left: How many more tries the worker will allow.
                ``<= 0`` means the worker has given up and the dialog
                rejects instead of re-prompting.
        """
        # The in-flight gate is cleared now that the worker has answered.
        self._submitting = False
        if success:
            self.accept()
            return
        if attempts_left <= 0:
            # Worker has already given up — just close.
            self._error_label.setText("Wrong PIN — device locked.")
            self._error_label.setVisible(True)
            self.reject()
            return
        word = "attempt" if attempts_left == 1 else "attempts"
        self._error_label.setText(
            f"Wrong PIN — {attempts_left} {word} remaining"
        )
        self._error_label.setVisible(True)
        self._pin_edit.clear()
        self._pin_edit.setFocus()


class SetPinDialog(QDialog):
    """Admin action: choose a new 4-character PIN and lock the device with it.

    Two matching entries — the Set button stays disabled until both
    fields are full and equal. No "remove PIN" exists in the
    protocol, so the dialog has no opt-out once submitted. The device
    drops the connection after acking; the normal reconnect path
    then triggers ``UnlockPinDialog``.

    Signals:
        pinChosen (str): Emitted on Set with the confirmed PIN.
            Caller forwards to ``DeviceThread.request_set_pin``.
    """

    pinChosen = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build a fresh set-PIN prompt.

        Args:
            parent: Qt parent window; the dialog is modal w.r.t. it.
        """
        super().__init__(parent)
        self.setWindowTitle("Set device PIN")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose a new 4-character PIN:"))
        self._pin_edit = _make_pin_edit()
        layout.addWidget(self._pin_edit)

        layout.addWidget(QLabel("Confirm PIN:"))
        self._confirm_edit = _make_pin_edit()
        layout.addWidget(self._confirm_edit)

        self._error_label = QLabel("")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._set_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._set_btn.setText("Set PIN")
        self._set_btn.setEnabled(False)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._pin_edit.textChanged.connect(self._refresh_state)
        self._confirm_edit.textChanged.connect(self._refresh_state)

    def _refresh_state(self) -> None:
        pin = self._pin_edit.text()
        confirm = self._confirm_edit.text()
        both_full = len(pin) == PIN_LENGTH and len(confirm) == PIN_LENGTH
        match = pin == confirm
        self._set_btn.setEnabled(both_full and match)
        if both_full and not match:
            self._error_label.setText("PINs do not match")
            self._error_label.setVisible(True)
        else:
            self._error_label.setVisible(False)

    def _on_accept(self) -> None:
        pin = self._pin_edit.text()
        if len(pin) != PIN_LENGTH or pin != self._confirm_edit.text():
            return
        self.pinChosen.emit(pin)
        self.accept()
