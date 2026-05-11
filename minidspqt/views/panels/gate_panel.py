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
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from minidsp.protocol import gate_threshold_to_db, gate_time_to_ms

from ...widgets import GateGraph, ParamKnob
from ._slave_lock import apply_link_state, install_link_banner


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

    Signals
    -------
    gate_params_changed(int, int, int, int)
        Emitted with ``(attack, release, hold, threshold)`` raw values
        whenever any knob changes.
    """

    gate_params_changed = Signal(int, int, int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._link_banner = install_link_banner(root)

        title = QLabel("Gate Settings")
        title.setObjectName("panelTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(title)

        self._graph = GateGraph()
        self._graph.setMinimumHeight(120)
        self._graph.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self._graph, stretch=1)

        knobs_row = QHBoxLayout()
        knobs_row.setSpacing(24)

        self._threshold = self._make_knob(
            "Threshold",
            minimum=0,
            maximum=180,
            default=0,
            formatter=_fmt_threshold,
            parser=_parse_threshold,
        )
        self._attack = self._make_knob(
            "Attack",
            minimum=0,
            maximum=998,
            default=0,
            formatter=_fmt_time,
            parser=_parse_attack,
        )
        self._hold = self._make_knob(
            "Hold",
            minimum=9,
            maximum=998,
            default=9,
            formatter=_fmt_time,
            parser=_parse_hold,
        )
        self._release = self._make_knob(
            "Release",
            minimum=0,
            maximum=2999,
            default=0,
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

    def _on_any_knob(self) -> None:
        self.gate_params_changed.emit(
            self._knob_attack.value(),
            self._knob_release.value(),
            self._knob_hold.value(),
            self._knob_threshold.value(),
        )

    def set_params_silently(
        self, attack: int, release: int, hold: int, threshold: int
    ) -> None:
        """Update all knobs without emitting signals."""
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
        """
        apply_link_state(
            self._link_banner,
            is_slave,
            master_name,
            [self._knob_threshold, self._knob_attack, self._knob_hold, self._knob_release],
        )
