"""Saving a .unt file while connected (and offline), like the original editor.

Three layers are covered:

* the worker's ``export_unt`` operation, driven synchronously against the
  ``FakeDSPmini`` (it inherits ``VirtualDSP.export_unt``);
* the pure helpers in ``minidspqt.unt_files`` that detect and include
  unsaved edits of the active preset;
* the ``MainWindow`` save flow: when the menu entry is enabled, the
  unsaved-changes prompt, and abandoned requests.
"""

from __future__ import annotations

import pytest
from minidsp.device import DeviceLockedError
from minidsp.unt import UntFile
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from minidspqt.device_thread import DeviceThread
from minidspqt.unt_files import differs_from_stored, include_live_changes


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


def _save_to(monkeypatch, path) -> list:
    """Make the save dialog return ``path``; record each time it opens."""
    opened = []

    def dialog(*_a, **_kw):
        opened.append(1)
        return str(path), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", dialog)
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

    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    window._on_unt_exported(*_stored(fake_dsp))
    assert window._save_action.isEnabled()
    assert QApplication.overrideCursor() is None


def test_unchanged_preset_is_saved_without_a_prompt(window, monkeypatch, fake_dsp, tmp_path):
    unt, live = _stored(fake_dsp)
    out = tmp_path / "out.unt"
    _save_to(monkeypatch, out)
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
    _save_to(monkeypatch, out)

    _start_save(window, monkeypatch)
    window._on_unt_exported(unt, live)

    assert asked == [slot]
    saved = UntFile.read(out).slot_params(slot)["gains"][0]
    assert saved == (stored_gain + 1 if expect_live_gain else stored_gain)


def test_cancel_in_the_prompt_writes_nothing(window, monkeypatch, fake_dsp):
    unt, live = _stored(fake_dsp)
    live["gains"][0] += 1
    monkeypatch.setattr(window, "_ask_unsaved_changes", lambda s: "cancel")
    opened = _save_to(monkeypatch, "never.unt")

    _start_save(window, monkeypatch)
    window._on_unt_exported(unt, live)

    assert opened == []


def test_f00_active_saves_without_a_prompt(window, monkeypatch, fake_dsp, tmp_path):
    unt, live = _stored(fake_dsp)
    live["active_slot"] = 0
    live["gains"][0] += 1
    monkeypatch.setattr(window, "_ask_unsaved_changes", lambda slot: pytest.fail("no prompt"))
    out = tmp_path / "out.unt"
    _save_to(monkeypatch, out)

    _start_save(window, monkeypatch)
    window._on_unt_exported(unt, live)

    assert out.read_bytes() == unt.to_bytes()


def test_failed_export_reports_and_writes_nothing(window, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: errors.append(a[1:]))
    opened = _save_to(monkeypatch, "never.unt")

    _start_save(window, monkeypatch)
    window._on_unt_exported(None, None)

    assert errors and errors[0][0] == "Cannot save .unt file"
    assert opened == []
    assert QApplication.overrideCursor() is None


def test_answer_after_a_disconnect_is_ignored(window, monkeypatch, fake_dsp):
    unt, live = _stored(fake_dsp)
    window._on_connection_changed(True)
    opened = _save_to(monkeypatch, "never.unt")

    _start_save(window, monkeypatch)
    window._on_connection_changed(False)
    assert QApplication.overrideCursor() is None

    window._on_unt_exported(unt, live)
    assert opened == []


def test_unt_exported_is_wired_to_the_worker(window, monkeypatch):
    """Emitting the worker's signal must reach the window's handler."""
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: errors.append(a[1:]))

    _start_save(window, monkeypatch)
    window._thread.unt_exported.emit(None, None)

    assert errors and errors[0][0] == "Cannot save .unt file"
