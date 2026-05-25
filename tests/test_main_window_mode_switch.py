"""Runtime switch between connected and offline modes via the menu.

Covers the contract added by the ``Connection mode`` submenu:
  - menu radios reflect the constructor's ``offline`` arg
  - flipping the radio rebuilds the worker against the right DSP source
  - offline → online warns first and respects the user's choice
  - online → offline seeds the new VirtualDSP with the last-known device
    config so the user keeps editing what was on the device

Plus a unit test for the new ``VirtualDSP.seed_from_config`` helper.
"""

from __future__ import annotations

import copy

import pytest
from PySide6.QtWidgets import QMessageBox

from minidspqt.virtual_dsp import VirtualDSP


# ---------------------------------------------------------------------------
# VirtualDSP.seed_from_config
# ---------------------------------------------------------------------------


def test_seed_from_config_round_trips(preset_cfg):
    """Seeding a fresh VirtualDSP with a config dict mirrors every slot key."""
    target = VirtualDSP()
    target.seed_from_config(preset_cfg)

    out = target.read_config()
    for k in (
        "names",
        "gains",
        "mutes",
        "phases",
        "link_flags",
        "routings",
        "gates",
        "delays",
        "crossovers",
        "compressors",
        "peqs",
        "active_slot",
        "preset_names",
    ):
        assert out[k] == preset_cfg[k], f"key {k!r} did not round-trip"


def test_seed_from_config_is_deep_copy(preset_cfg):
    """Mutating the seeded VirtualDSP must not leak back into the source dict."""
    cfg = copy.deepcopy(preset_cfg)
    dsp = VirtualDSP()
    dsp.seed_from_config(cfg)

    dsp.set_gain(0, 999)
    # Source dict is untouched even though we mutated the DSP.
    assert cfg["gains"][0] == preset_cfg["gains"][0]


# ---------------------------------------------------------------------------
# MainWindow mode switching
# ---------------------------------------------------------------------------


def _stop_worker(window, qtbot):
    """Stop the worker thread and drain any queued signals.

    Otherwise a queued ``config_loaded`` from VirtualDSP's startup config
    read can land after the test has already mutated ``_state``.
    """
    window._thread.request_stop()
    window._thread.wait(2000)
    qtbot.wait(50)


@pytest.fixture
def offline_window(qtbot):
    from minidspqt.views.main_window import MainWindow

    w = MainWindow(offline=True)
    qtbot.addWidget(w)
    _stop_worker(w, qtbot)
    yield w


@pytest.fixture
def online_window(qtbot, fake_dsp):
    """A MainWindow constructed in online mode against a FakeDSPmini.

    The fake records calls and serves canned data so we don't need
    real hardware; constructing with ``offline=False`` is what flips
    the menu radios and ``_offline`` flag into the connected branch.
    """
    from minidspqt.views.main_window import MainWindow

    w = MainWindow(offline=False, dsp_instance=fake_dsp)
    qtbot.addWidget(w)
    _stop_worker(w, qtbot)
    yield w


def test_initial_menu_state_offline(offline_window):
    """Constructed with ``offline=True`` → Offline radio checked, Online not."""
    assert offline_window._mode_action_offline.isChecked()
    assert not offline_window._mode_action_online.isChecked()


def test_initial_menu_state_online(online_window):
    """Constructed with ``offline=False`` → Online radio checked, Offline not."""
    assert online_window._mode_action_online.isChecked()
    assert not online_window._mode_action_offline.isChecked()


def test_online_to_offline_uses_virtual_dsp(online_window, qtbot):
    """Switching online → offline rebuilds the worker against a VirtualDSP."""
    online_window._on_mode_chosen(offline=True)

    assert online_window._offline is True
    assert isinstance(online_window._thread._dsp_instance, VirtualDSP)
    assert online_window._mode_action_offline.isChecked()
    assert online_window._save_action.isEnabled()


def test_online_to_offline_seeds_from_last_config(online_window, preset_cfg, qtbot):
    """Seed the new VirtualDSP from the cached last-known device config."""
    # Simulate the worker having reported a config (normally arrives via the
    # config_loaded signal). Bypass the slot-internal DeviceState parsing
    # noise by writing _last_config directly with the canned dict.
    online_window._last_config = copy.deepcopy(preset_cfg)

    online_window._on_mode_chosen(offline=True)

    seeded_cfg = online_window._thread._dsp_instance.read_config()
    # Gains in preset_cfg fixture: [280, 281, 282, 283, 100, 101, 102, 103]
    assert seeded_cfg["gains"] == preset_cfg["gains"]
    assert seeded_cfg["preset_names"] == preset_cfg["preset_names"]


def test_offline_to_online_warns_and_cancels(offline_window, monkeypatch):
    """Cancelling the warning keeps offline mode active."""
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **kw: QMessageBox.StandardButton.No,
    )

    offline_window._on_mode_chosen(offline=False)

    # No-op: still offline, still using VirtualDSP, offline radio still checked.
    assert offline_window._offline is True
    assert isinstance(offline_window._thread._dsp_instance, VirtualDSP)
    assert offline_window._mode_action_offline.isChecked()


def test_offline_to_online_warns_and_proceeds(offline_window, monkeypatch, qtbot):
    """Confirming the warning rebuilds the worker against the DSPmini factory."""
    from minidsp.device import DSPmini

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **kw: QMessageBox.StandardButton.Yes,
    )

    offline_window._on_mode_chosen(offline=False)

    # The new thread carries no dsp_instance and uses the real DSPmini
    # factory — the worker will fail to open since no hardware is plugged
    # in, but that's expected and irrelevant to this test.
    assert offline_window._offline is False
    assert offline_window._thread._dsp_instance is None
    assert offline_window._thread._dsp_factory is DSPmini
    assert offline_window._mode_action_online.isChecked()
    assert not offline_window._save_action.isEnabled()
    # Make sure we don't leave a probing worker running into the next test.
    _stop_worker(offline_window, qtbot)


def test_mode_chosen_no_op_when_already_in_mode(offline_window):
    """Re-clicking the active radio must not tear the worker down."""
    original_thread = offline_window._thread
    offline_window._on_mode_chosen(offline=True)
    assert offline_window._thread is original_thread


def test_online_to_offline_falls_back_to_blank_when_no_config(online_window):
    """Cold switch (no config ever seen) seeds VirtualDSP from blank.unt."""
    # FakeDSPmini's worker may have managed to emit one config_loaded before
    # _stop_worker drained it; force the "no config" premise we want to test.
    online_window._last_config = None

    online_window._on_mode_chosen(offline=True)

    assert online_window._offline is True
    assert isinstance(online_window._thread._dsp_instance, VirtualDSP)
    # blank.unt's slot 1 has all 30 preset names defined; the seed worked.
    cfg = online_window._thread._dsp_instance.read_config()
    assert len(cfg["preset_names"]) == 30
