"""Level-payload adapter: one place that knows the meter's units.

The DSP reports every channel level as a **24-bit linear amplitude**. The
legacy ``uint16`` value that ``parse_levels`` has always returned is simply
its upper 16 bits (``level24 >> 8``), i.e. 24-bit units are ``uint16`` units
times :data:`LEVEL24_PER_UINT16`. The GUI works in 24-bit units end to end
because the extra byte is worth ~0.0005 dB of resolution near 0 dBu instead
of ~0.1 dB, so bars and readouts stop stepping visibly.

This module exists for two reasons:

1. **One import point.** Widgets and views take the level symbols from
   here, never from ``minidsp.protocol`` directly, so a change in the
   library's level API has exactly one place to adapt. (While the 24-bit
   API was still unreleased upstream, this is where the compatibility
   fallback lived; it was deleted when the pin moved to minidsp-linux
   v1.4.0.)
2. **Normalisation.** ``levels_from_payload`` turns whatever shape a poll
   response has (with or without the 24-bit and clipping keys) into a single
   :class:`ChannelLevels` record, keeping the three ``update_levels`` methods
   in the views trivial and identical.

Channel indices follow the project-wide convention: 0–3 are the inputs
InA–InD, 4–7 are the outputs Out1–Out4.
"""

from __future__ import annotations

from dataclasses import dataclass

from minidsp.protocol import (
    LEVEL24_PER_UINT16,
    LEVEL_CLIP_LEVEL24,
    level24_is_clipping,
    level24_to_dbu,
)

NUM_INPUTS = 4
NUM_CHANNELS = 8

__all__ = [
    "LEVEL24_PER_UINT16",
    "LEVEL_CLIP_LEVEL24",
    "ChannelLevels",
    "clip_for",
    "level24_for",
    "level24_is_clipping",
    "level24_to_dbu",
    "levels_from_payload",
]


@dataclass(frozen=True)
class ChannelLevels:
    """One poll cycle's levels, normalised to 24-bit units.

    Attributes:
        inputs24: Input levels InA–InD as 24-bit linear amplitudes.
        outputs24: Output levels Out1–Out4, same units.
        clipping: Per-channel clip flags in channel order (inputs
            0–3 then outputs 4–7), or ``None`` when the payload did
            not carry them — the meter then decides on the level
            itself via :func:`level24_is_clipping`.
    """

    inputs24: list[int]
    outputs24: list[int]
    clipping: list[bool] | None = None


def levels_from_payload(payload: dict) -> ChannelLevels:
    """Normalise a ``parse_levels`` payload into :class:`ChannelLevels`.

    Prefers the ``inputs24`` / ``outputs24`` keys. When they are absent
    (a protocol library older than the 24-bit API) the legacy uint16
    lists are scaled by :data:`LEVEL24_PER_UINT16`, which is exact: the
    uint16 value *is* the upper 16 bits of the 24-bit one, so the
    reconstruction only loses the low byte the old parser dropped.

    Args:
        payload: The dict produced by ``parse_levels`` /
            ``poll_levels``. Recognised keys: ``inputs``, ``outputs``,
            and optionally ``inputs24``, ``outputs24``, ``clipping``.

    Returns:
        The levels in 24-bit units, with ``clipping`` set only when the
        payload carried a full per-channel flag list.
    """
    inputs24 = payload.get("inputs24")
    if inputs24 is None:
        inputs24 = [v * LEVEL24_PER_UINT16 for v in payload.get("inputs", [])]
    outputs24 = payload.get("outputs24")
    if outputs24 is None:
        outputs24 = [v * LEVEL24_PER_UINT16 for v in payload.get("outputs", [])]

    clipping = payload.get("clipping")
    if not isinstance(clipping, list) or len(clipping) < NUM_CHANNELS:
        clipping = None

    return ChannelLevels(
        inputs24=list(inputs24),
        outputs24=list(outputs24),
        clipping=clipping,
    )


def level24_for(levels: ChannelLevels, channel: int) -> int | float | None:
    """Return one channel's 24-bit level.

    Args:
        levels: The normalised payload.
        channel: Absolute channel index, 0–3 inputs, 4–7 outputs.

    Returns:
        The 24-bit level, or ``None`` when the payload has no value for
        that channel (a short or missing list). Callers reset the
        corresponding meter in that case.
    """
    if channel < 0:
        return None
    if channel < NUM_INPUTS:
        values = levels.inputs24
        index = channel
    else:
        values = levels.outputs24
        index = channel - NUM_INPUTS
    if index >= len(values):
        return None
    return values[index]


def clip_for(levels: ChannelLevels, channel: int) -> bool | None:
    """Return one channel's clip flag as reported by the device parser.

    Args:
        levels: The normalised payload.
        channel: Absolute channel index, 0–3 inputs, 4–7 outputs.

    Returns:
        The flag, or ``None`` when the payload carried none — the meter
        then applies :func:`level24_is_clipping` to the raw level, which
        is the same rule the parser uses.
    """
    if levels.clipping is None or not 0 <= channel < len(levels.clipping):
        return None
    return levels.clipping[channel]
