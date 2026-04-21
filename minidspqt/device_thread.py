"""Background QThread that owns the DSPmini and serializes all device I/O.

Commands from the UI are stored in a coalescing dict keyed by
(CommandType, channel[, band]). The poll loop drains the dict once per
cycle (150ms default), so rapid slider drags collapse to a single send.

Preset load/store are queued non-coalescing because they also
re-read the full config.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from enum import Enum, auto

from PySide6.QtCore import QThread, Signal

from minidsp.device import DSPmini

log = logging.getLogger(__name__)


class CommandType(Enum):
    GAIN = auto()
    MUTE = auto()
    PHASE = auto()
    GATE = auto()
    HIPASS = auto()
    LOPASS = auto()
    COMPRESSOR = auto()
    DELAY = auto()
    PEQ_BAND = auto()
    PEQ_CHANNEL_BYPASS = auto()
    MATRIX_ROUTE = auto()
    CHANNEL_LINK = auto()
    CHANNEL_NAME = auto()


class DeviceThread(QThread):
    """Polls levels and dispatches commands on a background thread."""

    levels_updated = Signal(dict)
    connection_changed = Signal(bool)
    config_loaded = Signal(dict)

    POLL_INTERVAL_MS = 150
    RECONNECT_INTERVAL_MS = 2000
    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(self, dsp_factory=DSPmini, dsp_instance=None, parent=None) -> None:
        super().__init__(parent)
        self._dsp_factory = dsp_factory
        self._dsp_instance = dsp_instance
        self._stop = False
        self._lock = threading.Lock()
        self._pending: dict[tuple, tuple] = {}
        self._preset_queue: deque[tuple] = deque()

    # --- Thread-safe command interface (called from UI thread) ---

    def request_gain(self, channel: int, raw_value: int) -> None:
        self._enqueue((CommandType.GAIN, channel), (raw_value,))

    def request_mute(self, channel: int, mute: bool) -> None:
        self._enqueue((CommandType.MUTE, channel), (mute,))

    def request_phase(self, channel: int, inverted: bool) -> None:
        self._enqueue((CommandType.PHASE, channel), (inverted,))

    def request_gate(
        self, channel: int, attack: int, release: int, hold: int, threshold: int
    ) -> None:
        self._enqueue(
            (CommandType.GATE, channel), (attack, release, hold, threshold)
        )

    def request_hipass(self, channel: int, freq_raw: int, slope: int) -> None:
        self._enqueue((CommandType.HIPASS, channel), (freq_raw, slope))

    def request_lopass(self, channel: int, freq_raw: int, slope: int) -> None:
        self._enqueue((CommandType.LOPASS, channel), (freq_raw, slope))

    def request_compressor(
        self,
        channel: int,
        ratio: int,
        knee: int,
        attack: int,
        release: int,
        threshold: int,
    ) -> None:
        self._enqueue(
            (CommandType.COMPRESSOR, channel),
            (ratio, knee, attack, release, threshold),
        )

    def request_delay(self, channel: int, samples: int) -> None:
        self._enqueue((CommandType.DELAY, channel), (samples,))

    def request_peq_band(
        self,
        channel: int,
        band: int,
        gain_raw: int,
        freq_raw: int,
        q_raw: int,
        filter_type: int,
        bypass: bool,
    ) -> None:
        self._enqueue(
            (CommandType.PEQ_BAND, channel, band),
            (gain_raw, freq_raw, q_raw, filter_type, bypass),
        )

    def request_peq_channel_bypass(self, channel: int, bypass: bool) -> None:
        self._enqueue((CommandType.PEQ_CHANNEL_BYPASS, channel), (bypass,))

    def request_matrix_route(self, output_ch: int, input_mask: int) -> None:
        self._enqueue((CommandType.MATRIX_ROUTE, output_ch), (input_mask,))

    def request_channel_link(self, channel: int, link_flags: int) -> None:
        self._enqueue((CommandType.CHANNEL_LINK, channel), (link_flags,))

    def request_channel_name(self, channel: int, name: str) -> None:
        self._enqueue((CommandType.CHANNEL_NAME, channel), (name,))

    def request_load_preset(self, slot: int) -> None:
        with self._lock:
            self._preset_queue.append(("load", slot))

    def request_store_preset(self, slot: int, name: str) -> None:
        with self._lock:
            self._preset_queue.append(("store", slot, name))

    def request_stop(self) -> None:
        self._stop = True

    # --- Internal helpers ---

    def _enqueue(self, key: tuple, args: tuple) -> None:
        with self._lock:
            self._pending[key] = args

    # --- Thread body ---

    def run(self) -> None:
        while not self._stop:
            if self._dsp_instance is not None:
                dsp = self._dsp_instance
            else:
                dsp = self._dsp_factory()
            if not self._try_connect(dsp):
                continue  # retry or stop

            log.info("Connected to DSPmini")
            self.connection_changed.emit(True)

            log.info("Reading device config...")
            try:
                config = dsp.read_config()
            except Exception:
                log.exception("read_config failed")
                config = None
            if config is not None:
                self.config_loaded.emit(config)
            else:
                log.warning("Config read failed")

            log.info("Starting poll loop")
            self._poll_loop(dsp)
            log.info("Poll loop exited, closing device")
            try:
                dsp.close()
            except Exception:
                log.exception("Error closing device")
            self.connection_changed.emit(False)

    def _try_connect(self, dsp) -> bool:
        while not self._stop:
            try:
                dsp.open()
                return True
            except OSError:
                log.debug(
                    "Device not found, retrying in %dms", self.RECONNECT_INTERVAL_MS
                )
                for _ in range(self.RECONNECT_INTERVAL_MS // 100):
                    if self._stop:
                        return False
                    self.msleep(100)
        return False

    def _poll_loop(self, dsp) -> None:
        failures = 0
        while not self._stop:
            self._drain_preset_queue(dsp)
            self._drain_pending(dsp)

            levels = dsp.poll_levels()
            if levels is not None:
                failures = 0
                self.levels_updated.emit(levels)
            else:
                failures += 1
                log.warning(
                    "Poll failed (%d/%d)", failures, self.MAX_CONSECUTIVE_FAILURES
                )
                if failures >= self.MAX_CONSECUTIVE_FAILURES:
                    log.error("Too many poll failures, disconnecting")
                    return

            self.msleep(self.POLL_INTERVAL_MS)

    def _drain_pending(self, dsp) -> None:
        with self._lock:
            batch = dict(self._pending)
            self._pending.clear()

        for key, args in batch.items():
            try:
                self._dispatch(dsp, key, args)
            except Exception:
                log.exception("Failed dispatching %s(%s)", key, args)

    def _drain_preset_queue(self, dsp) -> bool:
        """Process pending preset load/store requests.

        Returns True if a preset load was attempted (whether it succeeded or not).
        """
        with self._lock:
            pending = list(self._preset_queue)
            self._preset_queue.clear()

        did_recall = False
        for entry in pending:
            kind = entry[0]
            try:
                if kind == "load":
                    _, slot = entry
                    did_recall = True
                    log.info("recall: calling dsp.load_preset(slot=%d)", slot)
                    config = dsp.load_preset(slot)
                    if config is not None:
                        log.info(
                            "recall: load_preset returned dict keys=%s",
                            sorted(config.keys()),
                        )
                        config["active_slot"] = slot
                        log.info("recall: emitting config_loaded active_slot=%d", slot)
                        self.config_loaded.emit(config)
                    else:
                        log.warning("recall: load_preset returned None — UI will NOT update")
                elif kind == "store":
                    _, slot, name = entry
                    log.info("store: calling dsp.store_preset(slot=%d, name='%s')", slot, name)
                    dsp.store_preset(slot, name)
                    log.info("store: done")
            except Exception:
                log.exception("Preset operation %s failed", entry)
        return did_recall

    def _dispatch(self, dsp, key: tuple, args: tuple) -> None:
        cmd = key[0]
        channel = key[1]

        if cmd is CommandType.GAIN:
            dsp.set_gain(channel, args[0])
        elif cmd is CommandType.MUTE:
            dsp.mute(channel, args[0])
        elif cmd is CommandType.PHASE:
            dsp.set_phase(channel, args[0])
        elif cmd is CommandType.GATE:
            dsp.set_gate(channel, *args)
        elif cmd is CommandType.HIPASS:
            dsp.set_hipass(channel, *args)
        elif cmd is CommandType.LOPASS:
            dsp.set_lopass(channel, *args)
        elif cmd is CommandType.COMPRESSOR:
            dsp.set_compressor(channel, *args)
        elif cmd is CommandType.DELAY:
            dsp.set_delay(channel, args[0])
        elif cmd is CommandType.PEQ_BAND:
            band = key[2]
            dsp.set_peq_band(channel, band, *args)
        elif cmd is CommandType.PEQ_CHANNEL_BYPASS:
            dsp.set_peq_channel_bypass(channel, args[0])
        elif cmd is CommandType.MATRIX_ROUTE:
            dsp.set_matrix_route(channel, args[0])
        elif cmd is CommandType.CHANNEL_LINK:
            dsp.set_channel_link(channel, args[0])
        elif cmd is CommandType.CHANNEL_NAME:
            dsp.set_channel_name(channel, args[0])
        else:
            log.warning("Unknown command key %s", key)
