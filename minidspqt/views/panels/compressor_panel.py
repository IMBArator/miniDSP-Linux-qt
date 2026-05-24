"""Compressor settings panel for output channels.

Provides four :class:`ParamKnob` widgets and one :class:`QComboBox` for
the compressor parameters (Threshold, Ratio, Knee, Attack, Release).
All five values are emitted together whenever any control changes,
because the device compressor command (0x30) sends all parameters
atomically.

Protocol raw ranges and conversions:

============  ==========  ====================  ==========================
Parameter     Raw range   Display               Formula
============  ==========  ====================  ==========================
Threshold     0 -- 220    -90.0 .. +20.0 dB     dB = raw / 2 - 90.0
Ratio         0 -- 15     1:1.0 .. Limit        COMP_RATIO_NAMES[raw]
Knee          0 -- 12     0 .. 12 dB            (direct)
Attack        0 -- 998    1 .. 999 ms           ms = raw + 1
Release       9 -- 2999   10 .. 3000 ms         ms = raw + 1
============  ==========  ====================  ==========================
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from minidsp.protocol import (
    COMP_RATIO_NAMES,
    comp_attack_to_ms,
    comp_release_to_ms,
    comp_threshold_to_db,
)

from ...widgets import CompressorGraph, ParamKnob
from ._slave_lock import apply_link_state, install_link_banner
from ...defaults import default_compressor_state


def _fmt_threshold(raw: int) -> str:
    return f"{comp_threshold_to_db(raw):+.1f} dB"


def _parse_threshold(text: str) -> int:
    db = float(text.lower().removesuffix("db").strip())
    raw = round((db + 90.0) * 2)
    return max(0, min(220, raw))


def _fmt_knee(raw: int) -> str:
    return f"{raw} dB"


def _parse_knee(text: str) -> int:
    db = int(round(float(text.lower().removesuffix("db").strip())))
    return max(0, min(12, db))


def _fmt_attack(raw: int) -> str:
    return f"{comp_attack_to_ms(raw)} ms"


def _parse_attack(text: str) -> int:
    ms = float(text.lower().removesuffix("ms").strip())
    return max(0, min(998, round(ms) - 1))


def _fmt_release(raw: int) -> str:
    return f"{comp_release_to_ms(raw)} ms"


def _parse_release(text: str) -> int:
    ms = float(text.lower().removesuffix("ms").strip())
    return max(9, min(2999, round(ms) - 1))


class CompressorPanel(QWidget):
    """Compressor parameter controls for one output channel.

    Four ``ParamKnob`` widgets (threshold, knee, attack, release) plus
    a 16-entry ratio combo feed the shared ``CompressorGraph``. All
    five raw values are sent atomically via
    ``compressor_params_changed`` — the caller forwards to
    ``DeviceThread.request_compressor``.

    Signals:
        compressor_params_changed (int, int, int, int, int):
            ``(ratio, knee, attack, release, threshold)`` raw values
            emitted on any control change.
        reset_requested (): Emitted after the user confirms the
            "Reset" header button.
    """

    compressor_params_changed = Signal(int, int, int, int, int)
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the panel seeded with F00 factory compressor values.

        Args:
            parent: Qt parent widget.
        """
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._link_banner = install_link_banner(root)

        header = QHBoxLayout()
        title = QLabel("Compressor Settings")
        title.setObjectName("panelTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(title)
        header.addStretch()
        self._reset_btn = QPushButton("Reset")
        self._reset_btn.setObjectName("resetButton")
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        header.addWidget(self._reset_btn)
        root.addLayout(header)

        self._graph = CompressorGraph()
        self._graph.setMinimumHeight(120)
        self._graph.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self._graph, stretch=1)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(24)

        factory_defaults = default_compressor_state()

        self._knob_threshold = ParamKnob(
            minimum=0,
            maximum=220,
            default=factory_defaults[4],
            formatter=_fmt_threshold,
            parser=_parse_threshold,
        )
        self._ratio_combo = QComboBox()
        for raw in range(16):
            self._ratio_combo.addItem(COMP_RATIO_NAMES[raw])
        self._knob_knee = ParamKnob(
            minimum=0,
            maximum=12,
            default=factory_defaults[1],
            formatter=_fmt_knee,
            parser=_parse_knee,
        )
        self._knob_attack = ParamKnob(
            minimum=0,
            maximum=998,
            default=factory_defaults[2],
            formatter=_fmt_attack,
            parser=_parse_attack,
        )
        self._knob_release = ParamKnob(
            minimum=9,
            maximum=2999,
            default=factory_defaults[3],
            formatter=_fmt_release,
            parser=_parse_release,
        )

        controls_row.addStretch(1)
        controls_row.addLayout(self._make_column("Threshold", self._knob_threshold))
        controls_row.addStretch(1)
        controls_row.addLayout(self._make_column("Ratio", self._ratio_combo))
        controls_row.addStretch(1)
        controls_row.addLayout(self._make_column("Knee", self._knob_knee))
        controls_row.addStretch(1)
        controls_row.addLayout(self._make_column("Attack", self._knob_attack))
        controls_row.addStretch(1)
        controls_row.addLayout(self._make_column("Release", self._knob_release))
        controls_row.addStretch(1)

        root.addLayout(controls_row)

        # Wire change notifications. The combo emits currentIndexChanged
        # both when the user clicks and when setCurrentIndex runs — the
        # silent setter blocks signals so refresh paths don't re-emit.
        for knob in (
            self._knob_threshold,
            self._knob_knee,
            self._knob_attack,
            self._knob_release,
        ):
            knob.valueChanged.connect(self._on_any_change)
        self._ratio_combo.currentIndexChanged.connect(self._on_any_change)

        self._sync_graph()

    def _make_column(self, label: str, widget: QWidget) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(2)
        col.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        lbl = QLabel(label)
        lbl.setObjectName("paramLabel")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(lbl)
        col.addWidget(widget, alignment=Qt.AlignmentFlag.AlignHCenter)
        return col

    def _on_reset_clicked(self) -> None:
        if (
            QMessageBox.question(
                self,
                "Reset Compressor",
                "Reset Compressor to factory defaults for this channel?",
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.reset_requested.emit()

    def _sync_graph(self) -> None:
        self._graph.set_params(
            self._knob_threshold.value(),
            self._ratio_combo.currentIndex(),
            self._knob_knee.value(),
        )

    def _on_any_change(self, *_args) -> None:
        self._sync_graph()
        self.compressor_params_changed.emit(
            self._ratio_combo.currentIndex(),
            self._knob_knee.value(),
            self._knob_attack.value(),
            self._knob_release.value(),
            self._knob_threshold.value(),
        )

    def reset_to_defaults(self) -> None:
        """Reset all controls to F00 factory defaults without emitting signals."""
        self.set_params_silently(*default_compressor_state())

    def set_params_silently(
        self,
        ratio: int,
        knee: int,
        attack: int,
        release: int,
        threshold: int,
    ) -> None:
        """Apply device-driven state without emitting ``compressor_params_changed``.

        Args:
            ratio: Raw ratio index (0–15); index 15 is the Limit
                setting.
            knee: Raw knee width in dB (0–12).
            attack: Raw attack value.
            release: Raw release value.
            threshold: Raw threshold value.

        Used when the device thread has just delivered fresh config
        so the UI mirrors it without echoing right back.
        """
        self._knob_threshold.setValueSilently(threshold)
        self._knob_knee.setValueSilently(knee)
        self._knob_attack.setValueSilently(attack)
        self._knob_release.setValueSilently(release)
        was = self._ratio_combo.blockSignals(True)
        self._ratio_combo.setCurrentIndex(max(0, min(15, int(ratio))))
        self._ratio_combo.blockSignals(was)
        self._sync_graph()

    def set_linked_slave(self, is_slave: bool, master_name: str = "") -> None:
        """Lock the panel when showing a slave channel.

        Args:
            is_slave: True if the displayed channel is a slave in a
                link group; disables every control and shows the
                banner.
            master_name: Display name of the master channel, used
                inside the banner text.
        """
        apply_link_state(
            self._link_banner,
            is_slave,
            master_name,
            [
                self._knob_threshold,
                self._ratio_combo,
                self._knob_knee,
                self._knob_attack,
                self._knob_release,
                self._reset_btn,
            ],
        )
