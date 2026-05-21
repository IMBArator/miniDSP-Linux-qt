"""Stateful in-RAM virtual DSP for offline mode.

Implements the same public interface as ``minidsp.device.DSPmini`` so that
``DeviceThread`` can use it as a drop-in replacement.  Every setter mutates
the internal config dict in-place; ``read_config()`` returns a deep copy.
"""

from __future__ import annotations

import copy
from typing import Any

from minidsp.defaults import load_factory_defaults
from minidsp.device import DeviceLockedError

_SLOT_KEYS = frozenset(
    {
        "names",
        "gains",
        "mutes",
        "phases",
        "link_flags",
        "routings",
        "gates",
        "delays",
        "crossovers",
        "compressors",
        "peqs",
        "test_tone_mode",
        "test_tone_freq",
    }
)

_FACTORY_PARAMS_CACHE: dict[str, Any] | None = None


def _factory_params() -> dict[str, Any]:
    global _FACTORY_PARAMS_CACHE
    if _FACTORY_PARAMS_CACHE is None:
        _FACTORY_PARAMS_CACHE = load_factory_defaults()["params"]
    return _FACTORY_PARAMS_CACHE


def _default_config() -> dict[str, Any]:
    params = _factory_params()
    cfg = {k: copy.deepcopy(params[k]) for k in _SLOT_KEYS if k in params}
    cfg["active_slot"] = 1
    cfg["preset_names"] = [f"U{i + 1:02d}" for i in range(30)]
    return cfg


class VirtualDSP:
    """In-RAM DSP that implements the DSPmini interface.

    ``DeviceThread`` already serialises access (all DSP calls happen on its
    worker thread), so no extra locking is needed here.
    """

    def __init__(self) -> None:
        self._config: dict[str, Any] = _default_config()
        self._slots: list[dict[str, Any] | None] = [None] * 30
        self._source_bytes: bytes | None = None
        self._open: bool = True
        self._locked: bool = False
        self._pin: str | None = None

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
        self._config["preset_names"] = list(preset_names)

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

    # --- Connection ---

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    # --- Lock / unlock ---

    def submit_pin(self, pin: str) -> bool:
        if pin == self._pin:
            self._locked = False
            return True
        return False

    def set_lock_pin(self, pin: str) -> bool:
        self._pin = pin
        self._locked = True
        # The real device ACKs and stays nominally connected; the client
        # is what closes the USB session. We mirror that here — leave
        # _open alone, the worker calls close() after the ACK.
        return True

    # --- Config readback ---

    def read_config(self) -> dict:
        if self._locked:
            raise DeviceLockedError(
                "Device is locked. Call submit_pin(pin) before read_config()."
            )
        return self._full_config()

    def poll_levels(self) -> dict | None:
        if not self._open or self._locked:
            return None
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
        self,
        channel: int,
        ratio: int,
        knee: int,
        attack: int,
        release: int,
        threshold: int,
    ) -> bool:
        out_idx = channel - 4
        self._config["compressors"][out_idx] = {
            "ratio": ratio,
            "knee": knee,
            "attack": attack,
            "release": release,
            "threshold": threshold,
        }
        return True

    def set_delay(self, channel: int, samples: int) -> bool:
        self._config["delays"][channel - 4] = samples
        return True

    def set_peq_band(
        self,
        channel: int,
        band: int,
        gain_raw: int,
        freq_raw: int,
        q_raw: int,
        filter_type: int,
        bypass: bool = False,
    ) -> bool:
        out_idx = channel - 4
        self._config["peqs"][out_idx]["bands"][band] = {
            "gain": gain_raw,
            "freq": freq_raw,
            "q": q_raw,
            "type": filter_type,
            "bypass": bypass,
        }
        return True

    def set_peq_channel_bypass(self, channel: int, bypass: bool) -> bool:
        self._config["peqs"][channel - 4]["channel_bypass"] = bypass
        return True

    def set_matrix_route(self, output_ch: int, input_mask: int) -> bool:
        self._config["routings"][output_ch - 4] = input_mask
        return True

    def prepare_link(self, master_ch: int, slave_ch: int) -> bool:
        # 0x2A is the firmware's "declare master/slave pair" handshake; the
        # device side-effect is copying every per-channel setting from master
        # to slave so the next config re-read shows them in lock-step.
        # Mirror that copy here so offline behaviour matches the wire.
        self._copy_channel_params(master_ch, slave_ch)
        return True

    def _copy_channel_params(self, src_ch: int, dst_ch: int) -> None:
        """Replicate the firmware's master→slave parameter copy.

        Deep-copies every per-channel setting from ``src_ch`` to ``dst_ch``
        in ``self._config``. Excludes ``names`` (user identifiers), the
        ``routings`` matrix (firmware keeps it per-channel — each linked
        output still needs its own input source), the ``link_flags``
        themselves (set separately by set_channel_link), and the global
        ``test_tone_*`` keys.
        """
        if src_ch == dst_ch:
            return
        if (src_ch < 4) != (dst_ch < 4):
            return  # input↔output mixing is a caller bug — refuse silently

        cfg = self._config
        for key in ("gains", "mutes", "phases"):
            cfg[key][dst_ch] = cfg[key][src_ch]

        if src_ch < 4:
            cfg["gates"][dst_ch] = copy.deepcopy(cfg["gates"][src_ch])
        else:
            src_idx = src_ch - 4
            dst_idx = dst_ch - 4
            cfg["delays"][dst_idx] = cfg["delays"][src_idx]
            cfg["crossovers"][dst_idx] = copy.deepcopy(cfg["crossovers"][src_idx])
            cfg["compressors"][dst_idx] = copy.deepcopy(cfg["compressors"][src_idx])
            cfg["peqs"][dst_idx] = copy.deepcopy(cfg["peqs"][src_idx])

    def set_channel_link(self, channel: int, link_flags: int) -> bool:
        self._config["link_flags"][channel] = link_flags
        return True

    def set_channel_name(self, channel: int, name: str) -> bool:
        self._config["names"][channel] = name
        return True

    def set_test_tone(self, mode: int, freq_index: int = 0) -> bool:
        self._config["test_tone_mode"] = mode
        # The device keeps the last sine freq index even across noise/off
        # transitions; mirror that here so the dialog's "sticky freq"
        # behaviour works in offline mode too.
        self._config["test_tone_freq"] = freq_index
        return True

    # --- Presets ---

    def load_preset(self, slot: int) -> dict | None:
        """Load a preset by device slot number (0=F00, 1=U01, …, 30=U30).

        Returns the full config dict, or *None* if the user slot is empty.
        F00 always succeeds — it resets to factory defaults.
        """
        current_names = list(self._config["preset_names"])
        if slot == 0:
            self._config = _default_config()
            self._config["active_slot"] = 0
            self._config["preset_names"] = current_names
            return self._full_config()
        if slot < 1 or slot > 30:
            return None
        idx = slot - 1
        cfg = self._slots[idx]
        if cfg is None:
            return None
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
        if idx < len(self._preset_names):
            self._preset_names[idx] = name
        return True
