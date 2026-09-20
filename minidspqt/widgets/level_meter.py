"""Horizontal LED-style audio level meter built on QProgressBar.

Draws discrete segments (LEDs) from left to right: green → yellow → red.
Levels are fed in the device's **24-bit** units and converted to calibrated
dBu with `level24_to_dbu()` (re-exported by `minidspqt.levels`, which also
carries the fallback for older protocol libraries).

Segment layout (20 LEDs):
  - 15 green : -50 dB  →  0 dB
  -  4 yellow:   0 dB  → the clip point (about +11 dBu)
  -  1 red   : clip indicator — lit only by the clip decision, never by
               the smoothed level

The red segment is deliberately *not* a level zone: clip is decided on the
raw, unsmoothed sample (so a single loud frame cannot be averaged away) and
latched for `CLIP_HOLD` frames so the user sees it.

A peak-hold indicator is drawn as a bright segment marker.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QProgressBar, QWidget

from ..levels import LEVEL_CLIP_LEVEL24, level24_is_clipping, level24_to_dbu
from ..theme import theme_manager

EMA_ALPHA = 0.75         # Exponential moving average smoothing for the raw level
                         #   1.0 = no smoothing, 0.0 = frozen
LED_PEAK_DECAY = 0.93    # LED peak indicator: multiplicative decay per 150 ms frame
                         #   half-life ≈ 150 ms × log(0.5)/log(0.93) ≈ 1.5 s
LED_PEAK_HOLD = 7        # LED peak indicator: frames to hold before decaying
                         #   at 150 ms polling → ≈ 1.05 s hold
DB_DISPLAY_DECAY = 0.93  # Numeric dB readout: multiplicative decay per frame after hold
                         #   same factor as LED peak → same visual decay rate
DB_DISPLAY_HOLD = 7      # Numeric dB readout: frames to hold the peak before decaying
                         #   at 150 ms polling → ≈ 1.05 s hold
CLIP_HOLD = LED_PEAK_HOLD  # Clip LED: frames the latch stays lit after a clipping
                           #   sample — same ≈ 1 s as the peak marker, so a brief
                           #   overload is still visible at a 150 ms poll rate

NUM_SEGMENTS = 20
GREEN_SEGMENTS = 15
YELLOW_SEGMENTS = 4
RED_SEGMENTS = 1

DB_FLOOR = -50.0


@lru_cache(maxsize=1)
def _db_ceil() -> float:
    """Return the top of the level scale in dBu: the clip point.

    The yellow zone ends exactly where the manufacturer's editor lights
    its Clip segment, so the bar being "full" and the red LED mean the
    same thing.

    This is computed lazily and cached rather than evaluated at import
    time: the protocol library loads its calibration file on the first
    conversion, and pulling that into module import would fix the
    reference before the environment is fully set up.

    Returns:
        The dBu value of ``LEVEL_CLIP_LEVEL24`` (about +11.3 dBu with
        the bench-verified calibration).
    """
    return level24_to_dbu(LEVEL_CLIP_LEVEL24)


SEGMENT_GAP = 2
CORNER_RADIUS = 2


def _db_to_segments(db: float) -> int:
    """Map a dB value to the number of lit segments.

    Args:
        db: dB level (``-inf`` is allowed and means "no signal").

    Returns:
        Lit-segment count in ``[0, NUM_SEGMENTS - RED_SEGMENTS]``. The
        first ``GREEN_SEGMENTS`` cover ``DB_FLOOR..0`` and the next
        ``YELLOW_SEGMENTS`` cover ``0..`` the clip point. The red
        segment is never counted here — it is driven exclusively by the
        clip latch in :meth:`LevelMeter.set_level`.
    """
    ceil = _db_ceil()
    if db == float("-inf") or db <= DB_FLOOR:
        return 0
    if db < 0.0:
        frac = (db - DB_FLOOR) / -DB_FLOOR
        return min(GREEN_SEGMENTS - 1, int(frac * GREEN_SEGMENTS))
    if db < ceil:
        frac = db / ceil
        return GREEN_SEGMENTS + min(YELLOW_SEGMENTS - 1, int(frac * YELLOW_SEGMENTS))
    return NUM_SEGMENTS - RED_SEGMENTS


def _segment_color(index: int) -> QColor:
    """Return the bright color for a lit segment at the given index.

    The green segments brighten from "low" to "high" along the ramp; the
    endpoints come from the active theme so the meter follows light/dark
    mode.  Yellow and red segments are flat theme colors.
    """
    theme = theme_manager.current
    if index < GREEN_SEGMENTS:
        # Linearly interpolate each channel between the low and high
        # green endpoints rather than only G as before — this lets the
        # light theme use a slightly different hue if needed.
        lo = theme.meter_segment_green_low
        hi = theme.meter_segment_green_high
        t = index / max(1, GREEN_SEGMENTS - 1)
        return QColor(
            int(lo.red() * (1 - t) + hi.red() * t),
            int(lo.green() * (1 - t) + hi.green() * t),
            int(lo.blue() * (1 - t) + hi.blue() * t),
        )
    elif index < GREEN_SEGMENTS + YELLOW_SEGMENTS:
        return theme.meter_segment_amber
    else:
        return theme.meter_segment_red


def _dim(color: QColor) -> QColor:
    """Blend *color* toward the active theme's unlit target.

    Dark theme blends toward black so unlit LEDs look "off"; light theme
    blends toward the meter frame fill so unlit segments stay legible
    without becoming dark blobs in an otherwise light UI.
    """
    return theme_manager.current.dim_segment(color)


class LevelMeter(QProgressBar):
    """LED-segment audio level meter with peak-hold.

    Visual elements:
        * 19 discrete LED segments (green → yellow) driven by the
          EMA-smoothed signal level.
        * A final red segment lit only while ``is_clipping`` — decided
          on the raw sample and latched for ``CLIP_HOLD`` frames.
        * A white semi-transparent peak-hold marker that tracks the
          highest level and decays slowly.
        * A numeric dB readout (via the ``display_db`` property) with
          its own hold-then-decay behaviour for stable readability.

    The widget is driven entirely by ``set_level``, called from the
    device poll loop (~150 ms interval). There are no internal timers.
    """

    def __init__(self, parent: QWidget | None = None, *, vertical: bool = False) -> None:
        """Build a level meter, optionally in vertical orientation.

        Args:
            parent: Qt parent widget.
            vertical: When True the meter is drawn bottom-to-top
                instead of left-to-right. Used by the detail view's
                side panels showing routed channel levels.
        """
        super().__init__(parent)
        self._vertical = vertical
        self._peak = 0.0
        self._peak_hold = 0
        self._smoothed = 0.0
        self._db_peak = float("-inf")
        self._db_hold = 0
        self._clip_hold = 0
        orient = Qt.Orientation.Vertical if vertical else Qt.Orientation.Horizontal
        self.setOrientation(orient)
        self.setRange(0, NUM_SEGMENTS)
        self.setValue(0)
        self.setTextVisible(False)
        if vertical:
            self.setMinimumWidth(14)
            self.setMinimumHeight(60)
        else:
            self.setMinimumWidth(80)
            self.setMinimumHeight(14)
        theme_manager.themeChanged.connect(self.update)

    def set_level(self, value: int | float, clipping: bool | None = None) -> None:
        """Feed a raw 24-bit level sample from the DSP.

        Updates the clip latch, the EMA-smoothed level, the LED
        peak-hold marker, and the numeric dB display peak. Triggers a
        repaint when the peak position changes even if the bar value
        stays the same.

        The clip decision is taken on ``value`` **before** smoothing:
        the EMA would average a single overloaded frame away, and an
        overload the user never sees is worse than useless. Once set,
        the latch holds for ``CLIP_HOLD`` frames.

        Args:
            value: Raw 24-bit level reading from ``parse_levels``
                (``inputs24`` / ``outputs24``); negative values are
                clamped to 0. Callers holding a legacy uint16 value
                get the conversion from ``minidspqt.levels``, which
                multiplies by ``LEVEL24_PER_UINT16``.
            clipping: The device parser's clip flag for this channel
                when the payload carried one. ``None`` (the default)
                means "decide here", applying the library's
                ``level24_is_clipping`` rule to ``value``.
        """
        clamped = max(0.0, float(value))
        clipped = level24_is_clipping(clamped) if clipping is None else clipping
        if clipped:
            self._clip_hold = CLIP_HOLD
        elif self._clip_hold > 0:
            self._clip_hold -= 1
        self._smoothed = EMA_ALPHA * clamped + (1 - EMA_ALPHA) * self._smoothed
        if self._smoothed >= self._peak:
            self._peak = self._smoothed
            self._peak_hold = LED_PEAK_HOLD
        elif self._peak_hold > 0:
            self._peak_hold -= 1
        else:
            self._peak *= LED_PEAK_DECAY
        seg = _db_to_segments(level24_to_dbu(self._smoothed))
        seg = max(0, min(NUM_SEGMENTS - RED_SEGMENTS, seg))
        peak_seg = _db_to_segments(level24_to_dbu(self._peak))
        clip_changed = self.is_clipping != getattr(self, "_last_clip", False)
        if seg == self.value() and (
            clip_changed or peak_seg != getattr(self, "_last_peak_seg", -1)
        ):
            # The bar value did not move, so setValue() will not repaint —
            # but the clip LED or the peak marker did, so ask explicitly.
            self.update()
        self._last_peak_seg = peak_seg
        self._last_clip = self.is_clipping
        self.setValue(seg)

        db = level24_to_dbu(self._smoothed)
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
        return level24_to_dbu(self._smoothed)

    @property
    def is_clipping(self) -> bool:
        """Whether the clip LED is lit (latched for ``CLIP_HOLD`` frames)."""
        return self._clip_hold > 0

    @property
    def display_db(self) -> float:
        """Peak-held dB value for the numeric readout.

        Holds the peak for ``DB_DISPLAY_HOLD`` frames, then decays at
        ``DB_DISPLAY_DECAY`` per frame.  Returns ``-inf`` when idle.
        """
        return self._db_peak

    def reset(self) -> None:
        """Zero all state (smoothed level, peaks, hold counters, clip latch)."""
        self._smoothed = 0.0
        self._peak = 0.0
        self._peak_hold = 0
        self._db_peak = float("-inf")
        self._db_hold = 0
        self._clip_hold = 0
        self._last_clip = False
        self.setValue(0)
        self.update()

    def _segment_lit(self, index: int) -> bool:
        """Whether the segment at *index* is drawn bright.

        Args:
            index: Segment index, 0 at the bottom / left end.

        Returns:
            For the level segments, whether the bar reaches them. The
            trailing ``RED_SEGMENTS`` ignore the level entirely and
            follow :attr:`is_clipping`.
        """
        if index >= NUM_SEGMENTS - RED_SEGMENTS:
            return self.is_clipping
        return index < self.value()

    def paintEvent(self, event) -> None:
        """Custom paint: draw dim/lit LED segments and the peak-hold marker."""
        p = QPainter()
        if not p.begin(self):
            return
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()

            total_gap = SEGMENT_GAP * (NUM_SEGMENTS - 1)
            lit = self.value()

            peak_seg = _db_to_segments(level24_to_dbu(self._peak))
            peak_seg = max(0, min(NUM_SEGMENTS - RED_SEGMENTS - 1, peak_seg))

            if self._vertical:
                seg_h = (h - total_gap) / NUM_SEGMENTS
                seg_w = w - 2
                for i in range(NUM_SEGMENTS):
                    y = h - 1 - (i + 1) * (seg_h + SEGMENT_GAP) + SEGMENT_GAP
                    color = (
                        _segment_color(i)
                        if self._segment_lit(i)
                        else _dim(_segment_color(i))
                    )
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(color)
                    p.drawRoundedRect(
                        1,
                        int(y),
                        int(seg_w),
                        max(1, int(seg_h)),
                        CORNER_RADIUS,
                        CORNER_RADIUS,
                    )
                if 0 < peak_seg < NUM_SEGMENTS and peak_seg >= lit:
                    y = h - 1 - (peak_seg + 1) * (seg_h + SEGMENT_GAP) + SEGMENT_GAP
                    p.setBrush(theme_manager.current.meter_peak_marker)
                    p.drawRoundedRect(
                        1,
                        int(y),
                        int(seg_w),
                        max(1, int(seg_h)),
                        CORNER_RADIUS,
                        CORNER_RADIUS,
                    )
            else:
                seg_w = (w - total_gap) / NUM_SEGMENTS
                seg_h = h - 2
                for i in range(NUM_SEGMENTS):
                    x = i * (seg_w + SEGMENT_GAP)
                    color = (
                        _segment_color(i)
                        if self._segment_lit(i)
                        else _dim(_segment_color(i))
                    )
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
                if 0 < peak_seg < NUM_SEGMENTS and peak_seg >= lit:
                    x = peak_seg * (seg_w + SEGMENT_GAP)
                    p.setBrush(theme_manager.current.meter_peak_marker)
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
