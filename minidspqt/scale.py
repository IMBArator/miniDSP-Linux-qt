"""Centralised UI scale factor for runtime zoom (Ctrl+Plus / Ctrl+Minus).

All pixel values in custom widgets and layouts should go through ``s()``
so that changing the factor resizes everything uniformly.  Each widget that
has hardcoded pixel sizes implements ``apply_scale()`` which is called by
the main window when the factor changes.

Persistence uses QSettings (``miniDSP/miniDSP-Qt``, key ``ui/scale_factor``).
"""

from __future__ import annotations

__all__ = ["s", "factor", "set_factor", "zoom_in", "zoom_out", "zoom_reset",
           "load_settings", "save_settings", "apply_scale_recursive"]

_FACTOR: float = 1.0
_MIN: float = 0.5
_MAX: float = 2.0
_STEP: float = 0.1

_SETTINGS_ORG = "miniDSP"
_SETTINGS_APP = "miniDSP-Qt"
_SETTINGS_KEY = "ui/scale_factor"


def s(px: float) -> int:
    """Scale a base pixel value by the current factor, clamped to >= 1."""
    return max(1, round(px * _FACTOR))


def sf(px: float) -> float:
    """Like ``s()`` but returns a float (useful for paint metrics)."""
    return max(0.5, px * _FACTOR)


def factor() -> float:
    return _FACTOR


def set_factor(f: float) -> float:
    """Set the scale factor (clamped to 0.5–2.0, rounded to 0.1).

    Returns the actual factor applied (may differ from *f* after clamping).
    """
    global _FACTOR
    f = round(max(_MIN, min(_MAX, f)), 1)
    if f == _FACTOR:
        return f
    _FACTOR = f
    save_settings()
    return f


def zoom_in() -> float:
    return set_factor(_FACTOR + _STEP)


def zoom_out() -> float:
    return set_factor(_FACTOR - _STEP)


def zoom_reset() -> float:
    return set_factor(1.0)


def load_settings() -> None:
    """Load the persisted scale factor from QSettings.

    Call once at startup, after QApplication is created.
    """
    global _FACTOR
    try:
        from PySide6.QtCore import QSettings
        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        val = settings.value(_SETTINGS_KEY, 1.0, type=float)
        _FACTOR = round(max(_MIN, min(_MAX, val)), 1)
    except Exception:
        _FACTOR = 1.0


def save_settings() -> None:
    try:
        from PySide6.QtCore import QSettings
        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        settings.setValue(_SETTINGS_KEY, _FACTOR)
    except Exception:
        pass


def apply_scale_recursive(widget) -> None:
    """Walk *widget*'s children; call ``apply_scale()`` where present.

    Does **not** call ``apply_scale()`` on *widget* itself — the caller
    is responsible for handling its own sizes.
    """
    for child in widget.findChildren(object):
        if hasattr(child, "apply_scale"):
            child.apply_scale()
