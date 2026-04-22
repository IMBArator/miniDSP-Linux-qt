"""Horizontal LED-style audio level meter built on QProgressBar.

Draws discrete segments (LEDs) from left to right: green → yellow → red.
The dB scale is calibrated against the `level_uint16_to_dbu()` conversion
from the protocol library.

Segment layout (20 LEDs):
  - 15 green : -60 dB  →  0 dB
  -  4 yellow:   0 dB  → +15 dB   (3.75 dB per segment)
  -  1 red   : +15 dB              (clip indicator)

A peak-hold indicator is drawn as a bright segment marker.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QProgressBar

from minidsp.protocol import level_uint16_to_dbu

PEAK_DECAY = 0.93
EMA_ALPHA = 0.55

NUM_SEGMENTS = 20
GREEN_SEGMENTS = 15
YELLOW_SEGMENTS = 4
RED_SEGMENTS = 1

DB_FLOOR = -60.0
DB_CEIL = 15.0

SEGMENT_GAP = 2
CORNER_RADIUS = 2


def _db_to_segments(db: float) -> int:
    """Map a dB value to the number of lit segments (0..NUM_SEGMENTS)."""
    if db == float("-inf") or db <= DB_FLOOR:
        return 0
    if db < 0.0:
        frac = (db - DB_FLOOR) / -DB_FLOOR
        return min(GREEN_SEGMENTS - 1, int(frac * GREEN_SEGMENTS))
    if db < DB_CEIL:
        frac = db / DB_CEIL
        return GREEN_SEGMENTS + int(frac * YELLOW_SEGMENTS)
    return NUM_SEGMENTS


def _segment_color(index: int) -> QColor:
    if index < GREEN_SEGMENTS:
        g = 140 + int(60 * (index / max(1, GREEN_SEGMENTS - 1)))
        return QColor(0, g, 0)
    elif index < GREEN_SEGMENTS + YELLOW_SEGMENTS:
        return QColor(210, 200, 0)
    else:
        return QColor(255, 0, 0)


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
        seg = _db_to_segments(level_uint16_to_dbu(self._smoothed))
        self.setValue(max(0, min(NUM_SEGMENTS, seg)))

    @property
    def current_db(self) -> float:
        return level_uint16_to_dbu(self._smoothed)

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

            peak_seg = _db_to_segments(level_uint16_to_dbu(self._peak))
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
