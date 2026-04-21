"""Stateful in-RAM virtual DSP for offline mode.

Implements the same public interface as ``minidsp.device.DSPmini`` so that
``DeviceThread`` can use it as a drop-in replacement.  Every setter mutates
the internal config dict in-place; ``read_config()`` returns a deep copy.
"""

from __future__ import annotations

import copy
from typing import Any

_SLOT_KEYS = frozenset({
    "names", "gains", "mutes", "phases", "link_flags",
    "routings", "gates", "delays", "crossovers", "compressors", "peqs",
})


def _default_config() -> dict[str, Any]:
    return {
        "names": ["InA", "InB", "InC", "InD", "Out1", "Out2", "Out3", "Out4"],
        "gains": [280, 280, 280, 280, 280, 280, 280, 280],
        "mutes": [False] * 8,
        "phases": [False] * 8,
        "link_flags": [0x01, 0x02, 0x04, 0x08, 0x01, 0x02, 0x04, 0x08],
        "routings": [0x01, 0x02, 0x04, 0x08],
        "gates": [
            {"attack": 50, "release": 100, "hold": 200, "threshold": 20}
            for _ in range(4)
        ],
        "delays": [0, 0, 0, 0],
        "crossovers": [
            {"hipass_freq": 0, "hipass_slope": 0, "lopass_freq": 0, "lopass_slope": 0}
            for _ in range(4)
        ],
        "compressors": [
            {"ratio": 0, "knee": 0, "attack": 0, "release": 0, "threshold": 0}
            for _ in range(4)
        ],
        "peqs": [
            {
                "bands": [
                    {"gain": 120, "freq": 150, "q": 40, "type": 0, "bypass": False}
                    for _ in range(7)
                ],
                "channel_bypass": False,
            }
            for _ in range(4)
        ],
        "active_slot": 1,
        "preset_names": [""] + [f"U{i+1:02d}" for i in range(29)],
    }


class VirtualDSP:
    """In-RAM DSP that implements the DSPmini interface.

    ``DeviceThread`` already serialises access (all DSP calls happen on its
    worker thread), so no extra locking is needed here.
    """

    def __init__(self) -> None:
        self._config: dict[str, Any] = _default_config()
        self._slots: list[dict[str, Any] | None] = [None] * 30
        self._source_bytes: bytes | None = None

    def load_from_unt_bytes(
        self,
        raw: bytes,
        slots: list[dict[str, Any] | None],
        active_slot_0based: int,
        preset_names: list[str],
    ) -> None:
        """Seed state from a parsed .unt file.

        *active_slot_0based* is 0-indexed (0 = U01).  Internally we store
        active_slot in device numbering (1 = U01, …, 30 = U30).
        """
        self._source_bytes = raw
        self._slots = list(slots)
        active = active_slot_0based + 1
        if 0 <= active_slot_0based < 30 and slots[active_slot_0based] is not None:
            self._config = copy.deepcopy(slots[active_slot_0based])
        self._config["active_slot"] = active
        self._config["preset_names"] = [""] + list(preset_names)

    def export_to_unt_args(
        self,
    ) -> tuple[list[dict[str, Any] | None], int, bytes | None]:
        """Return ``(slots_0based, active_slot_0based, source_bytes)``."""
        return list(self._slots), self._active_slot - 1, self._source_bytes

    @property
    def _active_slot(self) -> int:
        return self._config["active_slot"]

    @_active_slot.setter
    def _active_slot(self, value: int) -> None:
        self._config["active_slot"] = value

    @property
    def _preset_names(self) -> list[str]:
        return self._config["preset_names"]

    def _slot_config(self) -> dict[str, Any]:
        return {k: copy.deepcopy(v) for k, v in self._config.items() if k in _SLOT_KEYS}

    def _full_config(self) -> dict[str, Any]:
        return copy.deepcopy(self._config)

    # --- Connection (no-ops) ---

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    # --- Config readback ---

    def read_config(self) -> dict:
        return self._full_config()

    def poll_levels(self) -> dict:
        return {
            "inputs": [0, 0, 0, 0],
            "outputs": [0, 0, 0, 0],
            "limiter_mask": 0,
            "state": 0,
        }

    # --- Setters ---

    def set_gain(self, channel: int, raw_value: int) -> bool:
        self._config["gains"][channel] = raw_value
        return True

    def mute(self, channel: int, mute: bool) -> bool:
        self._config["mutes"][channel] = mute
        return True

    def set_phase(self, channel: int, inverted: bool) -> bool:
        self._config["phases"][channel] = inverted
        return True

    def set_gate(
        self, channel: int, attack: int, release: int, hold: int, threshold: int
    ) -> bool:
        self._config["gates"][channel] = {
            "attack": attack,
            "release": release,
            "hold": hold,
            "threshold": threshold,
        }
        return True

    def set_hipass(self, channel: int, freq_raw: int, slope: int) -> bool:
        out_idx = channel - 4
        self._config["crossovers"][out_idx]["hipass_freq"] = freq_raw
        self._config["crossovers"][out_idx]["hipass_slope"] = slope
        return True

    def set_lopass(self, channel: int, freq_raw: int, slope: int) -> bool:
        out_idx = channel - 4
        self._config["crossovers"][out_idx]["lopass_freq"] = freq_raw
        self._config["crossovers"][out_idx]["lopass_slope"] = slope
        return True

    def set_compressor(
        self, channel: int, ratio: int, knee: int,
        attack: int, release: int, threshold: int,
    ) -> bool:
        out_idx = channel - 4
        self._config["compressors"][out_idx] = {
            "ratio": ratio, "knee": knee, "attack": attack,
            "release": release, "threshold": threshold,
        }
        return True

    def set_delay(self, channel: int, samples: int) -> bool:
        self._config["delays"][channel - 4] = samples
        return True

    def set_peq_band(
        self, channel: int, band: int, gain_raw: int, freq_raw: int,
        q_raw: int, filter_type: int, bypass: bool = False,
    ) -> bool:
        out_idx = channel - 4
        self._config["peqs"][out_idx]["bands"][band] = {
            "gain": gain_raw, "freq": freq_raw, "q": q_raw,
            "type": filter_type, "bypass": bypass,
        }
        return True

    def set_peq_channel_bypass(self, channel: int, bypass: bool) -> bool:
        self._config["peqs"][channel - 4]["channel_bypass"] = bypass
        return True

    def set_matrix_route(self, output_ch: int, input_mask: int) -> bool:
        self._config["routings"][output_ch - 4] = input_mask
        return True

    def set_channel_link(self, channel: int, link_flags: int) -> bool:
        self._config["link_flags"][channel] = link_flags
        return True

    def set_channel_name(self, channel: int, name: str) -> bool:
        self._config["names"][channel] = name
        return True

    # --- Presets ---

    def load_preset(self, slot: int) -> dict | None:
        """Load a preset by device slot number (0=F00, 1=U01, …, 30=U30).

        Returns the full config dict, or *None* if the slot is empty/invalid.
        """
        if slot < 1 or slot > 30:
            return None
        idx = slot - 1
        cfg = self._slots[idx]
        if cfg is None:
            return None
        current_names = list(self._config["preset_names"])
        self._config = copy.deepcopy(cfg)
        self._config["active_slot"] = slot
        self._config["preset_names"] = current_names
        return self._full_config()

    def store_preset(self, slot: int, name: str) -> bool:
        """Store current config to a user preset slot (1=U01, …, 30=U30)."""
        if slot < 1 or slot > 30:
            return False
        idx = slot - 1
        self._slots[idx] = self._slot_config()
        if slot < len(self._preset_names):
            self._preset_names[slot] = name
        return True
