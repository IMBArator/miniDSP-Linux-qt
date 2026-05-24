"""Gate settings panel for input channels.

Provides four :class:`ParamKnob` widgets for the gate parameters
(Threshold, Attack, Hold, Release) and emits all four values together
whenever any single knob changes, because the device gate command (0x3E)
sends all parameters atomically.

Protocol raw ranges and conversions:

============  ==========  ==================  ===========================
Parameter     Raw range   Display             Formula
============  ==========  ==================  ===========================
Threshold     1 -- 180    -89.5 .. 0.0 dB     dB = raw * 0.5 - 90.0
Attack        0 -- 998    1 .. 999 ms          ms = raw + 1
Hold          9 -- 998    10 .. 999 ms         ms = raw + 1
Release       0 -- 2999   1 .. 3000 ms         ms = raw + 1
============  ==========  ==================  ===========================
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from minidsp.protocol import gate_threshold_to_db, gate_time_to_ms

from ...widgets import GateGraph, ParamKnob
from ._slave_lock import apply_link_state, install_link_banner
from ...defaults import default_gate_state


def _fmt_threshold(raw: int) -> str:
    return f"{gate_threshold_to_db(raw):.1f} dB"


def _parse_threshold(text: str) -> int:
    db = float(text.lower().removesuffix("db").strip())
    raw = round((db + 90.0) * 2)
    return max(0, min(180, raw))


def _fmt_time(raw: int) -> str:
    return f"{gate_time_to_ms(raw)} ms"


def _parse_time_generic(text: str, raw_min: int, raw_max: int) -> int:
    ms = float(text.lower().removesuffix("ms").strip())
    raw = round(ms) - 1
    return max(raw_min, min(raw_max, raw))


def _parse_attack(text: str) -> int:
    return _parse_time_generic(text, 0, 998)


def _parse_hold(text: str) -> int:
    return _parse_time_generic(text, 9, 998)


def _parse_release(text: str) -> int:
    return _parse_time_generic(text, 0, 2999)


class GatePanel(QWidget):
    """Gate parameter controls for one input channel.

    Four ``ParamKnob`` widgets (threshold, attack, hold, release)
    feed a shared transfer-function graph. All four raw values reach
    the device atomically via the ``gate_params_changed`` signal —
    the caller forwards to ``DeviceThread.request_gate``.

    Signals:
        gate_params_changed (int, int, int, int): ``(attack, release,
            hold, threshold)`` raw values, emitted on any knob change.
        reset_requested (): Emitted after the user confirms the
            "Reset" header button. The caller (typically the detail
            view) decides what defaults to apply.
    """

    gate_params_changed = Signal(int, int, int, int)
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the panel seeded with the F00 factory gate values.

        Args:
            parent: Qt parent widget.
        """
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._link_banner = install_link_banner(root)

        header = QHBoxLayout()
        title = QLabel("Gate Settings")
        title.setObjectName("panelTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(title)
        header.addStretch()
        self._reset_btn = QPushButton("Reset")
        self._reset_btn.setObjectName("resetButton")
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        header.addWidget(self._reset_btn)
        root.addLayout(header)

        self._graph = GateGraph()
        self._graph.setMinimumHeight(120)
        self._graph.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self._graph, stretch=1)

        knobs_row = QHBoxLayout()
        knobs_row.setSpacing(24)

        factory_defaults = default_gate_state()

        self._threshold = self._make_knob(
            "Threshold",
            minimum=0,
            maximum=180,
            default=factory_defaults[3],
            formatter=_fmt_threshold,
            parser=_parse_threshold,
        )
        self._attack = self._make_knob(
            "Attack",
            minimum=0,
            maximum=998,
            default=factory_defaults[0],
            formatter=_fmt_time,
            parser=_parse_attack,
        )
        self._hold = self._make_knob(
            "Hold",
            minimum=9,
            maximum=998,
            default=factory_defaults[2],
            formatter=_fmt_time,
            parser=_parse_hold,
        )
        self._release = self._make_knob(
            "Release",
            minimum=0,
            maximum=2999,
            default=factory_defaults[1],
            formatter=_fmt_time,
            parser=_parse_release,
        )

        for col in (self._threshold, self._attack, self._hold, self._release):
            knobs_row.addStretch(1)
            knobs_row.addLayout(col)
        knobs_row.addStretch(1)

        root.addLayout(knobs_row)

    def _make_knob(
        self,
        label: str,
        minimum: int,
        maximum: int,
        default: int,
        formatter,
        parser,
    ) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(2)
        col.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        lbl = QLabel(label)
        lbl.setObjectName("paramLabel")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(lbl)

        knob = ParamKnob(
            minimum=minimum,
            maximum=maximum,
            default=default,
            formatter=formatter,
            parser=parser,
        )
        knob.valueChanged.connect(self._on_any_knob)
        if label == "Threshold":
            knob.valueChanged.connect(self._graph.set_threshold)
        col.addWidget(knob)

        setattr(self, f"_knob_{label.lower()}", knob)
        return col

    def _on_reset_clicked(self) -> None:
        if (
            QMessageBox.question(
                self,
                "Reset Gate",
                "Reset Gate to factory defaults for this channel?",
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.reset_requested.emit()

    def _on_any_knob(self) -> None:
        self.gate_params_changed.emit(
            self._knob_attack.value(),
            self._knob_release.value(),
            self._knob_hold.value(),
            self._knob_threshold.value(),
        )

    def reset_to_defaults(self) -> None:
        """Reset all knobs to F00 factory defaults without emitting signals."""
        self.set_params_silently(*default_gate_state())

    def set_params_silently(
        self, attack: int, release: int, hold: int, threshold: int
    ) -> None:
        """Update all four knobs from device-driven state.

        Args:
            attack: Raw attack value.
            release: Raw release value.
            hold: Raw hold value.
            threshold: Raw threshold value.

        Does not emit ``gate_params_changed`` — used when the device
        thread has just delivered fresh config so the UI mirrors it
        without echoing right back.
        """
        self._knob_threshold.setValueSilently(threshold)
        self._knob_attack.setValueSilently(attack)
        self._knob_hold.setValueSilently(hold)
        self._knob_release.setValueSilently(release)
        self._graph.set_threshold(threshold)

    def set_linked_slave(self, is_slave: bool, master_name: str = "") -> None:
        """Lock the panel when showing a slave channel.

        Slaves are read-only mirrors of their master; the knobs stay
        visible so the user can see the inherited values but cannot
        change them. A banner above the panel explains the lock.

        Args:
            is_slave: True if the displayed channel is a slave in a
                link group; disables knobs and shows the banner.
            master_name: Display name of the master channel, used
                inside the banner text. Empty falls back to a
                generic "Linked — read-only" label.
        """
        apply_link_state(
            self._link_banner,
            is_slave,
            master_name,
            [
                self._knob_threshold,
                self._knob_attack,
                self._knob_hold,
                self._knob_release,
                self._reset_btn,
            ],
        )
