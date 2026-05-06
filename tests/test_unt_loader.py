"""Unit tests for the .unt file parser — pure Python, no Qt required."""

from __future__ import annotations

import pytest

from minidspqt.unt_loader import EXPECTED_SIZE, UntParseError, load_unt

FIXTURE_PATH = "/home/max/src/miniDSP-Linux/analysis/miniDSP current settings.unt"


@pytest.fixture
def real_unt(tmp_path):
    """Return the real .unt fixture path, or skip if absent."""
    import pathlib

    p = pathlib.Path(FIXTURE_PATH)
    if not p.exists():
        pytest.skip(f"fixture not found: {FIXTURE_PATH}")
    return p


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
