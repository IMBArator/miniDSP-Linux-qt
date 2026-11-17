"""Qt GUI for the t.racks DSP 4x4 Mini."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("minidsp-linux-qt")
except PackageNotFoundError:  # running from a source tree without metadata
    __version__ = "1.0.0"
