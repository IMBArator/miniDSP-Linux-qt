"""ChannelLinkingDialog — flag computation, initial state, and Apply emission."""

from __future__ import annotations

import pytest

from minidspqt.model import DeviceState
from minidspqt.views.channel_linking_dialog import (
    ChannelLinkingDialog,
    link_flags_from_targets,
)


# ------------------------------------------------------------------ #
# link_flags_from_targets — pure helper (no Qt needed)
# ------------------------------------------------------------------ #


class TestLinkFlagsFromTargets:
    def test_all_standalone(self):
        # Each row picks itself → standalone, each gets its own bit.
        assert link_flags_from_targets([0, 1, 2, 3]) == [0x01, 0x02, 0x04, 0x08]

    def test_pair_a_b(self):
        # B → A, C and D standalone → A is master of {A,B}.
        assert link_flags_from_targets([0, 0, 2, 3]) == [0x03, 0x00, 0x04, 0x08]

    def test_three_channel_group(self):
        # B → A, C → A, D standalone → A masters {A,B,C}, D alone.
        assert link_flags_from_targets([0, 0, 0, 3]) == [0x07, 0x00, 0x00, 0x08]

    def test_all_four_linked(self):
        # All point to A → A masters all four, slaves get 0x00.
        assert link_flags_from_targets([0, 0, 0, 0]) == [0x0F, 0x00, 0x00, 0x00]

    def test_two_disjoint_pairs(self):
        # B → A, D → B... wait — that's not disjoint. Let me pick: C→A, D→B.
        # A is master of {A, C} = bits 0 | 2 = 0x05
        # B is master of {B, D} = bits 1 | 3 = 0x0A
        assert link_flags_from_targets([0, 1, 0, 1]) == [0x05, 0x0A, 0x00, 0x00]

    def test_transitive_chain(self):
        # B → A, C → B, D → C — all resolve to A as the master via path
        # compression.  Crucial: the UI doesn't have to resolve transitivity
        # on the user's behalf; the helper does it at convert-time.
        assert link_flags_from_targets([0, 0, 1, 2]) == [0x0F, 0x00, 0x00, 0x00]

    def test_b_master_group(self):
        # A standalone, then C → B and D → B → B masters {B, C, D}.
        assert link_flags_from_targets([0, 1, 1, 1]) == [0x01, 0x0E, 0x00, 0x00]


# ------------------------------------------------------------------ #
# Dialog UI integration (needs qtbot)
# ------------------------------------------------------------------ #


def _state_with_link_flags(flags: list[int]) -> DeviceState:
    """Build a minimal DeviceState carrying the given link_flags list."""
    cfg = {
        "names": ["InA", "InB", "InC", "InD", "Out1", "Out2", "Out3", "Out4"],
        "gains": [0] * 8,
        "mutes": [False] * 8,
        "phases": [False] * 8,
        "link_flags": list(flags),
        "routings": [0x01, 0x02, 0x04, 0x08],
        "gates": [
            {"attack": 0, "release": 0, "hold": 0, "threshold": 0} for _ in range(4)
        ],
        "delays": [0] * 4,
        "crossovers": [
            {
                "hipass_freq": 0,
                "hipass_slope": 0,
                "lopass_freq": 0,
                "lopass_slope": 0,
            }
            for _ in range(4)
        ],
        "compressors": [
            {"ratio": 0, "knee": 0, "attack": 0, "release": 0, "threshold": 0}
            for _ in range(4)
        ],
        "peqs": [{"bands": [], "channel_bypass": False} for _ in range(4)],
        "active_slot": 1,
        "preset_names": [f"P{i:02d}" for i in range(30)],
    }
    return DeviceState.from_config(cfg)


@pytest.fixture
def dialog(qtbot):
    state = _state_with_link_flags([0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80])
    dlg = ChannelLinkingDialog(None, state)
    qtbot.addWidget(dlg)
    return dlg


class TestDialogInitialState:
    def test_all_standalone_each_row_diagonal_selected(self, dialog):
        # With all-standalone link flags, each row's own diagonal radio
        # should be the one checked.
        for row in range(4):
            for col, rb in enumerate(dialog._input_radios[row]):
                assert rb.isChecked() is (col == row), f"input row {row} col {col}"
            for col, rb in enumerate(dialog._output_radios[row]):
                assert rb.isChecked() is (col == row), f"output row {row} col {col}"

    def test_pre_existing_link_pre_checks_master_column(self, qtbot):
        # Inputs A+B linked (master InA, slave InB), C and D standalone.
        # → row InB should pre-check column 0 (InA).
        state = _state_with_link_flags([0x03, 0x00, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80])
        dlg = ChannelLinkingDialog(None, state)
        qtbot.addWidget(dlg)

        assert dlg._input_radios[0][0].isChecked()  # A → A (master)
        assert dlg._input_radios[1][0].isChecked()  # B → A (slave)
        assert not dlg._input_radios[1][1].isChecked()
        assert dlg._input_radios[2][2].isChecked()  # C standalone
        assert dlg._input_radios[3][3].isChecked()  # D standalone


class TestDialogApply:
    def test_apply_emits_current_flags(self, dialog, qtbot):
        # Click row InB column InA (row index 1, col index 0) to link B→A.
        dialog._input_radios[1][0].setChecked(True)

        with qtbot.waitSignal(dialog.applyRequested, timeout=500) as caught:
            dialog._on_apply_clicked()

        emitted = caught.args[0]
        # Inputs: A+B linked, C and D standalone → 0x03, 0x00, 0x04, 0x08
        # Outputs: unchanged from initial standalone-each → 0x01..0x08
        assert emitted == [0x03, 0x00, 0x04, 0x08, 0x01, 0x02, 0x04, 0x08]

    def test_unlink_pre_existing_pair(self, qtbot):
        # Start from A+B linked, click row InB column InB to unlink.
        state = _state_with_link_flags([0x03, 0x00, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80])
        dlg = ChannelLinkingDialog(None, state)
        qtbot.addWidget(dlg)

        dlg._input_radios[1][1].setChecked(True)

        with qtbot.waitSignal(dlg.applyRequested) as caught:
            dlg._on_apply_clicked()

        assert caught.args[0][:4] == [0x01, 0x02, 0x04, 0x08]


class TestDialogRefresh:
    def test_refresh_resets_radios_to_state(self, dialog, qtbot):
        # User clicks row InB column InA (linking B→A).
        dialog._input_radios[1][0].setChecked(True)
        assert dialog._input_radios[1][0].isChecked()

        # Now an external refresh re-syncs to a state with NO link.
        new_state = _state_with_link_flags(
            [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80]
        )
        dialog.refresh(new_state)

        # Row InB should snap back to its own diagonal.
        assert dialog._input_radios[1][1].isChecked()
        assert not dialog._input_radios[1][0].isChecked()


class TestStatusLabels:
    def test_status_labels_describe_groups(self, dialog):
        # Link InB → InA, InC → InA → InA masters {InA, InB, InC}, InD alone.
        dialog._input_radios[1][0].setChecked(True)
        dialog._input_radios[2][0].setChecked(True)
        # _on_radio_toggled fires synchronously and updates status labels.
        assert "master of InA, InB, InC" in dialog._input_status[0].text()
        assert "linked to InA" in dialog._input_status[1].text()
        assert "linked to InA" in dialog._input_status[2].text()
        assert "standalone" in dialog._input_status[3].text()


class TestEnabledStateRules:
    """The radios get disabled when picking them would create a forbidden
    configuration: chained slaves (slave-of-a-slave) or a master being
    demoted while it still has slaves attached."""

    def test_initial_all_enabled(self, dialog):
        for row in range(4):
            for rb in dialog._input_radios[row]:
                assert rb.isEnabled(), f"input row {row}"
            for rb in dialog._output_radios[row]:
                assert rb.isEnabled(), f"output row {row}"

    def test_slave_column_disabled_in_other_rows(self, dialog):
        # Link InB → InA → InB is now a slave.  Any other row should be
        # forbidden from picking column 1 (InB).
        dialog._input_radios[1][0].setChecked(True)

        assert not dialog._input_radios[2][1].isEnabled()
        assert not dialog._input_radios[3][1].isEnabled()
        # Diagonals always stay clickable so the user can drop back to
        # standalone.
        assert dialog._input_radios[2][2].isEnabled()
        assert dialog._input_radios[3][3].isEnabled()
        # InB → InA itself is the current selection and stays clickable
        # (you can re-click your own selection without harm).
        assert dialog._input_radios[1][0].isEnabled()

    def test_master_with_slaves_cannot_become_slave(self, dialog):
        # Link InD → InC → InC is master of {InC, InD}.  InC's row should
        # have its non-diagonal radios disabled — to free InC the user
        # must first release InD by clicking its diagonal.
        dialog._input_radios[3][2].setChecked(True)

        assert not dialog._input_radios[2][0].isEnabled()
        assert not dialog._input_radios[2][1].isEnabled()
        assert dialog._input_radios[2][2].isEnabled()  # diagonal stays free

    def test_releasing_slave_re_enables_master_row(self, dialog):
        # Link InD → InC, then release: InC's other radios should come back.
        dialog._input_radios[3][2].setChecked(True)
        assert not dialog._input_radios[2][0].isEnabled()  # disabled
        dialog._input_radios[3][3].setChecked(True)  # InD back to standalone
        assert dialog._input_radios[2][0].isEnabled()  # InC freed again

    def test_inputs_and_outputs_independent(self, dialog):
        # An input-side link should not disable any output-side radio.
        dialog._input_radios[1][0].setChecked(True)
        for row in range(4):
            for rb in dialog._output_radios[row]:
                assert rb.isEnabled(), f"output row {row}"


class TestCustomChannelNames:
    """The dialog should reflect the user-editable channel names from
    DeviceState rather than always showing the canonical InA/Out1 etc."""

    def test_custom_names_flow_to_headers_and_status(self, qtbot):
        cfg = {
            "names": [
                "Mic 1",
                "Mic 2",
                "Line L",
                "Line R",
                "Mains",
                "Sub",
                "Mon A",
                "Mon B",
            ],
            "gains": [0] * 8,
            "mutes": [False] * 8,
            "phases": [False] * 8,
            "link_flags": [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80],
            "routings": [0x01, 0x02, 0x04, 0x08],
            "gates": [
                {"attack": 0, "release": 0, "hold": 0, "threshold": 0} for _ in range(4)
            ],
            "delays": [0] * 4,
            "crossovers": [
                {
                    "hipass_freq": 0,
                    "hipass_slope": 0,
                    "lopass_freq": 0,
                    "lopass_slope": 0,
                }
                for _ in range(4)
            ],
            "compressors": [
                {"ratio": 0, "knee": 0, "attack": 0, "release": 0, "threshold": 0}
                for _ in range(4)
            ],
            "peqs": [{"bands": [], "channel_bypass": False} for _ in range(4)],
            "active_slot": 1,
            "preset_names": [f"P{i:02d}" for i in range(30)],
        }
        state = DeviceState.from_config(cfg)
        dlg = ChannelLinkingDialog(None, state)
        qtbot.addWidget(dlg)

        assert [h.text() for h in dlg._input_headers] == [
            "Mic 1",
            "Mic 2",
            "Line L",
            "Line R",
        ]
        assert [h.text() for h in dlg._output_headers] == [
            "Mains",
            "Sub",
            "Mon A",
            "Mon B",
        ]
        assert [lbl.text() for lbl in dlg._input_row_labels] == [
            "Mic 1",
            "Mic 2",
            "Line L",
            "Line R",
        ]
        # Status labels should also use the live names.
        assert "Mic 1: standalone" in dlg._input_status[0].text()
        assert "Mains: standalone" in dlg._output_status[0].text()

    def test_refresh_updates_names_after_rename(self, dialog, qtbot):
        # Construct with default fixture names, then refresh from a
        # state that renamed InA — the header should update in place.
        cfg = {
            "names": ["NEW_A", "InB", "InC", "InD", "Out1", "Out2", "Out3", "Out4"],
            "gains": [0] * 8,
            "mutes": [False] * 8,
            "phases": [False] * 8,
            "link_flags": [0x01, 0x02, 0x04, 0x08, 0x01, 0x02, 0x04, 0x08],
            "routings": [0x01, 0x02, 0x04, 0x08],
            "gates": [
                {"attack": 0, "release": 0, "hold": 0, "threshold": 0} for _ in range(4)
            ],
            "delays": [0] * 4,
            "crossovers": [
                {
                    "hipass_freq": 0,
                    "hipass_slope": 0,
                    "lopass_freq": 0,
                    "lopass_slope": 0,
                }
                for _ in range(4)
            ],
            "compressors": [
                {"ratio": 0, "knee": 0, "attack": 0, "release": 0, "threshold": 0}
                for _ in range(4)
            ],
            "peqs": [{"bands": [], "channel_bypass": False} for _ in range(4)],
            "active_slot": 1,
            "preset_names": [f"P{i:02d}" for i in range(30)],
        }
        renamed = DeviceState.from_config(cfg)
        dialog.refresh(renamed)
        assert dialog._input_headers[0].text() == "NEW_A"
        assert dialog._input_row_labels[0].text() == "NEW_A"
