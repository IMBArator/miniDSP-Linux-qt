"""Test fixtures.

FakeDSPmini gives tests a hardware-free stand-in for
`minidsp.device.DSPmini`: it records every command and returns a
canned config / level payload.
"""

from __future__ import annotations

import threading

import pytest


def _make_preset_cfg() -> dict:
    """Canned dict in the shape of parse_preset_params() + read_config()'s extras."""
    return {
        "names": [
            "InA", "InB", "InC", "InD",
            "Out1", "Out2", "Out3", "Out4",
        ],
        "gains": [280, 281, 282, 283, 100, 101, 102, 103],
        "mutes": [False, True, False, False, False, False, True, False],
        "phases": [False, False, True, False, False, False, False, False],
        "link_flags": [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80],
        "routings": [0x01, 0x02, 0x04, 0x08],
        "gates": [
            {"attack": 50, "release": 100, "hold": 200, "threshold": 20}
            for _ in range(4)
        ],
        "delays": [0, 48, 96, 144],
        "crossovers": [
            {"hipass_freq": 0, "hipass_slope": 0, "lopass_freq": 300, "lopass_slope": 0}
            for _ in range(4)
        ],
        "compressors": [
            {"ratio": 2, "knee": 0, "attack": 10, "release": 100, "threshold": 0}
            for _ in range(4)
        ],
        "peqs": [
            {
                "bands": [
                    {"gain": 120, "freq": 150, "q": 40, "type": 2, "bypass": False}
                    for _ in range(7)
                ],
                "channel_bypass": False,
            }
            for _ in range(4)
        ],
        "active_slot": 1,
        "preset_names": [f"P{i:02d}" for i in range(30)],
    }


class FakeDSPmini:
    """Hardware-free DSPmini substitute.

    Records all incoming calls in `self.calls` (list of `(method, args)`),
    so tests can assert coalescing behaviour.
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.opened = False
        self.closed = False
        self.config = _make_preset_cfg()
        self.levels = {
            "inputs": [100, 150, 50, 200],
            "outputs": [120, 80, 40, 220],
            "limiter_mask": 0,
            "state": 0,
        }
        self.poll_event = threading.Event()

    def open(self) -> None:
        self.opened = True
        self.calls.append(("open", ()))

    def close(self) -> None:
        self.closed = True
        self.calls.append(("close", ()))

    def read_config(self) -> dict:
        self.calls.append(("read_config", ()))
        return self.config

    def poll_levels(self) -> dict:
        self.calls.append(("poll_levels", ()))
        self.poll_event.set()
        return self.levels

    # Generic command sinks — one method per DSPmini opcode we invoke.
    def _record(self, name: str, *args) -> bool:
        self.calls.append((name, args))
        return True

    set_gain = lambda self, *a: self._record("set_gain", *a)
    mute = lambda self, *a: self._record("mute", *a)
    set_phase = lambda self, *a: self._record("set_phase", *a)
    set_gate = lambda self, *a: self._record("set_gate", *a)
    set_hipass = lambda self, *a: self._record("set_hipass", *a)
    set_lopass = lambda self, *a: self._record("set_lopass", *a)
    set_compressor = lambda self, *a: self._record("set_compressor", *a)
    set_delay = lambda self, *a: self._record("set_delay", *a)
    set_peq_band = lambda self, *a: self._record("set_peq_band", *a)
    set_peq_channel_bypass = lambda self, *a: self._record("set_peq_channel_bypass", *a)
    set_matrix_route = lambda self, *a: self._record("set_matrix_route", *a)
    set_channel_link = lambda self, *a: self._record("set_channel_link", *a)
    set_channel_name = lambda self, *a: self._record("set_channel_name", *a)
    load_preset = lambda self, slot: (self.calls.append(("load_preset", (slot,))) or self.config)
    store_preset = lambda self, *a: self._record("store_preset", *a)


@pytest.fixture
def fake_dsp() -> FakeDSPmini:
    return FakeDSPmini()


@pytest.fixture
def preset_cfg() -> dict:
    return _make_preset_cfg()
