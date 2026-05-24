"""Factory-default values for each per-channel feature.

These helpers expose the F00 factory preset's parameter values as plain
tuples / scalars suitable for seeding widgets and for the per-feature
"Reset" buttons in the detail view. The underlying dict comes from
``minidsp.defaults.load_factory_defaults()`` and is cached for the
lifetime of the process via ``functools.lru_cache``.

All factories return the *first channel's* values (channel 0 for inputs,
output 1 for outputs); the t.racks DSP 4x4 Mini ships with identical
defaults across all four inputs and all four outputs, so picking the
first slot is sufficient.
"""

from functools import lru_cache

from minidsp.defaults import load_factory_defaults


@lru_cache(maxsize=1)
def _factory() -> dict:
    return load_factory_defaults()["params"]


def default_gate_state() -> tuple:
    """Return the factory gate parameters as ``(attack, release, hold, threshold)``.

    Returns:
        Four raw protocol values in the same order the device expects them
        for ``cmd_gate``.
    """
    g = _factory()["gates"][0]
    return g["attack"], g["release"], g["hold"], g["threshold"]


def default_crossover_state() -> tuple:
    """Return the factory crossover as ``(hp_freq, hp_slope, lp_freq, lp_slope)``.

    Returns:
        Four raw protocol values: hi-pass frequency and slope index, then
        lo-pass frequency and slope index. Slope index 0 means "bypass".
    """
    x = _factory()["crossovers"][0]
    return x["hipass_freq"], x["hipass_slope"], x["lopass_freq"], x["lopass_slope"]


def default_compressor_state() -> tuple:
    """Return the factory compressor as ``(ratio, knee, attack, release, threshold)``.

    Returns:
        Five raw protocol values in the order ``cmd_compressor`` expects.
        ``ratio == 0`` corresponds to 1:1.0 (no compression).
    """
    c = _factory()["compressors"][0]
    return c["ratio"], c["knee"], c["attack"], c["release"], c["threshold"]


def default_peq_bands() -> list[tuple]:
    """Return the seven factory PEQ bands.

    Returns:
        A list of 7 tuples ``(gain, freq, q, type, bypass)`` in raw
        protocol units. ``gain == 120`` is 0 dB; ``bypass`` is a bool.
    """
    bands = _factory()["peqs"][0]["bands"]
    return [(b["gain"], b["freq"], b["q"], b["type"], b["bypass"]) for b in bands]


def default_peq_channel_bypass() -> bool:
    """Return the factory value of the per-channel PEQ bypass flag."""
    return _factory()["peqs"][0]["channel_bypass"]


def default_delay_samples() -> int:
    """Return the factory output-delay value, in samples (sample rate 48 kHz)."""
    return _factory()["delays"][0]


def default_gain() -> int:
    """Return the factory channel gain in raw protocol units (120 = 0 dB)."""
    return _factory()["gains"][0]
