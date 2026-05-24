"""Placeholder panel shown when the active feature does not apply to
the currently selected channel (e.g. Gate on an output channel)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderPanel(QWidget):
    """Single-label panel slotted in when no real feature panel applies."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build an empty placeholder; call ``set_message`` to populate it.

        Args:
            parent: Qt parent widget.
        """
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel("")
        self._label.setObjectName("placeholderLabel")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

    def set_message(self, text: str) -> None:
        """Replace the displayed message text."""
        self._label.setText(text)
