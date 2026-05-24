"""Console entry point: `minidspqt` — launches the Qt GUI."""

from __future__ import annotations

import argparse

from .app import run


def main() -> None:
    """Parse CLI flags and launch the Qt application.

    Flags:
        ``-v`` / ``--verbose``: counted; ``-v`` enables INFO logging,
        ``-vv`` enables DEBUG (including USB frame traces).
        ``--offline``: bypass hardware and run against the in-RAM
        ``VirtualDSP``.

    The function calls into ``app.run``, which itself enters the Qt
    event loop and ultimately calls ``sys.exit``; this entry point
    therefore does not return under normal use.
    """
    parser = argparse.ArgumentParser(prog="minidspqt")
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v: info, -vv: debug)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run against an in-RAM virtual DSP (no hardware required)",
    )
    args = parser.parse_args()
    run(offline=args.offline, verbose=args.verbose)


if __name__ == "__main__":
    main()
