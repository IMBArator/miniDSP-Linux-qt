"""Console entry point: `minidspqt` — launches the Qt GUI."""

from __future__ import annotations

import argparse

from .app import run


def main() -> None:
    parser = argparse.ArgumentParser(prog="minidspqt")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run against an in-RAM virtual DSP (no hardware required)",
    )
    args = parser.parse_args()
    run(offline=args.offline)


if __name__ == "__main__":
    main()
