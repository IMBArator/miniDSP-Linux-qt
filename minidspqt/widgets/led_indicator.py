"""Small circular LED indicator widget.

Draws a filled circle that is bright when active and dim when idle,
mimicking a hardware status LED. Used for compressor/limiter activity
on output channel strips.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

LED_SIZE = 14

_COLOR_ACTIVE = QColor(255, 40, 40)
_COLOR_DIM = QColor(80, 15, 15)
_COLOR_GLOW = QColor(255, 60, 60, 90)


class LedIndicator(QWidget):
    """A single circular LED indicator.

    Call :meth:`set_active` to toggle between active (bright red) and
    idle (dim dark-red) states.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active = False
        self.setFixedSize(LED_SIZE, LED_SIZE)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Kept inline (not in style.qss) as paint-plumbing for the custom
        # paintEvent: WA_TranslucentBackground stops Qt from auto-filling, and
        # an explicit transparent background prevents inherited QSS rules
        # (e.g. ChannelStrip's frame fill) from painting underneath the LED.
        self.setStyleSheet("background: transparent;")
        self.setToolTip("Limiter")

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self.update()

    @property
    def is_active(self) -> bool:
        return self._active

    def paintEvent(self, event) -> None:
        p = QPainter()
        if not p.begin(self):
            return
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)

            color = _COLOR_ACTIVE if self._active else _COLOR_DIM
            p.setBrush(color)
            p.drawEllipse(1, 1, self.width() - 2, self.height() - 2)

            if self._active:
                p.setBrush(_COLOR_GLOW)
                p.drawEllipse(0, 0, self.width(), self.height())
        finally:
            p.end()
