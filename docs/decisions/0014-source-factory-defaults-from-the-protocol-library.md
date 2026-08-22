---
status: accepted
date: 2026-05-09
decision-makers: Maximilian Zettler
---

# Source factory defaults from the protocol library rather than hardcoding them

## Context and Problem Statement

Several features need to know what "blank" means for a parameter: offline mode has
to start from a plausible configuration, the per-feature Reset buttons snap a
feature back to factory values, and double-clicking a knob resets it to its
default.

The convenient answer is a constant next to each widget. That was the original
approach, and it produced two visible bugs.

Offline mode started from hand-rolled values in `VirtualDSP._default_config()`
that did not match the device's actual F00 preset — wrong gate timings, low-pass
at 0 instead of 20.16 kHz, all PEQ bands sitting at 150 Hz. Worse, the bundled
`blank.unt` then *re-seeded* slot U01 with those same wrong values, so any in-RAM
correction was immediately masked (`8b54dcb`).

Separately, double-clicking a knob to reset it jumped to the knob's minimum rather
than its factory default, because `GAIN_RAW_DEFAULT` and friends were either wrong
or absent (`9cdf657`).

## Decision Drivers

* "Factory default" is a property of the firmware, not of a widget.
* The values are numerous and non-obvious in raw units, so hand-transcription is
  error-prone in a way that is hard to notice.
* Wrong defaults are a silent failure: the UI shows a plausible number that simply
  is not what the device would have.
* The values are needed in several unrelated places, so a single source matters.

## Considered Options

* Read defaults live from the protocol library's factory-defaults table
* Hardcode constants next to each widget or panel
* Read the F00 preset from a connected device at startup
* Ship a project-local copy of the defaults table

## Decision Outcome

Chosen option: **read defaults live from the protocol library.**
`minidspqt/defaults.py` thinly wraps `minidsp.defaults.load_factory_defaults()`,
which parses the library's bundled `factory_defaults.toml`. The wrapper exposes
one helper per feature, all returning raw protocol units:
`default_gate_state()`, `default_crossover_state()`, `default_compressor_state()`,
`default_peq_bands()`, `default_peq_channel_bypass()`, `default_delay_samples()`,
and `default_gain()`.

Upstream does no caching of its own, so caching is entirely on this side: a
private `_factory()` carries `@lru_cache(maxsize=1)`, making the TOML parse happen
once per process.

The same source feeds three consumers. `VirtualDSP` seeds both its initial config
and `load_preset(0)` from it, so offline mode and F00 recall agree. The
per-feature Reset buttons read it, so a reset always matches what the firmware
considers blank (`e64467b`, `44edd23`). And `ParamKnob`'s stored default value
comes from it, fixing the double-click behaviour and allowing `GAIN_RAW_DEFAULT`
to be deleted outright (`9cdf657`).

The `blank.unt` fix is the instructive half. Rather than correcting the template's
values, all 30 slots were **blanked** so the bundled file mimics a brand-new,
never-used DSP. The seeding path then falls through to factory defaults instead of
overwriting them — the template stopped competing with the authoritative source
(`8b54dcb`).

**This carries a device assumption worth stating plainly.** Every helper returns
the *first* channel's values — channel 0 for inputs, output 1 for outputs —
justified by defaults being identical across all four inputs and all four outputs
on the t.racks DSP 4x4 Mini. That is true for this device and is documented in the
module. On a device where per-channel defaults differ, these helpers would be
quietly wrong and would need a channel parameter.

### Consequences

* Good, because defaults cannot drift from the firmware; a correction upstream
  propagates on the next dependency bump (ADR-0003).
* Good, because offline mode, F00 recall, per-feature Reset, and knob double-click
  are guaranteed mutually consistent, because they read the same table.
* Good, because per-feature Reset needed no new architecture — it propagates
  through the existing edit signal flow and `mutate_with_links`, so linked slaves
  follow automatically (ADR-0009).
* Bad, because it deepens coupling to the library's data files, not just its API.
  A rename of the TOML structure breaks this even if the public API is unchanged.
* Bad, because the single-channel assumption is invisible at call sites; the
  helpers take no channel argument, so a multi-default device would need a
  signature change everywhere.
* Neutral, because the cached mapping is shared by every caller, so it must be
  treated as read-only. `factory_params()` documents that, and `VirtualDSP`
  deep-copies each slot key out of it rather than aliasing.

### Confirmation

Tests assert that `blank.unt` contains no stored presets, that a fresh
`VirtualDSP` matches `load_factory_defaults()` across all slot fields, and that
the end-to-end offline-startup path yields factory defaults. Knob tests cover
double-click resetting to the default value rather than the minimum.

## Pros and Cons of the Options

### Read live from the library

* Good, because the firmware's own table is the single source of truth
* Good, because one source serves four unrelated consumers consistently
* Bad, because it couples to the library's data layout as well as its API

### Hardcode constants per widget

* Good, because it is trivially simple with no dependency
* Bad, because transcription errors are silent and were the actual observed defect
* Bad, because the same value gets duplicated across offline seeding, reset, and knobs

### Read F00 from a connected device

* Good, because it is authoritative by definition, straight from the hardware
* Bad, because it is unavailable in offline mode, which is a primary consumer
* Bad, because it makes startup depend on a device round-trip

### Ship a local copy of the table

* Good, because it decouples from upstream file layout while staying data-driven
* Bad, because it is the drift problem again, just at file granularity instead of
  constant granularity

## More Information

* `8b54dcb` — offline seeding and the `blank.unt` blanking; `e64467b`, `44edd23` —
  per-feature Reset; `9cdf657` — knob defaults
* Related: ADR-0001 (upstream as source of truth), ADR-0008 (raw units),
  ADR-0010 (offline seeding), ADR-0016 (`blank.unt` as a writer template)
