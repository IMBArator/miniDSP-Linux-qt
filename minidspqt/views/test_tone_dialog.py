"""TestToneDialog — popup to drive the device's internal signal generator.

The DSP exposes a one-shot internal generator (Off / Pink / White / Sine).
Sine mode picks a frequency from a 31-step ISO 1/3-octave series (20 Hz …
20 kHz). State is persisted at config offsets 420/422, so reopening the
dialog (or power-cycling the DSP) reflects whatever the generator is
currently doing.

Like ChannelLinkingDialog, this dialog is non-modal and stays open after
Apply — the user typically wants to step through frequencies or swap
waveforms back-to-back. ``applyRequested(mode, freq_index)`` is emitted
on Apply; the caller writes through the device thread and triggers a
config re-read, then calls :meth:`refresh` to snap the UI to truth.

A separate big red "Disable test tone" button (object name
``testToneStopButton``) is the panic stop — it emits ``disableRequested``
and flips the local radio to Off without prompting.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from minidsp.protocol import TONE_OFF, TONE_PINK, TONE_SINE, TONE_WHITE

from ..model import DeviceState

# 31 ISO 1/3-octave labels matching minidsp.protocol.SINE_FREQ_* indices 0..30.
# Hard-coded (rather than reflected from the constant names) because the
# series is fixed by the device firmware and the labels are friendlier than
# parsing "SINE_FREQ_1K25HZ" → "1.25 kHz".
_FREQ_LABELS: tuple[str, ...] = (
    "20 Hz",
    "25 Hz",
    "31 Hz",
    "40 Hz",
    "50 Hz",
    "63 Hz",
    "80 Hz",
    "100 Hz",
    "125 Hz",
    "160 Hz",
    "200 Hz",
    "250 Hz",
    "315 Hz",
    "400 Hz",
    "500 Hz",
    "630 Hz",
    "800 Hz",
    "1 kHz",
    "1.25 kHz",
    "1.6 kHz",
    "2 kHz",
    "2.5 kHz",
    "3.15 kHz",
    "4 kHz",
    "5 kHz",
    "6.3 kHz",
    "8 kHz",
    "10 kHz",
    "12.5 kHz",
    "16 kHz",
    "20 kHz",
)

_MODES = (TONE_OFF, TONE_PINK, TONE_WHITE, TONE_SINE)
_MODE_LABELS = ("Off", "Pink noise", "White noise", "Sine")


class TestToneDialog(QDialog):
    """Non-modal dialog to control the internal test signal generator.

    Stays open so the user can flip frequencies and listen
    continuously. The generator is device-wide — switching modes here
    affects every output. The big red panic button issues
    ``disableRequested`` so the user can drop the tone with one click
    from anywhere in the dialog.

    Signals:
        applyRequested (int, int): ``(mode, freq_index)`` where mode
            is one of ``TONE_OFF``/``TONE_PINK``/``TONE_WHITE``/
            ``TONE_SINE``. ``freq_index`` is always sent — the device
            ignores it for non-sine modes but stores it so a later
            sine selection picks the user's last frequency.
        disableRequested (): Emitted by the panic button. Caller
            sends ``TONE_OFF`` and refreshes the dialog.
    """

    # Suppresses pytest's name-based collection heuristic that otherwise
    # tries to treat this class as a test class.
    __test__ = False

    applyRequested = Signal(int, int)
    disableRequested = Signal()

    def __init__(self, parent: QWidget | None, state: DeviceState) -> None:
        """Build the dialog with widgets reflecting ``state.test_tone``.

        Args:
            parent: Qt parent window. The dialog is non-modal so it
                will not block the parent.
            state: Current device state; the dialog seeds its radios
                and frequency spinbox from ``state.test_tone``.
        """
        super().__init__(parent)
        self.setWindowTitle("Test tone")
        self.setMinimumWidth(320)

        root = QVBoxLayout(self)

        # --- Waveform group ---------------------------------------------
        wave_group = QGroupBox("Waveform")
        wave_row = QHBoxLayout(wave_group)
        self._wave_group = QButtonGroup(self)
        self._wave_radios: list[QRadioButton] = []
        for mode, label in zip(_MODES, _MODE_LABELS):
            rb = QRadioButton(label)
            self._wave_group.addButton(rb, mode)
            wave_row.addWidget(rb)
            self._wave_radios.append(rb)
        root.addWidget(wave_group)

        # --- Sine frequency group ---------------------------------------
        freq_group = QGroupBox("Sine frequency")
        freq_row = QHBoxLayout(freq_group)
        self._freq_spin = QSpinBox()
        self._freq_spin.setRange(0, len(_FREQ_LABELS) - 1)
        # Suffix shows the friendly label; the value itself is the raw index.
        self._freq_spin.setWrapping(False)
        self._freq_label = QLabel(_FREQ_LABELS[0])
        self._freq_label.setObjectName("testToneFreqLabel")
        self._freq_spin.valueChanged.connect(self._on_freq_value_changed)
        freq_row.addWidget(self._freq_spin)
        freq_row.addWidget(self._freq_label, 1)
        root.addWidget(freq_group)

        # --- Big panic button -------------------------------------------
        self._stop_btn = QPushButton("Disable test tone")
        self._stop_btn.setObjectName("testToneStopButton")
        self._stop_btn.setMinimumHeight(48)
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        root.addWidget(self._stop_btn)

        # --- Apply / Close ----------------------------------------------
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Close
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(
            self._on_apply_clicked
        )
        self._buttons.rejected.connect(self.reject)
        self._buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(
            self.reject
        )
        root.addWidget(self._buttons)

        # React to mode changes after wiring everything (so the initial
        # refresh() below doesn't trigger redundant work).
        self._wave_group.idToggled.connect(self._on_mode_toggled)

        self.refresh(state)

    # ----------------------------------------------------------------- #
    # Public API
    # ----------------------------------------------------------------- #

    def refresh(self, state: DeviceState) -> None:
        """Snap the dialog to ``state.test_tone``.

        Called at construction and after every Apply round-trip so the
        UI mirrors the device's authoritative state — including any
        silent rejection of an out-of-range value.
        """
        tone = state.test_tone
        mode = tone.mode if tone.mode in _MODES else TONE_OFF
        freq = max(0, min(len(_FREQ_LABELS) - 1, tone.sine_freq_index))

        # Block signals so refresh() doesn't fire applyRequested or
        # similar via the toggled callbacks.
        for rb in self._wave_radios:
            rb.blockSignals(True)
        self._freq_spin.blockSignals(True)
        try:
            for rb_mode, rb in zip(_MODES, self._wave_radios):
                rb.setChecked(rb_mode == mode)
            self._freq_spin.setValue(freq)
            self._freq_label.setText(_FREQ_LABELS[freq])
        finally:
            for rb in self._wave_radios:
                rb.blockSignals(False)
            self._freq_spin.blockSignals(False)

        self._stop_btn.setEnabled(mode != TONE_OFF)
        self._update_enabled_state()

    def current_mode(self) -> int:
        """Return the currently selected mode constant.

        Falls back to TONE_OFF if, for some reason, no radio is checked
        (should not happen in practice but avoids returning -1).
        """
        return (
            self._wave_group.checkedId()
            if self._wave_group.checkedId() != -1
            else TONE_OFF
        )

    def current_freq_index(self) -> int:
        """Return the 0–30 ISO 1/3-octave sine frequency index.

        Always returns the spin-box value, even when the current
        mode isn't sine — the device stores the index across mode
        switches.
        """
        return self._freq_spin.value()

    # ----------------------------------------------------------------- #
    # Internal helpers
    # ----------------------------------------------------------------- #

    def _update_enabled_state(self) -> None:
        """Spin-box enabled only when Sine is selected."""
        self._freq_spin.setEnabled(self.current_mode() == TONE_SINE)

    def _on_freq_value_changed(self, value: int) -> None:
        self._freq_label.setText(_FREQ_LABELS[value])

    def _on_mode_toggled(self, mode_id: int, checked: bool) -> None:
        # Exclusive group fires twice per toggle (old off, new on); only
        # react on the new selection.
        if not checked:
            return
        self._update_enabled_state()

    def _on_apply_clicked(self) -> None:
        self.applyRequested.emit(self.current_mode(), self.current_freq_index())

    def _on_stop_clicked(self) -> None:
        # Optimistically flip the UI to Off so the dialog looks stopped
        # before the device command even reaches the hardware. The main
        # window's _disable_test_tone handler will send the command and
        # update self._state.test_tone; the next refresh() (triggered by
        # _sync_test_tone_dialog) confirms or corrects this optimistic state.
        for rb_mode, rb in zip(_MODES, self._wave_radios):
            rb.blockSignals(True)
            rb.setChecked(rb_mode == TONE_OFF)
            rb.blockSignals(False)
        self._stop_btn.setEnabled(False)
        self._update_enabled_state()
        self.disableRequested.emit()
