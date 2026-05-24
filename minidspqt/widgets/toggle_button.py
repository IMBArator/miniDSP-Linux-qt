"""Checkable QPushButton with per-feature color theming.

Call `setFeature("mute" | "phase" | "gate" | ...)` to pick the accent.
When unchecked the accent colors the border and text only (outline
look); when checked it fills the whole button.

Styling lives entirely in `resources/style.qss`: the per-feature accent
is selected via the `feature` dynamic property, e.g.
`ToggleButton[feature="mute"]:checked { ... }`.
"""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QWidget


class ToggleButton(QPushButton):
    """Checkable button whose accent colour follows a feature name.

    The accent is selected by QSS rules keyed on the ``feature``
    dynamic property; the Python side only stores the string and
    repolishes the widget so the new selectors take effect.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build a button in the ``"generic"`` feature class.

        Args:
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self.setCheckable(True)
        self.setProperty("feature", "generic")

    def setFeature(self, feature: str) -> None:
        """Switch the button's accent class.

        Args:
            feature: Feature name (``"mute"``, ``"phase"``, ``"gate"``,
                ``"peq"`` …). Case-insensitive — stored lowercase.
                Unknown names fall through to the QSS default rule.
        """
        self.setProperty("feature", feature.lower())
        # Re-evaluate stylesheet selectors after a dynamic property change.
        self.style().unpolish(self)
        self.style().polish(self)

    def feature(self) -> str:
        """Return the current feature class string."""
        return str(self.property("feature") or "generic")
