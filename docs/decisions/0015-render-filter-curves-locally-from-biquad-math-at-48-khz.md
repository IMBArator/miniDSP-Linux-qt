---
status: accepted
date: 2026-05-08
decision-makers: Maximilian Zettler
---

# Render filter response curves locally from biquad maths at the device's 48 kHz rate

## Context and Problem Statement

The PEQ and crossover panels are unusable without a frequency-response plot. The
user needs to see the summed effect of seven PEQ bands plus a high-pass and
low-pass filter, and needs it to track a knob as it moves.

The device offers no way to ask for this. The protocol exposes filter
*parameters* — frequency, gain, Q, type, slope — and nothing resembling a computed
magnitude response. So either the application computes the curve itself, or there
is no curve.

## Decision Drivers

* The plot must update live during a knob drag, so it cannot involve device I/O.
* The curve should represent what the hardware actually does, not an idealised
  analogue approximation.
* Both the PEQ and crossover panels need the *same* summed curve, since the two
  filter stages interact.
* Filter maths is the one place where duplicating protocol-adjacent knowledge is
  unavoidable, so the duplication should be contained and documented.

## Considered Options

* Compute curves locally from biquad coefficients, in the digital domain at the
  device's sample rate
* Compute curves from idealised analogue transfer functions
* Query the device for a response
* Show parameter values only, with no plot

## Decision Outcome

Chosen option: **compute locally from biquad coefficients using Audio EQ Cookbook
(RBJ) formulas, evaluated at the device's actual internal sample rate of 48 kHz.**

`_FS_HZ = 48_000.0` in `minidspqt/widgets/freq_response_graph.py`. The rate is
established by the protocol documentation: the 0x38 delay opcode is specified as
samples at 48 kHz, with max 32640 = 680 ms.

This is the deliberate exception to ADR-0001's rule that protocol knowledge lives
upstream. It is acceptable because the maths is **display-only** and never produces
a value sent to the device — but it means the digital domain matters. Coefficients
are computed via bilinear transform at `_FS_HZ`, so the plotted curve inherits the
same frequency warping the hardware has, and a resonant peak appears where the
device actually puts it.

That distinction was learned the hard way. The graphs initially used 96 kHz and
the user guide claimed the approximation was "virtually identical". It is not:
bilinear warping at 96 kHz versus 48 kHz shifts high-frequency resonance peaks
away from where they land in hardware — true enough at low and mid frequencies,
increasingly wrong approaching Nyquist. Both the constant and the documentation
were corrected (`1b57275`).

Crossover slopes map to cascaded sections dispatched on the protocol's `SLOPE_*`
constants, with Bessel and Butterworth Q tables and Linkwitz-Riley expressed as
two cascaded Butterworth pairs. PEQ types use standard RBJ formulas for peaking,
low/high shelf, low/high pass, and second-order allpass.

**Three known approximations are recorded deliberately, because a plot that
misleads is worse than no plot:**

* The 18 dB/oct families are approximated with two second-order sections and no
  first-order stage, so `_BUTTERWORTH_Q[3]` and `_BESSEL_Q[3]` render a 24 dB/oct
  asymptotic slope rather than 18.
* First-order allpass and any unrecognised PEQ type return an identity biquad.
  The graph is magnitude-only by design; allpass phase response is not plotted at all.
* The y-axis spans ±18 dB while raw PEQ gain spans only ±12 dB. The 6 dB of
  headroom is intentional so the summed curve has room, and marker drags clamp to
  12 dB so a marker cannot be dragged into dead axis space.

Slope 0 contributes nothing, because slope 0 *is* the bypass state — which is also
why interactive bypass needed no new data field (ADR-0022).

### Consequences

* Good, because the curve updates instantly during a drag, with no device round-trip.
* Good, because it works identically in offline mode, where there is no device at all.
* Good, because evaluating in the digital domain at the correct rate means the plot
  is faithful near Nyquist, where an analogue approximation diverges most.
* Good, because a single shared graph serves both panels, so the crossover and PEQ
  contributions are summed rather than shown separately (ADR-0022).
* Bad, because filter maths is duplicated knowledge that the device could
  contradict. There is no way to verify the plot against the hardware's actual
  response short of acoustic measurement.
* Bad, because the three approximations above are real inaccuracies. The 18 dB/oct
  case is the most likely to mislead, since it plots a steeper slope than selected.
* Neutral, because the sample rate is redefined here rather than imported. The
  upstream library encodes 48 kHz only implicitly, inside `delay_samples_to_ms`
  as `raw / 48.0`. Exposing a public `SAMPLE_RATE_HZ` constant upstream was
  suggested at the time (`1b57275`) and would remove this duplication.

### Confirmation

`tests/test_xover_panel.py` covers the biquad maths, and deliberately imports
`_FS_HZ` rather than hardcoding a rate, so the tests self-scale if the constant
changes — which is why the 96 kHz correction needed no test edits.
`tests/test_freq_response_graph_overlay.py` covers the shared response-polyline
helper for flat and active cases.

## Pros and Cons of the Options

### Local biquads at the device sample rate

* Good, because it is instant, works offline, and is faithful near Nyquist
* Bad, because it duplicates filter knowledge with no way to verify against hardware
* Bad, because it carries documented approximations for odd-order slopes

### Idealised analogue transfer functions

* Good, because the formulas are simpler and slope behaviour is exact by construction
* Bad, because it ignores bilinear warping, so it diverges from the hardware exactly
  where users care — high-frequency crossover points
* Neutral, because at low and mid frequencies the two agree closely

### Query the device

* Good, because it would be authoritative
* Bad, because the protocol has no such command; this is not available at any price
* Bad, because even if it existed, per-drag latency would make it unusable

### No plot

* Good, because nothing can be wrong
* Bad, because seven-band PEQ plus a crossover is not tunable by numbers alone

## More Information

* Robert Bristow-Johnson, *Audio EQ Cookbook* — the coefficient formulas
* `d665602` — the PEQ graph; `c03eddc` — extraction of the shared
  `FreqResponseGraph` with crossover families; `1b57275` — the 96 kHz → 48 kHz
  correction and the documentation fix
* Related: ADR-0001 (why this is the exception), ADR-0022 (the shared graph widget)
