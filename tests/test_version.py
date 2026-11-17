"""Tests that the package's ``__version__`` matches pyproject.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path

import minidspqt

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


# --- Version ---

def test_version_matches_pyproject():
    """scripts/version.sh bumps pyproject.toml and __version__ together."""
    with PYPROJECT.open("rb") as f:
        version = tomllib.load(f)["project"]["version"]
    assert minidspqt.__version__ == version
