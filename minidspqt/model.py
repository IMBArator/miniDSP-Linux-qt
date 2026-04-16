"""Typed device state mirroring the dict returned by DSPmini.read_config().

`DSPmini.read_config()` returns the dict produced by
`minidsp.protocol.parse_preset_params()` plus `active_slot` and
`preset_names`. Channel ordering across the list fields is
inputs 0–3, outputs 4–7. `gates` is input-only; `delays`, `crossovers`,
`compressors`, `peqs`, `routings` are output-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GateState:
    attack: int = 0
    release: int = 0
    hold: int = 0
    threshold: int = 0


@dataclass
class CrossoverState:
    hipass_freq: int = 0
    hipass_slope: int = 0
    lopass_freq: int = 0
    lopass_slope: int = 0


@dataclass
class CompressorState:
    ratio: int = 0
    knee: int = 0
    attack: int = 0
    release: int = 0
    threshold: int = 0


@dataclass
class PEQBand:
    gain_raw: int = 0
    freq_raw: int = 0
    q_raw: int = 0
    filter_type: int = 0
    bypass: bool = False


@dataclass
class InputChannelState:
    name: str = ""
    gain_raw: int = 0
    muted: bool = False
    phase_inverted: bool = False
    gate: GateState = field(default_factory=GateState)
    link_flags: int = 0


@dataclass
class OutputChannelState:
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


@dataclass
class DeviceState:
    """Full mirror of the active preset, plus connection status."""

    connected: bool = False
    inputs: list[InputChannelState] = field(default_factory=list)
    outputs: list[OutputChannelState] = field(default_factory=list)
    active_slot: int | None = None
    preset_names: list[str] = field(default_factory=list)

    @classmethod
    def from_config(cls, cfg: dict) -> DeviceState:
        """Build a DeviceState from the dict returned by DSPmini.read_config()."""
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

        return cls(
            connected=True,
            inputs=inputs,
            outputs=outputs,
            active_slot=cfg.get("active_slot"),
            preset_names=list(cfg.get("preset_names", [])),
        )
