"""Saving a .unt file while connected (and offline), like the original editor.

Three layers are covered:

* the worker's ``export_unt`` operation, driven synchronously against the
  ``FakeDSPmini`` (it inherits ``VirtualDSP.export_unt``);
* the pure helpers in ``minidspqt.unt_files`` that detect and include
  unsaved edits of the active preset;
* the ``MainWindow`` save flow: when the menu entry is enabled, the
  unsaved-changes prompt, abandoned requests, and the save dialog that adds
  the ``.unt`` extension and warns about the extended name itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from minidsp.device import DeviceLockedError
from minidsp.unt import UntFile
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QMessageBox,
    QProxyStyle,
    QStyle,
)

from minidspqt.device_thread import DeviceThread
from minidspqt.unt_files import UNT_FILTER, differs_from_stored, include_live_changes


@pytest.fixture
def thread(fake_dsp):
    # Never started: the queue is drained synchronously, so emits are direct.
    return DeviceThread(dsp_factory=lambda: fake_dsp)


def _stored(fake_dsp) -> tuple[UntFile, dict]:
    """Store the fake's live config in its active slot; return (file, live)."""
    live = fake_dsp.read_config()
    fake_dsp.store_preset(live["active_slot"], live["preset_names"][live["active_slot"] - 1])
    live = fake_dsp.read_config()
    return fake_dsp.export_unt(live["preset_names"]), live


# --- Worker operation ------------------------------------------------------------------


def test_export_emits_the_file_and_the_live_config(thread, fake_dsp):
    fake_dsp.store_preset(1, "Stored")
    got = []
    thread.unt_exported.connect(lambda unt, live: got.append((unt, live)))

    thread.request_export_unt()
    thread._drain_preset_queue(fake_dsp)

    assert len(got) == 1
    unt, live = got[0]
    assert unt.filled_slots() == [1]
    assert unt.slot_name(1) == "Stored"
    assert live["active_slot"] == 1


def test_export_flushes_pending_writes_first(thread, fake_dsp):
    got = []
    thread.unt_exported.connect(lambda unt, live: got.append(live))

    thread.request_gain(0, 222)
    thread.request_export_unt()
    thread._drain_preset_queue(fake_dsp)

    assert got[0]["gains"][0] == 222
    names = [c[0] for c in fake_dsp.calls]
    assert names.index("set_gain") < names.index("read_config")


@pytest.mark.parametrize("error", [OSError("unplugged"), DeviceLockedError("locked")])
def test_export_failure_emits_none(thread, fake_dsp, monkeypatch, error):
    def boom(*_args):
        raise error

    monkeypatch.setattr(fake_dsp, "read_config", boom)
    got = []
    thread.unt_exported.connect(lambda unt, live: got.append((unt, live)))

    thread.request_export_unt()
    thread._drain_preset_queue(fake_dsp)

    assert got == [(None, None)]


def test_export_without_a_file_emits_none(thread, fake_dsp, monkeypatch):
    monkeypatch.setattr(fake_dsp, "export_unt", lambda *_a: None)
    got = []
    thread.unt_exported.connect(lambda unt, live: got.append((unt, live)))

    thread.request_export_unt()
    thread._drain_preset_queue(fake_dsp)

    assert got == [(None, None)]


# --- Stored versus live ------------------------------------------------------------------


def test_unchanged_live_config_matches_the_stored_preset(fake_dsp):
    unt, live = _stored(fake_dsp)
    assert not differs_from_stored(live, unt, live["active_slot"])


def test_a_gain_edit_differs_from_the_stored_preset(fake_dsp):
    unt, live = _stored(fake_dsp)
    live["gains"][0] += 1
    assert differs_from_stored(live, unt, live["active_slot"])


def test_test_tone_alone_does_not_count_as_a_change(fake_dsp):
    unt, live = _stored(fake_dsp)
    live["test_tone_mode"] = 1
    live["test_tone_freq"] = 5
    assert not differs_from_stored(live, unt, live["active_slot"])


def test_an_unstored_slot_differs_and_f00_never_does(fake_dsp):
    unt, live = _stored(fake_dsp)
    assert differs_from_stored(live, unt, 7)
    assert not differs_from_stored(live, unt, 0)


def test_include_live_changes_writes_the_live_values(fake_dsp):
    unt, live = _stored(fake_dsp)
    slot = live["active_slot"]
    name = unt.slot_name(slot)
    live["gains"][0] += 1

    include_live_changes(unt, slot, live)

    assert unt.slot_params(slot)["gains"][0] == live["gains"][0]
    assert unt.slot_name(slot) == name


def test_include_live_changes_names_a_new_slot(fake_dsp):
    unt, live = _stored(fake_dsp)
    include_live_changes(unt, 7, live)
    assert unt.slot_name(7) == live["preset_names"][6]


# --- MainWindow save flow ------------------------------------------------------------------


@pytest.fixture
def window(qtbot, fake_dsp):
    """An online MainWindow whose worker has been stopped.

    Stopping the worker emits ``connection_changed(False)``; tests set the
    connection state they need explicitly.
    """
    from minidspqt.views.main_window import MainWindow

    w = MainWindow(offline=False, dsp_instance=fake_dsp)
    qtbot.addWidget(w)
    w._thread.request_stop()
    w._thread.wait(2000)
    qtbot.wait(50)
    yield w
    while QApplication.overrideCursor() is not None:
        QApplication.restoreOverrideCursor()


def _start_save(window, monkeypatch) -> list:
    """Click Save with the worker request replaced by a recorder."""
    requests = []
    monkeypatch.setattr(window._thread, "request_export_unt", lambda: requests.append(1))
    window._on_save_unt()
    return requests


def _save_to(window, monkeypatch, path) -> list:
    """Make the save dialog return ``path`` (``None`` = cancelled).

    Returns a list that records each time the dialog would have opened.
    """
    opened = []

    def ask():
        opened.append(1)
        return None if path is None else str(path)

    monkeypatch.setattr(window, "_ask_save_path", ask)
    return opened


def test_save_is_enabled_only_when_connected_with_a_config(window, preset_cfg):
    assert not window._save_action.isEnabled()  # worker stopped → disconnected

    window._on_connection_changed(True)
    window._last_config = None
    window._update_save_action()
    assert not window._save_action.isEnabled()  # no device config read yet

    window._on_config_loaded(preset_cfg)
    assert window._save_action.isEnabled()

    window._on_connection_changed(False)
    assert not window._save_action.isEnabled()


def test_save_shows_busy_state_until_the_answer(window, monkeypatch, preset_cfg, fake_dsp):
    window._on_connection_changed(True)
    window._on_config_loaded(preset_cfg)

    requests = _start_save(window, monkeypatch)
    assert requests == [1]
    assert not window._save_action.isEnabled()
    assert QApplication.overrideCursor() is not None

    _save_to(window, monkeypatch, None)
    window._on_unt_exported(*_stored(fake_dsp))
    assert window._save_action.isEnabled()
    assert QApplication.overrideCursor() is None


def test_unchanged_preset_is_saved_without_a_prompt(window, monkeypatch, fake_dsp, tmp_path):
    unt, live = _stored(fake_dsp)
    out = tmp_path / "out.unt"
    _save_to(window, monkeypatch, out)
    monkeypatch.setattr(window, "_ask_unsaved_changes", lambda slot: pytest.fail("no prompt"))

    _start_save(window, monkeypatch)
    window._on_unt_exported(unt, live)

    assert out.read_bytes() == unt.to_bytes()


@pytest.mark.parametrize(
    ("choice", "expect_live_gain"),
    [("stored", False), ("include", True)],
)
def test_unsaved_edit_prompt_choices(
    window, monkeypatch, fake_dsp, tmp_path, choice, expect_live_gain
):
    unt, live = _stored(fake_dsp)
    slot = live["active_slot"]
    stored_gain = live["gains"][0]
    live["gains"][0] = stored_gain + 1
    asked = []
    monkeypatch.setattr(window, "_ask_unsaved_changes", lambda s: asked.append(s) or choice)
    out = tmp_path / "out.unt"
    _save_to(window, monkeypatch, out)

    _start_save(window, monkeypatch)
    window._on_unt_exported(unt, live)

    assert asked == [slot]
    saved = UntFile.read(out).slot_params(slot)["gains"][0]
    assert saved == (stored_gain + 1 if expect_live_gain else stored_gain)


def test_cancel_in_the_prompt_writes_nothing(window, monkeypatch, fake_dsp):
    unt, live = _stored(fake_dsp)
    live["gains"][0] += 1
    monkeypatch.setattr(window, "_ask_unsaved_changes", lambda s: "cancel")
    opened = _save_to(window, monkeypatch, "never.unt")

    _start_save(window, monkeypatch)
    window._on_unt_exported(unt, live)

    assert opened == []


def test_f00_active_saves_without_a_prompt(window, monkeypatch, fake_dsp, tmp_path):
    unt, live = _stored(fake_dsp)
    live["active_slot"] = 0
    live["gains"][0] += 1
    monkeypatch.setattr(window, "_ask_unsaved_changes", lambda slot: pytest.fail("no prompt"))
    out = tmp_path / "out.unt"
    _save_to(window, monkeypatch, out)

    _start_save(window, monkeypatch)
    window._on_unt_exported(unt, live)

    assert out.read_bytes() == unt.to_bytes()


def test_failed_export_reports_and_writes_nothing(window, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: errors.append(a[1:]))
    opened = _save_to(window, monkeypatch, "never.unt")

    _start_save(window, monkeypatch)
    window._on_unt_exported(None, None)

    assert errors and errors[0][0] == "Cannot save .unt file"
    assert opened == []
    assert QApplication.overrideCursor() is None


def test_answer_after_a_disconnect_is_ignored(window, monkeypatch, fake_dsp):
    unt, live = _stored(fake_dsp)
    window._on_connection_changed(True)
    opened = _save_to(window, monkeypatch, "never.unt")

    _start_save(window, monkeypatch)
    window._on_connection_changed(False)
    assert QApplication.overrideCursor() is None

    window._on_unt_exported(unt, live)
    assert opened == []


def _save_dialog_in(window, directory, typed):
    """The window's real save dialog, opened on ``directory`` with ``typed`` entered."""
    dialog = window._make_save_dialog()
    dialog.setDirectory(str(directory))
    dialog.selectFile(typed)
    return dialog


def test_save_dialog_is_qts_own_with_unt_default_suffix(window):
    """Qt's dialog, not the platform's: only it adds the suffix before its
    overwrite check, on Linux as on Windows."""
    dialog = window._make_save_dialog()
    assert dialog.testOption(QFileDialog.Option.DontUseNativeDialog)
    assert dialog.acceptMode() == QFileDialog.AcceptMode.AcceptSave
    assert dialog.defaultSuffix() == "unt"
    assert dialog.nameFilters()[0] == UNT_FILTER


@pytest.mark.parametrize(
    ("typed", "saved_as"),
    [
        ("backup", "backup.unt"),
        ("backup.unt", "backup.unt"),
        ("backup.v2", "backup.v2"),  # a typed extension is kept
    ],
)
def test_save_dialog_adds_unt_to_a_name_without_extension(window, tmp_path, typed, saved_as):
    dialog = _save_dialog_in(window, tmp_path, typed)
    assert Path(dialog.selectedFiles()[0]).name == saved_as


@pytest.mark.parametrize(("button", "accepted"), [("No", False), ("Yes", True)])
def test_save_dialog_warns_about_the_extended_name(window, tmp_path, qtbot, button, accepted):
    """Typing "backup" next to an existing backup.unt: the dialog itself asks."""
    (tmp_path / "backup.unt").write_bytes(b"previous")
    dialog = _save_dialog_in(window, tmp_path, "backup")
    qtbot.addWidget(dialog)
    dialog.show()
    warnings = []

    def answer():
        box = QApplication.activeModalWidget()
        if isinstance(box, QMessageBox):
            warnings.append(box.text())
            box.button(getattr(QMessageBox.StandardButton, button)).click()

    QTimer.singleShot(100, answer)
    dialog.accept()  # runs the dialog's overwrite check; the timer answers it

    assert warnings and "backup.unt" in warnings[0]
    assert (dialog.result() == QDialog.DialogCode.Accepted) is accepted


class _ButtonLayoutStyle(QProxyStyle):
    """Fusion with a chosen dialog-button layout, to emulate other desktops."""

    def __init__(self, layout: QDialogButtonBox.ButtonLayout) -> None:
        super().__init__("Fusion")
        self._layout = layout

    def styleHint(self, hint, option=None, widget=None, return_data=None):
        if hint == QStyle.StyleHint.SH_DialogButtonLayout:
            return int(self._layout.value)
        return super().styleHint(hint, option, widget, return_data)


def _shown_order(box, layout) -> list[str]:
    """Button texts left to right after laying ``box`` out with ``layout``."""
    style = _ButtonLayoutStyle(layout)
    button_box = box.findChild(QDialogButtonBox)
    button_box.setStyle(style)
    box.show()
    QApplication.processEvents()
    order = sorted(box.buttons(), key=lambda b: b.mapToGlobal(QPoint(0, 0)).x())
    box.close()
    del style  # keep alive until the layout was read
    return [b.text() for b in order]


ALL_LAYOUTS = [
    QDialogButtonBox.ButtonLayout.WinLayout,
    QDialogButtonBox.ButtonLayout.MacLayout,
    QDialogButtonBox.ButtonLayout.KdeLayout,
    QDialogButtonBox.ButtonLayout.GnomeLayout,
    QDialogButtonBox.ButtonLayout.AndroidLayout,
]


def test_layout_emulation_reproduces_the_gnome_order(window):
    """Guard for the harness: mixed roles really are reordered under GNOME."""
    box = QMessageBox(window)
    box.addButton("Save stored version", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Include current changes", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    assert _shown_order(box, QDialogButtonBox.ButtonLayout.GnomeLayout) == [
        "Include current changes",
        "Cancel",
        "Save stored version",
    ]


@pytest.mark.parametrize("layout", ALL_LAYOUTS, ids=lambda layout: layout.name)
def test_unsaved_changes_buttons_keep_their_order_on_every_desktop(window, layout):
    box, buttons = window._build_unsaved_changes_box(3)
    assert set(box.buttons()) == set(buttons.values())
    assert _shown_order(box, layout) == [
        "Save stored version",
        "Include current changes",
        "Cancel",
    ]


def test_unsaved_changes_defaults_to_stored_and_escapes_to_cancel(window):
    box, buttons = window._build_unsaved_changes_box(3)
    assert box.defaultButton() is buttons["stored"]
    assert box.escapeButton() is buttons["cancel"]


@pytest.mark.parametrize("choice", ["stored", "include", "cancel"])
def test_ask_unsaved_changes_returns_the_clicked_choice(window, monkeypatch, choice):
    build = window._build_unsaved_changes_box

    def build_and_click(slot):
        box, buttons = build(slot)
        QTimer.singleShot(0, buttons[choice].click)
        return box, buttons

    monkeypatch.setattr(window, "_build_unsaved_changes_box", build_and_click)
    assert window._ask_unsaved_changes(3) == choice


def test_escape_in_the_unsaved_changes_box_cancels(window, monkeypatch):
    build = window._build_unsaved_changes_box

    def build_and_escape(slot):
        box, buttons = build(slot)
        QTimer.singleShot(0, lambda: QTest.keyClick(box, Qt.Key.Key_Escape))
        return box, buttons

    monkeypatch.setattr(window, "_build_unsaved_changes_box", build_and_escape)
    assert window._ask_unsaved_changes(3) == "cancel"


def test_unt_exported_is_wired_to_the_worker(window, monkeypatch):
    """Emitting the worker's signal must reach the window's handler."""
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: errors.append(a[1:]))

    _start_save(window, monkeypatch)
    window._thread.unt_exported.emit(None, None)

    assert errors and errors[0][0] == "Cannot save .unt file"
