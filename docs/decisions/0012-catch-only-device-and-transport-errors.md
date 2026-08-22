---
status: accepted
date: 2026-05-06
decision-makers: Maximilian Zettler
---

# Catch only device and transport errors; let programming errors propagate

## Context and Problem Statement

`DeviceThread` runs a long-lived loop against removable hardware. USB devices get
unplugged mid-read, `hidraw` returns `EBUSY` or `EIO`, and the device rejects
commands while a preset operation holds an internal lock. The loop has to survive
all of that and reconnect.

The obvious way to write that is `except Exception` around the loop body, and that
is what the code originally did — in five places. The problem is that it also
swallows `KeyError`, `AttributeError`, and `TypeError`: genuine bugs in command
dispatch were being silently absorbed by the same handler that absorbs a cable
being pulled, presenting as a mysterious reconnect instead of a traceback.

## Decision Drivers

* Transport failures are expected and must not kill the worker.
* Programming errors are not expected and must be loud, especially during
  development.
* The worker is on a background thread, so a swallowed exception leaves no trace
  in the UI at all.
* Reconnect logic already handles the transport cases correctly, so widening the
  catch adds nothing.

## Considered Options

* Catch a named tuple of device and transport exception types
* Catch `Exception` broadly
* Catch `Exception` but log with a traceback
* Catch nothing and let the worker die on any failure

## Decision Outcome

Chosen option: a **module-level `DEVICE_ERRORS` tuple** naming exactly the
transport and protocol failures, used at every catch site in the poll and dispatch
paths. Anything else propagates, crashing the run loop with a real traceback,
which is the desired outcome for a logic error.

`DEVICE_ERRORS` is `(OSError, DeviceClosedError, DeviceLockedError)`:

* `OSError` — the `hidraw`/libusb layer on disconnect, `EBUSY`, `EIO`,
  `BlockingIOError`.
* `DeviceClosedError` — raised by the upstream library on operations against a
  closed handle. **This member is redundant in effect**, because it subclasses
  `OSError`; it is listed for documentation, and the code comments say so. A
  future reader should not "simplify" it away without understanding it was
  deliberate.
* `DeviceLockedError` — a `RuntimeError` subclass, so this is the only member that
  actually widens the tuple beyond `OSError`. Raised when the device rejects a
  command while locked (ADR-0017).

The `DeviceClosedError` member also records an upstream improvement driven from
here. Version 1.0.1 of the protocol library replaced a bare `AssertionError` on
closed handles with `DeviceClosedError`, specifically so this side could catch it
as a device error rather than pattern-matching on an assertion — an instance of
the upstream relationship described in ADR-0001 (`7b23114`, `ae0cdd7`).

The policy is applied to the loop and dispatch paths rather than universally: a
few sites deliberately catch bare `OSError` where a locked device is not a
possible outcome, such as `_try_connect` and the `submit_pin` call inside the
lock handler.

### Consequences

* Good, because a dispatch bug now produces a traceback instead of an unexplained
  reconnect, which is a large debugging improvement on a background thread.
* Good, because the intended failure set is written down in one place with a
  comment explaining each member.
* Bad, because an unanticipated exception type from the library will now take the
  worker down rather than degrade. That is the intended trade — but it means
  upstream changes to raised types are a compatibility concern, which is part of
  why the dependency is pinned (ADR-0003).
* Bad, because the redundant `DeviceClosedError` member invites well-meaning
  cleanup that would lose the documentation, mitigated only by a comment.
* Neutral, because it interacts with ADR-0008's strict `from_config`: a parser
  change that renames a required key produces a loud `KeyError` rather than a
  half-populated model. Consistent, and intended.

### Confirmation

`tests/test_device_thread.py` covers the transport paths, including `OSError`
mid-PIN-submit and the post-`set_pin` early bail, which was updated to simulate
`DeviceClosedError` when upstream changed (`ae0cdd7`). No `except Exception`
remains in `device_thread.py`.

## Pros and Cons of the Options

### A named DEVICE_ERRORS tuple

* Good, because expected failures are enumerated and documented in one place
* Good, because bugs surface immediately with a usable traceback
* Bad, because a new upstream exception type crashes the worker until it is added

### Catch Exception broadly

* Good, because the worker is maximally resilient and never dies
* Bad, because it hides real bugs as spurious reconnects — the defect this replaced
* Bad, because on a background thread the evidence is lost entirely

### Catch Exception but log a traceback

* Good, because it is resilient and leaves evidence
* Neutral, because it is a reasonable middle ground
* Bad, because a logged-and-continued logic error keeps running against corrupt
  state, and warning-level noise is easy to miss in a GUI application

### Catch nothing

* Good, because every failure is maximally visible
* Bad, because unplugging the USB cable would crash the application, and that is a
  normal user action

## More Information

* `8017e7b` — narrowing the five catches, with the reasoning per exception type
* `7b23114`, `ae0cdd7` — the upstream `DeviceClosedError` change and its adoption
* Related: ADR-0001 (upstream relationship), ADR-0005 (the loop being protected),
  ADR-0017 (`DeviceLockedError` in the lock flow)
