"""Offline .unt round trips through VirtualDSP and the library's UntFile.

The file format itself (parsing, size and magic checks, atomic writes) is
tested in the protocol library, which owns it. These tests cover what this
application adds on top: loading a file into the offline ``VirtualDSP``,
editing it, and exporting it again without disturbing bytes it does not
model (ADR-0016).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from minidsp.unt import UNT_SIZE, UntFile, UntParseError

from minidspqt.virtual_dsp import VirtualDSP

# Files saved by the manufacturer's editor, kept in a sibling checkout of the
# protocol library. Located relative to this file so they resolve on any
# machine; the tests skip when the checkout is absent.
ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "miniDSP-Linux" / "analysis"
EDITOR_FILES = [
    "miniDSP current settings.unt",
    "miniDSP current settings 260409.unt",
    "miniDSP current settings 261026.unt",
]


def _editor_file(name: str) -> Path:
    """Return the path of an editor-saved fixture, or skip if it is missing."""
    path = ANALYSIS_DIR / name
    if not path.exists():
        pytest.skip(f"fixture not found: {path}")
    return path


def _loaded(path: Path) -> tuple[VirtualDSP, bytes]:
    """Load ``path`` into a fresh VirtualDSP; return it with the original bytes."""
    raw = path.read_bytes()
    dsp = VirtualDSP()
    dsp.load_from_unt(UntFile(raw))
    return dsp, raw


@pytest.mark.parametrize("name", EDITOR_FILES)
def test_load_then_export_is_byte_identical(name):
    dsp, raw = _loaded(_editor_file(name))
    assert dsp.export_unt().to_bytes() == raw


@pytest.mark.parametrize("name", EDITOR_FILES)
def test_double_round_trip_is_byte_identical(name):
    dsp, raw = _loaded(_editor_file(name))
    again = VirtualDSP()
    again.load_from_unt(dsp.export_unt())
    assert again.export_unt().to_bytes() == raw


def test_stored_gain_edit_changes_only_its_slot():
    path = _editor_file("miniDSP current settings 261026.unt")
    dsp, raw = _loaded(path)
    original = UntFile(raw)
    active = original.active_slot

    dsp.set_gain(0, dsp.read_config()["gains"][0] + 1)
    dsp.store_preset(active, original.slot_name(active))
    saved = dsp.export_unt().to_bytes()

    slot_start = 0x32 + (active - 1) * 432
    diffs = [i for i in range(UNT_SIZE) if raw[i] != saved[i]]
    assert diffs, "the stored gain edit must reach the file"
    assert all(slot_start <= i < slot_start + 432 for i in diffs), diffs
    assert len(diffs) <= 2, f"a gain is one u16; changed bytes: {diffs}"


def test_unsaved_edit_is_not_exported():
    """Like the device, the file holds stored presets, not the working copy."""
    dsp, raw = _loaded(_editor_file("miniDSP current settings 261026.unt"))
    dsp.set_gain(0, dsp.read_config()["gains"][0] + 1)
    assert dsp.export_unt().to_bytes() == raw


def test_stored_mute_edit_round_trips():
    dsp, raw = _loaded(_editor_file("miniDSP current settings 261026.unt"))
    active = UntFile(raw).active_slot
    dsp.mute(0, True)
    dsp.store_preset(active, "Muted")

    reread = dsp.export_unt()
    assert reread.slot_params(active)["mutes"][0] is True
    assert reread.slot_name(active) == "Muted"


def test_f00_active_file_loads_with_factory_working_config():
    path = _editor_file("miniDSP current settings 261026.unt")
    unt = UntFile.read(path)
    unt.active_slot = 0
    dsp = VirtualDSP()
    dsp.load_from_unt(unt)

    cfg = dsp.read_config()
    assert cfg["active_slot"] == 0
    assert cfg["gains"] == VirtualDSP().read_config()["gains"]
    # The stored slots are still there and the active byte survives export.
    assert dsp.export_unt().to_bytes() == unt.to_bytes()


def test_fresh_virtual_dsp_exports_the_empty_file():
    assert VirtualDSP().export_unt().to_bytes() == UntFile.blank().to_bytes()


def test_seeded_active_slot_is_exported():
    """Connected → Offline → Save used to write an empty file."""
    live = VirtualDSP().read_config()
    live["gains"] = [123] * 8
    live["active_slot"] = 5
    live["preset_names"] = [f"Name{i:02d}" for i in range(1, 31)]

    dsp = VirtualDSP()
    dsp.seed_from_config(live)
    unt = dsp.export_unt()

    assert unt.active_slot == 5
    assert unt.filled_slots() == [5]
    assert unt.slot_params(5)["gains"] == [123] * 8
    assert unt.slot_name(5) == "Name05"


def test_load_does_not_share_state_with_the_callers_file():
    dsp, raw = _loaded(_editor_file("miniDSP current settings 261026.unt"))
    unt = UntFile(raw)
    dsp2 = VirtualDSP()
    dsp2.load_from_unt(unt)
    unt.clear_slot(unt.filled_slots()[0])
    assert dsp2.export_unt().to_bytes() == raw


def test_malformed_file_raises_the_error_the_gui_catches(tmp_path):
    bad = tmp_path / "short.unt"
    bad.write_bytes(b"\x00" * 100)
    with pytest.raises(UntParseError):
        UntFile.read(bad)
