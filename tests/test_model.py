"""DeviceState.from_config() — channel ordering and field propagation."""

from __future__ import annotations

import copy

from minidspqt.model import DeviceState


def _linked_cfg(preset_cfg):
    """Variant where In0+In1 are linked (master In0) and Out0+Out1+Out2 are linked (master Out0)."""
    cfg = copy.deepcopy(preset_cfg)
    # Inputs: In0 master = own (0x01) | In1 (0x02) = 0x03; In1 slave = 0x00
    cfg["link_flags"][0] = 0x03
    cfg["link_flags"][1] = 0x00
    # Outputs: Out0 master = own (0x01) | Out1 (0x02) | Out2 (0x04) = 0x07; Out1, Out2 slaves = 0x00
    cfg["link_flags"][4] = 0x07
    cfg["link_flags"][5] = 0x00
    cfg["link_flags"][6] = 0x00
    return cfg


def test_from_config_channel_order(preset_cfg):
    state = DeviceState.from_config(preset_cfg)

    assert state.connected is True
    assert len(state.inputs) == 4
    assert len(state.outputs) == 4

    # Inputs pull gains[0..3] / names[0..3]
    assert [ch.name for ch in state.inputs] == ["InA", "InB", "InC", "InD"]
    assert [ch.gain_raw for ch in state.inputs] == [280, 281, 282, 283]
    assert state.inputs[1].muted is True
    assert state.inputs[2].phase_inverted is True

    # Outputs pull gains[4..7] / names[4..7]
    assert [ch.name for ch in state.outputs] == ["Out1", "Out2", "Out3", "Out4"]
    assert [ch.gain_raw for ch in state.outputs] == [100, 101, 102, 103]
    assert state.outputs[2].muted is True


def test_from_config_output_details(preset_cfg):
    state = DeviceState.from_config(preset_cfg)

    out2 = state.outputs[1]
    assert out2.delay_samples == 48
    assert out2.crossover.lopass_freq == 300
    assert out2.compressor.ratio == 2
    assert len(out2.peqs) == 7
    assert out2.peqs[0].gain_raw == 120
    assert out2.peqs[0].freq_raw == 150
    assert out2.routing_mask == 0x02
    assert out2.link_flags == 0x20


def test_from_config_preset_metadata(preset_cfg):
    state = DeviceState.from_config(preset_cfg)
    assert state.active_slot == 1
    assert state.preset_names[0] == "P00"
    assert len(state.preset_names) == 30


def test_set_field_writes_through(preset_cfg):
    state = DeviceState.from_config(preset_cfg)
    assert state.set_field(0, "muted", True) is True
    assert state.inputs[0].muted is True

    assert state.set_field(5, "gain_raw", 200) is True
    assert state.outputs[1].gain_raw == 200


def test_set_field_out_of_range(preset_cfg):
    state = DeviceState.from_config(preset_cfg)
    assert state.set_field(-1, "muted", True) is False
    assert state.set_field(99, "muted", True) is False


def test_set_field_with_links_lone_channel(preset_cfg):
    state = DeviceState.from_config(preset_cfg)
    affected = state.set_field_with_links(2, "gain_raw", 250)
    assert affected == [2]
    assert state.inputs[2].gain_raw == 250


def test_set_field_with_links_master_propagates(preset_cfg):
    state = DeviceState.from_config(_linked_cfg(preset_cfg))
    affected = state.set_field_with_links(0, "gain_raw", 250)
    assert affected[0] == 0
    assert set(affected) == {0, 1}
    assert state.inputs[0].gain_raw == 250
    assert state.inputs[1].gain_raw == 250

    affected_out = state.set_field_with_links(4, "muted", True)
    assert affected_out[0] == 4
    assert set(affected_out) == {4, 5, 6}
    assert state.outputs[0].muted is True
    assert state.outputs[1].muted is True
    assert state.outputs[2].muted is True


def test_set_field_with_links_slave_only_self(preset_cfg):
    # Slaves never receive UI signals (their strips are disabled), but the
    # helper should still update only the slave channel itself in that
    # hypothetical case — never reach back into the master.
    state = DeviceState.from_config(_linked_cfg(preset_cfg))
    affected = state.set_field_with_links(1, "gain_raw", 99)
    assert affected == [1]
    assert state.inputs[1].gain_raw == 99
    assert state.inputs[0].gain_raw != 99


def test_set_field_with_links_out_of_range(preset_cfg):
    state = DeviceState.from_config(preset_cfg)
    assert state.set_field_with_links(99, "muted", True) == []
