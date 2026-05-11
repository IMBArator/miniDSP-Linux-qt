"""Shared slave-lock helpers for feature panels.

When a feature panel (Gate/PEQ/Xover) is showing the state of a slave
channel, its controls should be disabled and a "Linked to <master>"
banner shown so the user understands why edits are inert. Each panel
composes the helpers here to gain this behaviour with a tiny amount of
code rather than duplicating banner setup three times.

The banner uses ``objectName="panelLinkBanner"`` so themes can style it
via QSS; the default styling is fine if no rule matches.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout, QLabel, QWidget


def install_link_banner(layout: QBoxLayout) -> QLabel:
    """Insert a hidden 'Linked to ...' banner at the top of ``layout``.

    Returns the QLabel so the panel can pass it to :func:`apply_link_state`
    later. The banner is hidden by default; standalone channels see no
    visual artefact.
    """
    banner = QLabel("")
    banner.setObjectName("panelLinkBanner")
    banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
    banner.hide()
    layout.insertWidget(0, banner)
    return banner


def apply_link_state(
    banner: QLabel,
    is_slave: bool,
    master_name: str,
    interactive: list[QWidget],
) -> None:
    """Toggle banner visibility/text and enable-state of ``interactive`` widgets.

    Each widget in ``interactive`` is disabled when ``is_slave`` is True
    so the user can still see the slave's mirrored values but cannot edit
    them. The banner reads "Linked to <master_name> — read-only" or just
    "Linked — read-only" if no master name is available.
    """
    if is_slave:
        if master_name:
            banner.setText(f"\U0001f517 Linked to {master_name} — read-only")
        else:
            banner.setText("\U0001f517 Linked — read-only")
        banner.show()
    else:
        banner.hide()
    for w in interactive:
        w.setEnabled(not is_slave)
