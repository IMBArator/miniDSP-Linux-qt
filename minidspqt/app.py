"""QApplication setup: theme manager + Fusion style + MainWindow."""

from __future__ import annotations

import logging
import signal
import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from .blank_seed import seed_virtual_dsp_from_blank
from .theme import theme_manager
from .views.main_window import MainWindow


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
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Let Ctrl+C work from the terminal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Org/app names so QSettings (used by the theme manager) writes to a
    # predictable location and is shared between sessions.
    QCoreApplication.setOrganizationName("miniDSP")
    QCoreApplication.setApplicationName("minidspqt")

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
