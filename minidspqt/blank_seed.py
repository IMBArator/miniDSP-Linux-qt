"""Shared helper for seeding a :class:`VirtualDSP` with an empty .unt file.

Both the application entry point (``app.run`` in offline-on-launch mode) and
``MainWindow`` (on a cold runtime switch to offline before any live config has
arrived) need an identical "fresh VirtualDSP with sane defaults" recipe.

Keeping it here avoids a circular import between ``app.py`` (which imports
``MainWindow``) and ``views/main_window.py``.
"""

from __future__ import annotations

from minidsp.unt import UntFile

from .virtual_dsp import VirtualDSP


def seed_virtual_dsp_from_blank(dsp: VirtualDSP) -> None:
    """Load the protocol library's empty .unt file into ``dsp``.

    ``UntFile.blank()`` is a file with all 30 user slots unused and U01
    active, so the working configuration stays at the factory defaults
    (ADR-0014). Its header becomes the byte base for a later save.

    Args:
        dsp: VirtualDSP instance to seed in place. After this call its 30
            user slots are empty, its preset names are blank and U01 is
            the active slot.
    """
    dsp.load_from_unt(UntFile.blank())
