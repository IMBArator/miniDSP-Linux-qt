"""Rotary gain dial.

Raw value range 0..400 maps to the device gain (−60 dB .. +12 dB), using
`raw_to_db()` from the protocol library for the centre label. Interaction:
vertical mouse drag and the scroll wheel both step the raw value.

The exact dB value is shown in an editable label below the arc.
Click the label to type a new value; press Enter to apply.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from minidsp.protocol import raw_to_db

GAIN_RAW_MIN = 0  # −60 dB
GAIN_RAW_MAX = 400  # +12 dB
GAIN_RAW_DEFAULT = 280  # 0 dB

_ARC_START_DEG = 225.0
_ARC_SWEEP_DEG = -270.0
_DRAG_PIXELS_PER_STEP = 1.5


def _format_db(raw: int) -> str:
    db = raw_to_db(raw)
    if db <= -60.0:
        return "-inf"
    return f"{db:+.1f}"


def _format_db_full(raw: int) -> str:
    db = raw_to_db(raw)
    if db <= -60.0:
        return "-inf dB"
    return f"{db:+.1f} dB"


class GainKnob(QWidget):
    valueChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = GAIN_RAW_DEFAULT
        self._minimum = GAIN_RAW_MIN
        self._maximum = GAIN_RAW_MAX
        self._drag_anchor_y: float | None = None
        self._drag_anchor_value: int = self._value

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._arc_widget = _ArcWidget(self)
        self._arc_widget.setMinimumSize(56, 56)
        layout.addWidget(self._arc_widget, stretch=1)

        self._value_edit = QLineEdit(_format_db_full(self._value))
        self._value_edit.setObjectName("gainKnobEdit")
        self._value_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value_edit.setFixedWidth(68)
        self._value_edit.setReadOnly(True)
        self._value_edit.returnPressed.connect(self._apply_edit)
        self._value_edit.editingFinished.connect(self._apply_edit)
        self._value_edit.focusInEvent = lambda e: (
            self._value_edit.setReadOnly(False),
            self._value_edit.selectAll(),
        )
        layout.addWidget(self._value_edit, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # --- Public API ---

    def setRange(self, minimum: int, maximum: int) -> None:
        self._minimum = minimum
        self._maximum = maximum
        self.setValue(self._value)

    def value(self) -> int:
        return self._value

    def setValue(self, raw: int) -> None:
        clamped = max(self._minimum, min(self._maximum, int(raw)))
        if clamped != self._value:
            self._value = clamped
            self.valueChanged.emit(self._value)
            self._arc_widget.update()
            self._value_edit.setText(_format_db_full(self._value))
        else:
            self._arc_widget.update()

    def setValueSilently(self, raw: int) -> None:
        clamped = max(self._minimum, min(self._maximum, int(raw)))
        if clamped != self._value:
            self._value = clamped
            self._arc_widget.update()
            self._value_edit.setText(_format_db_full(self._value))

    # --- Edit handling ---

    def _apply_edit(self) -> None:
        text = self._value_edit.text().strip().lower()
        self._value_edit.setReadOnly(True)
        try:
            if text in ("-inf", "-∞", "-inf db", "-∞ db"):
                self.setValue(self._minimum)
                return
            num_str = text.removesuffix("db").strip()
            db_val = float(num_str)
            db_val = max(-60.0, min(12.0, db_val))
            from minidsp.protocol import db_to_raw

            raw = db_to_raw(db_val)
            self.setValue(raw)
        except (ValueError, OSError):
            pass
        finally:
            self._value_edit.setText(_format_db_full(self._value))

    # --- Interaction (forwarded to arc) ---

    def _arc_value(self) -> int:
        return self._value

    def _arc_minimum(self) -> int:
        return self._minimum

    def _arc_maximum(self) -> int:
        return self._maximum

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_anchor_y = event.position().y()
            self._drag_anchor_value = self._value
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_anchor_y is None:
            super().mouseMoveEvent(event)
            return
        dy = self._drag_anchor_y - event.position().y()
        step = int(dy / _DRAG_PIXELS_PER_STEP)
        self.setValue(self._drag_anchor_value + step)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_anchor_y = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        steps = event.angleDelta().y() // 120
        if steps:
            self.setValue(self._value + steps)
            event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Right):
            self.setValue(self._value + 1)
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Left):
            self.setValue(self._value - 1)
            event.accept()
            return
        super().keyPressEvent(event)


class _ArcWidget(QWidget):
    def __init__(self, knob: GainKnob, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._knob = knob

    def paintEvent(self, event) -> None:
        p = QPainter()
        if not p.begin(self):
            return
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            value = self._knob._value
            minimum = self._knob._minimum
            maximum = self._knob._maximum

            side = min(self.width(), self.height())
            cx = self.width() / 2
            cy = self.height() / 2
            radius = side / 2 - 4
            rect = QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)

            pen_bg = QPen(QColor(60, 60, 64), max(2.0, radius * 0.10))
            pen_bg.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen_bg)
            p.drawArc(rect, int(_ARC_START_DEG * 16), int(_ARC_SWEEP_DEG * 16))

            span = maximum - minimum
            frac = (value - minimum) / span if span else 0.0
            pen_fg = QPen(QColor(80, 160, 230), max(2.0, radius * 0.10))
            pen_fg.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen_fg)
            p.drawArc(
                rect,
                int(_ARC_START_DEG * 16),
                int(_ARC_SWEEP_DEG * frac * 16),
            )

            angle_deg = _ARC_START_DEG + _ARC_SWEEP_DEG * frac
            angle_rad = math.radians(angle_deg)
            tip = QPointF(
                cx + radius * 0.85 * math.cos(angle_rad),
                cy - radius * 0.85 * math.sin(angle_rad),
            )
            p.setPen(QPen(QColor(230, 230, 230), max(1.5, radius * 0.06)))
            p.drawLine(QPointF(cx, cy), tip)
        finally:
            p.end()
