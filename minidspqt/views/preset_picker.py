"""PresetPickerDialog — small picker for Recall / Store operations.

Lists all 30 user slots (U01–U30) by name.  Empty slots are shown dimmed
and non-selectable.  In *store* mode an extra ``QLineEdit`` is shown
pre-filled with the current preset name; the user can edit it before
saving.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PresetPickerDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        slot_names: list[str],
        active_slot: int,
        mode: Literal["recall", "store"],
        current_name: str = "",
    ) -> None:
        super().__init__(parent)
        self._mode = mode
        self._slot_names = slot_names

        title = "Recall Preset" if mode == "recall" else "Store Preset"
        self.setWindowTitle(title)
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)

        self._list = QListWidget()
        for i, name in enumerate(slot_names):
            slot_label = f"U{i + 1:02d}"
            if name:
                text = f"{slot_label} \u2014 {name}"
            else:
                text = f"{slot_label} \u2014 (empty)"

            item = QListWidgetItem(text)
            if not name:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsEnabled)
                foreground = item.foreground()
                foreground.setColor(Qt.GlobalColor.gray)
                item.setForeground(foreground)
            if i + 1 == active_slot and name:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self._list.addItem(item)

        self._list.setCurrentRow(-1)
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

        if mode == "store":
            row = QHBoxLayout()
            row.addWidget(QLabel("Name:"))
            self._name_edit = QLineEdit(current_name)
            self._name_edit.setMaxLength(14)
            row.addWidget(self._name_edit)
            layout.addLayout(row)
        else:
            self._name_edit = None

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._ok_btn = QPushButton("Recall" if mode == "recall" else "Store")
        self._ok_btn.setEnabled(False)
        self._ok_btn.clicked.connect(self.accept)
        self._ok_btn.setDefault(True)
        btn_row.addWidget(self._ok_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _on_row_changed(self, row: int) -> None:
        self._ok_btn.setEnabled(row >= 0)

    @property
    def chosen_slot(self) -> int:
        """Device slot number (1 = U01, …, 30 = U30)."""
        return self._list.currentRow() + 1

    @property
    def chosen_name(self) -> str:
        if self._name_edit is not None:
            return self._name_edit.text().strip()
        return ""
