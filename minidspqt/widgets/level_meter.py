"""Horizontal LED-style audio level meter built on QProgressBar.

Draws discrete segments (LEDs) from left to right: green → yellow → red.
The dB scale is calibrated against the `level_uint16_to_dbu()` conversion
from the protocol library, so 0 dBu lands at ~75% of the bar width.
A peak-hold indicator is drawn as a bright segment marker.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QProgressBar

from minidsp.protocol import level_uint16_to_dbu

PEAK_DECAY = 0.93
EMA_ALPHA = 0.55
DB_RANGE = 63.0

NUM_SEGMENTS = 20
GREEN_SEGMENTS = 12
YELLOW_SEGMENTS = 4
RED_SEGMENTS = NUM_SEGMENTS - GREEN_SEGMENTS - YELLOW_SEGMENTS
SEGMENT_GAP = 2
CORNER_RADIUS = 2


def _to_db_fraction(value: float) -> float:
    db = level_uint16_to_dbu(value)
    if db == float("-inf"):
        return 0.0
    return max(0.0, min(1.0, (db + DB_RANGE) / DB_RANGE))


def _segment_color(index: int) -> QColor:
    if index < GREEN_SEGMENTS:
        g = 140 + int(60 * (index / max(1, GREEN_SEGMENTS - 1)))
        return QColor(0, g, 0)
    elif index < GREEN_SEGMENTS + YELLOW_SEGMENTS:
        return QColor(210, 200, 0)
    else:
        r = 180 + int(
            40 * ((index - GREEN_SEGMENTS - YELLOW_SEGMENTS) / max(1, RED_SEGMENTS - 1))
        )
        return QColor(min(255, r), 0, 0)


def _dim(color: QColor) -> QColor:
    return QColor(color.red() // 5, color.green() // 5, color.blue() // 5)


class LevelMeter(QProgressBar):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._peak = 0.0
        self._smoothed = 0.0
        self.setOrientation(Qt.Orientation.Horizontal)
        self.setRange(0, NUM_SEGMENTS)
        self.setValue(0)
        self.setTextVisible(False)
        self.setMinimumWidth(80)
        self.setMinimumHeight(14)
        self.setStyleSheet(
            "QProgressBar { background: #1c1c1e; border: 1px solid #333336;"
            " border-radius: 3px; }"
            "QProgressBar::chunk { background: transparent; }"
        )

    def set_level(self, value: int) -> None:
        clamped = max(0.0, float(value))
        self._smoothed = EMA_ALPHA * clamped + (1 - EMA_ALPHA) * self._smoothed
        if self._smoothed >= self._peak:
            self._peak = self._smoothed
        else:
            self._peak *= PEAK_DECAY
        seg = int(_to_db_fraction(self._smoothed) * NUM_SEGMENTS)
        self.setValue(max(0, min(NUM_SEGMENTS, seg)))

    def reset(self) -> None:
        self._smoothed = 0.0
        self._peak = 0.0
        self.setValue(0)

    def paintEvent(self, event) -> None:
        p = QPainter()
        if not p.begin(self):
            return
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()

            total_gap = SEGMENT_GAP * (NUM_SEGMENTS - 1)
            seg_w = (w - total_gap) / NUM_SEGMENTS
            seg_h = h - 2

            lit = self.value()

            peak_seg = int(_to_db_fraction(self._peak) * NUM_SEGMENTS)
            peak_seg = max(0, min(NUM_SEGMENTS - 1, peak_seg))

            for i in range(NUM_SEGMENTS):
                x = i * (seg_w + SEGMENT_GAP)
                color = _segment_color(i) if i < lit else _dim(_segment_color(i))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(color)
                p.drawRoundedRect(
                    int(x),
                    1,
                    max(1, int(seg_w)),
                    int(seg_h),
                    CORNER_RADIUS,
                    CORNER_RADIUS,
                )

            if 0 <= peak_seg < NUM_SEGMENTS and peak_seg >= lit:
                x = peak_seg * (seg_w + SEGMENT_GAP)
                p.setBrush(QColor(255, 255, 255, 160))
                p.drawRoundedRect(
                    int(x),
                    1,
                    max(1, int(seg_w)),
                    int(seg_h),
                    CORNER_RADIUS,
                    CORNER_RADIUS,
                )
        finally:
            p.end()
