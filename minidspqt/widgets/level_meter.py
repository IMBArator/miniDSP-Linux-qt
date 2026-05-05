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

from ..scale import s, sf

EMA_ALPHA = 0.55           # Exponential moving average smoothing for the raw level
                           #   1.0 = no smoothing, 0.0 = frozen
LED_PEAK_DECAY = 0.93      # LED peak indicator: multiplicative decay per 150 ms frame
                           #   half-life ≈ 150 ms × log(0.5)/log(0.93) ≈ 1.5 s
LED_PEAK_HOLD = 7          # LED peak indicator: frames to hold before decaying
                           #   at 150 ms polling → ≈ 1.05 s hold
DB_DISPLAY_HOLD = 7        # Numeric dB readout: frames to hold the peak before decaying
                           #   at 150 ms polling → ≈ 1.05 s hold
DB_DISPLAY_DECAY = 0.93    # Numeric dB readout: multiplicative decay per frame after hold
                           #   same factor as LED peak → same visual decay rate

NUM_SEGMENTS = 20
GREEN_SEGMENTS = 15
YELLOW_SEGMENTS = 4
RED_SEGMENTS = 1

DB_FLOOR = -60.0
DB_CEIL = 15.0

_BASE_SEGMENT_GAP = 2
_BASE_CORNER_RADIUS = 2
_BASE_MIN_WIDTH = 80
_BASE_MIN_HEIGHT = 14


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
    """Return the bright color for a lit segment at the given index.

    Green segments brighten from dark-green (G=140) to bright-green (G=200).
    Yellow segments are gold/amber. The red segment is pure red.
    """
    if index < GREEN_SEGMENTS:
        g = 140 + int(60 * (index / max(1, GREEN_SEGMENTS - 1)))
        return QColor(0, g, 0)
    elif index < GREEN_SEGMENTS + YELLOW_SEGMENTS:
        return QColor(210, 200, 0)
    else:
        return QColor(255, 0, 0)


def _dim(color: QColor) -> QColor:
    """Return a 1/5-brightness version of *color*, used for unlit segments."""
    return QColor(color.red() // 5, color.green() // 5, color.blue() // 5)


class LevelMeter(QProgressBar):
    """Horizontal LED-segment audio level meter with peak-hold.

    Visual elements:
      - 20 discrete LED segments (green → yellow → red) driven by the
        EMA-smoothed signal level.
      - A white semi-transparent peak-hold marker that tracks the highest
        level and decays slowly.
      - A numeric dB readout (via :pyattr:`display_db`) with its own
        hold-then-decay behaviour for stable readability.

    The widget is driven entirely by :meth:`set_level`, called from the
    device poll loop (~150 ms interval).  There are no internal timers.
    """

    def __init__(self, parent=None) -> None:
        """Set up the progress bar, apply styling and initialise state."""
        super().__init__(parent)
        self._peak = 0.0
        self._peak_hold = 0
        self._smoothed = 0.0
        self._db_peak = float("-inf")
        self._db_hold = 0
        self.setOrientation(Qt.Orientation.Horizontal)
        self.setRange(0, NUM_SEGMENTS)
        self.setValue(0)
        self.setTextVisible(False)
        self.apply_scale()

    def set_level(self, value: int) -> None:
        """Feed a raw uint16 level sample from the DSP.

        Updates the EMA-smoothed level, the LED peak-hold marker, and the
        numeric dB display peak.  Triggers a repaint when the peak position
        changes even if the bar value stays the same.
        """
        clamped = max(0.0, float(value))
        self._smoothed = EMA_ALPHA * clamped + (1 - EMA_ALPHA) * self._smoothed
        if self._smoothed >= self._peak:
            self._peak = self._smoothed
            self._peak_hold = LED_PEAK_HOLD
        elif self._peak_hold > 0:
            self._peak_hold -= 1
        else:
            self._peak *= LED_PEAK_DECAY
        seg = _db_to_segments(level_uint16_to_dbu(self._smoothed))
        seg = max(0, min(NUM_SEGMENTS, seg))
        peak_seg = _db_to_segments(level_uint16_to_dbu(self._peak))
        if seg == self.value() and peak_seg != getattr(self, "_last_peak_seg", -1):
            self.update()
        self._last_peak_seg = peak_seg
        self.setValue(seg)

        db = level_uint16_to_dbu(self._smoothed)
        if db <= DB_FLOOR:
            if self._db_hold > 0:
                self._db_hold -= 1
            else:
                self._db_peak -= DB_DISPLAY_DECAY
                if self._db_peak <= DB_FLOOR:
                    self._db_peak = float("-inf")
        elif db >= self._db_peak:
            self._db_peak = db
            self._db_hold = DB_DISPLAY_HOLD
        elif self._db_hold > 0:
            self._db_hold -= 1
        else:
            self._db_peak -= DB_DISPLAY_DECAY
            if self._db_peak < db:
                self._db_peak = db

    @property
    def current_db(self) -> float:
        """Instantaneous smoothed level in dBu (no hold)."""
        return level_uint16_to_dbu(self._smoothed)

    @property
    def display_db(self) -> float:
        """Peak-held dB value for the numeric readout.

        Holds the peak for ``DB_DISPLAY_HOLD`` frames, then decays at
        ``DB_DISPLAY_DECAY`` per frame.  Returns ``-inf`` when idle.
        """
        return self._db_peak

    def reset(self) -> None:
        """Zero all state (smoothed level, peaks, hold counters)."""
        self._smoothed = 0.0
        self._peak = 0.0
        self._peak_hold = 0
        self._db_peak = float("-inf")
        self._db_hold = 0
        self.setValue(0)

    def apply_scale(self) -> None:
        """Re-apply fixed sizes and stylesheet using the current scale factor."""
        self.setMinimumWidth(s(_BASE_MIN_WIDTH))
        self.setMinimumHeight(s(_BASE_MIN_HEIGHT))
        br = s(1)
        cr = s(3)
        self.setStyleSheet(
            "QProgressBar { background: #1c1c1e;"
            f" border: {br}px solid #333336; border-radius: {cr}px; }}"
            "QProgressBar::chunk { background: transparent; }"
        )
        self.update()

    def paintEvent(self, event) -> None:
        """Custom paint: draw dim/lit LED segments and the peak-hold marker."""
        p = QPainter()
        if not p.begin(self):
            return
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()

            seg_gap = sf(_BASE_SEGMENT_GAP)
            cr = sf(_BASE_CORNER_RADIUS)
            total_gap = seg_gap * (NUM_SEGMENTS - 1)
            seg_w = (w - total_gap) / NUM_SEGMENTS
            y_off = sf(1)
            seg_h = h - sf(2)

            lit = self.value()

            peak_seg = _db_to_segments(level_uint16_to_dbu(self._peak))
            peak_seg = max(0, min(NUM_SEGMENTS - 1, peak_seg))

            for i in range(NUM_SEGMENTS):
                x = i * (seg_w + seg_gap)
                color = _segment_color(i) if i < lit else _dim(_segment_color(i))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(color)
                p.drawRoundedRect(
                    int(x), int(y_off),
                    max(1, int(seg_w)), int(seg_h),
                    cr, cr,
                )

            if 0 < peak_seg < NUM_SEGMENTS and peak_seg >= lit:
                x = peak_seg * (seg_w + seg_gap)
                p.setBrush(QColor(255, 255, 255, 160))
                p.drawRoundedRect(
                    int(x), int(y_off),
                    max(1, int(seg_w)), int(seg_h),
                    cr, cr,
                )
        finally:
            p.end()
