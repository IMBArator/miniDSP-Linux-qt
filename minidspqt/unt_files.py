"""GUI-side helpers for saving .unt files: stored versus live presets.

A .unt file written by the manufacturer's editor, and by
``DSPmini.export_unt``, holds the presets as *stored* on the device. Edits
that were made but not stored to a slot are not in it. The save flow uses
these helpers to notice that case and, if the user asks for it, to patch the
live settings into the active slot.

Pure functions, no Qt, so they can be tested directly.
"""

from __future__ import annotations

import copy

from minidsp.unt import UNT_SLOT_COUNT, UntFile

from .virtual_dsp import _SLOT_KEYS

#: Preset keys compared and patched. The test-tone keys are left out: the
#: generator is transient state the user switches on and off while testing,
#: not part of what they mean by "changed the preset".
PRESET_KEYS = _SLOT_KEYS - {"test_tone_mode", "test_tone_freq"}


def differs_from_stored(live_cfg: dict, unt: UntFile, slot: int) -> bool:
    """Tell whether the live settings differ from the stored preset in ``slot``.

    Args:
        live_cfg: A ``read_config`` dict; keys other than the preset
            parameters (``active_slot``, ``preset_names``, …) are ignored.
        unt: The file built from the stored presets.
        slot: User slot 1–30.

    Returns:
        ``True`` if any preset parameter differs, or if the file has no
        stored preset in ``slot`` at all.
    """
    if not 1 <= slot <= UNT_SLOT_COUNT:
        return False
    stored = unt.slot_params(slot)
    if stored is None:
        return True
    return any(live_cfg.get(key) != stored.get(key) for key in PRESET_KEYS)


def include_live_changes(unt: UntFile, slot: int, live_cfg: dict) -> None:
    """Overwrite the preset in ``slot`` with the live settings, in place.

    Only the modelled preset parameters are written; every other byte of
    the stored preset is kept (ADR-0016). The test-tone fields keep their
    stored values.

    Args:
        unt: The file to patch.
        slot: User slot 1–30.
        live_cfg: A ``read_config`` dict with every preset key.
    """
    params = {key: copy.deepcopy(live_cfg[key]) for key in PRESET_KEYS}
    name = None
    if not unt.is_filled(slot):
        # A slot that was never stored has no name in the file yet.
        names = live_cfg.get("preset_names") or []
        name = names[slot - 1] if slot - 1 < len(names) else ""
    unt.set_slot_params(slot, params, name=name)
