"""QApplication setup: dark Fusion palette, instantiates MainWindow."""

from __future__ import annotations

import logging
import signal
import sys

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from pathlib import Path

from .unt_loader import load_unt_all_slots
from .views.main_window import MainWindow

BLANK_UNT = Path(__file__).parent / "resources" / "blank.unt"
STYLESHEET = Path(__file__).parent / "resources" / "style.qss"


def _apply_stylesheet(app: QApplication) -> None:
    if STYLESHEET.exists():
        app.setStyleSheet(STYLESHEET.read_text(encoding="utf-8"))


def _seed_from_blank(dsp) -> None:
    """Load the bundled blank.unt into a VirtualDSP instance."""
    if not BLANK_UNT.exists():
        return
    slots, active_slot, names, raw = load_unt_all_slots(BLANK_UNT)
    dsp.load_from_unt_bytes(raw, slots, active_slot, names)


def _apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(45, 45, 48))
    p.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.Base, QColor(30, 30, 32))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(40, 40, 44))
    p.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.Button, QColor(55, 55, 58))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.BrightText, QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.Highlight, QColor(70, 130, 200))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(p)


def run(*, offline: bool = False, verbose: int = 0) -> None:
    level = (logging.DEBUG if verbose >= 2
             else logging.INFO if verbose >= 1
             else logging.WARNING)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Let Ctrl+C work from the terminal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    _apply_dark_theme(app)
    _apply_stylesheet(app)

    if offline:
        from .virtual_dsp import VirtualDSP
        dsp_instance = VirtualDSP()
        _seed_from_blank(dsp_instance)
    else:
        dsp_instance = None

    window = MainWindow(dsp_instance=dsp_instance, offline=offline)
    window.show()
    sys.exit(app.exec())
