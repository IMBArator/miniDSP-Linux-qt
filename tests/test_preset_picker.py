"""PresetPickerDialog smoke test with pytest-qt."""

from __future__ import annotations

import pytest


from minidspqt.views.preset_picker import PresetPickerDialog


@pytest.mark.qt_no_exception_capture
def test_recall_dialog_selects_slot(qtbot):
    names = [f"Slot{i}" for i in range(30)]
    dlg = PresetPickerDialog(None, names, active_slot=1, mode="recall")
    qtbot.addWidget(dlg)

    assert dlg._list.count() == 31  # F00 + 30 user slots

    dlg._list.setCurrentRow(5)
    assert dlg.chosen_slot == 5

    dlg._list.setCurrentRow(0)
    assert dlg.chosen_slot == 0  # F00


@pytest.mark.qt_no_exception_capture
def test_store_dialog_has_name_edit(qtbot):
    names = [""] * 30
    names[2] = "Existing"
    dlg = PresetPickerDialog(
        None, names, active_slot=3, mode="store", current_name="TestName"
    )
    qtbot.addWidget(dlg)

    assert dlg._name_edit is not None
    assert dlg._name_edit.text() == "TestName"


@pytest.mark.qt_no_exception_capture
def test_empty_slots_are_disabled_in_recall(qtbot):
    names = [""] * 30
    names[0] = "OnlyOne"
    dlg = PresetPickerDialog(None, names, active_slot=1, mode="recall")
    qtbot.addWidget(dlg)

    from PySide6.QtCore import Qt

    assert (
        dlg._list.item(0).flags() & Qt.ItemFlag.ItemIsSelectable
    )  # F00 always selectable
    assert dlg._list.item(1).flags() & Qt.ItemFlag.ItemIsSelectable  # U01 (OnlyOne)
    assert not (dlg._list.item(2).flags() & Qt.ItemFlag.ItemIsSelectable)  # U02 empty


@pytest.mark.qt_no_exception_capture
def test_empty_slots_are_selectable_in_store(qtbot):
    names = [""] * 30
    names[0] = "OnlyOne"
    dlg = PresetPickerDialog(
        None, names, active_slot=1, mode="store", current_name="Test"
    )
    qtbot.addWidget(dlg)

    from PySide6.QtCore import Qt

    assert not (
        dlg._list.item(0).flags() & Qt.ItemFlag.ItemIsSelectable
    )  # F00 disabled in store
    assert dlg._list.item(1).flags() & Qt.ItemFlag.ItemIsSelectable  # U01
    assert (
        dlg._list.item(2).flags() & Qt.ItemFlag.ItemIsSelectable
    )  # U02 empty but selectable


@pytest.mark.qt_no_exception_capture
def test_f00_highlighted_when_active(qtbot):
    names = [f"Slot{i}" for i in range(30)]
    dlg = PresetPickerDialog(None, names, active_slot=0, mode="recall")
    qtbot.addWidget(dlg)

    assert dlg._list.item(0).font().bold()
