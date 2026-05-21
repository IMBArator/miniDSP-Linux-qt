"""Test fixtures.

FakeDSPmini gives tests a hardware-free stand-in for
``minidsp.device.DSPmini``: it records every command and returns a
canned config / level payload.

The implementation lives in ``minidspqt.virtual_dsp.VirtualDSP``; this
module thin-wraps it for backward-compat with existing tests.
"""

from __future__ import annotations

# pytest-qt's qt_compat.get_versions() reads PySide6.__version__ directly.
# When we depend on PySide6-Essentials (no Addons), PySide6 is a namespace
# package with no __init__.py, so the attribute is absent. Synthesize it from
# QtCore.__version__ before pytest-qt's pytest_report_header fires.
import PySide6 as _pyside6  # noqa: E402
if not hasattr(_pyside6, "__version__"):
    from PySide6.QtCore import __version__ as _qt_version
    _pyside6.__version__ = _qt_version

import threading

import pytest

from minidspqt.virtual_dsp import VirtualDSP


def _make_preset_cfg() -> dict:
    """Canned dict in the shape of parse_preset_params() + read_config()'s extras."""
    return {
        "names": [
            "InA",
            "InB",
            "InC",
            "InD",
            "Out1",
            "Out2",
            "Out3",
            "Out4",
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


class FakeDSPmini(VirtualDSP):
    """VirtualDSP subclass that also records calls for test assertions.

    Records every incoming call in ``self.calls`` (list of ``(method, args)``).
    """

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple] = []
        self.poll_event = threading.Event()

        cfg = _make_preset_cfg()
        self._config.update(cfg)

    def open(self) -> None:
        self.calls.append(("open", ()))

    def close(self) -> None:
        self.calls.append(("close", ()))

    def read_config(self) -> dict:
        self.calls.append(("read_config", ()))
        return self._full_config()

    def poll_levels(self) -> dict:
        self.calls.append(("poll_levels", ()))
        self.poll_event.set()
        return {
            "inputs": [100, 150, 50, 200],
            "outputs": [120, 80, 40, 220],
            "limiter_mask": 0,
            "state": 0,
        }

    def set_gain(self, channel: int, raw_value: int) -> bool:
        self.calls.append(("set_gain", (channel, raw_value)))
        return super().set_gain(channel, raw_value)

    def mute(self, channel: int, mute: bool) -> bool:
        self.calls.append(("mute", (channel, mute)))
        return super().mute(channel, mute)

    def set_phase(self, channel: int, inverted: bool) -> bool:
        self.calls.append(("set_phase", (channel, inverted)))
        return super().set_phase(channel, inverted)

    def set_gate(
        self, channel: int, attack: int, release: int, hold: int, threshold: int
    ) -> bool:
        self.calls.append(("set_gate", (channel, attack, release, hold, threshold)))
        return super().set_gate(channel, attack, release, hold, threshold)

    def set_hipass(self, channel: int, freq_raw: int, slope: int) -> bool:
        self.calls.append(("set_hipass", (channel, freq_raw, slope)))
        return super().set_hipass(channel, freq_raw, slope)

    def set_lopass(self, channel: int, freq_raw: int, slope: int) -> bool:
        self.calls.append(("set_lopass", (channel, freq_raw, slope)))
        return super().set_lopass(channel, freq_raw, slope)

    def set_compressor(
        self,
        channel: int,
        ratio: int,
        knee: int,
        attack: int,
        release: int,
        threshold: int,
    ) -> bool:
        self.calls.append(
            ("set_compressor", (channel, ratio, knee, attack, release, threshold))
        )
        return super().set_compressor(channel, ratio, knee, attack, release, threshold)

    def set_delay(self, channel: int, samples: int) -> bool:
        self.calls.append(("set_delay", (channel, samples)))
        return super().set_delay(channel, samples)

    def set_peq_band(
        self,
        channel: int,
        band: int,
        gain_raw: int,
        freq_raw: int,
        q_raw: int,
        filter_type: int,
        bypass: bool = False,
    ) -> bool:
        self.calls.append(
            (
                "set_peq_band",
                (channel, band, gain_raw, freq_raw, q_raw, filter_type, bypass),
            )
        )
        return super().set_peq_band(
            channel, band, gain_raw, freq_raw, q_raw, filter_type, bypass
        )

    def set_peq_channel_bypass(self, channel: int, bypass: bool) -> bool:
        self.calls.append(("set_peq_channel_bypass", (channel, bypass)))
        return super().set_peq_channel_bypass(channel, bypass)

    def set_matrix_route(self, output_ch: int, input_mask: int) -> bool:
        self.calls.append(("set_matrix_route", (output_ch, input_mask)))
        return super().set_matrix_route(output_ch, input_mask)

    def prepare_link(self, master_ch: int, slave_ch: int) -> bool:
        self.calls.append(("prepare_link", (master_ch, slave_ch)))
        return super().prepare_link(master_ch, slave_ch)

    def set_channel_link(self, channel: int, link_flags: int) -> bool:
        self.calls.append(("set_channel_link", (channel, link_flags)))
        return super().set_channel_link(channel, link_flags)

    def set_channel_name(self, channel: int, name: str) -> bool:
        self.calls.append(("set_channel_name", (channel, name)))
        return super().set_channel_name(channel, name)

    def set_test_tone(self, mode: int, freq_index: int = 0) -> bool:
        self.calls.append(("set_test_tone", (mode, freq_index)))
        return super().set_test_tone(mode, freq_index)

    def load_preset(self, slot: int) -> dict | None:
        self.calls.append(("load_preset", (slot,)))
        return super().load_preset(slot)

    def store_preset(self, slot: int, name: str) -> bool:
        self.calls.append(("store_preset", (slot, name)))
        return super().store_preset(slot, name)

    def submit_pin(self, pin: str) -> bool:
        result = super().submit_pin(pin)
        self.calls.append(("submit_pin", (pin, result)))
        return result

    def set_lock_pin(self, pin: str) -> bool:
        self.calls.append(("set_lock_pin", (pin,)))
        return super().set_lock_pin(pin)


@pytest.fixture
def fake_dsp() -> FakeDSPmini:
    return FakeDSPmini()


@pytest.fixture
def preset_cfg() -> dict:
    return _make_preset_cfg()
