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
    """In-RAM DSP that implements the ``DSPmini`` interface.

    Used by offline mode and the test suite as a drop-in replacement
    for ``minidsp.device.DSPmini``. Every setter mutates the internal
    config dict in place; ``read_config`` returns a deep copy so the
    caller cannot accidentally clobber the live state.

    ``DeviceThread`` already serialises access (all DSP calls happen
    on its worker thread), so no extra locking is needed here.

    Lock / PIN behaviour mirrors the device wire protocol: ``set_lock_pin``
    arms the lock and ``submit_pin`` clears it; ``read_config`` and the
    level poll raise / return ``None`` while locked. Unlike the real
    device, a fresh ``VirtualDSP`` starts unlocked with no PIN.
    """

    def __init__(self) -> None:
        """Create an unlocked virtual DSP seeded with the factory config.

        All 30 user slots start empty (``None``); use
        ``load_from_unt_bytes`` to seed them from a .unt file.
        """
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

        Args:
            raw: Full 13,010 raw bytes from the .unt file; retained so
                a later ``export_to_unt_args`` can round-trip unknown
                fields byte-identically.
            slots: 30 parsed slot dicts (0-indexed); ``None`` for
                empty slots.
            active_slot_0based: 0-indexed active slot (0 = U01 …
                29 = U30). Internally we store it in device numbering
                (1 = U01 … 30 = U30).
            preset_names: 30 ASCII preset names; empty string for
                unused slots.
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
        """Return the inputs needed for ``unt_writer.save_unt``.

        Returns:
            A 3-tuple ``(slots_0based, active_slot_0based, source_bytes)``:

            * ``slots_0based`` — 30 slot dicts in user-slot order, with
              ``None`` for empty slots.
            * ``active_slot_0based`` — 0-indexed active slot.
            * ``source_bytes`` — the original 13,010-byte file content
              if this instance was seeded via ``load_from_unt_bytes``,
              else ``None`` (caller falls back to the bundled template).
        """
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
        """Mark the virtual session as open (no I/O happens)."""
        self._open = True

    def close(self) -> None:
        """Mark the virtual session as closed.

        After ``close``, ``poll_levels`` returns ``None`` to mimic the
        real device's behaviour over a dropped USB session.
        """
        self._open = False

    # --- Lock / unlock ---

    def submit_pin(self, pin: str) -> bool:
        """Try to unlock the device with ``pin``.

        Args:
            pin: 4-character ASCII PIN as set by ``set_lock_pin``.

        Returns:
            True on a match (the lock clears), False on a mismatch.
        """
        if pin == self._pin:
            self._locked = False
            return True
        return False

    def set_lock_pin(self, pin: str) -> bool:
        """Install ``pin`` as the device PIN and arm the lock.

        Mirrors the wire protocol: the device ACKs and stays nominally
        connected — the *client* is what closes the USB session after
        the ACK. ``_open`` is therefore left alone here; the worker
        thread calls ``close()`` after the ACK.

        Args:
            pin: 4-character ASCII PIN to store.

        Returns:
            Always True (the real device always ACKs this command).
        """
        self._pin = pin
        self._locked = True
        return True

    # --- Config readback ---

    def read_config(self) -> dict:
        """Return a deep copy of the active preset config.

        Returns:
            The full config dict (same shape ``parse_preset_params``
            produces), augmented with ``active_slot`` and
            ``preset_names`` so ``DeviceState.from_config`` can consume
            it directly.

        Raises:
            DeviceLockedError: If the device is currently locked.
                Callers must ``submit_pin`` first.
        """
        if self._locked:
            raise DeviceLockedError(
                "Device is locked. Call submit_pin(pin) before read_config()."
            )
        return self._full_config()

    def poll_levels(self) -> dict | None:
        """Return a flat zero-level reading (offline mode has no signal).

        Returns:
            A dict shaped like the real ``parse_levels`` output, with
            all inputs and outputs at 0 and no limiter active. ``None``
            when the session is closed or the device is locked.
        """
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
        """Set the per-channel gain.

        Args:
            channel: 0–7 (inputs first, then outputs).
            raw_value: Raw protocol gain (120 = 0 dB).
        """
        self._config["gains"][channel] = raw_value
        return True

    def mute(self, channel: int, mute: bool) -> bool:
        """Set the per-channel mute flag for ``channel`` (0–7)."""
        self._config["mutes"][channel] = mute
        return True

    def set_phase(self, channel: int, inverted: bool) -> bool:
        """Set the per-channel phase-invert flag for ``channel`` (0–7)."""
        self._config["phases"][channel] = inverted
        return True

    def set_gate(
        self, channel: int, attack: int, release: int, hold: int, threshold: int
    ) -> bool:
        """Replace the noise-gate parameters on an input channel.

        Args:
            channel: 0–3 (inputs only).
            attack: Raw protocol attack value.
            release: Raw protocol release value.
            hold: Raw protocol hold value.
            threshold: Raw protocol threshold value.
        """
        self._config["gates"][channel] = {
            "attack": attack,
            "release": release,
            "hold": hold,
            "threshold": threshold,
        }
        return True

    def set_hipass(self, channel: int, freq_raw: int, slope: int) -> bool:
        """Set the hi-pass freq/slope on an output (channel 4–7).

        ``slope`` of 0 means the hi-pass is bypassed.
        """
        out_idx = channel - 4
        self._config["crossovers"][out_idx]["hipass_freq"] = freq_raw
        self._config["crossovers"][out_idx]["hipass_slope"] = slope
        return True

    def set_lopass(self, channel: int, freq_raw: int, slope: int) -> bool:
        """Set the lo-pass freq/slope on an output (channel 4–7).

        ``slope`` of 0 means the lo-pass is bypassed.
        """
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
        """Replace all five compressor parameters on an output (4–7).

        Args:
            channel: 4–7 (outputs only).
            ratio: Raw ratio index; 0 = 1:1.0 (no compression).
            knee: Raw knee value.
            attack: Raw attack value.
            release: Raw release value.
            threshold: Raw threshold value.
        """
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
        """Set the output delay in samples for an output (channel 4–7)."""
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
        """Overwrite a single PEQ band on an output channel.

        Args:
            channel: 4–7 (outputs only).
            band: Band index 0–6.
            gain_raw: Raw gain (120 = 0 dB).
            freq_raw: Raw frequency value.
            q_raw: Raw Q value.
            filter_type: Filter-type index (peak / shelf / pass /
                allpass).
            bypass: Per-band bypass flag.
        """
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
        """Set the channel-wide PEQ bypass flag for an output (4–7)."""
        self._config["peqs"][channel - 4]["channel_bypass"] = bypass
        return True

    def set_matrix_route(self, output_ch: int, input_mask: int) -> bool:
        """Set the input-mask bitfield for one output (4–7).

        Args:
            output_ch: Output channel index 4–7.
            input_mask: 4-bit mask; bit ``i`` set means input ``i`` is
                routed to this output.
        """
        self._config["routings"][output_ch - 4] = input_mask
        return True

    def prepare_link(self, master_ch: int, slave_ch: int) -> bool:
        """Declare a master/slave link pair (firmware op ``0x2A``).

        The device side-effect on the real hardware is to copy every
        per-channel setting from master to slave so the next config
        re-read shows them in lock-step. We mirror that copy here so
        offline behaviour matches the wire.
        """
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
        """Write the raw link-flag bitmask for ``channel`` (0–7)."""
        self._config["link_flags"][channel] = link_flags
        return True

    def set_channel_name(self, channel: int, name: str) -> bool:
        """Rename ``channel`` (0–7) to ``name`` (caller truncates to 8 chars)."""
        self._config["names"][channel] = name
        return True

    def set_test_tone(self, mode: int, freq_index: int = 0) -> bool:
        """Set the device-wide test-tone generator.

        Args:
            mode: ``TONE_OFF`` / ``TONE_PINK`` / ``TONE_WHITE`` /
                ``TONE_SINE`` raw value.
            freq_index: 0–30 ISO 1/3-octave sine frequency index. The
                device keeps the last sine index across noise/off
                transitions, so we always write it.
        """
        self._config["test_tone_mode"] = mode
        self._config["test_tone_freq"] = freq_index
        return True

    # --- Presets ---

    def load_preset(self, slot: int) -> dict | None:
        """Load a preset by device slot number.

        Args:
            slot: Device slot — 0 = F00 (factory), 1–30 = U01–U30.

        Returns:
            The full config dict after loading, or ``None`` if a user
            slot is empty or ``slot`` is out of range. F00 always
            succeeds — it resets to factory defaults.
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
        """Store the current config to a user preset slot.

        Args:
            slot: Device slot 1–30 (U01–U30). F00 (0) cannot be
                overwritten.
            name: Preset name; the device firmware accepts up to 14
                ASCII bytes, the caller is responsible for truncation.

        Returns:
            True on success, False if ``slot`` is out of range.
        """
        if slot < 1 or slot > 30:
            return False
        idx = slot - 1
        self._slots[idx] = self._slot_config()
        if idx < len(self._preset_names):
            self._preset_names[idx] = name
        return True
