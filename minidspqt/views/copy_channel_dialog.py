"""Dialog for copying channel settings from one channel to others."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from minidsp.protocol import CHANNEL_NAMES

from ..model import DeviceState

INPUT_PARAMS = ["Name", "Gain", "Mute", "Phase", "Gate"]
OUTPUT_PARAMS = [
    "Name",
    "Gain",
    "Mute",
    "Phase",
    "Routing",
    "Crossover",
    "PEQ",
    "Compressor",
    "Delay",
]


class CopyChannelDialog(QDialog):
    """Modal dialog for copying parameter groups between channels.

    User picks a source channel (any of the 8 strips), which parameter
    groups to copy (the choices depend on whether the source is an
    input or an output), and the target channels. Targets are filtered
    to the same channel type as the source — input → input or
    output → output only.

    After ``exec()`` returns ``Accepted``, read ``result_data`` as
    ``(source_channel, targets, groups)`` — a tuple of an int, a list
    of ints, and a set of group-name strings — and pass it to
    ``DeviceState.copy_params`` plus the matching device-thread
    requests.
    """

    def __init__(self, device_state: DeviceState, parent: QWidget | None = None) -> None:
        """Build the dialog seeded with the current device state.

        Args:
            device_state: The current ``DeviceState``. The dialog
                reads channel names, link topology, and which groups
                have non-default values so the UI can pre-tick
                meaningful options.
            parent: Qt parent window; the dialog is modal w.r.t. it.
        """
        super().__init__(parent)
        self._device_state = device_state
        self._setup_ui()
        self._populate()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Copy Channel Settings")
        self.setMinimumWidth(400)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        source_layout = QHBoxLayout()
        source_layout.addWidget(QLabel("Copy from:"))
        self._source_combo = QComboBox()
        self._source_combo.setMinimumWidth(150)
        source_layout.addWidget(self._source_combo)
        source_layout.addStretch(1)
        root.addLayout(source_layout)

        root.addSpacing(8)
        param_header = QHBoxLayout()
        param_header.addWidget(QLabel("Parameters to copy:"))
        param_header.addStretch(1)
        self._select_all_cb = QCheckBox("Select all")
        self._select_all_cb.setTristate(True)
        self._select_all_cb.stateChanged.connect(self._on_select_all_toggled)
        param_header.addWidget(self._select_all_cb)
        root.addLayout(param_header)
        self._param_container = QGridLayout()
        root.addLayout(self._param_container)

        root.addSpacing(8)
        root.addWidget(QLabel("Apply to:"))
        self._target_container = QGridLayout()
        root.addLayout(self._target_container)

        self._warning_label = QLabel("")
        self._warning_label.setWordWrap(True)
        self._warning_label.setStyleSheet("color: #ff6b6b;")
        self._warning_label.hide()
        root.addWidget(self._warning_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        self._apply_btn = buttons.button(QDialogButtonBox.StandardButton.Apply)
        self._apply_btn.clicked.connect(self._on_apply)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._source_combo.currentIndexChanged.connect(self._on_source_changed)

        self._param_checkboxes: dict[str, QCheckBox] = {}
        self._target_checkboxes: dict[int, QCheckBox] = {}

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _display_name(self, channel: int) -> str:
        """Return channel name with custom name suffix if set.

        Format: "InA (Subwoofer)" if custom name exists, else just "InA".
        """
        base_name = CHANNEL_NAMES[channel]
        custom_name: str | None = None

        if 0 <= channel < 4 and channel < len(self._device_state.inputs):
            custom_name = self._device_state.inputs[channel].name
        elif 4 <= channel < 8 and (channel - 4) < len(self._device_state.outputs):
            custom_name = self._device_state.outputs[channel - 4].name

        if custom_name:
            return f"{base_name} ({custom_name})"
        return base_name

    def _populate(self) -> None:
        for ch in range(8):
            self._source_combo.blockSignals(True)
            self._source_combo.addItem(self._display_name(ch), ch)
        self._source_combo.blockSignals(False)
        self._on_source_changed()

    def _on_source_changed(self) -> None:
        source = self._source_combo.currentData()
        if source is None:
            return

        self._clear_layout(self._param_container)
        self._param_checkboxes.clear()

        params = INPUT_PARAMS if source < 4 else OUTPUT_PARAMS
        row, col = 0, 0
        for group in params:
            cb = QCheckBox(group)
            cb.setChecked(True)
            cb.stateChanged.connect(self._on_param_toggled)
            self._param_checkboxes[group] = cb
            self._param_container.addWidget(cb, row, col)
            col += 1
            if col == 3:
                row += 1
                col = 0

        self._sync_select_all()

        self._clear_layout(self._target_container)
        self._target_checkboxes.clear()

        target_range = range(4) if source < 4 else range(4, 8)
        row, col = 0, 0
        for ch in target_range:
            if ch == source:
                continue
            cb = QCheckBox(self._display_name(ch))
            cb.stateChanged.connect(self._update_ui_state)
            self._target_checkboxes[ch] = cb
            self._target_container.addWidget(cb, row, col)
            col += 1
            if col == 4:
                row += 1
                col = 0

        self._update_ui_state()

    def _update_ui_state(self) -> None:
        targets = [
            ch for ch, cb in self._target_checkboxes.items() if cb.isChecked()
        ]

        any_slave = any(self._device_state.is_linked_slave(t) for t in targets)

        for cb in self._param_checkboxes.values():
            if any_slave and cb.text() != "Name":
                cb.setEnabled(False)
                cb.setChecked(False)
            else:
                cb.setEnabled(True)

        self._sync_select_all()

        if any_slave and targets:
            names = [
                self._display_name(t)
                for t in targets
                if self._device_state.is_linked_slave(t)
            ]
            self._warning_label.setText(
                f"⚠ {', '.join(names)} is/are linked slaves — only Name can be copied."
            )
            self._warning_label.show()
        else:
            self._warning_label.hide()

        self._apply_btn.setEnabled(bool(targets))

    def _on_apply(self) -> None:
        source = self._source_combo.currentData()
        targets = [
            ch for ch, cb in self._target_checkboxes.items() if cb.isChecked()
        ]
        groups = {
            cb.text().lower()
            for cb in self._param_checkboxes.values()
            if cb.isChecked()
        }

        self.result_data = (source, targets, groups)
        self.accept()

    def _on_select_all_toggled(self, state: int) -> None:
        """Handle select-all checkbox state changes.

        - Checked or PartiallyChecked: check all enabled param checkboxes
        - Unchecked: uncheck all param checkboxes
        """
        enabled_checks = [cb for cb in self._param_checkboxes.values() if cb.isEnabled()]
        if not enabled_checks:
            return

        if state == Qt.CheckState.Unchecked.value:
            for cb in enabled_checks:
                cb.setChecked(False)
        else:
            for cb in enabled_checks:
                cb.setChecked(True)

    def _on_param_toggled(self) -> None:
        """Sync select-all checkbox when individual checkboxes change."""
        self._sync_select_all()

    def _sync_select_all(self) -> None:
        """Update select-all checkbox based on individual checkbox states.

        Shows:
        - Checked: if all enabled checkboxes are checked
        - Partially checked: if some (but not all) enabled checkboxes are checked
        - Unchecked: if no enabled checkboxes are checked
        """
        enabled_checks = [cb for cb in self._param_checkboxes.values() if cb.isEnabled()]
        if not enabled_checks:
            self._select_all_cb.setCheckState(Qt.CheckState.Unchecked)
            return

        all_checked = all(cb.isChecked() for cb in enabled_checks)
        any_checked = any(cb.isChecked() for cb in enabled_checks)

        self._select_all_cb.blockSignals(True)
        if all_checked:
            self._select_all_cb.setCheckState(Qt.CheckState.Checked)
        elif any_checked:
            self._select_all_cb.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            self._select_all_cb.setCheckState(Qt.CheckState.Unchecked)
        self._select_all_cb.blockSignals(False)
