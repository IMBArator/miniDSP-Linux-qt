"""Centralized color registry + theme manager for light / dark / system mode.

Why this module exists
----------------------
Qt 6.5 introduced ``QStyleHints.colorScheme`` and a ``colorSchemeChanged``
signal that lets an app react to the OS-level light/dark preference; Qt 6.8
added ``setColorScheme`` / ``unsetColorScheme`` so we can also force a
specific scheme (or unset to follow the system again).  But:

1.  ``QPalette`` only covers *system* widget colors (window, button, text…).
    Application-specific colors — e.g. our PEQ graph background, ToggleButton
    feature accents, level-meter LED ramp — are not part of the palette.
2.  Custom QSS does **not** auto-react to scheme changes.  The stylesheet
    has to be reloaded by hand.
3.  Custom-painted widgets (PEQ graph, level meter, knobs, LED, routing
    matrix) read their colors from Python constants, so they need to be
    reloaded too.

So this module owns:
  * Two ``Theme`` instances (DARK_THEME, LIGHT_THEME) holding every named
    colour the app uses.
  * A ``ThemeManager`` singleton that wires up Qt's signal, persists the
    user's preference (system/light/dark) via ``QSettings``, swaps palette
    + QSS + theme, and fires its own ``themeChanged`` signal that custom
    widgets connect to in order to refresh themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

ThemePreference = Literal["system", "light", "dark"]

_QSETTINGS_ORG = "miniDSP"
_QSETTINGS_APP = "minidspqt"
_QSETTINGS_KEY = "theme/preference"

_RESOURCES = Path(__file__).parent / "resources"
_QSS_DARK = _RESOURCES / "style_dark.qss"
_QSS_LIGHT = _RESOURCES / "style_light.qss"


@dataclass(frozen=True)
class Theme:
    """All named colors used by the app, plus a few derived helpers.

    Custom-painted widgets read these via ``theme_manager.current.<field>``
    in their ``paintEvent``, so a re-paint after ``themeChanged`` picks up
    the new values automatically.
    """

    name: str  # "dark" or "light" — used for QSS file selection / debugging

    # --- QPalette feeds (Fusion adapts to whatever palette we set) ---
    pal_window: QColor
    pal_window_text: QColor
    pal_base: QColor
    pal_alternate_base: QColor
    pal_text: QColor
    pal_button: QColor
    pal_button_text: QColor
    pal_bright_text: QColor
    pal_highlight: QColor
    pal_highlighted_text: QColor

    # --- Frequency / gate graphs ---
    graph_bg: QColor
    graph_grid: QColor
    graph_ref: QColor          # 0 dB / diagonal reference line
    graph_curve: QColor
    graph_curve_bypassed: QColor
    graph_label: QColor
    graph_border: QColor
    graph_marker_active: QColor
    graph_marker_bypassed: QColor
    graph_marker_text: QColor
    graph_xover_marker: QColor
    graph_xover_label_text: QColor

    # --- Per-feature curve colours (match the channel-strip toggle buttons) ---
    graph_curve_gate: QColor
    graph_curve_gate_bypassed: QColor
    graph_curve_peq: QColor
    graph_curve_peq_bypassed: QColor
    graph_curve_xover: QColor
    graph_curve_xover_bypassed: QColor
    graph_curve_comp: QColor
    graph_curve_comp_bypassed: QColor

    # --- Gate-only ---
    gate_closed_fill: QColor
    gate_open_fill: QColor
    gate_threshold_line: QColor
    gate_threshold_text: QColor

    # --- Knob arcs (gain_knob, param_knob) ---
    knob_arc_bg: QColor
    knob_arc_fg: QColor
    knob_pointer: QColor

    # --- Level meter ---
    meter_segment_green_low: QColor   # darkest green segment
    meter_segment_green_high: QColor  # brightest green segment
    meter_segment_amber: QColor
    meter_segment_red: QColor
    meter_peak_marker: QColor
    meter_unlit_target: QColor        # color we blend each segment toward
    meter_unlit_amount: float         # 0..1; 1.0 = fully replaced by target

    # --- LED indicator ---
    led_active: QColor
    led_dim: QColor
    led_glow: QColor

    # --- Routing matrix ---
    matrix_active: QColor
    matrix_drag: QColor
    matrix_highlight: QColor
    matrix_node_fill: QColor

    def dim_segment(self, lit: QColor) -> QColor:
        """Blend ``lit`` toward ``meter_unlit_target`` to produce the unlit colour.

        Dark theme blends toward black (gives a dim "off" LED look); light
        theme blends toward the meter frame fill (gives a soft pastel look
        rather than a near-black blob in an otherwise light UI).
        """
        t = self.meter_unlit_amount
        tgt = self.meter_unlit_target
        return QColor(
            int(lit.red() * (1 - t) + tgt.red() * t),
            int(lit.green() * (1 - t) + tgt.green() * t),
            int(lit.blue() * (1 - t) + tgt.blue() * t),
        )


# ---------------------------------------------------------------------------
# Dark theme — values preserved exactly from the pre-theming codebase so
# nothing visibly changes for users who stick with dark mode.
# ---------------------------------------------------------------------------

DARK_THEME = Theme(
    name="dark",

    pal_window=QColor(45, 45, 48),
    pal_window_text=QColor(220, 220, 220),
    pal_base=QColor(30, 30, 32),
    pal_alternate_base=QColor(40, 40, 44),
    pal_text=QColor(220, 220, 220),
    pal_button=QColor(55, 55, 58),
    pal_button_text=QColor(220, 220, 220),
    pal_bright_text=QColor(255, 255, 255),
    pal_highlight=QColor(70, 130, 200),
    pal_highlighted_text=QColor(255, 255, 255),

    graph_bg=QColor(26, 26, 46),
    graph_grid=QColor(255, 255, 255, 25),
    graph_ref=QColor(255, 255, 255, 60),
    graph_curve=QColor(80, 200, 120),
    graph_curve_bypassed=QColor(80, 200, 120, 70),
    graph_label=QColor(150, 150, 150),
    graph_border=QColor(80, 80, 90),
    graph_marker_active=QColor(80, 200, 120),
    graph_marker_bypassed=QColor(140, 140, 140, 140),
    graph_marker_text=QColor(20, 20, 28),
    graph_xover_marker=QColor(232, 114, 35),
    graph_xover_label_text=QColor(255, 255, 255, 200),

    graph_curve_gate=QColor(47, 168, 74),
    graph_curve_gate_bypassed=QColor(47, 168, 74, 70),
    graph_curve_peq=QColor(138, 90, 210),
    graph_curve_peq_bypassed=QColor(138, 90, 210, 70),
    graph_curve_xover=QColor(232, 114, 35),
    graph_curve_xover_bypassed=QColor(232, 114, 35, 70),
    graph_curve_comp=QColor(47, 168, 155),
    graph_curve_comp_bypassed=QColor(47, 168, 155, 70),

    gate_closed_fill=QColor(200, 50, 50, 40),
    gate_open_fill=QColor(50, 180, 80, 25),
    gate_threshold_line=QColor(255, 200, 50, 140),
    gate_threshold_text=QColor(255, 200, 50),

    knob_arc_bg=QColor(60, 60, 64),
    knob_arc_fg=QColor(80, 160, 230),
    knob_pointer=QColor(230, 230, 230),

    meter_segment_green_low=QColor(0, 140, 0),
    meter_segment_green_high=QColor(0, 200, 0),
    meter_segment_amber=QColor(210, 200, 0),
    meter_segment_red=QColor(255, 0, 0),
    meter_peak_marker=QColor(255, 255, 255, 160),
    meter_unlit_target=QColor(0, 0, 0),
    meter_unlit_amount=0.80,            # 1/5 of original brightness

    led_active=QColor(255, 40, 40),
    led_dim=QColor(80, 15, 15),
    led_glow=QColor(255, 60, 60, 90),

    matrix_active=QColor(80, 170, 230),
    matrix_drag=QColor(120, 200, 255, 180),
    matrix_highlight=QColor(120, 200, 255, 60),
    matrix_node_fill=QColor(200, 200, 200),
)


# ---------------------------------------------------------------------------
# Light theme — graph backgrounds use a soft tinted off-white (#f0f2f7) per
# the "follow theme but soften" decision, not pure white.  Accent colours are
# slightly darker than their dark-theme counterparts so they stay legible
# against light backgrounds.
# ---------------------------------------------------------------------------

LIGHT_THEME = Theme(
    name="light",

    pal_window=QColor(245, 245, 247),
    pal_window_text=QColor(40, 40, 42),
    pal_base=QColor(255, 255, 255),
    pal_alternate_base=QColor(238, 238, 242),
    pal_text=QColor(40, 40, 42),
    pal_button=QColor(232, 232, 236),
    pal_button_text=QColor(40, 40, 42),
    pal_bright_text=QColor(0, 0, 0),
    pal_highlight=QColor(70, 130, 200),
    pal_highlighted_text=QColor(255, 255, 255),

    graph_bg=QColor(240, 242, 247),
    graph_grid=QColor(0, 0, 0, 30),
    graph_ref=QColor(0, 0, 0, 70),
    graph_curve=QColor(40, 140, 80),
    graph_curve_bypassed=QColor(40, 140, 80, 80),
    graph_label=QColor(90, 90, 100),
    graph_border=QColor(180, 180, 190),
    graph_marker_active=QColor(40, 140, 80),
    graph_marker_bypassed=QColor(160, 160, 165, 160),
    graph_marker_text=QColor(255, 255, 255),
    graph_xover_marker=QColor(168, 80, 17),
    graph_xover_label_text=QColor(255, 255, 255, 220),

    graph_curve_gate=QColor(30, 122, 54),
    graph_curve_gate_bypassed=QColor(30, 122, 54, 80),
    graph_curve_peq=QColor(110, 63, 184),
    graph_curve_peq_bypassed=QColor(110, 63, 184, 80),
    graph_curve_xover=QColor(168, 80, 17),
    graph_curve_xover_bypassed=QColor(168, 80, 17, 80),
    graph_curve_comp=QColor(30, 133, 122),
    graph_curve_comp_bypassed=QColor(30, 133, 122, 80),

    gate_closed_fill=QColor(200, 50, 50, 50),
    gate_open_fill=QColor(50, 160, 80, 35),
    gate_threshold_line=QColor(200, 140, 30, 200),
    gate_threshold_text=QColor(170, 110, 20),

    knob_arc_bg=QColor(220, 220, 225),
    knob_arc_fg=QColor(70, 130, 200),
    knob_pointer=QColor(60, 60, 64),

    meter_segment_green_low=QColor(0, 150, 0),
    meter_segment_green_high=QColor(40, 200, 40),
    meter_segment_amber=QColor(220, 170, 0),
    meter_segment_red=QColor(220, 30, 30),
    meter_peak_marker=QColor(0, 0, 0, 160),
    meter_unlit_target=QColor(232, 232, 236),  # match meter frame fill
    meter_unlit_amount=0.85,

    led_active=QColor(220, 30, 30),
    led_dim=QColor(220, 170, 170),
    led_glow=QColor(255, 80, 80, 90),

    matrix_active=QColor(50, 130, 200),
    matrix_drag=QColor(70, 160, 220, 200),
    matrix_highlight=QColor(70, 160, 220, 60),
    matrix_node_fill=QColor(80, 80, 90),
)


# ---------------------------------------------------------------------------


def _build_palette(theme: Theme) -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, theme.pal_window)
    p.setColor(QPalette.ColorRole.WindowText, theme.pal_window_text)
    p.setColor(QPalette.ColorRole.Base, theme.pal_base)
    p.setColor(QPalette.ColorRole.AlternateBase, theme.pal_alternate_base)
    p.setColor(QPalette.ColorRole.Text, theme.pal_text)
    p.setColor(QPalette.ColorRole.Button, theme.pal_button)
    p.setColor(QPalette.ColorRole.ButtonText, theme.pal_button_text)
    p.setColor(QPalette.ColorRole.BrightText, theme.pal_bright_text)
    p.setColor(QPalette.ColorRole.Highlight, theme.pal_highlight)
    p.setColor(QPalette.ColorRole.HighlightedText, theme.pal_highlighted_text)
    return p


def _load_qss_for(scheme: Qt.ColorScheme) -> str:
    path = _QSS_LIGHT if scheme == Qt.ColorScheme.Light else _QSS_DARK
    return path.read_text(encoding="utf-8") if path.exists() else ""


class ThemeManager(QObject):
    """Owns the active ``Theme`` and applies it to the ``QApplication``.

    Lifecycle
    ---------
    1. ``bind_to_app(app)`` is called once at startup.  It:
       - Reads the user's last preference from ``QSettings``.
       - Tells Qt about it via ``setColorScheme`` / ``unsetColorScheme``.
       - Connects ``QStyleHints.colorSchemeChanged`` so OS-level toggles
         re-apply automatically.
       - Applies the resolved theme (palette + QSS + emits ``themeChanged``).

    2. ``set_user_preference("system"|"light"|"dark")`` is called by the
       View → Theme menu.  It persists the choice and re-applies.

    Custom widgets connect to ``themeChanged`` and call ``update()``; their
    ``paintEvent`` reads ``theme_manager.current.<field>`` afresh.
    """

    themeChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._app: QApplication | None = None
        self._pref: ThemePreference = "system"
        self._current: Theme = DARK_THEME

    @property
    def current(self) -> Theme:
        return self._current

    @property
    def preference(self) -> ThemePreference:
        return self._pref

    def bind_to_app(self, app: QApplication) -> None:
        self._app = app
        self._pref = self._load_preference()
        # Connect *before* pushing the preference so we don't miss the
        # signal emitted by setColorScheme/unsetColorScheme.
        app.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)
        self._push_preference_to_qt(self._pref)
        # Always apply once at startup — Qt may not emit the signal if the
        # resolved scheme already matches the system default.
        self._reapply()

    def set_user_preference(self, pref: ThemePreference) -> None:
        if pref not in ("system", "light", "dark"):
            return
        self._pref = pref
        self._save_preference(pref)
        if self._app is not None:
            self._push_preference_to_qt(pref)
        self._reapply()

    # ----------------- internals -----------------

    def _on_system_scheme_changed(self, scheme: Qt.ColorScheme) -> None:  # noqa: ARG002
        # Re-resolve from scratch — the signal arg can be Unknown on some
        # platforms, but ``styleHints().colorScheme()`` is authoritative.
        self._reapply()

    def _push_preference_to_qt(self, pref: ThemePreference) -> None:
        sh = self._app.styleHints()
        if pref == "system":
            sh.unsetColorScheme()
        elif pref == "light":
            sh.setColorScheme(Qt.ColorScheme.Light)
        elif pref == "dark":
            sh.setColorScheme(Qt.ColorScheme.Dark)

    def _resolve_scheme(self) -> Qt.ColorScheme:
        if self._app is None:
            return Qt.ColorScheme.Dark
        scheme = self._app.styleHints().colorScheme()
        if scheme != Qt.ColorScheme.Unknown:
            return scheme
        # Some Linux setups (no DBus colour-scheme portal, headless tests) report
        # Unknown.  Honour an explicit user pref, otherwise keep the historical
        # dark default.
        if self._pref == "light":
            return Qt.ColorScheme.Light
        return Qt.ColorScheme.Dark

    def _reapply(self) -> None:
        if self._app is None:
            return
        scheme = self._resolve_scheme()
        new_theme = LIGHT_THEME if scheme == Qt.ColorScheme.Light else DARK_THEME
        self._current = new_theme
        self._app.setPalette(_build_palette(new_theme))
        self._app.setStyleSheet(_load_qss_for(scheme))
        self.themeChanged.emit()

    def _load_preference(self) -> ThemePreference:
        s = QSettings(_QSETTINGS_ORG, _QSETTINGS_APP)
        raw = s.value(_QSETTINGS_KEY, "system")
        if isinstance(raw, str) and raw in ("system", "light", "dark"):
            return raw  # type: ignore[return-value]
        return "system"

    def _save_preference(self, pref: ThemePreference) -> None:
        s = QSettings(_QSETTINGS_ORG, _QSETTINGS_APP)
        s.setValue(_QSETTINGS_KEY, pref)


# ---------------------------------------------------------------------------
# Module-level singleton.  Custom widgets import this directly:
#   from ..theme import theme_manager
# ---------------------------------------------------------------------------

theme_manager = ThemeManager()


def current_theme() -> Theme:
    """Convenience accessor used by widgets that don't want to import the
    manager singleton just to read one property."""
    return theme_manager.current


def _bootstrap_for_headless() -> None:
    """Ensure ``theme_manager.current`` is non-None in tests that paint a
    widget without ever calling ``ThemeManager.bind_to_app``.

    Tests still get the dark default; production calls ``bind_to_app`` once
    in ``app.run()`` and overrides this.
    """
    # No-op: the dataclass default already gives us DARK_THEME.  This
    # function exists only as a documented hook in case future tests need
    # to opt into LIGHT_THEME.


_bootstrap_for_headless()
