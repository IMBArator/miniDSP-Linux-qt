"""Delay overview graph: horizontal bars for all four output delays.

Unlike the Gate and Compressor graphs (which plot a per-channel transfer
function for the displayed channel only), the Delay graph shows *all four*
output delays at once. This lets the user see relative time-alignment
across the four outputs at a glance — useful for tuning a multi-way
loudspeaker system. The active row (the channel the panel's edit knob
drives) is highlighted with bold text and a dashed outline.

The x-axis auto-scales: it snaps the upper bound to the next 20 ms above
the largest active delay (clamped to the 680 ms protocol max — 32 640
samples / 48 kHz).  Small delays stay legible without losing the option
to view the full range when needed.

Colours come from a hard-coded ``#6c92c2`` / ``#4d7299`` brand hue rather
than ``theme.graph_curve`` because the bars *are* the Delay feature's
visual identity — the same hue the channel-strip Delay button uses. The
inactive rows use a translucent variant of the same hue so it is obvious
they belong to the same group.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..theme import theme_manager

_SAMPLES_PER_MS = 48.0  # 48 kHz sample rate
_SAMPLES_MAX = 32640
_PROTOCOL_MAX_MS = 680.0  # absolute upper bound (32 640 samples / 48 kHz)

# Axis behaviour: round the largest in-use delay up to the next multiple
# of ``_AXIS_STEP_MS`` so small delays are readable while the same widget
# also handles the full 0–680 ms range.  See ``_current_axis_max_ms``.
_AXIS_STEP_MS = 20.0
_AXIS_MIN_MS = 20.0  # used when every channel is 0 ms

_OUTER_PADDING = 10
_LABEL_GAP = 4
_X_LABEL_HEIGHT = 12
_ROW_LABEL_WIDTH = 44  # fits "Out 1" comfortably; user-renamed names elide
_MS_READOUT_WIDTH = 72  # fits "680.000 ms"
_ROW_GAP = 10

_MARGIN_TOP = _OUTER_PADDING
_MARGIN_RIGHT = _OUTER_PADDING + _MS_READOUT_WIDTH + _LABEL_GAP
_MARGIN_BOTTOM = _OUTER_PADDING + _LABEL_GAP + _X_LABEL_HEIGHT
_MARGIN_LEFT = _OUTER_PADDING + _ROW_LABEL_WIDTH + _LABEL_GAP

# Brand hue for Delay — matches the channel-strip Delay button QSS.
_BAR_HUE_DARK = QColor(0x6C, 0x92, 0xC2)
_BAR_HUE_LIGHT = QColor(0x4D, 0x72, 0x99)


def _bar_colors(is_light: bool) -> tuple[QColor, QColor]:
    """Return (active, inactive) bar colours for the current theme."""
    base = _BAR_HUE_LIGHT if is_light else _BAR_HUE_DARK
    inactive = QColor(base)
    inactive.setAlpha(110)
    return base, inactive


class DelayGraph(QWidget):
    """Horizontal bar chart of four output delays on an auto-scaling axis.

    Shows all four outputs as horizontal bars on a shared x-axis that
    snaps to the next 20 ms above the largest active delay (clamped to
    the 680 ms protocol maximum). The "active row" — typically the
    output currently shown in the detail view — is outlined so the
    user can see which bar belongs to the panel they are editing.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build a graph with all four delays at 0 samples.

        Args:
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self._samples: list[int] = [0, 0, 0, 0]
        self._names: list[str] = ["Out1", "Out2", "Out3", "Out4"]
        self._active_row: int = 0
        self.setMinimumHeight(140)
        theme_manager.themeChanged.connect(self.update)

    def set_delays(self, samples: list[int]) -> None:
        """Replace all four output delay values.

        Args:
            samples: List of exactly 4 raw sample counts. Values are
                clamped into ``[0, 32640]`` (the 680 ms protocol
                ceiling at 48 kHz). Wrong-length lists are ignored.
        """
        if len(samples) != 4:
            return
        clamped = [max(0, min(_SAMPLES_MAX, int(s))) for s in samples]
        if clamped != self._samples:
            self._samples = clamped
            self.update()

    def set_channel_names(self, names: list[str]) -> None:
        """Replace the row labels.

        Args:
            names: List of exactly 4 strings. Wrong-length lists are
                ignored. Names propagate from the user's renames in
                the home view.
        """
        if len(names) != 4:
            return
        new = list(names)
        if new != self._names:
            self._names = new
            self.update()

    def set_active_row(self, idx: int) -> None:
        """Highlight one of the four rows.

        Args:
            idx: 0-based row index. Clamped to ``[0, 3]``.
        """
        idx = max(0, min(3, int(idx)))
        if idx != self._active_row:
            self._active_row = idx
            self.update()

    # ------------------------------------------------------------------ #

    def _current_axis_max_ms(self) -> float:
        """Pick the smallest 20-ms-aligned upper bound that fits every bar.

        Rounds the largest in-use delay up to the next multiple of
        ``_AXIS_STEP_MS``.  When every channel is at 0 ms the axis
        defaults to ``_AXIS_MIN_MS`` (20 ms) so the first edit lands
        inside a meaningful range rather than against a 680 ms wall.
        """
        max_ms = max(s / _SAMPLES_PER_MS for s in self._samples)
        if max_ms <= 0.0:
            return _AXIS_MIN_MS
        steps = math.ceil(max_ms / _AXIS_STEP_MS)
        upper = steps * _AXIS_STEP_MS
        return min(_PROTOCOL_MAX_MS, max(_AXIS_MIN_MS, upper))

    def _grid_ticks_ms(self, upper_ms: float) -> tuple[float, ...]:
        """Tick positions for the current axis.

        Uses 20 ms steps at low ranges (≤ 100 ms) where every increment
        is meaningful for time alignment, then switches to 100 ms steps
        so we don't crowd 35 labels into a 600 px-wide plot at full
        range.  Always anchors at 0 and at the upper bound so both ends
        of the axis are labelled.  If the regular step would land within
        half a step of the upper bound it is absorbed into the endpoint
        to avoid two labels (e.g. 100 and 120) jammed together.
        """
        step = 20.0 if upper_ms <= 100.0 else 100.0
        ticks: list[float] = []
        t = 0.0
        while t < upper_ms - step / 2:
            ticks.append(t)
            t += step
        ticks.append(upper_ms)
        return tuple(ticks)

    def _plot_rect(self) -> QRectF:
        return QRectF(
            _MARGIN_LEFT,
            _MARGIN_TOP,
            self.width() - _MARGIN_LEFT - _MARGIN_RIGHT,
            self.height() - _MARGIN_TOP - _MARGIN_BOTTOM,
        )

    def _ms_to_x(self, ms: float, upper_ms: float) -> float:
        r = self._plot_rect()
        return r.left() + (ms / upper_ms) * r.width()

    def _row_rect(self, idx: int) -> QRectF:
        r = self._plot_rect()
        # 5 gap slots: one above row 0, three between rows, one below row 3.
        # Keeps the first/last bars from sitting flush against the plot
        # border, matching the breathing room between adjacent bars.
        total_gaps = _ROW_GAP * 5
        row_h = max(1.0, (r.height() - total_gaps) / 4)
        top = r.top() + _ROW_GAP + idx * (row_h + _ROW_GAP)
        return QRectF(r.left(), top, r.width(), row_h)

    # ------------------------------------------------------------------ #

    def paintEvent(self, event) -> None:  # noqa: ARG002 — Qt signature
        p = QPainter()
        if not p.begin(self):
            return
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            theme = theme_manager.current
            upper = self._current_axis_max_ms()

            p.fillRect(0, 0, self.width(), self.height(), theme.graph_bg)

            self._draw_grid(p, upper)
            self._draw_axis_labels(p, upper)
            self._draw_bars(p, upper)
            self._draw_active_row_outline(p)
            self._draw_row_labels(p)
            self._draw_readouts(p)

            p.setPen(QPen(theme.graph_border, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self._plot_rect())
        finally:
            p.end()

    def _draw_grid(self, p: QPainter, upper_ms: float) -> None:
        rect = self._plot_rect()
        pen = QPen(theme_manager.current.graph_grid, 1, Qt.PenStyle.DotLine)
        p.setPen(pen)
        for ms in self._grid_ticks_ms(upper_ms):
            if ms in (0.0, upper_ms):
                continue  # drawn by the plot border
            x = self._ms_to_x(ms, upper_ms)
            p.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))

    def _draw_axis_labels(self, p: QPainter, upper_ms: float) -> None:
        rect = self._plot_rect()
        font = QFont(p.font())
        font.setPixelSize(10)
        p.setFont(font)
        p.setPen(QPen(theme_manager.current.graph_label))
        for ms in self._grid_ticks_ms(upper_ms):
            x = self._ms_to_x(ms, upper_ms)
            p.drawText(
                int(x) - 16,
                int(rect.bottom()) + _LABEL_GAP,
                32,
                _X_LABEL_HEIGHT,
                Qt.AlignmentFlag.AlignCenter,
                f"{int(ms)}",
            )

    def _draw_bars(self, p: QPainter, upper_ms: float) -> None:
        active_color, inactive_color = _bar_colors(
            theme_manager.current.name == "light"
        )
        for i, samples in enumerate(self._samples):
            row = self._row_rect(i)
            ms = samples / _SAMPLES_PER_MS
            bar_w = min(row.width(), (ms / upper_ms) * row.width())
            color = active_color if i == self._active_row else inactive_color
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRect(QRectF(row.left(), row.top(), bar_w, row.height()))

    def _draw_active_row_outline(self, p: QPainter) -> None:
        active_color, _ = _bar_colors(theme_manager.current.name == "light")
        row = self._row_rect(self._active_row)
        pen = QPen(active_color, 1, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(row.adjusted(-2, -2, 2, 2))

    def _draw_row_labels(self, p: QPainter) -> None:
        theme = theme_manager.current
        base_font = QFont(p.font())
        base_font.setPixelSize(11)
        bold_font = QFont(base_font)
        bold_font.setBold(True)
        for i, name in enumerate(self._names):
            row = self._row_rect(i)
            p.setFont(bold_font if i == self._active_row else base_font)
            p.setPen(QPen(theme.pal_window_text))
            p.drawText(
                _OUTER_PADDING,
                int(row.top()),
                _ROW_LABEL_WIDTH,
                int(row.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                name,
            )

    def _draw_readouts(self, p: QPainter) -> None:
        theme = theme_manager.current
        base_font = QFont(p.font())
        base_font.setPixelSize(10)
        bold_font = QFont(base_font)
        bold_font.setBold(True)
        for i, samples in enumerate(self._samples):
            row = self._row_rect(i)
            ms = samples / _SAMPLES_PER_MS
            p.setFont(bold_font if i == self._active_row else base_font)
            p.setPen(QPen(theme.graph_label))
            p.drawText(
                int(row.right()) + _LABEL_GAP,
                int(row.top()),
                _MS_READOUT_WIDTH,
                int(row.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{ms:.3f} ms",
            )
