"""Vertical audio level meter: EMA smoothing, peak hold, dB-scaled gradient.

Ported from the minidsp-linux proof-of-concept (minidsp/gui/level_meter.py).
The dB scale is calibrated against the `level_uint16_to_dbu()` conversion
from the protocol library, so 0 dBu lands at ~75% of the bar height.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget

from minidsp.protocol import level_uint16_to_dbu

PEAK_DECAY = 0.93   # ~7% drop per update cycle
EMA_ALPHA = 0.55    # 0=frozen, 1=no smoothing
DB_RANGE = 63.0     # meter spans −63 dB .. 0 dB


def _to_db_fraction(value: float) -> float:
    db = level_uint16_to_dbu(value)
    if db == float("-inf"):
        return 0.0
    return max(0.0, min(1.0, (db + DB_RANGE) / DB_RANGE))


class LevelMeter(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._level = 0.0
        self._peak = 0.0
        self.setMinimumWidth(16)
        self.setMinimumHeight(60)

    def set_level(self, value: int) -> None:
        clamped = max(0.0, float(value))
        self._level = EMA_ALPHA * clamped + (1 - EMA_ALPHA) * self._level
        if self._level >= self._peak:
            self._peak = self._level
        else:
            self._peak *= PEAK_DECAY
        self.update()

    def reset(self) -> None:
        self._level = 0.0
        self._peak = 0.0
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter()
        if not p.begin(self):
            return
        try:
            w, h = self.width(), self.height()
            p.fillRect(0, 0, w, h, QColor(28, 28, 30))

            frac = _to_db_fraction(self._level)
            bar_h = int(frac * h)
            if bar_h > 0:
                bar_top = h - bar_h
                grad = QLinearGradient(0, h, 0, 0)
                grad.setColorAt(0.00, QColor(0, 180, 0))
                grad.setColorAt(0.70, QColor(0, 200, 0))
                grad.setColorAt(0.75, QColor(220, 200, 0))   # 0 dBu boundary
                grad.setColorAt(0.88, QColor(220, 60, 0))
                grad.setColorAt(1.00, QColor(220, 0, 0))
                p.fillRect(1, bar_top, w - 2, bar_h, grad)

            peak_frac = _to_db_fraction(self._peak)
            if peak_frac > 0.01:
                peak_y = h - int(peak_frac * h)
                p.setPen(QColor(255, 255, 255))
                p.drawLine(1, peak_y, w - 2, peak_y)
        finally:
            p.end()
