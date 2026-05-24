"""Non-toggleable signal-chain indicator for the Gain stage.

Renders as a dashed-border label in the toggle row at the position where
Gain sits in the DSP signal chain.  Clicking it highlights the ParamKnob
above so the user can immediately locate the control.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPushButton, QWidget


class GainIndicator(QPushButton):
    """Static pseudo-button that marks where Gain sits in the signal chain.

    Not toggleable — clicking it just emits ``gain_clicked`` so the
    channel strip can highlight the corresponding ``ParamKnob``.

    Signals:
        gain_clicked (): Fires on every click. Forwarded from the
            built-in ``clicked`` signal so callers don't need to
            understand the QPushButton internals.
    """

    gain_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build a non-toggleable Gain indicator.

        Args:
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self.setProperty("feature", "gain")
        self.setCheckable(False)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.clicked.connect(self.gain_clicked.emit)
