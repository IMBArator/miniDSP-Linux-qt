"""Unit tests for the .unt file parser — pure Python, no Qt required."""

from __future__ import annotations

from pathlib import Path

import pytest

from minidspqt.unt_loader import (
    EXPECTED_SIZE,
    UntParseError,
    load_unt,
    load_unt_all_slots,
)

# Real-device capture from a sibling checkout of the protocol library, located
# relative to this file so it resolves on any machine and OS. Absent unless
# miniDSP-Linux is cloned next to this repository, hence the graceful skip.
FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "miniDSP-Linux"
    / "analysis"
    / "miniDSP current settings.unt"
)
BUNDLED_BLANK = (
    Path(__file__).resolve().parent.parent / "minidspqt" / "resources" / "blank.unt"
)


@pytest.fixture
def real_unt(tmp_path):
    """Return the real .unt fixture path, or skip if absent."""
    if not FIXTURE_PATH.exists():
        pytest.skip(f"fixture not found: {FIXTURE_PATH}")
    return FIXTURE_PATH


def test_load_unt_parses_real_fixture(real_unt):
    cfg, active_slot, preset_names = load_unt(real_unt)

    assert active_slot in range(30)
    assert len(preset_names) == 30
    assert preset_names[active_slot] != ""
    assert cfg["names"] == ["InA", "InB", "InC", "InD", "Out1", "Out2", "Out3", "Out4"]


def test_bad_magic_raises(tmp_path):
    bad = tmp_path / "bad.unt"
    bad.write_bytes(b"\x00" * EXPECTED_SIZE)
    with pytest.raises(UntParseError, match="magic"):
        load_unt(bad)


def test_wrong_size_raises(tmp_path):
    bad = tmp_path / "short.unt"
    bad.write_bytes(b"\x00" * 100)
    with pytest.raises(UntParseError, match="bytes"):
        load_unt(bad)


def test_bundled_blank_unt_has_no_stored_presets():
    """Mimics a brand-new DSP: every slot empty, no preset names."""
    slots, _, names, raw = load_unt_all_slots(BUNDLED_BLANK)
    assert len(raw) == EXPECTED_SIZE
    assert all(s is None for s in slots)
    assert all(n == "" for n in names)
