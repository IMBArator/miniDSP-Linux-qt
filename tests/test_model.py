"""DeviceState.from_config() — channel ordering and field propagation."""

from __future__ import annotations

import copy

from minidspqt.model import DeviceState, GateState, PEQBand


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


# ---------------------------------------------------------------------------
# mutate_with_links — generic linked mutator for nested-param fan-out
# ---------------------------------------------------------------------------


def test_mutate_with_links_gate_propagates(preset_cfg):
    """Setting gate threshold on a master should mirror to every slave.

    We mutate via the dedicated GateState assignment because a single edit
    on the panel emits all four gate fields atomically (device opcode 0x3E
    is also atomic) — the test mirrors that shape.
    """
    state = DeviceState.from_config(_linked_cfg(preset_cfg))

    def _mutate(obj):
        obj.gate = GateState(attack=10, release=20, hold=30, threshold=120)

    affected = state.mutate_with_links(0, _mutate)
    assert set(affected) == {0, 1}
    assert affected[0] == 0
    assert state.inputs[0].gate.threshold == 120
    assert state.inputs[1].gate.threshold == 120
    assert state.inputs[1].gate.attack == 10


def test_mutate_with_links_peq_band_grows_list(preset_cfg):
    """PEQ band index beyond the slave's existing list must grow it."""
    state = DeviceState.from_config(_linked_cfg(preset_cfg))
    # Truncate slave's peqs so the fan-out has to grow it
    state.outputs[1].peqs = []

    def _mutate(obj):
        while len(obj.peqs) <= 3:
            obj.peqs.append(PEQBand())
        obj.peqs[3] = PEQBand(gain_raw=160, freq_raw=170, q_raw=20, filter_type=0)

    affected = state.mutate_with_links(4, _mutate)
    assert set(affected) == {4, 5, 6}
    for ch_idx in (0, 1, 2):
        assert len(state.outputs[ch_idx].peqs) >= 4
        assert state.outputs[ch_idx].peqs[3].gain_raw == 160


def test_mutate_with_links_does_not_touch_link_flags(preset_cfg):
    """A well-behaved mutator should never alter link_flags.

    The contract is that link_flags are owned by the channel-linking
    dialog, not parameter handlers. Verify the topology survives a
    routine param fan-out.
    """
    state = DeviceState.from_config(_linked_cfg(preset_cfg))
    before = [ch.link_flags for ch in state.inputs] + [
        ch.link_flags for ch in state.outputs
    ]

    state.mutate_with_links(0, lambda obj: setattr(obj, "muted", True))

    after = [ch.link_flags for ch in state.inputs] + [
        ch.link_flags for ch in state.outputs
    ]
    assert after == before


def test_mutate_with_links_slave_only_self(preset_cfg):
    """Calling mutate_with_links on a slave should not reach back to the master."""
    state = DeviceState.from_config(_linked_cfg(preset_cfg))

    def _mutate(obj):
        obj.gate = GateState(threshold=99)

    affected = state.mutate_with_links(1, _mutate)
    assert affected == [1]
    assert state.inputs[1].gate.threshold == 99
    # Master must be untouched
    assert state.inputs[0].gate.threshold != 99


def test_mutate_with_links_out_of_range(preset_cfg):
    state = DeviceState.from_config(preset_cfg)
    assert state.mutate_with_links(99, lambda obj: None) == []


# ---------------------------------------------------------------------------
# comp_active property
# ---------------------------------------------------------------------------


def test_comp_active_ratio_zero_is_inactive(preset_cfg):
    """Raw ratio 0 = 1:1.0 = no compression -> indicator stays dark."""
    state = DeviceState.from_config(preset_cfg)
    state.outputs[0].compressor.ratio = 0
    assert state.outputs[0].comp_active is False


def test_comp_active_ratio_nonzero_is_active(preset_cfg):
    state = DeviceState.from_config(preset_cfg)
    state.outputs[0].compressor.ratio = 5  # 1:2.0
    assert state.outputs[0].comp_active is True

    state.outputs[0].compressor.ratio = 15  # Limit
    assert state.outputs[0].comp_active is True


# ---------------------------------------------------------------------------
# delay_active property
# ---------------------------------------------------------------------------


def test_delay_active_zero_is_inactive(preset_cfg):
    """No delay (0 samples) -> indicator stays dark."""
    state = DeviceState.from_config(preset_cfg)
    state.outputs[0].delay_samples = 0
    assert state.outputs[0].delay_active is False


def test_delay_active_nonzero_is_active(preset_cfg):
    state = DeviceState.from_config(preset_cfg)
    state.outputs[0].delay_samples = 1  # 1 sample ≈ 0.02 ms — still "on"
    assert state.outputs[0].delay_active is True

    state.outputs[0].delay_samples = 32640  # protocol max
    assert state.outputs[0].delay_active is True
