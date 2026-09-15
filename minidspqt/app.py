"""QApplication setup: theme manager + Fusion style + MainWindow."""

from __future__ import annotations

import logging
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QStandardPaths
from PySide6.QtWidgets import QApplication

from .blank_seed import seed_virtual_dsp_from_blank
from .theme import theme_manager
from .views.main_window import MainWindow

_LOG_FORMAT = "%(asctime)s %(levelname)-5s %(name)s: %(message)s"
_LOG_DATEFMT = "%H:%M:%S"

#: File name of the log written when the process has no console.
LOG_FILE_NAME = "minidspqt.log"


def _log_uncaught(exc_type, exc, tb) -> None:
    """``sys.excepthook`` replacement that routes crashes into the log."""
    logging.getLogger("minidspqt").critical(
        "uncaught exception", exc_info=(exc_type, exc, tb)
    )


def configure_logging(level: int, *, log_dir: Path | None = None) -> logging.Handler:
    """Attach the root logging handler and return it.

    With a console attached (``sys.stderr`` is a stream) this is the classic
    stderr handler. Without one — the packaged Windows build starts from a
    GUI-subsystem executable, where Python sets ``sys.stderr`` to ``None`` —
    a plain ``StreamHandler`` would swallow every record silently and an
    uncaught exception would end the process without a trace. In that case
    the log goes to ``minidspqt.log`` in the per-application data directory
    (``%LOCALAPPDATA%\\miniDSP\\minidspqt`` on Windows) and ``sys.excepthook``
    is pointed at the logger so crashes leave something to report.

    The decision is made on the stream, not on the operating system:
    ``minidspqt/`` carries no platform branch (ADR-0030).

    Args:
        level: Level to set on the root logger.
        log_dir: Directory for the log file in the no-console case. Defaults
            to Qt's ``AppLocalDataLocation``, which needs the organisation
            and application names set on ``QCoreApplication`` beforehand.

    Returns:
        The handler that was attached to the root logger.
    """
    root = logging.getLogger()
    if sys.stderr is None:
        if log_dir is None:
            log_dir = Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppLocalDataLocation
                )
            )
        log_dir.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(
            log_dir / LOG_FILE_NAME, mode="w", encoding="utf-8"
        )
        sys.excepthook = _log_uncaught
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, _LOG_DATEFMT))
    root.addHandler(handler)
    root.setLevel(level)
    return handler


def run(*, offline: bool = False, verbose: int = 0) -> None:
    """Configure logging, build the QApplication and run the main window.

    Args:
        offline: When True, instantiate a ``VirtualDSP``, seed it from
            the bundled ``blank.unt`` template, and pass it to the main
            window; no USB hardware is touched.
        verbose: Logging verbosity counter from the CLI; ``0`` =
            WARNING, ``1`` = INFO, ``>=2`` = DEBUG.

    Does not return: enters the Qt event loop and exits the process
    with the loop's exit code.
    """
    level = (
        logging.DEBUG
        if verbose >= 2
        else logging.INFO
        if verbose >= 1
        else logging.WARNING
    )
    # Org/app names so QSettings (used by the theme manager) writes to a
    # predictable location and is shared between sessions. Set before the
    # logging setup, which derives the no-console log directory from them.
    QCoreApplication.setOrganizationName("miniDSP")
    QCoreApplication.setApplicationName("minidspqt")

    configure_logging(level)

    # Let Ctrl+C work from the terminal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    # Fusion adapts cleanly to whatever palette we install — important for
    # both schemes; native styles on Windows/macOS often ignore palette
    # tweaks and fall back to platform defaults.
    app.setStyle("Fusion")
    theme_manager.bind_to_app(app)

    if offline:
        from .virtual_dsp import VirtualDSP

        dsp_instance = VirtualDSP()
        seed_virtual_dsp_from_blank(dsp_instance)
    else:
        dsp_instance = None

    window = MainWindow(dsp_instance=dsp_instance, offline=offline)
    window.show()
    sys.exit(app.exec())
