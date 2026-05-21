"""VirtualDSP lock/unlock round-trip.

The virtual device mirrors the real device's lock semantics so that
DeviceThread drives it identically in offline mode.
"""

from __future__ import annotations

import pytest

from minidsp.device import DeviceLockedError
from minidspqt.virtual_dsp import VirtualDSP


def test_fresh_virtual_dsp_is_unlocked():
    dsp = VirtualDSP()
    cfg = dsp.read_config()
    assert isinstance(cfg, dict)
    assert "names" in cfg


def test_set_lock_pin_locks_subsequent_read_config():
    dsp = VirtualDSP()
    assert dsp.set_lock_pin("1234") is True
    with pytest.raises(DeviceLockedError):
        dsp.read_config()


def test_submit_wrong_pin_keeps_device_locked():
    dsp = VirtualDSP()
    dsp.set_lock_pin("1234")
    assert dsp.submit_pin("0000") is False
    with pytest.raises(DeviceLockedError):
        dsp.read_config()


def test_submit_correct_pin_unlocks():
    dsp = VirtualDSP()
    dsp.set_lock_pin("1234")
    assert dsp.submit_pin("1234") is True
    # No exception now — read_config works again.
    cfg = dsp.read_config()
    assert isinstance(cfg, dict)


def test_set_lock_pin_leaves_session_open():
    """The real device ACKs and keeps the USB session alive — it is the
    client that closes after the ACK. VirtualDSP mirrors that: _open
    stays True, _locked goes True. The worker is responsible for the
    follow-up close()."""
    dsp = VirtualDSP()
    dsp.set_lock_pin("9999")
    assert dsp._open is True
    assert dsp._locked is True


def test_close_after_set_lock_pin_then_poll_returns_none():
    """After the worker drives close(), poll_levels reports the link as
    gone — that's how the poll loop detects the disconnect."""
    dsp = VirtualDSP()
    dsp.set_lock_pin("9999")
    dsp.close()
    assert dsp.poll_levels() is None


def test_reopen_after_lock_still_locked():
    """A fresh open() does not clear the lock — the device is back online
    but read_config will still raise until submit_pin succeeds."""
    dsp = VirtualDSP()
    dsp.set_lock_pin("4321")
    dsp.open()
    assert dsp._open is True
    with pytest.raises(DeviceLockedError):
        dsp.read_config()
