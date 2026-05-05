"""Checkable QPushButton with per-feature color theming.

Call `setFeature("mute" | "phase" | "gate" | ...)` to pick the active
color. Unchecked state is uniformly grey.
"""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QWidget

from ..scale import s

# active-background, active-border
_FEATURE_COLORS: dict[str, tuple[str, str]] = {
    "mute": ("#cc2424", "#801515"),
    "phase": ("#d5a021", "#8d6b15"),
    "gate": ("#2fa84a", "#1e6b30"),
    "xover": ("#4a8bd0", "#2f578a"),
    "peq": ("#8a5ad2", "#563789"),
    "comp": ("#2fa89b", "#1d675f"),
    "delay": ("#6c92c2", "#44587a"),
}


class ToggleButton(QPushButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self._feature = "generic"
        self._refresh_style()
        self.toggled.connect(self._refresh_style)

    def setFeature(self, feature: str) -> None:
        self._feature = feature.lower()
        self._refresh_style()

    def feature(self) -> str:
        return self._feature

    def _refresh_style(self, *_args) -> None:
        active_bg, active_border = _FEATURE_COLORS.get(
            self._feature, ("#5a7ab0", "#344a6b")
        )
        bw = s(1)
        cr = s(3)
        px = s(3)
        py = s(6)
        fs = s(11)
        self.setStyleSheet(
            "ToggleButton {"
            " background-color: #3a3a3e;"
            " color: #dddddd;"
            f" border: {bw}px solid #55555a;"
            f" border-radius: {cr}px;"
            f" padding: {px}px {py}px;"
            " font-weight: 600;"
            f" font-size: {fs}px;"
            "}"
            "ToggleButton:hover { background-color: #48484d; }"
            "ToggleButton:checked {"
            f" background-color: {active_bg};"
            " color: white;"
            f" border: {bw}px solid {active_border};"
            "}"
        )

    def apply_scale(self) -> None:
        self._refresh_style()

