"""Channel strip widgets for input and output channels.

:class:`ChannelStrip` is the shared base with gain knob, level meter, and
toggle buttons.  :class:`InputChannelStrip` and :class:`OutputChannelStrip`
configure the toggles and specialize the gate-button behavior.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..widgets import GainKnob, LedIndicator, LevelMeter, ToggleButton

INPUT_TOGGLES = [("Gate", "gate"), ("Phase", "phase"), ("Mute", "mute")]
OUTPUT_TOGGLES = [
    ("Xover", "xover"),
    ("PEQ", "peq"),
    ("Comp", "comp"),
    ("Phase", "phase"),
    ("Delay", "delay"),
    ("Mute", "mute"),
]


class ChannelStrip(QFrame):
    """Base channel strip with gain knob, level meter, and toggle row.

    Subclasses set ``_toggle_specs`` and ``_show_limiter`` before calling
    ``_build_ui()``.
    """

    gain_changed = Signal(int)
    toggle_changed = Signal(str, bool)
    name_changed = Signal(str)

    _toggle_specs: list[tuple[str, str]] = []
    _show_limiter: bool = False

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title_text = title
        self._is_linked_slave = False
        self._build_ui()

    def _build_ui(self) -> None:
        self.setFrameShape(QFrame.Shape.StyledPanel)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        self._title_btn = QPushButton(self._title_text)
        self._title_btn.setObjectName("channelTitle")
        self._title_btn.setFixedHeight(22)
        self._title_btn.setFlat(True)
        self._title_btn.clicked.connect(self._on_title_clicked)
        root.addWidget(self._title_btn)

        meter_row = QHBoxLayout()
        meter_row.setSpacing(0)

        self._knob = GainKnob()
        self._knob.setFixedSize(64, 76)
        meter_row.addWidget(self._knob)

        separator = QFrame()
        separator.setObjectName("channelSeparator")
        separator.setFrameShape(QFrame.Shape.VLine)
        meter_row.addWidget(separator)
        meter_row.addSpacing(4)

        meter_col = QVBoxLayout()
        meter_col.setSpacing(1)

        self._meter = LevelMeter()
        self._meter.setMinimumWidth(20)
        meter_col.addWidget(self._meter, stretch=1)

        self._db_label = QLabel("\u2014 dB")
        self._db_label.setObjectName("channelDbLabel")
        self._db_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._db_label.setFixedHeight(16)

        self._limiter_led: LedIndicator | None = None
        db_row = QHBoxLayout()
        db_row.setSpacing(4)
        db_row.setContentsMargins(0, 0, 0, 0)
        db_row.addWidget(self._db_label, stretch=1)
        if self._show_limiter:
            limiter_label = QLabel("Lim")
            limiter_label.setObjectName("channelLimLabel")
            limiter_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            db_row.addWidget(limiter_label)
            self._limiter_led = LedIndicator()
            db_row.addWidget(self._limiter_led)
        meter_col.addLayout(db_row)

        meter_row.addLayout(meter_col, stretch=1)

        root.addLayout(meter_row)

        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(4)
        self._toggles: dict[str, ToggleButton] = {}
        for label, feature in self._toggle_specs:
            btn = ToggleButton()
            btn.setText(label)
            btn.setFeature(feature)
            btn.toggled.connect(
                lambda checked, f=feature: self.toggle_changed.emit(f, checked)
            )
            toggle_row.addWidget(btn)
            self._toggles[feature] = btn

        self._link_label = QLabel("")
        self._link_label.setObjectName("channelLinkLabel")
        self._link_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._link_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self._link_label.hide()

        toggle_row.addStretch(1)
        toggle_row.addWidget(self._link_label)
        root.addLayout(toggle_row)

        root.setSizeConstraint(root.SizeConstraint.SetMinimumSize)

        self._knob.valueChanged.connect(self.gain_changed)

    def set_title(self, title: str) -> None:
        self._title_btn.setText(title)

    def _on_title_clicked(self) -> None:
        current = self._title_btn.text()
        new_name, ok = QInputDialog.getText(
            self,
            "Channel Name",
            "Name (max 8 chars):",
            text=current,
        )
        if ok and new_name != current:
            new_name = new_name[:8]
            self._title_btn.setText(new_name)
            self.name_changed.emit(new_name)

    def set_gain_silent(self, raw: int) -> None:
        self._knob.setValueSilently(raw)

    def set_gate_active(self, active: bool) -> None:
        btn = self._toggles.get("gate")
        if btn is None:
            return
        btn.setProperty("gate_active", active)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def set_peq_active(self, active: bool) -> None:
        btn = self._toggles.get("peq")
        if btn is None:
            return
        btn.setProperty("peq_active", active)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def set_toggle_silent(self, feature: str, checked: bool) -> None:
        btn = self._toggles.get(feature)
        if btn is None:
            return
        was = btn.blockSignals(True)
        btn.setChecked(checked)
        btn.blockSignals(was)

    def set_enabled_state(self, enabled: bool) -> None:
        if enabled and self._is_linked_slave:
            return
        self._knob.setEnabled(enabled)
        for btn in self._toggles.values():
            btn.setEnabled(enabled)
        if not enabled:
            self._meter.reset()
            self._db_label.setText("\u2014 dB")
            if self._limiter_led is not None:
                self._limiter_led.set_active(False)

    def set_limiter_active(self, active: bool) -> None:
        if self._limiter_led is not None:
            self._limiter_led.set_active(active)

    def set_linked_slave(self, is_slave: bool, master_name: str = "") -> None:
        self._is_linked_slave = is_slave
        self._knob.setEnabled(not is_slave)
        for btn in self._toggles.values():
            btn.setEnabled(not is_slave)
        if is_slave:
            self._link_label.setText("\U0001f517")
            self._link_label.setToolTip(
                f"Linked to {master_name}" if master_name else "Linked"
            )
            self._link_label.show()
        else:
            self._link_label.setToolTip("")
            self._link_label.hide()

    @property
    def meter(self) -> LevelMeter:
        return self._meter

    def update_level(self, value: int) -> None:
        self._meter.set_level(value)
        db = self._meter.display_db
        if db == float("-inf"):
            self._db_label.setText("\u2014 dB")
        else:
            self._db_label.setText(f"{db:+.1f} dB")


class InputChannelStrip(ChannelStrip):
    """Input channel strip: Gate / Phase / Mute toggles.

    The Gate button acts as a **navigation** button — clicking it emits
    :attr:`gate_clicked` and immediately unchecks itself.  It turns green
    via the ``gate_active`` QSS property when the gate threshold is above
    -90 dB.
    """

    _toggle_specs = INPUT_TOGGLES

    gate_clicked = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        gate_btn = self._toggles.get("gate")
        if gate_btn is not None:
            gate_btn.toggled.connect(self._on_gate_toggled)

    def _on_gate_toggled(self, checked: bool) -> None:
        self.set_toggle_silent("gate", False)
        if checked:
            self.gate_clicked.emit()


class OutputChannelStrip(ChannelStrip):
    """Output channel strip: Xover / PEQ / Comp / Phase / Delay / Mute toggles.

    Includes a limiter LED indicator.  PEQ is wired as a navigation
    button (clicks emit :attr:`toggle_changed` then auto-uncheck, the
    same pattern as the input Gate button).  It turns purple via the
    ``peq_active`` QSS property when at least one band has non-zero
    gain and is not bypassed.  Xover / Comp / Delay still latch as
    plain toggles until their detail-view panels exist — this will be
    unified once those panels land.
    """

    _toggle_specs = OUTPUT_TOGGLES
    _show_limiter = True

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        peq_btn = self._toggles.get("peq")
        if peq_btn is not None:
            peq_btn.toggled.connect(self._on_peq_toggled)

    def _on_peq_toggled(self, checked: bool) -> None:
        # Navigation button: when the user clicks an unchecked button the
        # underlying toggle_changed("peq", True) has already propagated to
        # MainWindow before this slot runs.  We force the visual state back
        # to unchecked so the button reads as a momentary tap.  blockSignals
        # inside set_toggle_silent prevents this False write from re-firing.
        # See InputChannelStrip._on_gate_toggled for the same pattern.
        if checked:
            self.set_toggle_silent("peq", False)
