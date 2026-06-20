"""Shared "show other outputs" overlay controls for output feature panels.

Both the PEQ and the Xover panel host the same :class:`FreqResponseGraph` and
are handed the same sibling-output data, so the overlay checkboxes and their
refresh logic live here and are composed by each panel — exactly like the
slave-lock helpers in :mod:`._slave_lock`, this keeps the two panels DRY.

A panel inserts the controls into its header row via
:func:`install_overlay_controls`, then feeds sibling data through
:meth:`OverlayControls.set_sources` on every channel render. Checking a box
overlays that output's full response (PEQ + crossover) on the graph in the
output's stable colour from ``theme.graph_overlay``.

The checkboxes are pure view toggles: they are never disabled by the
slave-lock path, so overlays remain usable even while viewing a linked
slave channel.
"""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QBoxLayout, QCheckBox, QLabel

from ...model import PEQBand
from ...theme import theme_manager
from ...widgets.freq_response_graph import CrossoverData, FreqResponseGraph

_NUM_OUTPUTS = 4

# A sibling source: (output_index, bands, channel_bypass, crossover, name).
OverlaySource = tuple[int, list[PEQBand], bool, CrossoverData, str]


class OverlayControls(QObject):
    """Owns the per-output overlay checkboxes and drives the graph's overlays.

    There is one checkbox per output channel (index 0–3). The checkbox for the
    currently-displayed output is hidden; the other three are labelled with the
    sibling outputs' names and tinted to match their overlay curve colour, so
    the row doubles as a colour legend.
    """

    def __init__(self, graph: FreqResponseGraph) -> None:
        """Build the four checkboxes (added to a layout later) and wire them.

        Args:
            graph: The :class:`FreqResponseGraph` whose overlays this
                controller updates. Also used as the QObject parent so the
                controller lives as long as the graph.
        """
        super().__init__(graph)
        self._graph = graph
        self._active_idx: int | None = None
        # output index -> (bands, channel_bypass, crossover, name)
        self._sources: dict[int, tuple[list[PEQBand], bool, CrossoverData, str]] = {}

        self._label = QLabel("Overlay")
        self._label.setObjectName("paramLabel")

        self._checks: list[QCheckBox] = []
        for _ in range(_NUM_OUTPUTS):
            cb = QCheckBox()
            cb.toggled.connect(self._refresh)
            self._checks.append(cb)

        self._retint()
        theme_manager.themeChanged.connect(self._retint)

    def add_to(self, layout: QBoxLayout) -> None:
        """Append the "Overlay" label and the four checkboxes to ``layout``.

        Call this at the point in the header where the controls should appear
        (e.g. just after the header's stretch) so they sit right-aligned with
        the panel's other header buttons.
        """
        layout.addWidget(self._label)
        for cb in self._checks:
            layout.addWidget(cb)

    def set_sources(self, active_idx: int, sources: list[OverlaySource]) -> None:
        """Update the sibling outputs available to overlay and refresh.

        Hides the active output's checkbox, shows and relabels the siblings,
        and clears all selections whenever the displayed channel changes
        (reset-on-switch). Re-running with the same ``active_idx`` keeps the
        current selections but refreshes their curve data, so a checked
        overlay tracks live edits to that sibling.

        Args:
            active_idx: Output index (0–3) currently displayed; its checkbox
                is hidden.
            sources: One :data:`OverlaySource` per *other* output.
        """
        switched = active_idx != self._active_idx
        self._active_idx = active_idx
        self._sources = {
            idx: (bands, bypass, xo, name) for idx, bands, bypass, xo, name in sources
        }

        for i, cb in enumerate(self._checks):
            if i == active_idx:
                cb.hide()
                continue
            src = self._sources.get(i)
            if src is None:
                cb.hide()
                continue
            cb.setText(src[3])
            cb.show()

        if switched:
            for cb in self._checks:
                blocked = cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(blocked)

        self._refresh()

    def _refresh(self) -> None:
        """Push the set of checked sibling curves to the graph."""
        overlays: list[tuple[int, list[PEQBand], bool, CrossoverData]] = []
        for i, cb in enumerate(self._checks):
            if not cb.isChecked():
                continue
            src = self._sources.get(i)
            if src is None:
                continue
            bands, bypass, xo, _name = src
            overlays.append((i, bands, bypass, xo))
        self._graph.set_overlays(overlays)

    def _retint(self) -> None:
        """Colour each checkbox's text to match its output's overlay curve."""
        palette = theme_manager.current.graph_overlay
        for i, cb in enumerate(self._checks):
            cb.setStyleSheet(f"QCheckBox {{ color: {palette[i].name()}; }}")


def install_overlay_controls(
    layout: QBoxLayout, graph: FreqResponseGraph
) -> OverlayControls:
    """Create overlay controls and append them to ``layout``.

    Convenience wrapper mirroring :func:`._slave_lock.install_link_banner`.

    Args:
        layout: The header layout to append the controls to (insert at the
            desired position, e.g. after the stretch for right alignment).
        graph: The graph whose overlays the controls drive.

    Returns:
        The :class:`OverlayControls` instance; keep a reference on the panel
        and feed it via :meth:`OverlayControls.set_sources`.
    """
    controls = OverlayControls(graph)
    controls.add_to(layout)
    return controls
