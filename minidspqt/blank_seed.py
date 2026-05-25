"""Shared helper for seeding a :class:`VirtualDSP` from the bundled blank.unt.

Both the application entry point (``app.run`` in offline-on-launch mode) and
``MainWindow`` (on a cold runtime switch to offline before any live config has
arrived) need an identical "fresh VirtualDSP with sane defaults" recipe.

Keeping it here avoids a circular import between ``app.py`` (which imports
``MainWindow``) and ``views/main_window.py``.
"""

from __future__ import annotations

from pathlib import Path

from .unt_loader import load_unt_all_slots
from .virtual_dsp import VirtualDSP

BLANK_UNT = Path(__file__).parent / "resources" / "blank.unt"


def seed_virtual_dsp_from_blank(dsp: VirtualDSP) -> None:
    """Load the bundled ``blank.unt`` template into ``dsp``.

    No-op if the template is missing from the install (e.g. running from a
    source tree without resources packaged) — the caller still gets a usable
    VirtualDSP, just with factory defaults instead of the curated blank.

    Args:
        dsp: VirtualDSP instance to seed in place. After this call its 30
            user slots, preset names and active-slot pointer match the
            bundled ``blank.unt`` template.
    """
    if not BLANK_UNT.exists():
        return
    slots, active_slot, names, raw = load_unt_all_slots(BLANK_UNT)
    dsp.load_from_unt_bytes(raw, slots, active_slot, names)
