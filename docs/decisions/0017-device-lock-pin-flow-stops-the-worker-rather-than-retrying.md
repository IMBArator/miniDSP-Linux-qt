---
status: accepted
date: 2026-05-22
decision-makers: Maximilian Zettler
---

# Stop the worker on lock cancellation rather than auto-reconnecting

## Context and Problem Statement

The device can be PIN-locked. When it is, the firmware reports it in the
`cmd_device_info` response (byte 6 = `0x01`) and rejects configuration reads. The
protocol provides `cmd_submit_pin` to unlock and `cmd_set_lock_pin` to set a new
PIN — and, notably, **nothing to remove one**.

This collides awkwardly with the connection lifecycle. The worker's normal
response to a failed config read is to close and reconnect every two seconds
(ADR-0005). Applied naively to a locked device, the user cancels the unlock prompt,
the worker reconnects, the device is still locked, and the prompt reappears —
forever.

## Decision Drivers

* A user who cancels an unlock prompt must not be trapped in a prompt loop.
* Wrong-PIN attempts should be limited and the remaining count visible, since the
  consequences of lockout are severe.
* Setting a PIN is a rare administrative action, not an ordinary parameter edit.
* The worker parks waiting for user input, which no existing queue supports.

## Considered Options

* Stop the worker on cancel or exhaustion; require an explicit Reconnect
* Keep reconnecting and re-prompting
* Reconnect but suppress further prompts until the user asks
* Block the GUI thread on a modal prompt while the worker waits

## Decision Outcome

Chosen option: **stop the worker, and give the user an explicit Reconnect.**

When the initial `read_config()` raises `DeviceLockedError` (ADR-0012),
`_handle_locked` takes over. It emits `pin_required` once, then blocks on a
dedicated `queue.Queue` waiting for the UI to hand back a PIN. This is a third
queue, separate from the coalescing dict and the preset deque (ADR-0007), because
it is the only place the worker deliberately *parks* — the others are drained
without blocking.

Up to `MAX_PIN_ATTEMPTS = 3` attempts. Each emits `pin_result(success,
remaining)` so the dialog can show `N attempts remaining` inline. A `_CANCEL_PIN`
sentinel distinguishes cancellation from a wrong PIN.

Four outcomes set `_stop`: the cancel sentinel, an `OSError` during
`submit_pin`, a failed post-unlock `read_config`, and exhausting all three
attempts. In every case `run()` closes the device, emits
`connection_changed(False)`, and **does not** auto-reconnect. `restart()` clears
`_stop`, empties all three queues, and starts the worker again — driven by an
explicit **Reconnect** menu entry, enabled only while disconnected.

Three further consequences of treating lock as a lifecycle event rather than an
error:

* **Set-PIN is a one-shot admin action.** It rides the preset queue so it
  serialises with other device operations, and on ACK the worker closes the session
  and stops itself. Deliberately no auto-reconnect. There is no close on a
  missing ACK, so a transport hiccup cannot look like a successful relock.
* **The poll loop bails early** when draining the preset queue flips `_stop`
  mid-iteration; otherwise the next `poll_levels` would hit an already-closed
  handle. This is why `run()` wraps the loop in `try/finally` (ADR-0005).
* **No "Remove PIN" action is exposed**, because the protocol has no such command.
  Inventing one would mean guessing at an opcode on a feature whose failure mode
  is a permanently inaccessible device. The user guide carries an explicit
  **no known factory reset** warning instead.

Offline mode mirrors the same semantics against `VirtualDSP` (ADR-0010) so the
flow can be exercised safely.

The dialog side has one non-obvious guard: an in-flight flag in `_on_accept`,
because `returnPressed` **and** the default-button click both reach it, so a
single Enter keystroke consumed two of the three attempts and the dialog appeared
to close after two visible tries (`7058014`).

PINs are transmitted as 4 raw bytes, so the input validator accepts any 4
printable ASCII characters — not digits only, as the upstream docstring claimed at
the time. The docstring was corrected upstream (`7b23114`).

### Consequences

* Good, because cancelling actually cancels; the user is never trapped.
* Good, because attempt feedback is precise, which matters when lockout may be
  unrecoverable.
* Good, because set-PIN's deliberate disconnect makes a consequential action feel
  consequential rather than silent.
* Bad, because "disconnected" now has two causes — cable and user choice — so the
  UI must distinguish them. A `config is None` because the user stopped the worker
  is logged as info rather than the misleading "Config read failed, reconnecting…"
  warning.
* Bad, because the third queue adds a distinct concurrency shape: a parked worker
  must be unblocked to shut down, which is why `request_stop()` also posts the
  cancel sentinel.
* Bad, because there is no recovery path for a forgotten PIN, and the application
  cannot offer one. Documented as a warning rather than solved.

### Confirmation

`tests/test_device_thread.py` covers the PIN flow end to end: success, three wrong
attempts, cancel, exhaustion, `OSError` mid-submit, the set-PIN close-and-stop
sequence including the no-ACK skip, the poll-loop early exit, and `restart()`'s
reset. `tests/test_device_pin_dialog.py` covers the validator, the in-flight
double-trigger guard, result handling, and confirm-field mismatch.
`tests/test_virtual_dsp_lock.py` covers the offline round-trip.

## Pros and Cons of the Options

### Stop the worker; explicit Reconnect

* Good, because cancel is honoured and the loop is impossible
* Good, because the user controls when to retry
* Bad, because it needs a Reconnect affordance and a `restart()` path

### Keep reconnecting and re-prompting

* Good, because it needs no new state or menu entry
* Bad, because it is the trap this decision exists to avoid
* Bad, because the only escape is quitting the application

### Reconnect but suppress prompts

* Good, because level metering could continue against a partly-usable device
* Bad, because a locked device rejects config reads, so there is little to show
* Bad, because "connected but not really" is a confusing third state

### Block the GUI thread on a modal prompt

* Good, because the control flow reads linearly
* Bad, because a blocked GUI thread cannot deliver `submit_pin` to the worker,
  which is why the dialog is opened non-blocking with `dialog.open()`

## More Information

* `752c861` — offline lock semantics; `9bfaec2` — worker PIN flow, `restart()`,
  early bail; `7058014` — dialogs, menu entries, the in-flight guard
* [Device Lock / PIN in the user guide](../user-guide.md#device-lock-pin)
* Related: ADR-0005 (lifecycle), ADR-0010 (offline parity), ADR-0012
  (`DeviceLockedError`)
