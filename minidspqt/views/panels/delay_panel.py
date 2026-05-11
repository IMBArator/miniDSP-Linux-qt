"""Delay settings panel for output channels.

A 4-row overview graph at the top shows the delay of every output so the
user sees relative time-alignment at a glance.  A single edit knob below
the graph drives the *currently displayed* output's delay — to edit a
different output the user navigates to that channel's strip and the same
panel re-targets via :meth:`set_active_channel`.

This panel is mounted once in the detail view's stacked widget and reused
across all four output channels; the state-pushing methods below are how
the detail view keeps it in sync without re-emitting signals.

Protocol notes
--------------
The device delay command (opcode ``0x38``) takes a single ``uint16`` LE
sample count per output channel, range 0–32 640 (0–680 ms @ 48 kHz).
Typed input on the knob accepts ``"12.5 ms"`` or ``"601 samples"`` (also
"sample"/"sa") so power users can dial in exact sample counts.
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

from ...widgets import DelayGraph, ParamKnob
from ._slave_lock import apply_link_state, install_link_banner

_SAMPLES_MAX = 32640
_SAMPLES_PER_MS = 48.0


def _fmt_delay(raw: int) -> str:
    return f"{raw / _SAMPLES_PER_MS:.3f} ms"


def _parse_delay(text: str) -> int:
    t = text.lower().strip()
    # Sample-mode input first — checked before ms because "sample" doesn't
    # contain "ms".  Longest suffix wins to avoid partial-match surprises.
    for suffix in ("samples", "sample", "sa"):
        if t.endswith(suffix):
            n = int(float(t[: -len(suffix)].strip()))
            return max(0, min(_SAMPLES_MAX, n))
    # Default: milliseconds (with or without explicit "ms" suffix).
    ms = float(t.removesuffix("ms").strip())
    return max(0, min(_SAMPLES_MAX, round(ms * _SAMPLES_PER_MS)))


class DelayPanel(QWidget):
    """Delay overview graph + single-channel edit knob.

    Signals
    -------
    delay_changed(int)
        Emitted with the raw samples value whenever the active row's
        knob changes.  The detail view knows which absolute channel is
        currently displayed and re-emits with the channel index.
    """

    delay_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._samples: list[int] = [0, 0, 0, 0]
        self._active_idx: int = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._link_banner = install_link_banner(root)

        title = QLabel("Delay Settings")
        title.setObjectName("panelTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(title)

        self._graph = DelayGraph()
        self._graph.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self._graph, stretch=1)

        knob_col = QVBoxLayout()
        knob_col.setSpacing(2)
        knob_col.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        self._active_label = QLabel("Out1")
        self._active_label.setObjectName("paramLabel")
        self._active_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        knob_col.addWidget(self._active_label)

        self._knob = ParamKnob(
            minimum=0,
            maximum=_SAMPLES_MAX,
            default=0,
            formatter=_fmt_delay,
            parser=_parse_delay,
        )
        self._knob.valueChanged.connect(self._on_knob_changed)
        knob_col.addWidget(self._knob)

        knob_row = QHBoxLayout()
        knob_row.addStretch(1)
        knob_row.addLayout(knob_col)
        knob_row.addStretch(1)
        root.addLayout(knob_row)

    # ---- public state-push API ---------------------------------------- #

    def set_channel_names(self, names: list[str]) -> None:
        """Update the four row labels on the graph (e.g. ``["Out 1", ...]``)."""
        if len(names) != 4:
            return
        self._graph.set_channel_names(list(names))

    def set_delays_silently(self, samples: list[int]) -> None:
        """Mirror all four delay values into the graph + active knob.

        Used on initial render and on master→slave fan-out refreshes; no
        ``delay_changed`` signal is emitted.
        """
        if len(samples) != 4:
            return
        self._samples = [max(0, min(_SAMPLES_MAX, int(s))) for s in samples]
        self._graph.set_delays(self._samples)
        self._knob.setValueSilently(self._samples[self._active_idx])

    def set_active_channel(
        self, output_idx: int, name: str, samples: int
    ) -> None:
        """Switch which row is the editable one and refresh its label/knob."""
        idx = max(0, min(3, int(output_idx)))
        self._active_idx = idx
        self._samples[idx] = max(0, min(_SAMPLES_MAX, int(samples)))
        self._graph.set_delays(self._samples)
        self._graph.set_active_row(idx)
        self._active_label.setText(name)
        self._knob.setValueSilently(self._samples[idx])

    def set_linked_slave(self, is_slave: bool, master_name: str = "") -> None:
        """Lock the knob (graph stays visible) when the active row is a slave."""
        apply_link_state(self._link_banner, is_slave, master_name, [self._knob])

    # ---- knob handler ------------------------------------------------- #

    def _on_knob_changed(self, value: int) -> None:
        # Mirror the new value into the graph immediately so the bar
        # follows the drag without waiting for the model round-trip.
        self._samples[self._active_idx] = value
        self._graph.set_delays(self._samples)
        self.delay_changed.emit(value)
