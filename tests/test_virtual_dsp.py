"""VirtualDSP — state persistence, load/store round-trip, read-after-write."""

from __future__ import annotations

from minidspqt.virtual_dsp import VirtualDSP


def test_set_gain_persists():
    dsp = VirtualDSP()
    dsp.set_gain(0, 250)
    cfg = dsp.read_config()
    assert cfg["gains"][0] == 250


def test_mute_persists():
    dsp = VirtualDSP()
    dsp.mute(3, True)
    assert dsp.read_config()["mutes"][3] is True
    dsp.mute(3, False)
    assert dsp.read_config()["mutes"][3] is False


def test_set_phase_persists():
    dsp = VirtualDSP()
    dsp.set_phase(4, True)
    assert dsp.read_config()["phases"][4] is True


def test_set_delay_persists():
    dsp = VirtualDSP()
    dsp.set_delay(0x06, 480)
    assert dsp.read_config()["delays"][2] == 480


def test_set_gate_persists():
    dsp = VirtualDSP()
    dsp.set_gate(1, 100, 200, 300, 40)
    gate = dsp.read_config()["gates"][1]
    assert gate == {"attack": 100, "release": 200, "hold": 300, "threshold": 40}


def test_set_peq_band_persists():
    dsp = VirtualDSP()
    dsp.set_peq_band(0x05, 2, 130, 200, 50, 1, True)
    band = dsp.read_config()["peqs"][1]["bands"][2]
    assert band == {"gain": 130, "freq": 200, "q": 50, "type": 1, "bypass": True}


def test_set_matrix_route_persists():
    dsp = VirtualDSP()
    dsp.set_matrix_route(0x07, 0x0F)
    assert dsp.read_config()["routings"][3] == 0x0F


def test_set_compressor_persists():
    dsp = VirtualDSP()
    dsp.set_compressor(0x04, 5, 6, 100, 500, 60)
    comp = dsp.read_config()["compressors"][0]
    assert comp == {"ratio": 5, "knee": 6, "attack": 100, "release": 500, "threshold": 60}


def test_store_then_load_roundtrip():
    dsp = VirtualDSP()
    dsp.set_gain(0, 250)
    dsp.set_gain(4, 180)
    dsp.mute(2, True)
    original = dsp.read_config()

    assert dsp.store_preset(5, "TestPreset")

    dsp.set_gain(0, 100)
    dsp.mute(2, False)
    assert dsp.read_config()["gains"][0] == 100

    loaded = dsp.load_preset(5)
    assert loaded is not None
    assert loaded["gains"][0] == 250
    assert loaded["gains"][4] == 180
    assert loaded["mutes"][2] is True
    assert dsp._preset_names[4] == "TestPreset"


def test_load_preset_updates_active_slot():
    dsp = VirtualDSP()
    dsp.store_preset(3, "Slot3")
    result = dsp.load_preset(3)
    assert result is not None
    assert result["active_slot"] == 3


def test_load_preset_f00_factory():
    dsp = VirtualDSP()
    dsp.set_gain(0, 100)
    dsp.mute(2, True)
    assert dsp.read_config()["gains"][0] == 100

    cfg = dsp.load_preset(0)
    assert cfg is not None
    assert cfg["active_slot"] == 0
    assert cfg["gains"][0] == 280  # factory default
    assert not cfg["mutes"][2]


def test_load_preset_invalid_slot():
    dsp = VirtualDSP()
    assert dsp.load_preset(0) is not None  # F00 is valid
    assert dsp.load_preset(31) is None


def test_load_preset_empty_slot():
    dsp = VirtualDSP()
    assert dsp.load_preset(1) is None


def test_store_preset_invalid_slot():
    dsp = VirtualDSP()
    assert dsp.store_preset(0, "bad") is False
    assert dsp.store_preset(31, "bad") is False


def test_read_config_returns_deep_copy():
    dsp = VirtualDSP()
    cfg1 = dsp.read_config()
    cfg1["gains"][0] = 999
    assert dsp.read_config()["gains"][0] == 280


def test_poll_levels():
    dsp = VirtualDSP()
    levels = dsp.poll_levels()
    assert levels["inputs"] == [0, 0, 0, 0]
    assert levels["outputs"] == [0, 0, 0, 0]


def test_open_close_noop():
    dsp = VirtualDSP()
    dsp.open()
    dsp.close()


def test_load_from_unt_bytes():
    dsp = VirtualDSP()
    slot_cfg = {
        "names": ["InA", "InB", "InC", "InD", "Out1", "Out2", "Out3", "Out4"],
        "gains": [300, 280, 280, 280, 200, 200, 200, 200],
        "mutes": [False] * 8,
        "phases": [False] * 8,
        "link_flags": [0x01, 0x02, 0x04, 0x08, 0x01, 0x02, 0x04, 0x08],
        "routings": [0x01, 0x02, 0x04, 0x08],
        "gates": [{"attack": 50, "release": 100, "hold": 200, "threshold": 20}] * 4,
        "delays": [0, 0, 0, 0],
        "crossovers": [{"hipass_freq": 0, "hipass_slope": 0, "lopass_freq": 0, "lopass_slope": 0}] * 4,
        "compressors": [{"ratio": 0, "knee": 0, "attack": 0, "release": 0, "threshold": 0}] * 4,
        "peqs": [{"bands": [{"gain": 120, "freq": 150, "q": 40, "type": 0, "bypass": False}] * 7, "channel_bypass": False}] * 4,
    }
    raw = b"\x00" * 13010
    slots = [None] * 30
    slots[1] = slot_cfg
    names = [""] * 30
    names[1] = "TestPreset"

    dsp.load_from_unt_bytes(raw, slots, active_slot_0based=1, preset_names=names)
    cfg = dsp.read_config()
    assert cfg["active_slot"] == 2  # device numbering: 0based=1 → 1based=2
    assert cfg["gains"][0] == 300
    assert cfg["gains"][4] == 200
    assert dsp._source_bytes == raw


def test_export_to_unt_args():
    dsp = VirtualDSP()
    dsp.store_preset(3, "ExportTest")
    dsp.load_preset(3)
    slots, active_0based, source = dsp.export_to_unt_args()
    assert active_0based == 2
    assert slots[2] is not None
    assert source is None


def test_set_channel_name():
    dsp = VirtualDSP()
    dsp.set_channel_name(4, "Left")
    assert dsp.read_config()["names"][4] == "Left"


def test_set_hipass_lopass():
    dsp = VirtualDSP()
    dsp.set_hipass(0x04, 100, 3)
    dsp.set_lopass(0x04, 200, 5)
    cfg = dsp.read_config()
    assert cfg["crossovers"][0]["hipass_freq"] == 100
    assert cfg["crossovers"][0]["hipass_slope"] == 3
    assert cfg["crossovers"][0]["lopass_freq"] == 200
    assert cfg["crossovers"][0]["lopass_slope"] == 5
