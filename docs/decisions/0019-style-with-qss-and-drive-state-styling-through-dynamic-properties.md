---
status: accepted
date: 2026-05-06
decision-makers: Maximilian Zettler
---

# Style with QSS and drive state-dependent styling through Qt dynamic properties

## Context and Problem Statement

Styling started as inline `setStyleSheet()` calls scattered across `home_view.py`
and every styled widget. Two patterns in particular had gone wrong.

The connection label swapped its background between four states — disconnected,
connected, offline, preview — via four nearly-identical `setStyleSheet` calls
differing only in a colour. And `ToggleButton` carried a 17-line `_refresh_style`
method that rebuilt its entire stylesheet string on **every toggle**, just to
select one of seven per-feature accent colours.

Meanwhile a genuinely different category existed: widgets that paint themselves.
`ParamKnob`'s arc, `LevelMeter`'s segments, `LedIndicator`'s glow, and
`RoutingMatrix`'s nodes do not consume stylesheets at all — they need `QColor`
values in `paintEvent`.

## Decision Drivers

* Static appearance should be declarative and live in one place.
* State-dependent appearance should not mean rebuilding stylesheet strings at runtime.
* Custom-painted widgets need colour values, not stylesheet rules, and pretending
  otherwise does not work.
* Whatever is chosen has to support a full light/dark swap (ADR-0020).

## Considered Options

* One application-level QSS file, with dynamic properties plus attribute selectors
  for state, and Python colours for custom painting
* Inline `setStyleSheet()` per widget
* Per-widget QSS files, loaded individually
* All appearance in Python, with no QSS at all

## Decision Outcome

Chosen option: a **three-way split by mechanism**, matching each need to the tool
that fits it.

**Static rules** live in one application-level stylesheet, loaded once at startup
(`e3dc6ba`).

**State-dependent rules** ride Qt dynamic properties with attribute selectors,
rather than runtime string building:

* `connectionLabel` gets `setProperty("state", "disconnected"|"connected"|
  "offline"|"preview")`, with one QSS rule per state — replacing the four
  near-identical `setStyleSheet` calls.
* `ToggleButton` gets `setProperty("feature", <name>)`, driving selectors like
  `ToggleButton[feature="mute"]:checked { ... }` for all seven features — removing
  `_refresh_style` entirely.

After a property change the code calls `style().unpolish()` / `polish()` so the
selectors re-evaluate. That step is mandatory and easy to forget.

**Custom-painted widgets keep their colours in Python**, read from the theme
registry (ADR-0020), because they draw rather than style themselves.

The boundary is deliberate but not self-evident, so it is documented in place. The
one remaining inline `setStyleSheet` — `LedIndicator`'s `background: transparent`
— carries a comment explaining that it is paint plumbing rather than visual
styling, specifically so a future reader does not "fix" it by moving it into the
QSS file (`45da26d`).

Widget appearance state is expressed as a QSS property throughout, which is what
made the `*_active` indicator pattern cheap to extend feature by feature
(ADR-0021).

### Consequences

* Good, because appearance is declarative and greppable — finding what styles a
  widget means searching one stylesheet for a selector.
* Good, because state changes are a property set plus a repolish, not string
  concatenation, so toggling a button no longer rebuilds a stylesheet.
* Good, because the light/dark swap became tractable: two files with identical
  selectors and different colours, selected at runtime (ADR-0020).
* Good, because each new `*_active` indicator is a QSS rule plus a property, with
  no Python appearance logic.
* Bad, because the unpolish/polish requirement is invisible and unenforced.
  Forgetting it produces a property that is set correctly and has no visible effect,
  which is a confusing failure.
* Bad, because the QSS-versus-Python boundary must be understood before styling a
  widget, and the answer depends on whether that widget paints itself.
* Bad, because QSS errors are silent. A typo'd selector or property name fails
  quietly, with no warning.
* Neutral, because two stylesheet files must stay in selector-sync. A new rule
  added to one and forgotten in the other produces a theme-specific visual bug.

### Confirmation

Only one inline `setStyleSheet` for static appearance remains, and it is the
documented `LedIndicator` exception. `tests/test_theme.py` covers theme
application; panel and strip tests assert the `*_active` property values that
drive the selectors, so the Python half of the contract is verified even though QSS
itself cannot be unit-tested.

## Pros and Cons of the Options

### One QSS file, dynamic properties, Python colours for painting

* Good, because each mechanism is used for what it is actually good at
* Good, because static appearance is centralised and state changes are cheap
* Bad, because the boundary needs explaining, and repolish is easy to forget

### Inline setStyleSheet per widget

* Good, because styling sits right next to the widget it affects
* Bad, because near-identical strings proliferate — four for one label's states
* Bad, because state changes mean rebuilding stylesheets at runtime
* Bad, because a theme swap would require touching every call site

### Per-widget QSS files

* Good, because it scopes rules narrowly and keeps files small
* Bad, because it multiplies file count and loading logic for a single-window app
* Bad, because it doubles again under two themes

### All appearance in Python

* Good, because it is uniform, with one mechanism and no silent selector failures
* Bad, because it discards Qt's native theming mechanism for the many widgets that
  are standard
* Bad, because Qt's stock widgets would have to be custom-painted to be styled at all

## More Information

* `e3dc6ba` — the consolidation and both dynamic-property patterns
* `45da26d` — documenting the `LedIndicator` exception
* `92d7d91` — the `:!checked` outline rules, an early payoff of declarative state
* Related: ADR-0018 (programmatic layout, which this complements), ADR-0020
  (theming), ADR-0021 (feature colour identity)
