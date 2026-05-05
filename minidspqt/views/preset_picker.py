"""PresetPickerDialog — picker for Recall / Store operations.

Row 0 is always **F00 — Factory** (the read-only factory default preset).
Rows 1–30 list user slots U01–U30.  In *recall* mode, empty user slots
are dimmed and non-selectable (but F00 is always selectable).  In *store*
mode F00 is disabled (cannot overwrite factory) but empty user slots are
selectable.  An extra ``QLineEdit`` is shown in store mode pre-filled
with the current preset name.
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

from ..scale import s


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
        self.setMinimumSize(s(400), s(500))

        layout = QVBoxLayout(self)

        self._list = QListWidget()

        f00 = QListWidgetItem("F00 \u2014 Factory")
        if mode == "store":
            f00.setFlags(f00.flags() & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsEnabled)
            fg = f00.foreground()
            fg.setColor(Qt.GlobalColor.gray)
            f00.setForeground(fg)
        if active_slot == 0:
            font = f00.font()
            font.setBold(True)
            f00.setFont(font)
        self._list.addItem(f00)

        for i, name in enumerate(slot_names):
            slot_label = f"U{i + 1:02d}"
            if name:
                text = f"{slot_label} \u2014 {name}"
            else:
                text = f"{slot_label} \u2014 (empty)"

            item = QListWidgetItem(text)
            if not name:
                foreground = item.foreground()
                foreground.setColor(Qt.GlobalColor.gray)
                item.setForeground(foreground)
                if mode == "recall":
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsEnabled)
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
        """Device slot number (0 = F00, 1 = U01, …, 30 = U30)."""
        row = self._list.currentRow()
        if row <= 0:
            return row  # -1 = nothing selected, 0 = F00
        return row  # row 1 → slot 1 (U01), row 30 → slot 30 (U30)

    @property
    def chosen_name(self) -> str:
        if self._name_edit is not None:
            return self._name_edit.text().strip()
        return ""
