"""ThemeManager scheme resolution — especially the KDE Plasma case.

Why these tests exist
---------------------
On KDE Plasma the platform-theme plugin keeps reporting the *system* colour
scheme from ``QStyleHints.colorScheme()`` even after the app calls
``setColorScheme()``.  An earlier version of ``_resolve_scheme`` always
trusted that reported value, so an explicit "Light"/"Dark" menu choice got
bounced straight back to the system colours and the theme appeared stuck.

These tests pin the fix: an explicit preference is authoritative and never
re-queries Qt; only the "system" preference follows the reported scheme.  We
drive the manager with a tiny fake ``QApplication`` so the resolution logic is
exercised without a display server or a real Plasma session.
"""

from __future__ import annotations

import pytest

from PySide6.QtCore import Qt

from minidspqt.theme import DARK_THEME, LIGHT_THEME, ThemeManager


class _FakeStyleHints:
    """Stand-in for ``QStyleHints`` that mimics KDE's behaviour.

    ``setColorScheme`` is intentionally a no-op on the *reported* value:
    ``colorScheme()`` always returns ``reported`` regardless of what the app
    asked for — exactly the Plasma quirk that broke explicit theme switching.
    """

    def __init__(self, reported: Qt.ColorScheme) -> None:
        self.reported = reported
        self.requested: Qt.ColorScheme | None = None
        self.unset = False

    def colorScheme(self) -> Qt.ColorScheme:
        return self.reported

    def setColorScheme(self, scheme: Qt.ColorScheme) -> None:
        self.requested = scheme  # recorded, but does NOT change `reported`

    def unsetColorScheme(self) -> None:
        self.unset = True

    # ThemeManager.bind_to_app connects to this; a plain attribute with a
    # no-op `connect` is enough for the resolution tests.
    class _Signal:
        def connect(self, _slot) -> None:  # noqa: ANN001
            pass

    colorSchemeChanged = _Signal()


class _FakeApp:
    """Minimal QApplication surface used by ThemeManager."""

    def __init__(self, reported: Qt.ColorScheme) -> None:
        self._hints = _FakeStyleHints(reported)
        self.palette = None
        self.stylesheet = None

    def styleHints(self) -> _FakeStyleHints:
        return self._hints

    def setPalette(self, palette) -> None:  # noqa: ANN001
        self.palette = palette

    def setStyleSheet(self, sheet: str) -> None:
        self.stylesheet = sheet


@pytest.fixture
def kde_dark_app() -> _FakeApp:
    """A fake app emulating KDE Plasma stuck on a dark system scheme."""
    return _FakeApp(Qt.ColorScheme.Dark)


def _bind(app: _FakeApp) -> ThemeManager:
    tm = ThemeManager()
    tm.bind_to_app(app)
    return tm


def test_explicit_light_overrides_kde_dark_report(kde_dark_app):
    """Picking Light wins even though Plasma keeps reporting Dark."""
    tm = _bind(kde_dark_app)

    tm.set_user_preference("light")

    assert tm.current is LIGHT_THEME
    assert tm.current.name == "light"
    # The native-widget nudge still fires via setColorScheme...
    assert kde_dark_app.styleHints().requested == Qt.ColorScheme.Light


def test_explicit_dark_on_kde_light_report():
    """Picking Dark wins even though Plasma reports a light system scheme."""
    app = _FakeApp(Qt.ColorScheme.Light)
    tm = _bind(app)

    tm.set_user_preference("dark")

    assert tm.current is DARK_THEME
    assert app.styleHints().requested == Qt.ColorScheme.Dark


def test_system_preference_follows_reported_scheme(kde_dark_app):
    """With 'system', we DO follow Qt's reported scheme."""
    tm = _bind(kde_dark_app)

    tm.set_user_preference("system")

    assert tm.current is DARK_THEME
    assert kde_dark_app.styleHints().unset is True


def test_system_follows_light_report():
    app = _FakeApp(Qt.ColorScheme.Light)
    tm = _bind(app)

    tm.set_user_preference("system")

    assert tm.current is LIGHT_THEME


def test_switch_back_and_forth(kde_dark_app):
    """Light -> Dark -> Light all take effect under the KDE quirk."""
    tm = _bind(kde_dark_app)

    tm.set_user_preference("light")
    assert tm.current is LIGHT_THEME

    tm.set_user_preference("dark")
    assert tm.current is DARK_THEME

    tm.set_user_preference("light")
    assert tm.current is LIGHT_THEME
