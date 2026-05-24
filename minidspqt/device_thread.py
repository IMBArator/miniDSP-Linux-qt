"""Background QThread that owns the DSPmini and serializes all device I/O.

Commands from the UI are stored in a coalescing dict keyed by
(CommandType, channel[, band]). The poll loop drains the dict once per
cycle (150ms default), so rapid slider drags collapse to a single send.

Preset load/store are queued non-coalescing because they also
re-read the full config.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections import deque
from enum import Enum, auto

from PySide6.QtCore import QThread, Signal

from minidsp.device import DeviceClosedError, DeviceLockedError, DSPmini

# Sentinel used on the PIN queue when the UI cancels the unlock dialog.
_CANCEL_PIN = object()
# Max unlock attempts before the worker gives up and disconnects.
MAX_PIN_ATTEMPTS = 3

log = logging.getLogger(__name__)

# Errors expected from the device/transport layer. Anything else raised from
# inside the poll loop or a command dispatch is a programming bug and should
# propagate to surface in logs/test failures rather than being swallowed.
# DeviceClosedError is an OSError subclass; listing it explicitly documents
# that hitting a closed handle is a known shutdown race, not a bug.
DEVICE_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    DeviceClosedError,
    DeviceLockedError,
)


class CommandType(Enum):
    """Identifies one kind of write the UI can send to the device.

    Used as part of the dict-key tuple in ``DeviceThread._pending``;
    pairing a ``CommandType`` with a channel index (and PEQ band index
    where relevant) lets repeated edits coalesce into a single send
    per poll cycle.
    """

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
    PREPARE_LINK = auto()
    CHANNEL_LINK = auto()
    CHANNEL_NAME = auto()
    TEST_TONE = auto()


class DeviceThread(QThread):
    """Background worker that owns the DSP and serialises all I/O.

    All USB / virtual-DSP calls happen on this thread. The UI calls
    the ``request_*`` methods from the main thread; each request goes
    into a coalescing dict keyed by ``(CommandType, channel[, band])``
    and is drained once per poll cycle (150 ms by default), so rapid
    slider drags collapse to a single device write. Preset
    load/store, ``read_config`` refreshes and the set-PIN admin op
    use a separate FIFO queue because they also re-read the full
    config and must not be coalesced.

    Signals:
        levels_updated (dict): Emitted every poll cycle with the
            ``parse_levels`` result.
        connection_changed (bool): True when a session opens, False
            when it closes.
        config_loaded (dict): Emitted when a full config has been
            read (initial connect, after a preset recall, or after a
            ``request_read_config``).
        pin_required (): The device reported it is locked; the UI
            should show the unlock dialog and call ``submit_pin``.
        pin_result (bool, int): ``(success, attempts_remaining)`` —
            result of one ``submit_pin`` round.
    """

    levels_updated = Signal(dict)
    connection_changed = Signal(bool)
    config_loaded = Signal(dict)
    pin_required = Signal()
    pin_result = Signal(bool, int)  # success, remaining_attempts

    POLL_INTERVAL_MS = 150
    RECONNECT_INTERVAL_MS = 2000
    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(self, dsp_factory=DSPmini, dsp_instance=None, parent=None) -> None:
        """Build a worker; pass ``dsp_instance`` for offline / tests.

        Args:
            dsp_factory: Callable returning a fresh DSP object on each
                connect attempt. Used in connected mode so the worker
                can re-open after a USB drop.
            dsp_instance: Pre-built DSP instance to use instead of the
                factory. The worker reuses the same instance across
                reconnects — required for the in-RAM ``VirtualDSP`` so
                state survives close/open cycles.
            parent: Qt parent for the ``QThread``.
        """
        super().__init__(parent)
        self._dsp_factory = dsp_factory
        self._dsp_instance = dsp_instance
        self._stop = False
        self._lock = threading.Lock()
        self._pending: dict[tuple, tuple] = {}
        self._preset_queue: deque[tuple] = deque()
        self._pin_queue: queue.Queue = queue.Queue()

    # --- Thread-safe command interface (called from UI thread) ---
    # Each request_* method coalesces by (CommandType, channel[, band]),
    # so repeated edits during a slider drag collapse to one device send
    # per poll cycle.

    def request_gain(self, channel: int, raw_value: int) -> None:
        """Queue a gain change for ``channel`` (0–7); ``raw_value`` 120 = 0 dB."""
        self._enqueue((CommandType.GAIN, channel), (raw_value,))

    def request_mute(self, channel: int, mute: bool) -> None:
        """Queue a mute change for ``channel`` (0–7)."""
        self._enqueue((CommandType.MUTE, channel), (mute,))

    def request_phase(self, channel: int, inverted: bool) -> None:
        """Queue a phase-invert change for ``channel`` (0–7)."""
        self._enqueue((CommandType.PHASE, channel), (inverted,))

    def request_gate(
        self, channel: int, attack: int, release: int, hold: int, threshold: int
    ) -> None:
        """Queue an atomic four-parameter gate update on input ``channel``.

        All four raw values reach the device in a single ``cmd_gate``
        send.
        """
        self._enqueue((CommandType.GATE, channel), (attack, release, hold, threshold))

    def request_hipass(self, channel: int, freq_raw: int, slope: int) -> None:
        """Queue a hi-pass update on output ``channel`` (4–7).

        ``slope`` of 0 means bypass.
        """
        self._enqueue((CommandType.HIPASS, channel), (freq_raw, slope))

    def request_lopass(self, channel: int, freq_raw: int, slope: int) -> None:
        """Queue a lo-pass update on output ``channel`` (4–7).

        ``slope`` of 0 means bypass.
        """
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
        """Queue an atomic five-parameter compressor update on output ``channel``."""
        self._enqueue(
            (CommandType.COMPRESSOR, channel),
            (ratio, knee, attack, release, threshold),
        )

    def request_delay(self, channel: int, samples: int) -> None:
        """Queue an output-delay change on ``channel`` (4–7), in samples."""
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
        """Queue an atomic update of one PEQ band on output ``channel``.

        Coalescing is keyed by ``(channel, band)`` — each of the seven
        bands can have its own pending update during a single cycle.
        """
        self._enqueue(
            (CommandType.PEQ_BAND, channel, band),
            (gain_raw, freq_raw, q_raw, filter_type, bypass),
        )

    def request_peq_channel_bypass(self, channel: int, bypass: bool) -> None:
        """Queue a channel-wide PEQ bypass change on output ``channel`` (4–7)."""
        self._enqueue((CommandType.PEQ_CHANNEL_BYPASS, channel), (bypass,))

    def request_matrix_route(self, output_ch: int, input_mask: int) -> None:
        """Queue an update of the 4-bit input mask for one output (4–7)."""
        self._enqueue((CommandType.MATRIX_ROUTE, output_ch), (input_mask,))

    def request_prepare_link(self, master_ch: int, slave_ch: int) -> None:
        """Queue an ``OP_PREPARE_LINK`` (0x2A) declaring a master/slave pair.

        Order matters: this MUST reach the device before the matching
        ``CHANNEL_LINK`` for the same slave. Callers should enqueue
        all prepare-link requests first; dict insertion order
        preserves that ordering through the coalescing batch.
        """
        self._enqueue(
            (CommandType.PREPARE_LINK, master_ch, slave_ch), (master_ch, slave_ch)
        )

    def request_channel_link(self, channel: int, link_flags: int) -> None:
        """Queue a write of the raw link-flag bitmask on ``channel`` (0–7)."""
        self._enqueue((CommandType.CHANNEL_LINK, channel), (link_flags,))

    def request_channel_name(self, channel: int, name: str) -> None:
        """Queue a rename of ``channel`` (0–7); caller truncates ``name`` to 8 chars."""
        self._enqueue((CommandType.CHANNEL_NAME, channel), (name,))

    def request_test_tone(self, mode: int, freq_index: int) -> None:
        """Queue a test-tone change (device-wide).

        Pinned to channel slot 0 so rapid mode flips coalesce into a
        single send and ``_dispatch``'s ``key[1]`` unpack still works.
        """
        self._enqueue((CommandType.TEST_TONE, 0), (mode, freq_index))

    def request_load_preset(self, slot: int) -> None:
        """Queue a preset recall.

        Args:
            slot: Device slot — 0 = F00, 1–30 = U01–U30.
        """
        with self._lock:
            self._preset_queue.append(("load", slot))

    def request_store_preset(self, slot: int, name: str) -> None:
        """Queue a preset store with a name.

        Args:
            slot: Target user slot 1–30 (U01–U30). F00 cannot be
                written.
            name: Preset name (caller truncates to 14 ASCII chars).
        """
        with self._lock:
            self._preset_queue.append(("store", slot, name))

    def request_read_config(self) -> None:
        """Queue a re-read of the current device config.

        Used after multi-step edits (e.g. channel-link changes) to
        refresh the UI from the device's authoritative state without
        changing the active slot.
        """
        with self._lock:
            self._preset_queue.append(("read_config",))

    def request_stop(self) -> None:
        """Ask the worker to stop after the current iteration.

        If the worker is currently parked in ``_handle_locked`` waiting
        for a PIN, also unblocks it with the cancel sentinel so it can
        exit cleanly instead of hanging on the queue.
        """
        self._stop = True
        self._pin_queue.put(_CANCEL_PIN)

    def restart(self) -> None:
        """Bring the worker back online after it stopped itself.

        Used by the "Reconnect" menu item to recover from a cancelled
        unlock prompt, exhausted PIN attempts, or any other state
        that flipped ``_stop`` to True. No-op if the worker is still
        running.

        Note:
            Callers MUST ensure the previous ``run()`` has exited
            (``isRunning()`` is False) before calling — otherwise
            ``start()`` is a no-op on Qt's side and we would leave
            ``_stop=False`` on a still-stopping worker, which races
            the next iteration.
        """
        if self.isRunning():
            log.info("restart: thread is still running, ignoring")
            return
        # Clear the stop flag and any stale queue state so the new run
        # starts from a clean slate.
        self._stop = False
        with self._lock:
            self._pending.clear()
            self._preset_queue.clear()
        while not self._pin_queue.empty():
            try:
                self._pin_queue.get_nowait()
            except queue.Empty:
                break
        self.start()

    def submit_pin(self, pin: str) -> None:
        """Hand a PIN to the worker blocked in ``_handle_locked``.

        The worker tries the PIN and emits ``pin_result`` with the
        outcome. Safe to call from the UI thread.
        """
        self._pin_queue.put(pin)

    def cancel_pin_entry(self) -> None:
        """Tell the worker to give up on the unlock prompt and disconnect.

        Unblocks ``_handle_locked`` with the cancel sentinel; the
        worker then flips ``_stop`` so it does not auto-reconnect into
        the same unlock prompt.
        """
        self._pin_queue.put(_CANCEL_PIN)

    def request_set_pin(self, pin: str) -> None:
        """Queue a set-PIN admin op.

        Serialised with other preset / config ops on the FIFO queue.
        After a successful set, the worker closes the USB session and
        stops itself — setting a PIN is a one-shot admin action and
        immediately cycling into the unlock prompt would be hostile UX.

        Args:
            pin: 4-character ASCII PIN to install on the device.
        """
        with self._lock:
            self._preset_queue.append(("set_pin", pin))

    # --- Internal helpers ---

    def _enqueue(self, key: tuple, args: tuple) -> None:
        with self._lock:
            self._pending[key] = args

    # --- Thread body ---

    def run(self) -> None:
        """Connect → read config → poll loop, repeating on reconnect.

        Qt entry point invoked by ``QThread.start``. Loops until
        ``_stop`` is set: each pass opens a DSP session, emits
        ``config_loaded`` (driving the unlock dialog via
        ``_handle_locked`` if the device is locked), then enters the
        poll loop until disconnect, error, or shutdown. Always emits
        ``connection_changed(False)`` on exit so the UI indicator
        clears even on unexpected errors.
        """
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
            except DeviceLockedError:
                log.info("Device is locked, prompting for PIN")
                config = self._handle_locked(dsp)
            except OSError:
                log.exception("read_config failed")
                config = None
            if config is not None:
                self.config_loaded.emit(config)
            else:
                if self._stop:
                    # _handle_locked (or any other early-exit path) flipped
                    # _stop to signal "give up, do not reconnect". Don't
                    # log it as a failure — it's the user's explicit choice.
                    log.info("Stopping worker (no auto-reconnect)")
                else:
                    log.warning("Config read failed, reconnecting...")
                try:
                    dsp.close()
                except DEVICE_ERRORS:
                    log.exception("Error closing device")
                self.connection_changed.emit(False)
                continue

            log.info("Starting poll loop")
            try:
                self._poll_loop(dsp)
            finally:
                # Defense in depth: even if _poll_loop raises something
                # unexpected, the UI must still see connection_changed(False)
                # so the connection indicator clears. Without this finally
                # the worker thread can die silently and the UI is stuck
                # showing "Connected".
                log.info("Poll loop exited, closing device")
                try:
                    dsp.close()
                except DEVICE_ERRORS:
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
            try:
                self._drain_preset_queue(dsp)
                # A preset op (e.g. successful set_pin) may have closed the
                # device and flipped _stop. Bail before touching dsp again
                # — otherwise the next call hits an already-closed handle
                # and emits a spurious "Device disconnected" warning for what
                # is actually an orderly user-initiated shutdown.
                if self._stop:
                    return
                self._drain_pending(dsp)
                levels = dsp.poll_levels()
            except DEVICE_ERRORS:
                log.warning("Device disconnected", exc_info=True)
                return

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
            except DEVICE_ERRORS:
                log.exception("Failed dispatching %s(%s)", key, args)

    def _drain_preset_queue(self, dsp) -> bool:
        """Process pending preset load/store/set-PIN/read-config requests.

        Returns:
            True if a preset load was attempted (whether it succeeded
            or not). Other entry kinds — store, set_pin, read_config
            — do not affect the return value.
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
                        log.warning(
                            "recall: load_preset returned None — UI will NOT update"
                        )
                elif kind == "store":
                    _, slot, name = entry
                    log.info(
                        "store: calling dsp.store_preset(slot=%d, name='%s')",
                        slot,
                        name,
                    )
                    dsp.store_preset(slot, name)
                    log.info("store: done")
                elif kind == "set_pin":
                    _, pin = entry
                    log.info("set_pin: calling dsp.set_lock_pin(...)")
                    ok = dsp.set_lock_pin(pin)
                    if ok:
                        # Per protocol capture analysis: the device ACKs
                        # but keeps the USB session alive — the client
                        # (we) closes. After a successful set-pin we
                        # deliberately do NOT auto-reconnect: setting a
                        # PIN is a one-shot admin action and immediately
                        # cycling into the unlock prompt is hostile UX.
                        # Stop the worker so the user can choose to
                        # restart the app when ready.
                        log.info(
                            "set_pin: ACK received, closing session and "
                            "stopping worker (no auto-reconnect)"
                        )
                        try:
                            dsp.close()
                        except DEVICE_ERRORS:
                            log.exception("set_pin: error closing after ACK")
                        self._stop = True
                    else:
                        log.warning(
                            "set_pin: device did not ACK; PIN was NOT set"
                        )
                elif kind == "read_config":
                    # Flush any pending writes (e.g. channel-link commands
                    # the UI just queued) before we read back state.  The
                    # poll loop normally drains _pending *after* this
                    # method, so without an explicit flush a read_config
                    # queued right after a write would observe the OLD
                    # state and the UI would snap back as if the write
                    # never happened.
                    self._drain_pending(dsp)
                    log.info("read_config: re-reading live device config")
                    config = dsp.read_config()
                    if config is not None:
                        # Preserve the active_slot the device reports — we are
                        # not switching presets, just refreshing live state.
                        log.info(
                            "read_config: emitting config_loaded keys=%s",
                            sorted(config.keys()),
                        )
                        self.config_loaded.emit(config)
                    else:
                        log.warning(
                            "read_config: dsp.read_config returned None — UI will NOT update"
                        )
            except DEVICE_ERRORS:
                log.exception("Preset operation %s failed", entry)
        return did_recall

    def _handle_locked(self, dsp) -> dict | None:
        """Drive the UI through up to ``MAX_PIN_ATTEMPTS`` unlock attempts.

        Emits ``pin_required`` once so the UI shows the dialog, then
        blocks on the PIN queue. Each ``submit_pin`` from the UI is
        tried against ``dsp.submit_pin``; ``pin_result`` reports
        whether it worked and how many attempts remain so the dialog
        can show inline feedback.

        Returns:
            The freshly-loaded config on success. On cancel or after
            ``MAX_PIN_ATTEMPTS`` wrong PINs returns ``None`` and sets
            ``self._stop`` so the worker exits instead of immediately
            reconnecting back into the same unlock prompt (which
            would make Cancel pointless).
        """
        # Drain any stale entries from a previous lock cycle.
        while not self._pin_queue.empty():
            try:
                self._pin_queue.get_nowait()
            except queue.Empty:
                break

        self.pin_required.emit()
        attempts_used = 0
        while attempts_used < MAX_PIN_ATTEMPTS and not self._stop:
            item = self._pin_queue.get()
            if item is _CANCEL_PIN:
                log.info("PIN entry cancelled — stopping worker")
                self._stop = True
                return None
            pin = item
            attempts_used += 1
            try:
                ok = dsp.submit_pin(pin)
            except OSError:
                log.exception("submit_pin failed")
                self._stop = True
                return None
            attempts_left = MAX_PIN_ATTEMPTS - attempts_used
            self.pin_result.emit(bool(ok), attempts_left)
            if ok:
                try:
                    return dsp.read_config()
                except DEVICE_ERRORS:
                    log.exception("read_config after unlock failed")
                    self._stop = True
                    return None
        log.info("PIN attempts exhausted — stopping worker")
        self._stop = True
        return None

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
        elif cmd is CommandType.PREPARE_LINK:
            master_ch, slave_ch = args
            dsp.prepare_link(master_ch, slave_ch)
        elif cmd is CommandType.CHANNEL_LINK:
            dsp.set_channel_link(channel, args[0])
        elif cmd is CommandType.CHANNEL_NAME:
            dsp.set_channel_name(channel, args[0])
        elif cmd is CommandType.TEST_TONE:
            dsp.set_test_tone(args[0], args[1])
        else:
            log.warning("Unknown command key %s", key)
