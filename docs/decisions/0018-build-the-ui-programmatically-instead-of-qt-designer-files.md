---
status: accepted
date: 2026-05-06
decision-makers: Maximilian Zettler
---

# Build the UI programmatically instead of using Qt Designer .ui files

## Context and Problem Statement

The home view was originally a hybrid. A thin `.ui` file declared the skeleton —
header, three-column centre row, footer — compiled to `ui_home.py` by
`pyside6-uic` through a `scripts/build_ui.sh` helper. Everything of substance was
built in Python: all eight channel strips, the routing matrix interaction, and the
state-driven styling.

That split was inherited from the standard PySide6 project shape rather than
chosen. After a few months of layout work it was clear the `.ui` file was carrying
its weight in neither direction.

## Decision Drivers

* Almost every widget here is custom-painted (`LevelMeter`, `ParamKnob`, the five
  graphs, `RoutingMatrix`, `LedIndicator`) or composite-built (`ChannelStrip`), and
  therefore not meaningfully editable in Designer.
* The repetitive parts — eight channel strips — are exactly what a loop expresses
  better than eight copies in XML.
* Every layout tweak required regenerating and committing a derived file.
* Generated files in version control invite merge conflicts and stale-artifact bugs.

## Considered Options

* Build everything programmatically in Python
* Keep the hybrid: `.ui` for skeletons, Python for custom widgets
* Move fully to `.ui` files, with promoted custom widgets

## Decision Outcome

Chosen option: **build everything programmatically.** The skeleton moved into
`HomeView._build_ui()`, and `home.ui`, the generated `ui_home.py`, the empty `ui/`
and `forms/` directories, `scripts/build_ui.sh`, and the associated `.gitignore`
rule were all deleted (`1bb08d1`).

**This reverses the project's initial approach.** The original home view commit
(`10552ee`) chose the hybrid explicitly, reasoning that the `.ui` file would keep
the form compact and Designer-friendly while the repetitive strips were built in
Python. In practice the Designer-friendliness never materialised, because there
was nothing in the file a designer could usefully manipulate — while the
regen-and-commit tax was paid on every layout change.

The refactor was done so that all ten named widgets (`titleLabel`,
`connectionLabel`, `menuButton`, `presetLabel`, `storeButton`, `recallButton`,
`inputsLayout`, `outputsLayout`, `rootLayout`, `routingMatrix`) kept their names
and types, leaving the rest of `HomeView` and all of `MainWindow` untouched. That
kept a structural change from becoming a behavioural one.

Every view added since — the detail view, all six feature panels, and six dialogs
— has been built programmatically, so this is now the project's uniform pattern.

The decision is not free-standing: it is what makes QSS-based styling the natural
choice for appearance (ADR-0019), since layout in Python plus appearance in
stylesheets is a cleaner split than layout in XML plus appearance in two places.

### Consequences

* Good, because there is no build step for the UI, no generated files in version
  control, and no possibility of a stale artifact.
* Good, because repetition is expressed as iteration. Eight channel strips are a
  loop, and adding a ninth would be a constant change.
* Good, because layout can be conditional — feature panels vary by channel type
  (ADR-0022), which XML cannot express.
* Good, because everything lives in one language, so following a widget from
  construction to signal wiring needs no context switch.
* Bad, because there is no visual preview. Layout changes are edit-run-look cycles,
  which is slower for pure visual tuning.
* Bad, because it forgoes Designer entirely, so a contributor who prefers visual
  tooling has no on-ramp. Judged acceptable given that the custom-painted widgets
  were never Designer-editable anyway.
* Neutral, because `_build_ui()` methods are long and mechanical. Verbose but
  unambiguous, and they read in the same order the widgets nest.

### Confirmation

No `.ui` or generated `ui_*.py` file exists anywhere in the repository, and there
is no UI build step in the [Makefile](https://github.com/IMBArator/miniDSP-Linux-qt/blob/main/Makefile).
The full suite passed unchanged across the refactor, which is what confirmed the
widget names and types had genuinely been preserved.

## Pros and Cons of the Options

### Fully programmatic

* Good, because no build step, no generated artifacts, no staleness
* Good, because repetition and conditional layout are expressible
* Bad, because there is no visual preview or Designer on-ramp

### Hybrid (.ui skeleton plus Python widgets)

* Good, because it is the conventional PySide6 shape, familiar to newcomers
* Neutral, because it works, and did for several months
* Bad, because the `.ui` file held nothing Designer-editable, so it delivered no
  round-trip benefit while taxing every layout change — the actual observed outcome

### Fully .ui with promoted custom widgets

* Good, because layout would be visually editable and separated from logic
* Bad, because promoted custom widgets appear in Designer as blank placeholders,
  so the preview would show empty boxes where every meaningful widget is
* Bad, because the eight channel strips would become eight XML copies

## More Information

* `10552ee` — the original hybrid, and its stated reasoning
* `1bb08d1` — the reversal, with the name-and-type preservation constraint
* Related: ADR-0019 (QSS styling, which this enables), ADR-0022 (conditional
  panel composition, which XML could not express)
