---
status: accepted
date: 2026-05-10
decision-makers: Maximilian Zettler
---

# Centralise theming in a ThemeManager, and let an explicit preference override the reported system scheme

## Context and Problem Statement

The application should follow the desktop's light/dark setting, and should also let
a user override it — a mixing application is often run in a dark room regardless of
what the desktop is doing.

Two things make this harder than reading one setting. First, roughly half the UI is
custom-painted (ADR-0019), so those widgets need `QColor` values and a repaint
signal, not just a stylesheet swap. Second, and discovered later: **on KDE Plasma
the platform theme plugin keeps reporting the system scheme even after
`setColorScheme()` has been called.** So code that resolved the effective theme by
querying Qt would immediately bounce an explicit choice back to the system colours,
and the theme would appear stuck.

## Decision Drivers

* Follow the OS scheme by default, and switch live when it changes.
* Support an explicit override that persists across sessions.
* Custom-painted widgets must re-theme, which requires a broadcast signal.
* The override must actually hold on the desktop environments users run —
  including KDE, where Qt's reported scheme is unreliable after an override.

## Considered Options

* A `ThemeManager` singleton holding the resolved theme, with an explicit
  preference taken as authoritative
* Resolve the effective scheme by querying `QStyleHints.colorScheme()` every time
* Follow the system scheme only, with no override
* Per-widget theme lookups with no central registry

## Decision Outcome

Chosen option: a **`ThemeManager` singleton**, with **an explicit preference
treated as authoritative**.

A frozen `Theme` dataclass holds every colour the application uses, grouped by
consumer: `QPalette` feeds, graph chrome, per-feature curve colours, a four-entry
`graph_overlay` tuple keyed by output index, gate-specific colours, knob arcs,
level meter colours (including a `meter_unlit_amount` blend factor and a
`dim_segment()` helper), LED indicator, and routing matrix. Two module-level
instances, `DARK_THEME` and `LIGHT_THEME`, hold the values.

`ThemeManager` resolves the effective scheme, swaps the `QPalette`, loads the
matching stylesheet (`style_dark.qss` or `style_light.qss` — ADR-0019), and emits a
single argument-less `themeChanged`. Custom-painted widgets connect to it in
`__init__` and repaint. The user preference persists in
`QSettings("miniDSP", "minidspqt")` under `theme/preference`, falling back to
`system` for missing or invalid values.

**The resolution rule is the substance of this record.** `_resolve_scheme` returns
an explicit `light` or `dark` preference directly, **without consulting
`QStyleHints.colorScheme()` at all**. Only when the preference is `system` is Qt's
reported scheme read, defaulting to dark when it is `Unknown`.

The manager still calls `setColorScheme()` / `unsetColorScheme()`, but purely to
nudge native widget rendering — explicitly not as the source of truth. That
separation is the fix: the original code re-queried Qt even for an explicit
preference, so on KDE the user's choice was overwritten by the system scheme
immediately (`2770558`).

One ordering detail is deliberate: `bind_to_app` connects `colorSchemeChanged`
*before* pushing the preference, so no emission is missed during setup, then
applies once.

### Consequences

* Good, because an explicit choice holds on every desktop, including those whose
  platform plugin misreports the scheme after an override.
* Good, because the whole palette is one frozen dataclass, so adding a themed
  colour means adding a field and filling it in both instances — the compiler-ish
  discipline of a dataclass catches omissions.
* Good, because custom-painted widgets re-theme through one signal rather than each
  polling a setting.
* Good, because it made later colour work mechanical: per-feature graph curve
  colours (ADR-0021) and the stable four-colour overlay ring became new fields.
* Bad, because two theme instances must stay structurally in sync. A field added to
  one is a runtime `AttributeError` in the other, not a startup error.
* Bad, because deliberately ignoring the platform's reported scheme means genuinely
  losing information. If a future Qt or KDE version makes `colorScheme()` reliable
  after an override, this code will still ignore it — correct but no longer
  necessary, and nothing will signal that.
* Neutral, because the light theme uses a soft tinted off-white (`#f0f2f7`) for
  graph backgrounds rather than pure white, so the plots do not glare while also
  not becoming a dark island in a light UI.
* Neutral, because this raised the Qt floor to 6.8 for
  `setColorScheme`/`unsetColorScheme` (ADR-0002).

### Confirmation

`tests/test_theme.py` covers the KDE quirk directly, using a fake application whose
`colorScheme()` never reflects `setColorScheme()` — so a regression to
re-querying Qt for explicit preferences fails the suite. Because those tests call
`set_user_preference()`, `conftest.py` enables `QStandardPaths` test mode so they
cannot overwrite the developer's real configuration (ADR-0025).

## Pros and Cons of the Options

### ThemeManager with explicit preference authoritative

* Good, because the override is reliable across desktop environments
* Good, because one registry and one signal serve both QSS and painted widgets
* Bad, because it ignores platform information that may become trustworthy later

### Always query QStyleHints.colorScheme()

* Good, because Qt's report is the natural single source of truth
* Good, because there is no separate state to keep consistent
* Bad, because it is **wrong on KDE Plasma** after an override — the defect that
  motivated this record

### System scheme only, no override

* Good, because it is the simplest correct behaviour with nothing to persist
* Bad, because it removes a genuinely wanted feature for audio work

### Per-widget theme lookups

* Good, because each widget is self-contained with no central registry
* Bad, because there is no coordinated repaint, so a live switch leaves widgets
  in mixed themes
* Bad, because colour values scatter, which is exactly what `6db60ae` consolidated

## More Information

* `9e4c844` — `ThemeManager`, the QSS split, and the Qt 6.8 floor
* `6db60ae` — routing custom-painted widget colours through the registry
* `2770558` — the KDE Plasma fix and `tests/test_theme.py`
* Related: ADR-0002 (Qt version floor), ADR-0019 (the QSS split),
  ADR-0021 (per-feature colours), ADR-0025 (QSettings isolation)
