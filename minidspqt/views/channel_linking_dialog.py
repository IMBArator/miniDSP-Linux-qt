"""ChannelLinkingDialog — popup to edit input/output channel link groups.

The dialog renders two triangular radio-button matrices (one for the four
inputs, one for the four outputs).  Each row represents a channel; the
selected column tells us which channel this row is linked to.  The
diagonal (row N, column N) means "standalone — its own master".  The
master of any group is implicitly the lowest-indexed channel in it,
which matches the device's wire-level convention (master holds the
OR-bitmask, slaves hold 0x00).

Why radio buttons (not checkboxes)?  A channel can only belong to one
group at a time, and the master is uniquely determined.  A row of radios
naturally enforces both invariants: pick exactly one master target per
channel.  Triangular layout further enforces "master = lowest-indexed",
because row N can only point to columns 0..N.

The dialog is non-modal and stays open after Apply (per user request,
useful for trial-and-error).  Apply emits ``applyRequested`` with the
new 8-entry link_flags list (inputs 0-3, then outputs 4-7) for the
caller to push to the device.  After the device round-trip completes,
the caller should invoke :meth:`refresh` to re-sync the matrices with
the authoritative device state — that way silent rejections on the
device side snap the UI back instead of leaving stale optimistic state.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from minidsp.protocol import INPUT_CHANNEL_NAMES, OUTPUT_CHANNEL_NAMES

from ..model import DeviceState

# Fallback channel labels come from the protocol library so we share
# one source of truth with the rest of the codebase.  They are only
# used when the live state lacks a name (e.g. an empty DeviceState in
# tests); normally the dialog displays the user-editable names from
# state.inputs[i].name / state.outputs[i].name, refreshed on every
# refresh() call.


def link_flags_from_targets(targets: list[int]) -> list[int]:
    """Convert a 4-element radio-target list into 4 device-ready link_flags.

    ``targets[i]`` is the within-group column the user picked for row
    ``i``, with ``0 <= targets[i] <= i`` (the triangular UI guarantees
    this).  Resolution: walk ``targets`` until a fixed point — that's
    the group's master.  Cycles are impossible because targets monotonically
    decrease.

    Returns 4 bitmasks following the protocol convention:

    - **Standalone:** own bit only (e.g. ``targets=[0,1,2,3]`` → ``[0x01, 0x02, 0x04, 0x08]``)
    - **Master:**     OR of all member bits (e.g. ``targets=[0,0,0,0]`` → ``[0x0F, 0, 0, 0]``)
    - **Slave:**      ``0x00``
    """
    # Resolve each row's master via path compression.
    master_of: list[int] = [0, 0, 0, 0]
    for i in range(4):
        m = i
        while targets[m] != m:
            m = targets[m]
        master_of[i] = m

    # Group members under each master.
    groups: dict[int, list[int]] = {}
    for ch, master in enumerate(master_of):
        groups.setdefault(master, []).append(ch)

    flags = [0, 0, 0, 0]
    for master, members in groups.items():
        if len(members) == 1:
            # Standalone: master bit set, no other members.
            flags[master] = 1 << master
        else:
            # Master gets OR of all member bits; slaves get 0x00.
            flags[master] = sum(1 << m for m in members)
            # (slaves are already 0)
    return flags


def _initial_target_for(role: str, master: int | None, ch_in_group: int) -> int:
    """Pick the radio column that mirrors a channel's current link role."""
    if role == "slave" and master is not None:
        # ``master`` is a unified channel index; convert to within-group.
        return master % 4
    # Standalone or master both point to themselves in the radio model.
    return ch_in_group


class ChannelLinkingDialog(QDialog):
    """Edit input/output channel link groups via triangular radio matrices."""

    # Emitted when the user clicks Apply.  Argument is an 8-entry
    # link_flags list: inputs 0-3 followed by outputs 4-7.
    applyRequested = Signal(list)

    def __init__(self, parent: QWidget | None, state: DeviceState) -> None:
        super().__init__(parent)
        self.setWindowTitle("Channel linking")
        self.setMinimumWidth(380)

        # Per-row radio buttons + button groups for inputs and outputs.
        # Indexed [row][col]; col only populated for col <= row.
        self._input_radios: list[list[QRadioButton]] = [[] for _ in range(4)]
        self._output_radios: list[list[QRadioButton]] = [[] for _ in range(4)]
        self._input_groups: list[QButtonGroup] = []
        self._output_groups: list[QButtonGroup] = []
        # Header / row labels — kept around so refresh() can rewrite
        # them when the user renames a channel via the home view.
        self._input_headers: list[QLabel] = []
        self._input_row_labels: list[QLabel] = []
        self._output_headers: list[QLabel] = []
        self._output_row_labels: list[QLabel] = []
        # Per-channel status label that reads "InA: standalone" /
        # "InB: linked to InA" / "InA: master of InA, InB" — gives the
        # user a plain-English readback while they fiddle.
        self._input_status: list[QLabel] = []
        self._output_status: list[QLabel] = []
        # Cached live names, set by refresh() and used by every helper
        # that needs to display a channel.
        self._input_names: tuple[str, ...] = INPUT_CHANNEL_NAMES
        self._output_names: tuple[str, ...] = OUTPUT_CHANNEL_NAMES

        layout = QVBoxLayout(self)
        layout.addWidget(
            self._build_matrix_group(
                "Inputs",
                INPUT_CHANNEL_NAMES,
                self._input_radios,
                self._input_groups,
                self._input_status,
                self._input_headers,
                self._input_row_labels,
            )
        )
        layout.addWidget(
            self._build_matrix_group(
                "Outputs",
                OUTPUT_CHANNEL_NAMES,
                self._output_radios,
                self._output_groups,
                self._output_status,
                self._output_headers,
                self._output_row_labels,
            )
        )

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Close
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(
            self._on_apply_clicked
        )
        self._buttons.rejected.connect(self.reject)
        # Close button on the right side fires `rejected`; wire its `clicked`
        # too so it works when the user closes via Esc as well.
        self._buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(
            self.reject
        )
        layout.addWidget(self._buttons)

        self.refresh(state)

    # ----------------------------------------------------------------- #
    # Public API
    # ----------------------------------------------------------------- #

    def refresh(self, state: DeviceState) -> None:
        """Re-check the radios against ``state`` and update status labels.

        Used both at construction and after an Apply round-trip, so the
        dialog mirrors whatever the device just reported — including any
        channel renames that happened in the meantime.
        """
        # Pull the live, user-editable names from state.  Fall back to
        # the canonical labels if a name is empty (defensive — the model
        # always populates them, but tests sometimes don't).
        self._input_names = tuple(
            (state.inputs[i].name or INPUT_CHANNEL_NAMES[i])
            if i < len(state.inputs)
            else INPUT_CHANNEL_NAMES[i]
            for i in range(4)
        )
        self._output_names = tuple(
            (state.outputs[i].name or OUTPUT_CHANNEL_NAMES[i])
            if i < len(state.outputs)
            else OUTPUT_CHANNEL_NAMES[i]
            for i in range(4)
        )
        self._apply_names_to_widgets(
            self._input_names,
            self._input_headers,
            self._input_row_labels,
            self._input_radios,
        )
        self._apply_names_to_widgets(
            self._output_names,
            self._output_headers,
            self._output_row_labels,
            self._output_radios,
        )

        info = state.link_info
        for ch in range(4):
            target = _initial_target_for(info[ch]["role"], info[ch]["master"], ch)
            self._select_row(self._input_radios, ch, target)
        for i in range(4):
            ch = 4 + i
            target = _initial_target_for(info[ch]["role"], info[ch]["master"], i)
            self._select_row(self._output_radios, i, target)
        self._update_status_labels(
            self._input_names,
            self._input_radios,
            self._input_status,
        )
        self._update_status_labels(
            self._output_names,
            self._output_radios,
            self._output_status,
        )
        self._update_enabled_state(self._input_radios)
        self._update_enabled_state(self._output_radios)

    def current_link_flags(self) -> list[int]:
        """Return the 8-entry link_flags list reflecting the current radios."""
        in_targets = self._row_targets(self._input_radios)
        out_targets = self._row_targets(self._output_radios)
        return link_flags_from_targets(in_targets) + link_flags_from_targets(
            out_targets
        )

    # ----------------------------------------------------------------- #
    # Build helpers
    # ----------------------------------------------------------------- #

    def _build_matrix_group(
        self,
        title: str,
        names: tuple[str, ...],
        radios_out: list[list[QRadioButton]],
        groups_out: list[QButtonGroup],
        status_labels_out: list[QLabel],
        headers_out: list[QLabel],
        row_labels_out: list[QLabel],
    ) -> QGroupBox:
        box = QGroupBox(title)
        outer = QVBoxLayout(box)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        # Column headers (row 0): leave column 0 blank for the row labels.
        for col, name in enumerate(names):
            header = QLabel(name)
            header.setObjectName("linkingHeaderLabel")
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(header, 0, col + 1)
            headers_out.append(header)

        # Rows 1..4: row label in col 0, then radios in cols 1..(row+1).
        for row in range(4):
            row_label = QLabel(names[row])
            row_label.setObjectName("linkingHeaderLabel")
            grid.addWidget(row_label, row + 1, 0)
            row_labels_out.append(row_label)
            group = QButtonGroup(self)
            group.setExclusive(True)
            for col in range(row + 1):
                rb = QRadioButton()
                # Tooltip text gets rewritten in refresh() with live names.
                rb.setToolTip(f"Link {names[row]} to {names[col]}")
                grid.addWidget(rb, row + 1, col + 1, Qt.AlignmentFlag.AlignCenter)
                group.addButton(rb, col)
                radios_out[row].append(rb)
                rb.toggled.connect(self._on_radio_toggled)
            groups_out.append(group)

        outer.addLayout(grid)

        # Per-row status labels under the matrix.  Sizing is in QSS;
        # colour is left to Qt's WindowText palette role so it stays
        # readable in both light and dark themes.
        for row in range(4):
            lbl = QLabel("")
            lbl.setObjectName("linkingStatusLabel")
            outer.addWidget(lbl)
            status_labels_out.append(lbl)

        return box

    # ----------------------------------------------------------------- #
    # Internal state helpers
    # ----------------------------------------------------------------- #

    def _select_row(self, radios: list[list[QRadioButton]], row: int, col: int) -> None:
        # Clamp col to a valid column for this row (defensive — should
        # always already be true).
        col = max(0, min(row, col))
        rb = radios[row][col]
        # Block signals while we set the initial / refreshed state so we
        # don't fire _on_radio_toggled and re-recompute statuses 4× per
        # refresh call.
        rb.blockSignals(True)
        rb.setChecked(True)
        rb.blockSignals(False)

    def _apply_names_to_widgets(
        self,
        names: tuple[str, ...],
        headers: list[QLabel],
        row_labels: list[QLabel],
        radios: list[list[QRadioButton]],
    ) -> None:
        """Rewrite header / row-label / radio-tooltip text from ``names``.

        Called from refresh() so the dialog always shows the user's
        current channel names rather than only the canonical fallback
        labels captured at construction time.
        """
        for col, name in enumerate(names):
            headers[col].setText(name)
        for row, name in enumerate(names):
            row_labels[row].setText(name)
        for row in range(4):
            for col, rb in enumerate(radios[row]):
                rb.setToolTip(f"Link {names[row]} to {names[col]}")

    def _update_enabled_state(self, radios: list[list[QRadioButton]]) -> None:
        """Disable radios that would create a forbidden link configuration.

        Two rules, in plain English:

        1. *A channel that is already a slave of someone cannot be
           selected as a target by another channel.*  No chains —
           A → B → C is not a valid encoding on this device, and even
           if we silently flattened it the user wouldn't see what they
           expect.
        2. *A channel that has slaves cannot itself become a slave.*
           Releasing slaves first is an explicit step, so the user
           always sees what they are about to dismantle.

        The diagonal (row R, column R) — meaning "standalone / I am my
        own master" — is always enabled.
        """
        targets = self._row_targets(radios)
        # A channel is currently a slave iff its row points away from
        # the diagonal.
        is_slave = [targets[i] != i for i in range(4)]
        # A channel has slaves iff some other row points to it.
        has_slaves = [
            any(j != i and targets[j] == i for j in range(4)) for i in range(4)
        ]
        for row in range(4):
            for col, rb in enumerate(radios[row]):
                if col == row:
                    rb.setEnabled(True)
                    continue
                forbidden = is_slave[col] or has_slaves[row]
                rb.setEnabled(not forbidden)

    def _row_targets(self, radios: list[list[QRadioButton]]) -> list[int]:
        targets: list[int] = []
        for row in range(4):
            chosen = row  # fallback (shouldn't happen — radios are exclusive)
            for col, rb in enumerate(radios[row]):
                if rb.isChecked():
                    chosen = col
                    break
            targets.append(chosen)
        return targets

    def _update_status_labels(
        self,
        names: tuple[str, ...],
        radios: list[list[QRadioButton]],
        labels: list[QLabel],
    ) -> None:
        targets = self._row_targets(radios)
        flags = link_flags_from_targets(targets)
        for ch in range(4):
            f = flags[ch]
            own_bit = 1 << ch
            if f == 0:
                # Slave — find which row points to ch as its master fixed point.
                master = ch
                while targets[master] != master:
                    master = targets[master]
                labels[ch].setText(f"{names[ch]}: linked to {names[master]}")
            elif f == own_bit:
                labels[ch].setText(f"{names[ch]}: standalone")
            else:
                members = [names[b] for b in range(4) if f & (1 << b)]
                labels[ch].setText(f"{names[ch]}: master of {', '.join(members)}")

    # ----------------------------------------------------------------- #
    # Signal handlers
    # ----------------------------------------------------------------- #

    def _on_radio_toggled(self, checked: bool) -> None:
        # We only care about the new selection in each row, so trigger
        # status refresh on `checked=True` events only (each toggle in
        # an exclusive group fires twice — old off, new on).
        if not checked:
            return
        self._update_status_labels(
            self._input_names,
            self._input_radios,
            self._input_status,
        )
        self._update_status_labels(
            self._output_names,
            self._output_radios,
            self._output_status,
        )
        # Re-evaluate which radios are clickable: forming a slave chain
        # or making a master into a slave should be disabled.
        self._update_enabled_state(self._input_radios)
        self._update_enabled_state(self._output_radios)

    def _on_apply_clicked(self) -> None:
        self.applyRequested.emit(self.current_link_flags())
