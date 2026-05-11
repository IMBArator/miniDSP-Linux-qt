"""Compressor settings panel for output channels (placeholder).

A blank placeholder shown when the user navigates to the Compressor
feature from an output strip. Real controls will land here once the
compressor protocol writer is wired up; for now it mirrors the look of
the other feature panels (title + framed body) so the detail view
stays consistent.

Implements :meth:`set_linked_slave` for API parity with Gate/PEQ/Xover
so :class:`DetailView` can call it uniformly when locking slaves.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ._slave_lock import apply_link_state, install_link_banner


class CompressorPanel(QWidget):
    """Placeholder panel for output-channel compressor settings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._link_banner = install_link_banner(root)

        title = QLabel("Compressor Settings")
        title.setObjectName("panelTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(title)

        body = QLabel("Compressor controls are not yet available.")
        body.setObjectName("placeholderLabel")
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setWordWrap(True)
        root.addWidget(body, stretch=1)

    def set_linked_slave(self, is_slave: bool, master_name: str = "") -> None:
        """Show the 'Linked to <master>' banner when displayed for a slave."""
        apply_link_state(self._link_banner, is_slave, master_name, [])
