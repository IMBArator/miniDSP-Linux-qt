"""Channel strip widgets for input and output channels.

:class:`ChannelStrip` is the shared base with gain knob, level meter, and
toggle buttons.  :class:`InputChannelStrip` and :class:`OutputChannelStrip`
configure the toggles and specialize the gate-button behavior.

Module-level helpers :func:`apply_input_strip_state` and
:func:`apply_output_strip_state` provide a single source of truth for
rendering a channel-state object onto a strip — used by both the home
view's overview and the detail view's header strip so any new field only
needs to be wired in once.
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

from minidsp.protocol import CHANNEL_NAMES, raw_to_db

from ..widgets import GainIndicator, LedIndicator, LevelMeter, ParamKnob, ToggleButton
from ..defaults import default_gain
from ..model import InputChannelState, OutputChannelState

GAIN_RAW_MIN = 0
GAIN_RAW_MAX = 400


def _format_db_full(raw: int) -> str:
    """Format a raw gain value as a signed dB string.

    Args:
        raw: Raw protocol gain value.

    Returns:
        A signed dB string for the value label, or ``"-inf dB"`` at
        and below ``-60 dB`` so the bottom of the range reads as
        "fully attenuated" rather than a misleading number.
    """
    db = raw_to_db(raw)
    if db <= -60.0:
        return "-inf dB"
    return f"{db:+.1f} dB"


def _parse_db(text: str) -> int:
    """Parse a typed dB string back into a raw gain value.

    Accepts a signed number with an optional ``dB`` suffix, plus the
    special tokens ``-inf`` and ``-∞`` (with or without the ``dB``
    suffix) which map to ``GAIN_RAW_MIN``. Values are clamped into
    ``[-60, +12]`` dB before conversion.

    Raises:
        ValueError: If the numeric part fails to parse as a float.
    """
    text = text.strip().lower()
    if text in ("-inf", "-∞", "-inf db", "-∞ db"):
        return GAIN_RAW_MIN
    num_str = text.removesuffix("db").strip()
    db_val = float(num_str)
    db_val = max(-60.0, min(12.0, db_val))
    from minidsp.protocol import db_to_raw

    return db_to_raw(db_val)


INPUT_TOGGLES = [
    ("Gain", "gain"),
    ("Gate", "gate"),
    ("Phase", "phase"),
    ("Mute", "mute"),
]
OUTPUT_TOGGLES = [
    ("Xover", "xover"),
    ("PEQ", "peq"),
    ("Gain", "gain"),
    ("Comp", "comp"),
    ("Phase", "phase"),
    ("Delay", "delay"),
    ("Mute", "mute"),
]


class ChannelStrip(QFrame):
    """Base channel strip — gain knob, level meter, toggle row, name button.

    Concrete subclasses (``InputChannelStrip``, ``OutputChannelStrip``)
    set ``_toggle_specs`` and ``_show_limiter`` at class level so that
    ``_build_ui`` can place the right toggles for the channel type. The
    base class owns the gain knob, level meter and the renamable title
    button.

    Signals:
        gain_changed (int): New raw gain value.
        toggle_changed (str, bool): ``(toggle_key, checked)`` where
            ``toggle_key`` is one of ``"gate"``/``"mute"``/``"phase"``/
            ``"xover"``/``"peq"``/``"comp"``/``"delay"`` depending on
            the channel type.
        name_changed (str): The user accepted a new channel name.
    """

    gain_changed = Signal(int)
    toggle_changed = Signal(str, bool)
    name_changed = Signal(str)

    _toggle_specs: list[tuple[str, str]] = []
    _show_limiter: bool = False

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        """Build a strip with the given title.

        Args:
            title: Initial channel name shown on the title button.
            parent: Qt parent widget.
        """
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

        self._link_label = QLabel("")
        self._link_label.setObjectName("channelLinkLabel")
        self._link_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._link_label.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        self._link_label.hide()

        title_row = QHBoxLayout()
        title_row.setSpacing(4)
        title_row.addWidget(self._title_btn, stretch=1)
        title_row.addWidget(self._link_label)
        root.addLayout(title_row)

        meter_row = QHBoxLayout()
        meter_row.setSpacing(0)

        self._knob = ParamKnob(
            minimum=GAIN_RAW_MIN,
            maximum=GAIN_RAW_MAX,
            default=default_gain(),
            formatter=_format_db_full,
            parser=_parse_db,
        )
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
        self._gain_indicator: GainIndicator | None = None
        for label, feature in self._toggle_specs:
            if feature == "gain":
                indicator = GainIndicator()
                indicator.setText(label)
                indicator.gain_clicked.connect(self._highlight_gain)
                toggle_row.addWidget(indicator)
                self._gain_indicator = indicator
            else:
                btn = ToggleButton()
                btn.setText(label)
                btn.setFeature(feature)
                btn.toggled.connect(
                    lambda checked, f=feature: self.toggle_changed.emit(f, checked)
                )
                toggle_row.addWidget(btn)
                self._toggles[feature] = btn

        toggle_row.addStretch(1)
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

    def _highlight_gain(self) -> None:
        self._knob.highlight()

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

    def set_link_master(self, member_names: list[str]) -> None:
        self._link_label.setText("\U0001f517")
        tooltip = ", ".join(member_names)
        self._link_label.setToolTip(f"Master of {tooltip}")
        self._link_label.show()

    def set_enabled_state(self, enabled: bool) -> None:
        if enabled and self._is_linked_slave:
            return
        self._knob.setEnabled(enabled)
        for btn in self._toggles.values():
            btn.setEnabled(enabled)
        if self._gain_indicator is not None:
            self._gain_indicator.setEnabled(enabled)
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
        if self._gain_indicator is not None:
            self._gain_indicator.setEnabled(not is_slave)
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
    """Input channel strip: Gain / Gate / Phase / Mute toggles.

    The Gate button is a navigation button — clicking it emits
    ``gate_clicked`` and immediately unchecks itself so the detail
    view opens cleanly. It turns green via the ``gate_active`` QSS
    property when the gate threshold is above -90 dB.

    Signals:
        gate_clicked (): Fired when the user presses the Gate
            button (in addition to the inherited toggle/gain/name
            signals).
    """

    _toggle_specs = INPUT_TOGGLES

    gate_clicked = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        """Build an input strip; ``title`` is the initial channel name."""
        super().__init__(title, parent)
        gate_btn = self._toggles.get("gate")
        if gate_btn is not None:
            gate_btn.toggled.connect(self._on_gate_toggled)

    def _on_gate_toggled(self, checked: bool) -> None:
        self.set_toggle_silent("gate", False)
        if checked:
            self.gate_clicked.emit()


class OutputChannelStrip(ChannelStrip):
    """Output channel strip: Xover / PEQ / Gain / Comp / Phase / Delay / Mute.

    Includes a limiter LED indicator on the meter. Xover, PEQ, Comp
    and Delay are wired as navigation buttons (auto-uncheck on
    click); their per-feature accent colour lights up via QSS
    dynamic properties (``xover_active``, ``comp_active``,
    ``delay_active``, and the inherited ``peq_active``) when the
    corresponding feature is shaping the signal.
    """

    _toggle_specs = OUTPUT_TOGGLES
    _show_limiter = True

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        """Build an output strip; ``title`` is the initial channel name."""
        super().__init__(title, parent)
        # Xover/PEQ/Comp/Delay are navigation buttons — they open the
        # corresponding detail-view panel and immediately uncheck so the
        # next press fires again. Phase and Mute remain real toggles.
        for nav in ("xover", "peq", "comp", "delay"):
            btn = self._toggles.get(nav)
            if btn is not None:
                btn.toggled.connect(
                    lambda checked, f=nav: self._on_nav_toggled(f, checked)
                )

    def _on_nav_toggled(self, feature: str, checked: bool) -> None:
        if checked:
            self.set_toggle_silent(feature, False)

    def set_xover_active(self, active: bool) -> None:
        """Light the Xover button's accent (amber) when the crossover is active."""
        btn = self._toggles.get("xover")
        if btn is None:
            return
        btn.setProperty("xover_active", active)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def set_comp_active(self, active: bool) -> None:
        """Light the Comp button's accent (teal) when the compressor is active."""
        btn = self._toggles.get("comp")
        if btn is None:
            return
        btn.setProperty("comp_active", active)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def set_delay_active(self, active: bool) -> None:
        """Light the Delay button's accent (blue) when the output delay is non-zero."""
        btn = self._toggles.get("delay")
        if btn is None:
            return
        btn.setProperty("delay_active", active)
        btn.style().unpolish(btn)
        btn.style().polish(btn)


def apply_input_strip_state(
    strip: InputChannelStrip,
    channel: int,
    ch_state: InputChannelState,
    master_name: str,
    is_slave: bool,
) -> None:
    """Render an ``InputChannelState`` onto an input strip.

    Single source of truth shared by ``HomeView`` (4 strips at once)
    and ``DetailView`` (1 strip + nav). Sets the title, silent
    control values, the gate-active indicator and the link
    indicator. Mute/phase/gate toggles are set silently to avoid
    feedback loops when called during a state refresh.

    Args:
        strip: The widget to update.
        channel: Channel index 0–3; used to fall back to the
            default ``CHANNEL_NAMES`` entry when the channel has no
            user-set name.
        ch_state: The ``InputChannelState`` to mirror.
        master_name: Display name of the master if this channel is a
            slave; empty otherwise.
        is_slave: True if the channel is a slave in a link group.
    """
    strip.set_title(ch_state.name or CHANNEL_NAMES[channel])
    strip.set_gain_silent(ch_state.gain_raw)
    strip.set_toggle_silent("mute", ch_state.muted)
    strip.set_toggle_silent("phase", ch_state.phase_inverted)
    strip.set_toggle_silent("gate", False)
    strip.set_gate_active(ch_state.gate.threshold > 0)
    strip.set_linked_slave(is_slave, master_name)


def apply_output_strip_state(
    strip: OutputChannelStrip,
    channel: int,
    ch_state: OutputChannelState,
    master_name: str,
    is_slave: bool,
) -> None:
    """Render an ``OutputChannelState`` onto an output strip.

    Sister of ``apply_input_strip_state`` for output channels. The
    per-feature active indicators (PEQ / Xover / Comp / Delay) are
    derived from the state object's computed properties so they
    stay consistent with the values the feature panels show.

    Args:
        strip: The widget to update.
        channel: Channel index 4–7; used to fall back to the
            default ``CHANNEL_NAMES`` entry when the channel has no
            user-set name.
        ch_state: The ``OutputChannelState`` to mirror.
        master_name: Display name of the master if this channel is a
            slave; empty otherwise.
        is_slave: True if the channel is a slave in a link group.
    """
    strip.set_title(ch_state.name or CHANNEL_NAMES[channel])
    strip.set_gain_silent(ch_state.gain_raw)
    strip.set_toggle_silent("mute", ch_state.muted)
    strip.set_toggle_silent("phase", ch_state.phase_inverted)
    for f in ("xover", "peq", "comp", "delay"):
        strip.set_toggle_silent(f, False)
    strip.set_peq_active(ch_state.peq_active)
    strip.set_xover_active(ch_state.xover_active)
    strip.set_comp_active(ch_state.comp_active)
    strip.set_delay_active(ch_state.delay_active)
    strip.set_linked_slave(is_slave, master_name)
