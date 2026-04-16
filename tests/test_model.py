"""DeviceState.from_config() — channel ordering and field propagation."""

from __future__ import annotations

from minidspqt.model import DeviceState


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
