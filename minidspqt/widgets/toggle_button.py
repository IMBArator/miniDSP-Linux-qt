"""Checkable QPushButton with per-feature color theming.

Call `setFeature("mute" | "phase" | "gate" | ...)` to pick the active
color. Unchecked state is uniformly grey.

Styling lives entirely in `resources/style.qss`: the per-feature accent
is selected via the `feature` dynamic property, e.g.
`ToggleButton[feature="mute"]:checked { ... }`.
"""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QWidget


class ToggleButton(QPushButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setProperty("feature", "generic")

    def setFeature(self, feature: str) -> None:
        self.setProperty("feature", feature.lower())
        # Re-evaluate stylesheet selectors after a dynamic property change.
        self.style().unpolish(self)
        self.style().polish(self)

    def feature(self) -> str:
        return str(self.property("feature") or "generic")
