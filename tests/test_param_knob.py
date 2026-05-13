"""ParamKnob — construction, value API, clamping, interaction, highlight."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from minidspqt.widgets.param_knob import ParamKnob


@pytest.fixture
def knob(qtbot):
    k = ParamKnob(minimum=0, maximum=100, default=50)
    qtbot.addWidget(k)
    return k


def _wheel_up(multiplier=1):
    return QWheelEvent(
        QPointF(0, 0),
        QPointF(0, 0),
        QPoint(0, 120 * multiplier),
        QPoint(0, 120 * multiplier),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollBegin,
        False,
    )


def _wheel_down(multiplier=1):
    return QWheelEvent(
        QPointF(0, 0),
        QPointF(0, 0),
        QPoint(0, -120 * multiplier),
        QPoint(0, -120 * multiplier),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollBegin,
        False,
    )


def _mouse_press(y, button=Qt.MouseButton.LeftButton):
    return QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(28, y),
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )


def _mouse_move(y):
    return QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(28, y),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _key(key, modifier=Qt.KeyboardModifier.NoModifier):
    return QKeyEvent(
        QKeyEvent.Type.KeyPress, key, modifier,
    )


# ------------------------------------------------------------------ #
# Construction
# ------------------------------------------------------------------ #


class TestConstruction:
    def test_defaults(self, qtbot):
        k = ParamKnob()
        qtbot.addWidget(k)
        assert k.value() == 0
        assert k._minimum == 0
        assert k._maximum == 100

    def test_custom_range_and_default(self, qtbot):
        k = ParamKnob(minimum=10, maximum=300, default=150)
        qtbot.addWidget(k)
        assert k.value() == 150
        assert k._minimum == 10
        assert k._maximum == 300

    def test_default_clamped_to_range(self, qtbot):
        k = ParamKnob(minimum=0, maximum=50, default=999)
        qtbot.addWidget(k)
        assert k.value() == 50

    def test_default_clamped_below_minimum(self, qtbot):
        k = ParamKnob(minimum=10, maximum=100, default=-5)
        qtbot.addWidget(k)
        assert k.value() == 10

    def test_custom_formatter(self, qtbot):
        k = ParamKnob(formatter=lambda v: f"{v} ms")
        qtbot.addWidget(k)
        assert k._value_edit.text() == "0 ms"

    def test_default_formatter_is_str(self, qtbot):
        k = ParamKnob(default=42)
        qtbot.addWidget(k)
        assert k._value_edit.text() == "42"


# ------------------------------------------------------------------ #
# setValue / value
# ------------------------------------------------------------------ #


class TestSetValue:
    def test_basic_set(self, knob):
        knob.setValue(75)
        assert knob.value() == 75

    def test_clamped_at_maximum(self, knob):
        knob.setValue(999)
        assert knob.value() == 100

    def test_clamped_at_minimum(self, knob):
        knob.setValue(-10)
        assert knob.value() == 0

    def test_signal_emitted_on_change(self, knob, qtbot):
        with qtbot.waitSignal(knob.valueChanged, timeout=500) as sig:
            knob.setValue(75)
        assert sig.args == [75]

    def test_no_signal_on_same_value(self, knob, qtbot):
        knob.setValue(50)
        with qtbot.assertNotEmitted(knob.valueChanged):
            knob.setValue(50)

    def test_label_updates_on_change(self, knob):
        knob.setValue(80)
        assert knob._value_edit.text() == "80"

    def test_float_truncated_to_int(self, knob):
        knob.setValue(33.7)
        assert knob.value() == 33


# ------------------------------------------------------------------ #
# setValueSilently
# ------------------------------------------------------------------ #


class TestSetValueSilently:
    def test_updates_value(self, knob):
        knob.setValueSilently(20)
        assert knob.value() == 20

    def test_no_signal(self, knob, qtbot):
        with qtbot.assertNotEmitted(knob.valueChanged):
            knob.setValueSilently(20)

    def test_label_updates(self, knob):
        knob.setValueSilently(20)
        assert knob._value_edit.text() == "20"

    def test_clamped(self, knob):
        knob.setValueSilently(999)
        assert knob.value() == 100


# ------------------------------------------------------------------ #
# setRange
# ------------------------------------------------------------------ #


class TestSetRange:
    def test_updates_range(self, knob):
        knob.setRange(0, 300)
        assert knob._minimum == 0
        assert knob._maximum == 300

    def test_clamps_value_into_new_range(self, knob):
        knob.setValue(80)
        knob.setRange(0, 50)
        assert knob.value() == 50

    def test_value_unchanged_if_within_new_range(self, knob):
        knob.setValue(30)
        knob.setRange(0, 200)
        assert knob.value() == 30

    def test_signal_if_clamped(self, knob, qtbot):
        knob.setValue(80)
        with qtbot.waitSignal(knob.valueChanged, timeout=500) as sig:
            knob.setRange(0, 50)
        assert sig.args == [50]


# ------------------------------------------------------------------ #
# Wheel interaction
# ------------------------------------------------------------------ #


class TestWheelEvent:
    def test_scroll_up_increments(self, knob):
        knob.wheelEvent(_wheel_up())
        assert knob.value() == 51

    def test_scroll_down_decrements(self, knob):
        knob.wheelEvent(_wheel_down())
        assert knob.value() == 49

    def test_scroll_multiple_steps(self, knob):
        knob.wheelEvent(_wheel_up(3))
        assert knob.value() == 53

    def test_clamped_at_maximum(self, knob):
        knob.setValue(100)
        knob.wheelEvent(_wheel_up())
        assert knob.value() == 100

    def test_clamped_at_minimum(self, knob):
        knob.setValue(0)
        knob.wheelEvent(_wheel_down())
        assert knob.value() == 0

    def test_signal_on_scroll(self, knob, qtbot):
        with qtbot.waitSignal(knob.valueChanged, timeout=500) as sig:
            knob.wheelEvent(_wheel_up())
        assert sig.args == [51]


# ------------------------------------------------------------------ #
# Keyboard interaction
# ------------------------------------------------------------------ #


class TestKeyEvent:
    def test_up_arrow_increments(self, knob):
        knob.keyPressEvent(_key(Qt.Key.Key_Up))
        assert knob.value() == 51

    def test_right_arrow_increments(self, knob):
        knob.keyPressEvent(_key(Qt.Key.Key_Right))
        assert knob.value() == 51

    def test_down_arrow_decrements(self, knob):
        knob.keyPressEvent(_key(Qt.Key.Key_Down))
        assert knob.value() == 49

    def test_left_arrow_decrements(self, knob):
        knob.keyPressEvent(_key(Qt.Key.Key_Left))
        assert knob.value() == 49

    def test_unknown_key_passes_through(self, knob):
        event = _key(Qt.Key.Key_A)
        knob.keyPressEvent(event)
        assert not event.isAccepted()

    def test_clamped_at_maximum(self, knob):
        knob.setValue(100)
        knob.keyPressEvent(_key(Qt.Key.Key_Up))
        assert knob.value() == 100

    def test_signal_on_key(self, knob, qtbot):
        with qtbot.waitSignal(knob.valueChanged, timeout=500) as sig:
            knob.keyPressEvent(_key(Qt.Key.Key_Up))
        assert sig.args == [51]


# ------------------------------------------------------------------ #
# Mouse drag
# ------------------------------------------------------------------ #


class TestMouseDrag:
    def test_drag_up_increases(self, knob):
        knob.mousePressEvent(_mouse_press(y=50))
        knob.mouseMoveEvent(_mouse_move(y=35))
        assert knob.value() > 50

    def test_drag_down_decreases(self, knob):
        knob.mousePressEvent(_mouse_press(y=50))
        knob.mouseMoveEvent(_mouse_move(y=65))
        assert knob.value() < 50

    def test_non_left_button_ignored(self, knob):
        knob.mousePressEvent(
            _mouse_press(y=50, button=Qt.MouseButton.RightButton)
        )
        assert knob._drag_anchor_y is None

    def test_release_resets_anchor(self, knob):
        knob.mousePressEvent(_mouse_press(y=50))
        assert knob._drag_anchor_y is not None
        release = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            QPointF(28, 50),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        knob.mouseReleaseEvent(release)
        assert knob._drag_anchor_y is None


# ------------------------------------------------------------------ #
# Text input (_apply_edit)
# ------------------------------------------------------------------ #


class TestApplyEdit:
    def test_valid_input(self, knob):
        knob._value_edit.setText("75")
        knob._apply_edit()
        assert knob.value() == 75

    def test_invalid_input_preserves_value(self, knob):
        knob._value_edit.setText("not a number")
        knob._apply_edit()
        assert knob.value() == 50

    def test_custom_parser(self, qtbot):
        k = ParamKnob(minimum=0, maximum=100, parser=lambda t: int(float(t)))
        qtbot.addWidget(k)
        k._value_edit.setText("33.7")
        k._apply_edit()
        assert k.value() == 33


# ------------------------------------------------------------------ #
# Highlight / blink
# ------------------------------------------------------------------ #


class TestHighlight:
    def test_highlight_starts_timer(self, knob):
        knob.highlight()
        assert knob._highlight_timer.isActive()
        assert knob._highlighted is True
        assert knob._blink_count == 0

    def test_blink_tick_toggles(self, knob):
        knob.highlight()
        assert knob._highlighted is True
        knob._blink_tick()
        assert knob._highlighted is False
        assert knob._blink_count == 0
        knob._blink_tick()
        assert knob._highlighted is True
        assert knob._blink_count == 1

    def test_stops_after_4_blinks(self, knob):
        knob.highlight()
        for _ in range(8):
            knob._blink_tick()
        assert knob._highlight_timer.isActive() is False
        assert knob._highlighted is False
        assert knob._blink_count == 4

    def test_clear_highlight(self, knob):
        knob.highlight()
        knob._clear_highlight()
        assert knob._highlighted is False


# ------------------------------------------------------------------ #
# Edge cases
# ------------------------------------------------------------------ #


class TestEdgeCases:
    def test_zero_span_range(self, qtbot):
        k = ParamKnob(minimum=42, maximum=42, default=42)
        qtbot.addWidget(k)
        k.setValue(999)
        assert k.value() == 42

    def test_large_range(self, qtbot):
        k = ParamKnob(minimum=0, maximum=32640, default=0)
        qtbot.addWidget(k)
        k.setValue(32640)
        assert k.value() == 32640
        k.setValue(0)
        assert k.value() == 0

    def test_formatter_receives_int(self, qtbot):
        received = []
        k = ParamKnob(
            minimum=0,
            maximum=100,
            formatter=lambda v: (received.append(type(v)), str(v))[1],
        )
        qtbot.addWidget(k)
        k.setValue(50)
        assert all(t is int for t in received)
