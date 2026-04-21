"""PresetPickerDialog smoke test with pytest-qt."""

from __future__ import annotations

import pytest

from PySide6.QtWidgets import QDialog

from minidspqt.views.preset_picker import PresetPickerDialog


@pytest.mark.qt_no_exception_capture
def test_recall_dialog_selects_slot(qtbot):
    names = [f"Slot{i}" for i in range(30)]
    dlg = PresetPickerDialog(None, names, active_slot=1, mode="recall")
    qtbot.addWidget(dlg)

    dlg._list.setCurrentRow(4)
    assert dlg.chosen_slot == 5
    assert dlg.chosen_name == ""


@pytest.mark.qt_no_exception_capture
def test_store_dialog_has_name_edit(qtbot):
    names = [""] * 30
    names[2] = "Existing"
    dlg = PresetPickerDialog(None, names, active_slot=3, mode="store", current_name="TestName")
    qtbot.addWidget(dlg)

    assert dlg._name_edit is not None
    assert dlg._name_edit.text() == "TestName"


@pytest.mark.qt_no_exception_capture
def test_empty_slots_are_disabled(qtbot):
    names = [""] * 30
    names[0] = "OnlyOne"
    dlg = PresetPickerDialog(None, names, active_slot=1, mode="recall")
    qtbot.addWidget(dlg)

    assert dlg._list.item(0).flags() != 0
    from PySide6.QtCore import Qt
    assert not (dlg._list.item(1).flags() & Qt.ItemFlag.ItemIsSelectable)
