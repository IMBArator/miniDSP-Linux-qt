"""unt_writer — byte-level round-trip and targeted-edit tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from minidspqt.unt_loader import load_unt_all_slots
from minidspqt.unt_writer import save_unt

FIXTURE_PATH = Path("/home/max/src/miniDSP-Linux/analysis/miniDSP current settings.unt")
skip_if_no_fixture = pytest.mark.skipif(
    not FIXTURE_PATH.exists(),
    reason="fixture .unt not available",
)


@skip_if_no_fixture
def test_round_trip_byte_identical():
    slots, active, names, raw = load_unt_all_slots(FIXTURE_PATH)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.unt"
        save_unt(out, slots, names, active, raw)
        saved = out.read_bytes()
    assert saved == raw, "Round-trip must produce byte-identical output"


@skip_if_no_fixture
def test_edit_gain_only_touches_expected_bytes():
    slots, active, names, raw = load_unt_all_slots(FIXTURE_PATH)
    modified = [s if s is not None else None for s in slots]
    edited = dict(modified[active])
    edited["gains"] = list(edited["gains"])
    edited["gains"][0] = edited["gains"][0] + 1
    modified[active] = edited

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.unt"
        save_unt(out, modified, names, active, raw)
        saved = out.read_bytes()

    diffs = []
    for i in range(len(raw)):
        if raw[i] != saved[i]:
            diffs.append(i)
    assert len(diffs) > 0, "Something should have changed"
    assert len(diffs) <= 6, f"Too many bytes changed: {diffs}"


@skip_if_no_fixture
def test_edit_mute_touches_footer_bitmask():
    slots, active, names, raw = load_unt_all_slots(FIXTURE_PATH)
    modified = [s if s is not None else None for s in slots]
    edited = dict(modified[active])
    edited["mutes"] = list(edited["mutes"])
    edited["mutes"][0] = True
    modified[active] = edited

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.unt"
        save_unt(out, modified, names, active, raw)
        saved = out.read_bytes()

    from minidspqt.unt_loader import SLOT_BASE, SLOT_STRIDE

    blob_start = SLOT_BASE + active * SLOT_STRIDE + 1
    input_mute_lo = saved[blob_start + 408]
    input_mute_hi = saved[blob_start + 409]
    input_mute = input_mute_lo + (input_mute_hi << 8)
    assert input_mute & 1 == 1, "Input 0 mute bit should be set"


def test_save_without_template_uses_blank():
    from minidspqt.virtual_dsp import VirtualDSP

    dsp = VirtualDSP()

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "blank_out.unt"
        slots_0, active_0, _ = dsp.export_to_unt_args()
        names_30 = [f"U{i + 1:02d}" for i in range(30)]
        save_unt(out, slots_0, names_30, active_0, template=None)

        saved = out.read_bytes()
        assert len(saved) == 13010

        slots, active, names, _ = load_unt_all_slots(out)
        assert active == active_0
        assert all(s is None for s in slots)


@skip_if_no_fixture
def test_round_trip_after_store_and_edit():
    slots, active, names, raw = load_unt_all_slots(FIXTURE_PATH)
    with tempfile.TemporaryDirectory() as tmp:
        out1 = Path(tmp) / "step1.unt"
        save_unt(out1, slots, names, active, raw)

        slots2, active2, names2, raw2 = load_unt_all_slots(out1)
        assert raw2 == raw

        out2 = Path(tmp) / "step2.unt"
        save_unt(out2, slots2, names2, active2, raw2)
        assert out2.read_bytes() == raw, "Double round-trip must be identical"
