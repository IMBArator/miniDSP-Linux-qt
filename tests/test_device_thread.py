"""DeviceThread — exercise the coalescing dispatch without Qt threading.

We drive `_drain_pending` / `_drain_preset_queue` directly with a FakeDSPmini,
which is faster and more deterministic than spinning up the real QThread.
"""

from __future__ import annotations

import pytest

from minidspqt.device_thread import CommandType, DeviceThread


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


def test_request_prepare_link_dispatches_in_order_before_channel_link(
    thread, fake_dsp
):
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
    }
    assert {c.name for c in CommandType} == expected
