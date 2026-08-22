---
status: accepted
date: 2026-04-16
decision-makers: Maximilian Zettler
---

# Mirror device configuration in a typed DeviceState dataclass

## Context and Problem Statement

The protocol library returns device configuration as a flat dictionary from
`parse_preset_params()`: parallel eight-element lists for `names`, `gains`,
`mutes`, `phases`, `link_flags`, plus output-only four-element lists for
`delays`, `crossovers`, `compressors`, `peqs`, `routings`, and nested dicts for
per-channel parameters.

That shape mirrors the wire format, which is exactly what a parser should do and
exactly what a UI should not consume. Every widget would need to know that
channel 5 means `gains[5]` but `delays[1]`, and every access would be an untyped
string key.

## Decision Drivers

* Inputs and outputs have genuinely different parameter sets — gates on inputs;
  delay, crossover, compressor, PEQ, and routing on outputs.
* The UI addresses channels with one flat index 0–7 (ADR-0006), while the data is
  split, so the offset translation has to live somewhere unambiguous.
* Several UI indicators are derived predicates over parameters, and the rule must
  not be duplicated per call site.
* The mirror must be updatable in place as edits happen, since edits are
  asynchronous and there is no read-back (ADR-0005).

## Considered Options

* A typed dataclass mirror with a `from_config` classmethod
* Pass the parser's dict around directly
* Read parameters back from the device whenever the UI needs them
* A generic nested-dict wrapper with attribute-style access

## Decision Outcome

Chosen option: a **typed dataclass mirror**, `DeviceState`
(`minidspqt/model.py`), holding four `InputChannelState` and four
`OutputChannelState` entries plus device-wide fields. `DeviceState.from_config`
converts the parser dict once, handling the input-0..3 / output-4..7 ordering
convention and renaming the PEQ band keys from the config's short forms
(`gain`, `freq`, `q`, `type`) to explicit ones (`gain_raw`, `freq_raw`, `q_raw`,
`filter_type`).

Three properties of the design are worth recording.

**Index translation lives in exactly one function.** `_channel_obj` resolves a
flat 0–7 index against the split layout and returns `None` when it cannot. Every
mutator routes through it, so the `channel - 4` arithmetic appears once rather
than at each call site, and out-of-range indices degrade to a falsy return rather
than an exception.

**Derived UI predicates are model properties, not view logic.** Four
`*_active` properties on `OutputChannelState` centralise rules that are otherwise
easy to get subtly wrong: `peq_active` is false when the channel bypass is set and
otherwise true when any band has `gain_raw != 120` and is not bypassed — raw 120
being 0 dB, so a band sitting at unity gain does not count as active regardless of
its frequency, Q, or type. `xover_active` tests `hipass_slope != 0 or lopass_slope
!= 0`, since slope 0 *is* the bypass state, ignoring frequency entirely.
`comp_active` is `ratio > 0`, raw 0 being 1:1.0. `delay_active` is
`delay_samples > 0`.

**Link topology is memoised with explicit invalidation.** `link_info` caches
`decode_link_groups` output, and `from_config` pre-warms it. `invalidate_link_cache()`
must be called after any `link_flags` mutation. This is the invariant behind the
mutator contract in ADR-0009.

Field values are stored as **raw protocol units** throughout, not engineering
units. Conversion to dB or milliseconds happens at the widget boundary.

### Consequences

* Good, because widgets read `state.outputs[i].compressor.ratio` instead of
  indexing a dict with a computed offset, and the type checker and IDE can help.
* Good, because indicator rules exist once, so home view and detail view cannot
  disagree about whether a channel is "active".
* Good, because raw-units storage means the mirror round-trips through
  `parse_preset_params`, `.unt` files, and device commands without lossy conversion.
* Good, because the mirror is cheap to mutate in place, which is what makes
  optimistic local updates plus asynchronous dispatch workable.
* Bad, because `from_config` requires five keys (`names`, `gains`, `mutes`,
  `phases`, `link_flags`) by direct subscripting, so a parser change that renames
  one produces a `KeyError` rather than a graceful degradation. That is a
  deliberate consequence of ADR-0012's error policy.
* Bad, because the memoised link cache introduces an invalidation obligation that
  is invisible at mutation sites.
* Neutral, because a few helpers still use a flat eight-element view rather than
  `_channel_obj` — `_link_flags_list` concatenates input and output `link_flags`,
  and the `is_linked_*`/`get_linked_slaves` helpers bound-check only the upper end.

### Confirmation

`tests/test_model.py` covers `from_config` channel-ordering and full field
propagation, every `*_active` rule at its boundary (including `ratio=0` versus
non-zero and the Limit value raw 15), and the mutators' out-of-range behaviour.

## Pros and Cons of the Options

### Typed dataclass mirror

* Good, because the shape matches how the UI thinks, not how the wire is framed
* Good, because derived rules and index translation each live in one place
* Bad, because every new protocol field needs adding in two places — parser and dataclass

### Pass the parser dict around

* Good, because there is no mapping layer to maintain
* Bad, because every consumer needs the offset convention and untyped keys
* Bad, because derived rules would be duplicated per call site, which is exactly
  how home view and detail view drift apart

### Read back from the device on demand

* Good, because there is only ever one source of truth
* Bad, because reads are asynchronous and slow; a repaint cannot wait on USB
* Bad, because it would make level-meter-rate repainting impossible

### Generic nested-dict wrapper

* Good, because it adapts automatically to new protocol fields
* Bad, because it gives up static typing, which is most of the benefit
* Bad, because there is still nowhere natural for derived predicates to live

## More Information

* `46bf3f5` — the dataclasses; `0d14eeb` — centralising mutation in the model;
  `558c433` — defensive firmware parsing (`cfg.get("firmware") or {}`), which
  yields empty strings offline and for `.unt` files, since neither has a device
* Related: ADR-0006 (the flat channel index), ADR-0009 (link-aware mutation),
  ADR-0014 (defaults in raw units)
