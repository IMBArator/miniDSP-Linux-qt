"""DeviceThread — exercise the coalescing dispatch without Qt threading.

We drive `_drain_pending` / `_drain_preset_queue` directly with a FakeDSPmini,
which is faster and more deterministic than spinning up the real QThread.
"""

from __future__ import annotations

import pytest

from minidsp.device import DeviceClosedError, DeviceLockedError
from minidspqt.device_thread import MAX_PIN_ATTEMPTS, CommandType, DeviceThread


@pytest.fixture
def thread(fake_dsp):
    # parent=None is fine outside of a QApplication as long as the thread
    # never runs (we call methods synchronously).
    return DeviceThread(dsp_factory=lambda: fake_dsp)


def test_gain_coalesces_to_latest(thread, fake_dsp):
    thread.request_gain(2, 100)
    thread.request_gain(2, 200)
    thread.request_gain(2, 250)

    thread._drain_pending(fake_dsp)

    gain_calls = [c for c in fake_dsp.calls if c[0] == "set_gain"]
    assert gain_calls == [("set_gain", (2, 250))]


def test_gain_different_channels_not_coalesced(thread, fake_dsp):
    thread.request_gain(0, 100)
    thread.request_gain(1, 200)
    thread.request_gain(2, 250)

    thread._drain_pending(fake_dsp)

    sent = sorted(
        (c[1] for c in fake_dsp.calls if c[0] == "set_gain"), key=lambda t: t[0]
    )
    assert sent == [(0, 100), (1, 200), (2, 250)]


def test_peq_band_coalesces_per_band(thread, fake_dsp):
    thread.request_peq_band(4, 0, 120, 150, 40, 2, False)
    thread.request_peq_band(4, 0, 130, 160, 45, 2, False)  # overrides the above
    thread.request_peq_band(4, 1, 100, 200, 50, 2, False)  # different band, kept

    thread._drain_pending(fake_dsp)

    peq_calls = [c for c in fake_dsp.calls if c[0] == "set_peq_band"]
    # Bands 0 and 1 both present, band 0 shows only the latest values.
    by_band = {c[1][1]: c[1] for c in peq_calls}
    assert by_band[0] == (4, 0, 130, 160, 45, 2, False)
    assert by_band[1] == (4, 1, 100, 200, 50, 2, False)


def test_mute_and_phase_independent(thread, fake_dsp):
    thread.request_mute(3, True)
    thread.request_phase(3, True)

    thread._drain_pending(fake_dsp)

    kinds = sorted(c[0] for c in fake_dsp.calls if c[0] in ("mute", "set_phase"))
    assert kinds == ["mute", "set_phase"]


def test_preset_queue_does_not_coalesce(thread, fake_dsp):
    thread.request_load_preset(2)
    thread.request_load_preset(3)

    thread._drain_preset_queue(fake_dsp)

    loads = [c for c in fake_dsp.calls if c[0] == "load_preset"]
    assert [c[1][0] for c in loads] == [2, 3]


def test_request_prepare_link_dispatches_in_order_before_channel_link(thread, fake_dsp):
    # The protocol contract requires prepare_link before set_channel_link
    # for the same slave. The thread coalesces via dict insertion order,
    # so as long as the caller enqueues the prepare first the dispatch
    # order must preserve that.
    thread.request_prepare_link(0, 1)
    thread.request_channel_link(0, 0x03)
    thread.request_channel_link(1, 0x00)

    thread._drain_pending(fake_dsp)

    relevant = [
        c for c in fake_dsp.calls if c[0] in ("prepare_link", "set_channel_link")
    ]
    assert relevant == [
        ("prepare_link", (0, 1)),
        ("set_channel_link", (0, 0x03)),
        ("set_channel_link", (1, 0x00)),
    ]


def test_request_read_config_emits_config_loaded(thread, fake_dsp, qtbot):
    # read_config goes through the preset queue (same lane as load_preset)
    # and emits config_loaded with the canned dict.
    with qtbot.waitSignal(thread.config_loaded, timeout=500) as caught:
        thread.request_read_config()
        thread._drain_preset_queue(fake_dsp)

    cfg = caught.args[0]
    assert "names" in cfg and "link_flags" in cfg
    # Crucially, no preset slot is implied — read_config preserves whatever
    # active_slot the device reports rather than overriding it.


def test_read_config_flushes_pending_writes_first(thread, fake_dsp, qtbot):
    # Regression: when the UI queues a write and immediately a read_config
    # (the channel-link Apply flow does exactly this), the read must
    # observe the write.  Previously _drain_preset_queue ran before
    # _drain_pending in the poll loop, so the read returned stale data
    # and the UI snapped back as if the write never happened.
    thread.request_channel_link(0, 0x03)  # link InA+InB
    thread.request_channel_link(1, 0x00)
    thread.request_read_config()

    with qtbot.waitSignal(thread.config_loaded, timeout=500) as caught:
        # Mimic the poll-loop ordering: preset queue first, pending second.
        thread._drain_preset_queue(fake_dsp)
        thread._drain_pending(fake_dsp)

    cfg = caught.args[0]
    # Crucial assertion: emitted config reflects the link writes, not the
    # pre-write state captured at the moment read_config was queued.
    assert cfg["link_flags"][0] == 0x03
    assert cfg["link_flags"][1] == 0x00
    # And the writes really did execute exactly once each — read_config's
    # internal flush must not double-dispatch them.
    set_link_calls = [c for c in fake_dsp.calls if c[0] == "set_channel_link"]
    assert set_link_calls == [
        ("set_channel_link", (0, 0x03)),
        ("set_channel_link", (1, 0x00)),
    ]


def test_request_test_tone_dispatches_mode_and_freq(thread, fake_dsp):
    thread.request_test_tone(3, 17)  # sine @ 1 kHz
    thread._drain_pending(fake_dsp)

    calls = [c for c in fake_dsp.calls if c[0] == "set_test_tone"]
    assert calls == [("set_test_tone", (3, 17))]


def test_request_test_tone_coalesces(thread, fake_dsp):
    # Rapid changes during a slider drag should collapse to the latest.
    thread.request_test_tone(3, 0)
    thread.request_test_tone(3, 5)
    thread.request_test_tone(3, 17)
    thread._drain_pending(fake_dsp)

    calls = [c for c in fake_dsp.calls if c[0] == "set_test_tone"]
    assert calls == [("set_test_tone", (3, 17))]


# --- PIN / device-lock flow ---


class _LockedThenUnlockedDSP:
    """Minimal fake whose first read_config() raises DeviceLockedError,
    succeeds after submit_pin returns True.

    Used to drive _handle_locked directly without spinning the worker
    thread — we pre-populate the PIN queue, then call _handle_locked
    synchronously.
    """

    def __init__(self, correct_pin: str = "1234") -> None:
        self._correct = correct_pin
        self._unlocked = False
        self.submit_calls: list[str] = []
        self.read_config_calls = 0

    def submit_pin(self, pin: str) -> bool:
        self.submit_calls.append(pin)
        if pin == self._correct:
            self._unlocked = True
            return True
        return False

    def read_config(self) -> dict:
        self.read_config_calls += 1
        if not self._unlocked:
            raise DeviceLockedError("locked")
        return {"names": [], "link_flags": []}


def _answer_on_prompt(thread, pins: list[str], cancel_after: bool = False):
    """Wire up the realistic flow: when the worker emits pin_required,
    drain stale entries already done, then feed our pre-canned answers in
    order via pin_result feedback.

    The worker emits pin_required ONCE before the first get(), then keeps
    blocking on get() between attempts. So we push the first answer on
    pin_required and the next answers on each pin_result.
    """
    pending = list(pins)

    def on_required():
        if pending:
            thread.submit_pin(pending.pop(0))
        elif cancel_after:
            thread.cancel_pin_entry()

    def on_result(_ok, _left):
        if pending:
            thread.submit_pin(pending.pop(0))
        elif cancel_after:
            thread.cancel_pin_entry()

    thread.pin_required.connect(on_required)
    thread.pin_result.connect(on_result)


def test_handle_locked_success_emits_pin_required_and_returns_config(thread):
    # Signals fire synchronously while _handle_locked runs in the test
    # thread; capture them with direct slot connections instead of
    # qtbot.waitSignal (which would deadlock waiting for events that have
    # already been emitted).
    dsp = _LockedThenUnlockedDSP(correct_pin="1234")

    prompted = []
    results: list[tuple[bool, int]] = []
    thread.pin_required.connect(lambda: prompted.append(True))
    thread.pin_result.connect(lambda ok, left: results.append((ok, left)))
    _answer_on_prompt(thread, ["1234"])

    config = thread._handle_locked(dsp)

    assert config == {"names": [], "link_flags": []}
    assert prompted == [True]
    assert results == [(True, MAX_PIN_ATTEMPTS - 1)]
    assert dsp.submit_calls == ["1234"]


def test_handle_locked_three_wrong_pins_returns_none(thread):
    dsp = _LockedThenUnlockedDSP(correct_pin="1234")

    results: list[tuple[bool, int]] = []
    thread.pin_result.connect(lambda ok, left: results.append((ok, left)))
    _answer_on_prompt(thread, ["0000", "0000", "0000"])

    config = thread._handle_locked(dsp)

    assert config is None
    # Three (False, attempts_left) results with attempts_left counting down.
    assert results == [(False, 2), (False, 1), (False, 0)]
    assert dsp.submit_calls == ["0000", "0000", "0000"]
    # Exhaustion stops the worker so we don't loop right back into the
    # same prompt on the next reconnect.
    assert thread._stop is True


def test_handle_locked_cancel_returns_none_without_submitting(thread):
    dsp = _LockedThenUnlockedDSP(correct_pin="1234")
    # Cancel as soon as the dialog is "shown".
    thread.pin_required.connect(thread.cancel_pin_entry)

    config = thread._handle_locked(dsp)

    assert config is None
    assert dsp.submit_calls == []
    # Cancel means "give up on this device" — the worker stops so the
    # user is not immediately re-prompted via auto-reconnect.
    assert thread._stop is True


def test_restart_clears_stop_flag_and_queues(thread, monkeypatch):
    # Set up state as if the worker had stopped itself mid-cycle:
    # _stop=True plus leftovers in every queue.
    thread._stop = True
    thread._pending[("dummy",)] = ("x",)
    thread._preset_queue.append(("noop",))
    thread._pin_queue.put("stale_pin")

    # Stub start() — we want to verify the state reset, not actually
    # spin up a concurrent QThread inside the test.
    start_calls = []
    monkeypatch.setattr(thread, "start", lambda: start_calls.append(True))

    thread.restart()

    assert thread._stop is False
    assert thread._pending == {}
    assert len(thread._preset_queue) == 0
    assert thread._pin_queue.empty()
    assert start_calls == [True]


def test_restart_no_op_while_running(thread, monkeypatch):
    # If the worker is still running, restart must NOT clobber _stop or
    # call start() again — that would race the existing run() iteration.
    monkeypatch.setattr(thread, "isRunning", lambda: True)
    start_calls = []
    monkeypatch.setattr(thread, "start", lambda: start_calls.append(True))
    thread._stop = True  # would normally be reset

    thread.restart()

    assert thread._stop is True
    assert start_calls == []


def test_handle_locked_success_does_not_stop_worker(thread):
    dsp = _LockedThenUnlockedDSP(correct_pin="1234")
    _answer_on_prompt(thread, ["1234"])

    config = thread._handle_locked(dsp)

    assert config is not None
    # Success is NOT a reason to stop — the app should keep running.
    assert thread._stop is False


def test_request_set_pin_dispatches_via_preset_queue(thread, fake_dsp):
    thread.request_set_pin("9999")
    thread._drain_preset_queue(fake_dsp)

    calls = [c for c in fake_dsp.calls if c[0] == "set_lock_pin"]
    assert calls == [("set_lock_pin", ("9999",))]


def test_set_pin_closes_session_after_ack(thread, fake_dsp):
    # Real device ACKs but keeps the link up; we initiate the disconnect
    # AND stop the worker so we don't auto-reconnect into the unlock prompt.
    thread.request_set_pin("9999")
    thread._drain_preset_queue(fake_dsp)

    kinds = [c[0] for c in fake_dsp.calls]
    assert kinds.index("close") > kinds.index("set_lock_pin")
    # The worker has signalled itself to stop — run() will exit on the
    # next while-check instead of looping back into _try_connect.
    assert thread._stop is True


class _NoAckDSP:
    """Fake whose set_lock_pin returns False (no device ACK)."""

    closed = False

    def set_lock_pin(self, pin: str) -> bool:
        return False

    def close(self) -> None:
        self.closed = True


def test_poll_loop_exits_before_touching_dsp_after_set_pin(thread, fake_dsp):
    """Regression: set_pin closes the dsp mid-iteration; the loop must
    not call poll_levels / _drain_pending on the closed handle. The real
    DSPmini raises DeviceClosedError on a closed handle — caught by
    DEVICE_ERRORS, but it would emit a misleading 'Device disconnected'
    warning for what is really an orderly user-initiated shutdown."""
    thread.request_set_pin("9999")
    # Manually drive one iteration of the poll loop. With the bug, this
    # would call poll_levels after close — surface that by patching
    # poll_levels to raise the same exception the real lib raises.
    real_poll = fake_dsp.poll_levels

    def boom(*_a, **_k):
        raise DeviceClosedError("Device not open")

    fake_dsp.poll_levels = boom
    try:
        thread._poll_loop(fake_dsp)  # must NOT raise
    finally:
        fake_dsp.poll_levels = real_poll
    # And the worker is correctly stopped.
    assert thread._stop is True


def test_set_pin_skips_close_when_device_does_not_ack(thread):
    dsp = _NoAckDSP()
    thread.request_set_pin("9999")
    thread._drain_preset_queue(dsp)

    # No ACK → no relock happened on the device → we MUST NOT close,
    # otherwise the user would see a confusing reconnect cycle for a
    # PIN that never took. Worker also stays running.
    assert dsp.closed is False
    assert thread._stop is False


def test_command_type_enum_is_exhaustive():
    # Guard against silently dropping a command when expanding the enum.
    expected = {
        "GAIN",
        "MUTE",
        "PHASE",
        "GATE",
        "HIPASS",
        "LOPASS",
        "COMPRESSOR",
        "DELAY",
        "PEQ_BAND",
        "PEQ_CHANNEL_BYPASS",
        "MATRIX_ROUTE",
        "PREPARE_LINK",
        "CHANNEL_LINK",
        "CHANNEL_NAME",
        "TEST_TONE",
    }
    assert {c.name for c in CommandType} == expected
