"""Write a miniDSP .unt preset file from slot configs.

Starts from a 13,010-byte template and overwrites only the fields we model,
preserving unknown/reserved bytes for round-trip fidelity.

Pure function — does not depend on VirtualDSP or Qt.
"""

from __future__ import annotations

import struct
from pathlib import Path

from .unt_loader import (
    ACTIVE_SLOT_OFFSET,
    EXPECTED_SIZE,
    SLOT_BASE,
    SLOT_COUNT,
    SLOT_STRIDE,
)

_INPUT_START = 16
_INPUT_BLOCK_SIZE = 24
_OUTPUT_START = 112
_OUTPUT_BLOCK_SIZE = 74

_BLOB_SIZE = 429
_NAME_OFFSET = 2
_NAME_SIZE = 14

# Offsets within each input block (24 bytes)
_IN_NAME = 0
_IN_NAME_SIZE = 8
_IN_GATE_ATTACK = 10
_IN_GATE_RELEASE = 12
_IN_GATE_HOLD = 14
_IN_GATE_THRESH = 16
_IN_GAIN = 18
_IN_PHASE = 20
_IN_LINK = 22

# Offsets within each output block (74 bytes)
_OUT_NAME = 0
_OUT_NAME_SIZE = 8
_OUT_ROUTING = 8
_OUT_HIPASS = 10
_OUT_LOPASS = 12
_OUT_HIPASS_SLOPE = 14
_OUT_LOPASS_SLOPE = 15
_OUT_PEQ = 16
_OUT_PEQ_BAND_SIZE = 6
_OUT_COMP_RATIO = 58
_OUT_COMP_KNEE = 59
_OUT_COMP_ATTACK = 60
_OUT_COMP_RELEASE = 62
_OUT_COMP_THRESH = 64
_OUT_GAIN = 66
_OUT_PHASE = 68
_OUT_DELAY = 70
_OUT_LINK = 72

# Footer offsets within the 429-byte blob
_FOOTER_INPUT_MUTE = 408
_FOOTER_OUTPUT_MUTE = 410
_FOOTER_PEQ_BAND_BYPASS = 412
_FOOTER_PEQ_CHAN_BYPASS = 428


def save_unt(
    path: str | Path,
    slots: list[dict | None],
    slot_names: list[str],
    active_slot: int,
    template: bytes | None = None,
) -> None:
    """Write a 13,010-byte .unt file.

    *slots*: 30 entries (0-indexed, U01–U30); ``None`` means empty.
    *slot_names*: 30 preset name strings.
    *active_slot*: 0-indexed active preset (0 = U01, …, 29 = U30).
    *template*: raw 13,010 bytes to start from (preserves unknown fields).
        Falls back to the bundled blank.unt if ``None``.
    """
    if template is not None:
        data = bytearray(template)
    else:
        from importlib.resources import files
        data = bytearray(files("minidspqt.resources").joinpath("blank.unt").read_bytes())

    if len(data) != EXPECTED_SIZE:
        raise ValueError(f"Template must be {EXPECTED_SIZE} bytes, got {len(data)}")

    data[ACTIVE_SLOT_OFFSET] = active_slot + 1

    for i in range(SLOT_COUNT):
        if slots[i] is None:
            continue
        _write_slot(data, i, slots[i], slot_names[i] if i < len(slot_names) else "")

    Path(path).write_bytes(bytes(data))


def _write_slot(
    data: bytearray, slot: int, cfg: dict, name: str,
) -> None:
    base = SLOT_BASE + slot * SLOT_STRIDE
    data[base] = slot + 1  # 1-indexed slot number byte

    blob_start = base + 1
    blob = bytearray(data[blob_start : blob_start + _BLOB_SIZE])

    # Preset name (bytes 2–15)
    encoded = name[:_NAME_SIZE].encode("ascii", errors="replace")
    blob[_NAME_OFFSET : _NAME_OFFSET + _NAME_SIZE] = encoded.ljust(_NAME_SIZE, b" ")

    _pack_inputs(blob, cfg)
    _pack_outputs(blob, cfg)
    _pack_footer(blob, cfg)

    data[blob_start : blob_start + _BLOB_SIZE] = blob
    # CRLF terminator
    data[blob_start + _BLOB_SIZE] = 0x0D
    data[blob_start + _BLOB_SIZE + 1] = 0x0A


def _pack_u16(buf: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<H", buf, offset, value)


def _pack_inputs(blob: bytearray, cfg: dict) -> None:
    for i in range(4):
        base = _INPUT_START + i * _INPUT_BLOCK_SIZE
        encoded = cfg["names"][i][:_IN_NAME_SIZE].encode("ascii", errors="replace")
        blob[base + _IN_NAME : base + _IN_NAME + _IN_NAME_SIZE] = encoded.ljust(
            _IN_NAME_SIZE, b"\x00"
        )
        _pack_u16(blob, base + _IN_GATE_ATTACK, cfg["gates"][i]["attack"])
        _pack_u16(blob, base + _IN_GATE_RELEASE, cfg["gates"][i]["release"])
        _pack_u16(blob, base + _IN_GATE_HOLD, cfg["gates"][i]["hold"])
        _pack_u16(blob, base + _IN_GATE_THRESH, cfg["gates"][i]["threshold"])
        _pack_u16(blob, base + _IN_GAIN, cfg["gains"][i])
        blob[base + _IN_PHASE] = 0x01 if cfg["phases"][i] else 0x00
        blob[base + _IN_LINK] = cfg["link_flags"][i]


def _pack_outputs(blob: bytearray, cfg: dict) -> None:
    for i in range(4):
        base = _OUTPUT_START + i * _OUTPUT_BLOCK_SIZE
        ch = i + 4  # unified index
        encoded = cfg["names"][ch][:_OUT_NAME_SIZE].encode("ascii", errors="replace")
        blob[base + _OUT_NAME : base + _OUT_NAME + _OUT_NAME_SIZE] = encoded.ljust(
            _OUT_NAME_SIZE, b"\x00"
        )
        blob[base + _OUT_ROUTING] = cfg["routings"][i]
        _pack_u16(blob, base + _OUT_HIPASS, cfg["crossovers"][i]["hipass_freq"])
        _pack_u16(blob, base + _OUT_LOPASS, cfg["crossovers"][i]["lopass_freq"])
        blob[base + _OUT_HIPASS_SLOPE] = cfg["crossovers"][i]["hipass_slope"]
        blob[base + _OUT_LOPASS_SLOPE] = cfg["crossovers"][i]["lopass_slope"]

        # PEQ bands
        bands = cfg["peqs"][i]["bands"]
        for b in range(7):
            boff = base + _OUT_PEQ + b * _OUT_PEQ_BAND_SIZE
            if b < len(bands):
                _pack_u16(blob, boff, bands[b]["gain"])
                _pack_u16(blob, boff + 2, bands[b]["freq"])
                blob[boff + 4] = bands[b]["q"]
                blob[boff + 5] = bands[b]["type"]

        # Compressor
        comp = cfg["compressors"][i]
        blob[base + _OUT_COMP_RATIO] = comp["ratio"]
        blob[base + _OUT_COMP_KNEE] = comp["knee"]
        _pack_u16(blob, base + _OUT_COMP_ATTACK, comp["attack"])
        _pack_u16(blob, base + _OUT_COMP_RELEASE, comp["release"])
        _pack_u16(blob, base + _OUT_COMP_THRESH, comp["threshold"])

        _pack_u16(blob, base + _OUT_GAIN, cfg["gains"][ch])
        blob[base + _OUT_PHASE] = 0x01 if cfg["phases"][ch] else 0x00
        _pack_u16(blob, base + _OUT_DELAY, cfg["delays"][i])
        blob[base + _OUT_LINK] = cfg["link_flags"][ch]


def _pack_footer(blob: bytearray, cfg: dict) -> None:
    input_mask = 0
    for i in range(4):
        if cfg["mutes"][i]:
            input_mask |= 1 << i
    _pack_u16(blob, _FOOTER_INPUT_MUTE, input_mask)

    output_mask = 0
    for i in range(4):
        if cfg["mutes"][i + 4]:
            output_mask |= 1 << i
    _pack_u16(blob, _FOOTER_OUTPUT_MUTE, output_mask)

    # PEQ band bypass: 4 bytes, one per output channel
    for i in range(4):
        byte_val = 0
        bands = cfg["peqs"][i]["bands"]
        for b in range(7):
            if b < len(bands) and bands[b]["bypass"]:
                byte_val |= 1 << b
        blob[_FOOTER_PEQ_BAND_BYPASS + i] = byte_val

    # PEQ channel bypass: byte 428 for output channel 0 only (429-byte blob)
    for i in range(4):
        offset = _FOOTER_PEQ_CHAN_BYPASS + i
        if offset < _BLOB_SIZE:
            blob[offset] = 0x01 if cfg["peqs"][i]["channel_bypass"] else 0x00
