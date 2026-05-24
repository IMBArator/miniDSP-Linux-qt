"""Typed device state mirroring the dict returned by DSPmini.read_config().

`DSPmini.read_config()` returns the dict produced by
`minidsp.protocol.parse_preset_params()` plus `active_slot` and
`preset_names`. Channel ordering across the list fields is
inputs 0–3, outputs 4–7. `gates` is input-only; `delays`, `crossovers`,
`compressors`, `peqs`, `routings` are output-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar

from minidsp.protocol import decode_link_groups, decode_routing_matrix


@dataclass
class GateState:
    """Per-input noise-gate parameters, in raw protocol units.

    Defaults are all zero, which is the "fully open" state (no gating).
    See ``analysis/protocol.md`` for the exact dB/ms encoding of each
    field.
    """

    attack: int = 0
    release: int = 0
    hold: int = 0
    threshold: int = 0


@dataclass
class CrossoverState:
    """Per-output crossover (hi-pass + lo-pass), in raw protocol units.

    ``hipass_slope`` / ``lopass_slope`` of 0 means the corresponding
    filter is bypassed; the panel keeps a separate "last non-bypass
    slope" so the user can toggle the filter on without losing their
    selection.
    """

    hipass_freq: int = 0
    hipass_slope: int = 0
    lopass_freq: int = 0
    lopass_slope: int = 0


@dataclass
class CompressorState:
    """Per-output compressor parameters, in raw protocol units.

    ``ratio == 0`` corresponds to 1:1.0 (no compression). The other
    fields use the encodings documented in ``analysis/protocol.md``.
    """

    ratio: int = 0
    knee: int = 0
    attack: int = 0
    release: int = 0
    threshold: int = 0


@dataclass
class TestToneState:
    """State of the device's internal test signal generator.

    Unlike the per-channel states, this is device-wide: the generator feeds
    all outputs simultaneously and its state is persisted in the live config
    at offsets 420 (mode) and 422 (last sine freq index).
    """

    # __test__ tells pytest's name-based heuristic that this is a
    # domain class, not a test class; without it pytest emits a
    # PytestCollectionWarning every run.
    __test__: ClassVar[bool] = False

    mode: int = 0  # TONE_OFF / TONE_PINK / TONE_WHITE / TONE_SINE
    sine_freq_index: int = 0  # 0..30, ISO 1/3-octave (20 Hz … 20 kHz)


@dataclass
class PEQBand:
    """A single parametric-EQ band, in raw protocol units.

    ``gain_raw == 120`` corresponds to 0 dB (flat). ``filter_type``
    indexes the protocol's filter-type table (peak, shelf, pass,
    allpass …). When ``bypass`` is True the band is muted regardless
    of its other values.
    """

    gain_raw: int = 0
    freq_raw: int = 0
    q_raw: int = 0
    filter_type: int = 0
    bypass: bool = False


@dataclass
class InputChannelState:
    """Mirror of one of the 4 input channels (InA–InD).

    Mirrors the per-channel fields ``DSPmini.read_config()`` returns
    plus the channel name. ``link_flags`` is the raw OR-bitmask used
    by the link-group decoder; see ``decode_link_groups`` in the
    upstream protocol library.
    """

    name: str = ""
    gain_raw: int = 0
    muted: bool = False
    phase_inverted: bool = False
    gate: GateState = field(default_factory=GateState)
    link_flags: int = 0


@dataclass
class OutputChannelState:
    """Mirror of one of the 4 output channels (Out1–Out4).

    Carries the full signal-chain state for an output: gain/mute/phase,
    output delay, crossover, compressor, seven PEQ bands plus the
    channel-wide PEQ bypass, the routing mask from the 4×4 input matrix,
    and the link-group bitmask.
    """

    name: str = ""
    gain_raw: int = 0
    muted: bool = False
    phase_inverted: bool = False
    delay_samples: int = 0
    crossover: CrossoverState = field(default_factory=CrossoverState)
    compressor: CompressorState = field(default_factory=CompressorState)
    peqs: list[PEQBand] = field(default_factory=list)
    peq_channel_bypass: bool = False
    routing_mask: int = 0
    link_flags: int = 0

    @property
    def peq_active(self) -> bool:
        """True if the PEQ block is shaping the signal.

        At least one band must have non-zero gain (raw 120 = 0 dB) and
        not be bypassed, with the channel-wide bypass off.
        """
        if self.peq_channel_bypass:
            return False
        return any(b.gain_raw != 120 and not b.bypass for b in self.peqs)

    @property
    def xover_active(self) -> bool:
        """True if either crossover filter is not bypassed.

        A slope index of 0 means "bypass" for that half of the
        crossover; the channel is only considered active when at
        least one of hi-pass or lo-pass has a real slope set.
        """
        return self.crossover.hipass_slope != 0 or self.crossover.lopass_slope != 0

    @property
    def comp_active(self) -> bool:
        """True if the compressor is applying a non-unity curve.

        Raw ratio 0 corresponds to 1:1.0 (no compression); any
        higher raw value applies a real curve.
        """
        return self.compressor.ratio > 0

    @property
    def delay_active(self) -> bool:
        """True if the output delay is non-zero."""
        return self.delay_samples > 0


@dataclass
class DeviceState:
    """Full mirror of the active preset, plus connection status."""

    connected: bool = False
    inputs: list[InputChannelState] = field(default_factory=list)
    outputs: list[OutputChannelState] = field(default_factory=list)
    active_slot: int | None = None
    preset_names: list[str] = field(default_factory=list)
    test_tone: TestToneState = field(default_factory=TestToneState)
    _link_info_cache: list[dict] | None = field(default=None, repr=False)

    def _link_flags_list(self) -> list[int]:
        flags = [ch.link_flags for ch in self.inputs]
        flags += [ch.link_flags for ch in self.outputs]
        return flags

    @property
    def link_info(self) -> list[dict]:
        """Cached per-channel link-group decoding for all 8 channels.

        Returns the list produced by ``decode_link_groups`` — each
        entry is a dict with ``"role"`` (``"master"``/``"slave"``/
        ``"standalone"``) and ``"linked_to"`` (list of channel
        indices in the group). The result is memoized; call
        ``invalidate_link_cache`` after mutating any ``link_flags``.
        """
        if self._link_info_cache is None:
            self._link_info_cache = decode_link_groups(self._link_flags_list())
        return self._link_info_cache

    def invalidate_link_cache(self) -> None:
        """Drop the memoized ``link_info`` so the next read re-decodes.

        Call this after mutating any ``link_flags`` field — the linking
        dialog does this after applying a new topology.
        """
        self._link_info_cache = None

    def is_linked_slave(self, channel: int) -> bool:
        """Return True if ``channel`` is a slave in its link group.

        Args:
            channel: 0–3 for inputs, 4–7 for outputs. Out-of-range
                values return False.
        """
        if channel >= len(self.link_info):
            return False
        return self.link_info[channel]["role"] == "slave"

    def is_linked_master(self, channel: int) -> bool:
        """Return True if ``channel`` is a master in its link group.

        Args:
            channel: 0–3 for inputs, 4–7 for outputs. Out-of-range
                values return False.
        """
        if channel >= len(self.link_info):
            return False
        return self.link_info[channel]["role"] == "master"

    def get_linked_slaves(self, channel: int) -> list[int]:
        """Return the channel indices that follow ``channel`` as slaves.

        Args:
            channel: A master channel index (0–7). For a non-master
                channel the list is empty.

        Returns:
            Slave channel indices, with ``channel`` itself excluded.
            Empty for slaves, standalone channels, and out-of-range
            inputs.
        """
        if channel >= len(self.link_info):
            return []
        info = self.link_info[channel]
        if info["role"] == "master":
            return [ch for ch in info["linked_to"] if ch != channel]
        return []

    def _channel_obj(
        self, channel: int
    ) -> InputChannelState | OutputChannelState | None:
        if 0 <= channel < 4 and channel < len(self.inputs):
            return self.inputs[channel]
        if 4 <= channel < 8 and (channel - 4) < len(self.outputs):
            return self.outputs[channel - 4]
        return None

    def set_field(self, channel: int, field: str, value: Any) -> bool:
        """Set a single attribute on the channel state at ``channel``.

        Args:
            channel: 0–3 for inputs, 4–7 for outputs.
            field: Attribute name on the channel state object.
            value: New value for ``field``.

        Returns:
            True if ``channel`` resolves to a real channel state and the
            attribute was set, False otherwise.
        """
        obj = self._channel_obj(channel)
        if obj is None:
            return False
        setattr(obj, field, value)
        return True

    def mutate_with_links(
        self,
        channel: int,
        mutator: Callable[[InputChannelState | OutputChannelState], None],
    ) -> list[int]:
        """Apply ``mutator`` to ``channel`` and each of its linked slaves.

        The same callable runs on the master and on every slave, which
        keeps the on-screen model in lock-step with the master without
        copying a snapshot.

        Args:
            channel: 0–3 for inputs, 4–7 for outputs.
            mutator: Callable that receives a channel state object and
                sets parameter fields on it (e.g.
                ``lambda obj: setattr(obj.gate, "threshold", 50)``).
                Must touch only parameter fields, never ``link_flags`` —
                mutating link flags here corrupts the cached link
                topology and is the linking dialog's job.

        Returns:
            The list of affected channels with ``channel`` first.
            Empty if ``channel`` is out of range. When ``channel`` is
            itself a slave, the mutator runs on it alone — slaves are
            read-only mirrors of their master and don't drive fan-out.
        """
        obj = self._channel_obj(channel)
        if obj is None:
            return []
        mutator(obj)
        affected = [channel]
        for slave in self.get_linked_slaves(channel):
            slave_obj = self._channel_obj(slave)
            if slave_obj is not None:
                mutator(slave_obj)
                affected.append(slave)
        return affected

    def set_field_with_links(
        self, channel: int, field: str, value: Any
    ) -> list[int]:
        """Set one flat attribute on ``channel`` and on every linked slave.

        Thin wrapper around ``mutate_with_links`` for flat-attribute
        edits (gain, mute, phase).

        Args:
            channel: 0–3 for inputs, 4–7 for outputs.
            field: Attribute name on the channel state object.
            value: New value for ``field``.

        Returns:
            The list of affected channels, so the caller can fan the
            same change out to the device thread and UI in one pass.
        """
        return self.mutate_with_links(channel, lambda obj: setattr(obj, field, value))

    @property
    def routing_info(self) -> list[dict]:
        """Decoded routing matrix for the 4 outputs.

        Returns the list produced by ``decode_routing_matrix`` —
        one entry per output describing which inputs are routed
        to it.
        """
        return decode_routing_matrix([ch.routing_mask for ch in self.outputs])

    def copy_params(
        self, source: int, targets: list[int], groups: set[str]
    ) -> list[dict]:
        """Copy selected parameter groups from ``source`` to each target.

        Source and target must be the same channel type (input or
        output) — cross-type copies silently produce no changes. The
        method does **not** check whether targets are linked slaves;
        that gating is the copy-channel dialog's responsibility.

        Args:
            source: Source channel index (0–3 for inputs, 4–7 for
                outputs).
            targets: Target channel indices. ``source`` itself should
                normally be excluded by the caller.
            groups: Parameter groups to copy. Valid keys are:

                * Inputs: ``"name"``, ``"gain"``, ``"mute"``,
                  ``"phase"``, ``"gate"``.
                * Outputs: ``"name"``, ``"gain"``, ``"mute"``,
                  ``"phase"``, ``"routing"``, ``"crossover"``,
                  ``"peq"``, ``"compressor"``, ``"delay"``.

                Keys not valid for the source's channel type are
                silently ignored.

        Returns:
            A list of change descriptors, one per modified field. Each
            descriptor is a dict with keys ``"channel"`` (int),
            ``"field"`` (internal field name), ``"value"`` (the new
            value) and ``"cmd_type"`` (string used to map the change to
            a ``DeviceThread`` request method). PEQ-band descriptors
            also include a ``"band"`` index. The caller iterates the
            list to fan changes out to the device.
        """
        changes: list[dict] = []
        source_obj = self._channel_obj(source)
        if source_obj is None:
            return changes

        if isinstance(source_obj, InputChannelState):
            valid_groups = {"name", "gain", "mute", "phase", "gate"}
        else:
            valid_groups = {
                "name",
                "gain",
                "mute",
                "phase",
                "routing",
                "crossover",
                "peq",
                "compressor",
                "delay",
            }

        groups = groups & valid_groups
        if not groups:
            return changes

        for target in targets:
            target_obj = self._channel_obj(target)
            if target_obj is None:
                continue

            if isinstance(target_obj, InputChannelState) and isinstance(
                source_obj, InputChannelState
            ):
                for group in groups:
                    if group == "name":
                        target_obj.name = source_obj.name
                        changes.append(
                            {
                                "channel": target,
                                "field": "name",
                                "value": source_obj.name,
                                "cmd_type": "CHANNEL_NAME",
                            }
                        )
                    elif group == "gain":
                        target_obj.gain_raw = source_obj.gain_raw
                        changes.append(
                            {
                                "channel": target,
                                "field": "gain_raw",
                                "value": source_obj.gain_raw,
                                "cmd_type": "GAIN",
                            }
                        )
                    elif group == "mute":
                        target_obj.muted = source_obj.muted
                        changes.append(
                            {
                                "channel": target,
                                "field": "muted",
                                "value": source_obj.muted,
                                "cmd_type": "MUTE",
                            }
                        )
                    elif group == "phase":
                        target_obj.phase_inverted = source_obj.phase_inverted
                        changes.append(
                            {
                                "channel": target,
                                "field": "phase_inverted",
                                "value": source_obj.phase_inverted,
                                "cmd_type": "PHASE",
                            }
                        )
                    elif group == "gate":
                        target_obj.gate = GateState(
                            attack=source_obj.gate.attack,
                            release=source_obj.gate.release,
                            hold=source_obj.gate.hold,
                            threshold=source_obj.gate.threshold,
                        )
                        changes.append(
                            {
                                "channel": target,
                                "field": "gate",
                                "value": (
                                    source_obj.gate.attack,
                                    source_obj.gate.release,
                                    source_obj.gate.hold,
                                    source_obj.gate.threshold,
                                ),
                                "cmd_type": "GATE",
                            }
                        )

            elif isinstance(target_obj, OutputChannelState) and isinstance(
                source_obj, OutputChannelState
            ):
                for group in groups:
                    if group == "name":
                        target_obj.name = source_obj.name
                        changes.append(
                            {
                                "channel": target,
                                "field": "name",
                                "value": source_obj.name,
                                "cmd_type": "CHANNEL_NAME",
                            }
                        )
                    elif group == "gain":
                        target_obj.gain_raw = source_obj.gain_raw
                        changes.append(
                            {
                                "channel": target,
                                "field": "gain_raw",
                                "value": source_obj.gain_raw,
                                "cmd_type": "GAIN",
                            }
                        )
                    elif group == "mute":
                        target_obj.muted = source_obj.muted
                        changes.append(
                            {
                                "channel": target,
                                "field": "muted",
                                "value": source_obj.muted,
                                "cmd_type": "MUTE",
                            }
                        )
                    elif group == "phase":
                        target_obj.phase_inverted = source_obj.phase_inverted
                        changes.append(
                            {
                                "channel": target,
                                "field": "phase_inverted",
                                "value": source_obj.phase_inverted,
                                "cmd_type": "PHASE",
                            }
                        )
                    elif group == "routing":
                        target_obj.routing_mask = source_obj.routing_mask
                        changes.append(
                            {
                                "channel": target,
                                "field": "routing_mask",
                                "value": source_obj.routing_mask,
                                "cmd_type": "MATRIX_ROUTE",
                            }
                        )
                    elif group == "crossover":
                        target_obj.crossover = CrossoverState(
                            hipass_freq=source_obj.crossover.hipass_freq,
                            hipass_slope=source_obj.crossover.hipass_slope,
                            lopass_freq=source_obj.crossover.lopass_freq,
                            lopass_slope=source_obj.crossover.lopass_slope,
                        )
                        changes.append(
                            {
                                "channel": target,
                                "field": "hipass",
                                "value": (
                                    source_obj.crossover.hipass_freq,
                                    source_obj.crossover.hipass_slope,
                                ),
                                "cmd_type": "HIPASS",
                            }
                        )
                        changes.append(
                            {
                                "channel": target,
                                "field": "lopass",
                                "value": (
                                    source_obj.crossover.lopass_freq,
                                    source_obj.crossover.lopass_slope,
                                ),
                                "cmd_type": "LOPASS",
                            }
                        )
                    elif group == "peq":
                        target_obj.peqs = [
                            PEQBand(
                                gain_raw=b.gain_raw,
                                freq_raw=b.freq_raw,
                                q_raw=b.q_raw,
                                filter_type=b.filter_type,
                                bypass=b.bypass,
                            )
                            for b in source_obj.peqs
                        ]
                        target_obj.peq_channel_bypass = source_obj.peq_channel_bypass
                        for band_idx, band in enumerate(target_obj.peqs):
                            changes.append(
                                {
                                    "channel": target,
                                    "field": f"peq_band_{band_idx}",
                                    "value": (
                                        band.gain_raw,
                                        band.freq_raw,
                                        band.q_raw,
                                        band.filter_type,
                                        band.bypass,
                                    ),
                                    "cmd_type": "PEQ_BAND",
                                    "band": band_idx,
                                }
                            )
                        changes.append(
                            {
                                "channel": target,
                                "field": "peq_channel_bypass",
                                "value": source_obj.peq_channel_bypass,
                                "cmd_type": "PEQ_CHANNEL_BYPASS",
                            }
                        )
                    elif group == "compressor":
                        target_obj.compressor = CompressorState(
                            ratio=source_obj.compressor.ratio,
                            knee=source_obj.compressor.knee,
                            attack=source_obj.compressor.attack,
                            release=source_obj.compressor.release,
                            threshold=source_obj.compressor.threshold,
                        )
                        changes.append(
                            {
                                "channel": target,
                                "field": "compressor",
                                "value": (
                                    source_obj.compressor.ratio,
                                    source_obj.compressor.knee,
                                    source_obj.compressor.attack,
                                    source_obj.compressor.release,
                                    source_obj.compressor.threshold,
                                ),
                                "cmd_type": "COMPRESSOR",
                            }
                        )
                    elif group == "delay":
                        target_obj.delay_samples = source_obj.delay_samples
                        changes.append(
                            {
                                "channel": target,
                                "field": "delay_samples",
                                "value": source_obj.delay_samples,
                                "cmd_type": "DELAY",
                            }
                        )

        return changes

    @classmethod
    def from_config(cls, cfg: dict) -> DeviceState:
        """Build a DeviceState from a parsed device config dict.

        Args:
            cfg: The dict returned by ``DSPmini.read_config()``. Must
                carry the 8-element per-channel lists (``names``,
                ``gains``, ``mutes``, ``phases``, ``link_flags``) plus
                the input ``gates`` list (4 entries) and the output
                ``delays``, ``crossovers``, ``compressors``, ``peqs``,
                ``routings`` lists (also 4 entries each). The
                ``active_slot``, ``preset_names``, ``test_tone_mode``
                and ``test_tone_freq`` keys are optional.

        Returns:
            A fully-populated ``DeviceState`` with ``connected=True``
            and the link-info cache pre-warmed.
        """
        inputs = [
            InputChannelState(
                name=cfg["names"][i],
                gain_raw=cfg["gains"][i],
                muted=cfg["mutes"][i],
                phase_inverted=cfg["phases"][i],
                gate=GateState(**cfg["gates"][i]),
                link_flags=cfg["link_flags"][i],
            )
            for i in range(4)
        ]

        outputs = []
        for i in range(4):
            xo = cfg["crossovers"][i]
            comp = cfg["compressors"][i]
            peq = cfg["peqs"][i]
            outputs.append(
                OutputChannelState(
                    name=cfg["names"][i + 4],
                    gain_raw=cfg["gains"][i + 4],
                    muted=cfg["mutes"][i + 4],
                    phase_inverted=cfg["phases"][i + 4],
                    delay_samples=cfg["delays"][i],
                    crossover=CrossoverState(
                        hipass_freq=xo["hipass_freq"],
                        hipass_slope=xo["hipass_slope"],
                        lopass_freq=xo["lopass_freq"],
                        lopass_slope=xo["lopass_slope"],
                    ),
                    compressor=CompressorState(**comp),
                    peqs=[
                        PEQBand(
                            gain_raw=b["gain"],
                            freq_raw=b["freq"],
                            q_raw=b["q"],
                            filter_type=b["type"],
                            bypass=b["bypass"],
                        )
                        for b in peq["bands"]
                    ],
                    peq_channel_bypass=peq["channel_bypass"],
                    routing_mask=cfg["routings"][i],
                    link_flags=cfg["link_flags"][i + 4],
                )
            )

        state = cls(
            connected=True,
            inputs=inputs,
            outputs=outputs,
            active_slot=cfg.get("active_slot"),
            preset_names=list(cfg.get("preset_names", [])),
            test_tone=TestToneState(
                mode=cfg.get("test_tone_mode", 0),
                sine_freq_index=cfg.get("test_tone_freq", 0),
            ),
        )
        state._link_info_cache = decode_link_groups(
            [ch.link_flags for ch in inputs] + [ch.link_flags for ch in outputs]
        )
        return state
