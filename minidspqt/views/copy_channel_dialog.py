"""Dialog for copying channel settings from one channel to others."""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from minidsp.protocol import CHANNEL_NAMES

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
    """Dialog for copying channel settings from source to target channels.

    User selects:
    - Source channel (all 8 channels)
    - Which parameter groups to copy (based on source type)
    - Target channels (same type as source, excluding source)

    Emits accepted with (source_channel, targets, groups).
    """

    def __init__(self, device_state, parent=None) -> None:
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

        root.addWidget(QLabel("Parameters to copy:"))
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

    def _populate(self) -> None:
        for ch in range(8):
            self._source_combo.blockSignals(True)
            self._source_combo.addItem(CHANNEL_NAMES[ch], ch)
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
            self._param_checkboxes[group] = cb
            self._param_container.addWidget(cb, row, col)
            col += 1
            if col == 3:
                row += 1
                col = 0

        self._clear_layout(self._target_container)
        self._target_checkboxes.clear()

        target_range = range(4) if source < 4 else range(4, 8)
        row, col = 0, 0
        for ch in target_range:
            if ch == source:
                continue
            cb = QCheckBox(CHANNEL_NAMES[ch])
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

        if any_slave and targets:
            names = [
                CHANNEL_NAMES[t]
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
