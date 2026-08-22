---
status: accepted
date: 2026-05-12
decision-makers: Maximilian Zettler
---

# Give each DSP feature one brand hue, reused across button, indicator, and graph

## Context and Problem Statement

Each channel strip carries a row of feature buttons — gate, mute, phase, xover,
peq, comp, delay. Each has three visual states: off, engaged as a toggle or
navigated-to, and "active", meaning the feature is actually doing something to the
signal (a PEQ band with non-zero gain, a crossover that is not bypassed, a
compressor with a ratio other than 1:1, a non-zero delay).

Each feature also has a detail panel containing a graph. So there are three
independent opportunities to pick a colour per feature, across two views, and the
question is whether they should be related.

## Decision Drivers

* Users need to see at a glance which features are engaged on which channel,
  across eight strips.
* A colour that means one thing in the strip and another in the panel makes the UI
  harder to read, not easier.
* Buttons must be distinguishable from each other in a tight horizontal row.
* Every colour has to work in both themes (ADR-0020).

## Considered Options

* One brand hue per feature, reused for the button in all states, the active
  indicator, and that feature's graph curve
* A separate semantic colour for "active" state, shared across all features
* Per-feature hues for buttons, with a single neutral colour for all graphs
* No colour coding; rely on labels and iconography

## Decision Outcome

Chosen option: **one brand hue per feature**, applied consistently everywhere that
feature appears.

The rule has three parts:

**Unchecked buttons outline in their accent.** Rather than a uniform grey, each
button paints its own accent on the border and text when off, and fills with the
same accent when on — giving the strip an outlined-when-idle, filled-when-engaged
feel via `:!checked` rules (`92d7d91`).

**Active indicators deepen the existing hue rather than introducing a new one.**
This is the part most easily got wrong, and it is a deliberate rule: a `*_active`
style reuses the same colour as that button's `:checked` state. The indicator
therefore signals *state* and never re-skins the button. Comp active uses the
button's own teal (`#2fa89b` dark, `#1e857a` light); delay active uses the button's
own blue (`#6c92c2` dark, `#4d7299` light). A new hue for "active" would make the
same button read as a different control depending on its value.

**Graph curves match their feature's button.** Each graph — gate, PEQ, xover,
compressor — draws in the same colour as the strip button that opens it, so it is
immediately obvious which feature a plot belongs to. Per-feature colours were added
to the `Theme` dataclass for both modes to support this (`b5563ba`).

Hues were tuned for discriminability rather than picked once. Xover moved to a
red-orange amber (`#e87223` dark, `#a85011` light) because its original hue was too
close to the surrounding chrome buttons, and phase was pushed further yellow
(`#e0b820` dark, `#c19a14` light) to open separation between the two warm hues
(`2ad696d`).

The overlay feature extends the same principle to a different axis: a stable
four-colour ring keyed by output index, so a given output keeps its colour
regardless of which channel is being viewed, and the checkbox row doubles as a
legend (ADR-0022).

### Consequences

* Good, because engaged features are readable across all eight strips at a glance,
  which is the actual task.
* Good, because a graph never needs a title to identify itself; its colour does it.
* Good, because the rule for adding a feature is mechanical: pick a hue, add
  `Theme` fields for both modes, add the `:checked` and `*_active` QSS rules, and
  reuse it for the graph curve.
* Bad, because the palette is nearly exhausted. Seven features plus chrome plus a
  four-colour overlay ring already forced two hue adjustments, and a further feature
  would be hard to place distinctly.
* Bad, because it is a convention with no enforcement. Nothing prevents a future
  `*_active` rule from introducing a new colour, and the resulting inconsistency
  would look like a deliberate signal rather than a mistake.
* Bad, because each hue needs a hand-tuned light-mode counterpart; the dark value
  is generally too saturated for a light background, so every colour is really two
  decisions.
* Neutral, because accessibility is not addressed. Colour is the primary channel
  for active state, with no shape or texture redundancy, so this UI is weak for
  colour-vision deficiency. Worth revisiting.

### Confirmation

Strip and panel tests assert the `*_active` property values that select these
rules, and graph tests assert that curve colours come from the theme registry
rather than local constants. The visual consistency itself is a review
responsibility — the rule is not machine-checked.

## Pros and Cons of the Options

### One brand hue per feature

* Good, because a colour means exactly one thing everywhere it appears
* Good, because adding a feature is a mechanical recipe
* Bad, because the palette is finite and nearly spent
* Bad, because it is convention-only and unenforced

### A separate semantic colour for "active"

* Good, because "active" would read identically across all features, and one new
  colour would cover every future feature
* Bad, because the button changes hue based on its value, so it reads as a
  different control — the specific outcome this decision rejects
* Neutral, because it would conserve the palette

### Per-feature buttons, neutral graphs

* Good, because graph colour could then encode something else, such as curve identity
* Bad, because a panel's graph loses its visual link to the button that opened it
* Bad, because with overlays present (ADR-0022), a neutral active curve competes
  poorly with coloured overlay curves

### No colour coding

* Good, because it sidesteps palette exhaustion and colour-accessibility concerns
* Bad, because scanning eight strips for engaged features becomes label-reading
* Bad, because the at-a-glance overview is the home view's main purpose

## More Information

* `92d7d91` — outline-when-unchecked; `2ad696d` — hue separation tuning;
  `b5563ba` — graph curves matched to button accents; `81b1806`, `5fb6927` — the
  reuse-the-checked-colour rule for comp and delay indicators
* Related: ADR-0019 (QSS properties that select these rules), ADR-0020 (the theme
  registry holding the hues), ADR-0022 (the overlay colour ring)
