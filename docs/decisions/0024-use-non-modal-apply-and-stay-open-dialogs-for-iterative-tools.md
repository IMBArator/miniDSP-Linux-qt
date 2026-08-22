---
status: accepted
date: 2026-05-10
decision-makers: Maximilian Zettler
---

# Use non-modal, apply-and-stay-open dialogs for iterative device tools

## Context and Problem Statement

Two features are inherently trial-and-error. Channel linking has rules the firmware
enforces silently, so the only way to learn what a configuration does is to apply it
and look at what came back (ADR-0011). The test tone generator is a listening tool:
you pick a waveform and a frequency, listen, and adjust.

Both were candidates for the conventional modal dialog with OK and Cancel. That
shape fights both workflows — every iteration becomes reopen, re-navigate,
re-configure, apply, close.

## Decision Drivers

* The linking dialog needs to survive the apply-and-re-read cycle so the snap-back
  is visible to the user who triggered it (ADR-0011).
* The test tone needs the main window reachable while a tone plays, so the user can
  watch meters and adjust channel settings.
* Some device state outlives the dialog: a running test tone survives closing the
  dialog and even a power cycle.
* A generator that emits sound needs an unmissable stop control.

## Considered Options

* Non-modal dialogs that stay open after Apply
* Modal dialogs with OK and Cancel
* Inline panels embedded in the main window
* Modeless docked tool windows

## Decision Outcome

Chosen option: **non-modal dialogs that stay open after Apply**, for tools whose
workflow is iterative.

The channel-linking dialog is explicitly non-modal so it remains useful for
trial and error, and its Apply is "send, re-read, stay open" — the matrix
re-derives from device state afterwards, so a silently rejected topology visibly
snaps back (`5d2189f`). The test tone dialog follows the same pattern (`5652063`).

Two supporting decisions fall out of the choice.

**Dialog controls reflect authoritative device state, not transient UI selection.**
The test tone's stop button is driven by `state.test_tone.mode` via a `refresh()`
call, so it is armed only when the device is actually generating a tone — not merely
when a radio button is selected. `MainWindow` calls `_sync_test_tone_dialog` on
every config reload and after every apply. This matters because the generator keeps
running after the dialog closes and its state survives power cycles, so a dialog
reopened later must show reality rather than defaults.

**A destructive action gets a dedicated panic control.** The test tone dialog has a
full-width red *Disable test tone* button, armed only after Apply. Clicking it flips
the UI optimistically to Off and emits a disable request; the main window sends the
off command and calls `refresh()` to confirm. For a tool that makes a PA system emit
noise, "find the Off radio button" is not adequate.

Modal dialogs remain correct elsewhere and are still used: the preset picker, the
PIN dialogs (ADR-0017), the copy-channel dialog, and every confirmation prompt. The
distinction is iterative-versus-transactional, not a blanket preference.

### Consequences

* Good, because iterating is cheap — adjust, apply, observe, adjust again, without
  reopening anything.
* Good, because it makes the re-read reconciliation of ADR-0011 legible: the user
  who pressed Apply sees the matrix correct itself.
* Good, because the main window stays reachable, so the user can watch level meters
  and change channel settings while a tone plays.
* Bad, because dialogs must handle external state changes. A non-modal dialog can be
  open while the device state changes underneath it, which is why `refresh()` and
  `_sync_test_tone_dialog` exist. A modal dialog would need neither.
* Bad, because it introduces a state-synchronisation obligation per dialog, and a
  future non-modal dialog that omits it will display stale values.
* Bad, because these dialogs need explicit teardown on connection-mode switches;
  the runtime offline toggle disposes them as part of rebuilding the worker
  (`7a1eb01`).
* Neutral, because a non-modal dialog can be lost behind the main window. Acceptable
  for tools opened deliberately from a menu.

### Confirmation

`tests/test_test_tone_dialog.py` covers initial state, apply emission, panic-button
behaviour, and `refresh()` round-trips — specifically that the stop button follows
device state rather than radio selection.
`tests/test_channel_linking_dialog.py` covers `refresh()` snap-back, asserting the
dialog re-derives from device state rather than keeping the user's selection.

## Pros and Cons of the Options

### Non-modal, stay open after Apply

* Good, because iteration is cheap and the main window stays usable
* Good, because apply-and-re-read reconciliation becomes visible
* Bad, because each dialog must stay synchronised with external state changes

### Modal with OK and Cancel

* Good, because state cannot change underneath it, so no refresh logic is needed
* Good, because it is conventional and needs no explanation
* Bad, because every linking experiment becomes a full reopen cycle
* Bad, because a modal dialog cannot show a snap-back after apply — it would
  already be closed

### Inline panels in the main window

* Good, because there is no window to lose and no separate lifecycle
* Bad, because both tools are occasional; permanent screen space is the wrong trade
* Bad, because the main window is already dense with eight strips and a matrix

### Docked tool windows

* Good, because they are persistent, arrangeable, and never lost behind the window
* Neutral, because it is a heavier Qt mechanism than these two tools justify
* Bad, because docking widgets into a fixed-layout main window would complicate
  the resize behaviour already tuned in `cc5a540` and `99fec52`

## More Information

* `5d2189f` — the non-modal linking dialog and its apply-and-re-read flow
* `5652063` — the test tone dialog, state-driven stop button, and panic button
* Related: ADR-0011 (device authority and snap-back), ADR-0017 (where modal is
  correct instead)
