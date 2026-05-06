"""Parser for the miniDSP .unt binary preset file format."""

from __future__ import annotations

import os

from minidsp.protocol import parse_preset_params

MAGIC = b"***4x4MINIV010**"
EXPECTED_SIZE = 13010
SLOT_COUNT = 30
SLOT_STRIDE = 432  # 1 slot-number byte + 429 config bytes + 2-byte CRLF
SLOT_BASE = 0x32  # file offset of slot 0 (U01)
ACTIVE_SLOT_OFFSET = 0x11  # header byte: 1-indexed active slot (1=U01 ... 30=U30)
EMPTY_FILL = 0x64  # 'd' — byte used to fill unused slots


class UntParseError(ValueError):
    """Raised when a .unt file cannot be parsed."""


def load_unt_all_slots(
    path: str | os.PathLike,
) -> tuple[list[dict | None], int, list[str], bytes]:
    """Load a .unt file and parse **all** 30 slots.

    Returns ``(slots, active_slot, preset_names, raw_bytes)``.

    *slots*: 30 entries (0-indexed); ``None`` for empty slots.
    *active_slot*: 0-indexed (0 = U01, …, 29 = U30).
    *preset_names*: 30 strings.
    *raw_bytes*: the full 13,010-byte file content.
    """
    with open(path, "rb") as f:
        data = f.read()

    if len(data) != EXPECTED_SIZE:
        raise UntParseError(f"Expected {EXPECTED_SIZE} bytes, got {len(data)}")
    if data[:16] != MAGIC:
        raise UntParseError("Not a miniDSP .unt file (bad magic header)")

    active_slot_raw = data[ACTIVE_SLOT_OFFSET]
    if not (1 <= active_slot_raw <= SLOT_COUNT):
        raise UntParseError(
            f"Active slot byte {active_slot_raw} out of range [1, {SLOT_COUNT}]"
        )
    active_slot = active_slot_raw - 1

    slots: list[dict | None] = [None] * SLOT_COUNT
    preset_names: list[str] = [""] * SLOT_COUNT

    for slot in range(SLOT_COUNT):
        offset = SLOT_BASE + slot * SLOT_STRIDE
        if data[offset] == EMPTY_FILL:
            continue
        blob = _slot_blob(data, slot)
        raw_name = blob[2:16]
        preset_names[slot] = (
            raw_name.rstrip(b"\x00").rstrip(b" ").decode("ascii", errors="replace")
        )
        parsed = parse_preset_params(blob)
        if parsed is not None:
            slots[slot] = parsed

    return slots, active_slot, preset_names, bytes(data)


def load_unt(path: str | os.PathLike) -> tuple[dict, int, list[str]]:
    """Load a .unt preset file and return (cfg_dict, active_slot, preset_names).

    active_slot is 0-indexed (0=U01 ... 29=U30).
    preset_names is a list of 30 strings (empty string for unused slots).
    cfg_dict is the dict produced by parse_preset_params, ready for DeviceState.from_config.
    """
    with open(path, "rb") as f:
        data = f.read()

    if len(data) != EXPECTED_SIZE:
        raise UntParseError(f"Expected {EXPECTED_SIZE} bytes, got {len(data)}")
    if data[:16] != MAGIC:
        raise UntParseError("Not a miniDSP .unt file (bad magic header)")

    active_slot_raw = data[ACTIVE_SLOT_OFFSET]
    if not (1 <= active_slot_raw <= SLOT_COUNT):
        raise UntParseError(
            f"Active slot byte {active_slot_raw} out of range [1, {SLOT_COUNT}]"
        )
    active_slot = active_slot_raw - 1  # convert to 0-based

    preset_names: list[str] = []
    for slot in range(SLOT_COUNT):
        offset = SLOT_BASE + slot * SLOT_STRIDE
        if data[offset] == EMPTY_FILL:
            preset_names.append("")
            continue
        blob = _slot_blob(data, slot)
        # Preset name: bytes 2–15 of blob (after FF FF marker), space-padded ASCII
        raw_name = blob[2:16]
        preset_names.append(
            raw_name.rstrip(b"\x00").rstrip(b" ").decode("ascii", errors="replace")
        )

    cfg = parse_preset_params(_slot_blob(data, active_slot))
    if cfg is None:
        raise UntParseError(f"Failed to parse active slot U{active_slot + 1:02d}")

    return cfg, active_slot, preset_names


def _slot_blob(data: bytes, slot: int) -> bytes:
    """Return the 429-byte config blob for a slot (0-indexed)."""
    offset = SLOT_BASE + slot * SLOT_STRIDE
    # byte 0 = 1-indexed slot number; bytes 1..429 = config blob
    return data[offset + 1 : offset + 430]
