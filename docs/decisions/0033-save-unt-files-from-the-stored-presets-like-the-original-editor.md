---
status: accepted
date: 2026-10-27
decision-makers: Maximilian Zettler
---

# Save .unt files from the stored presets, like the original editor

## Context and Problem Statement

**Save .unt file…** was available in offline mode only. While the DSP was
connected the menu entry was disabled, because saving exported the 30 in-RAM slots
of the offline `VirtualDSP` and the GUI held only the active preset's parameters:
at startup it reads the 30 preset names (`0x29`) and the active preset's
configuration (`0x27` ×9), and no known command read any other stored preset
without recalling it (`0x20`, which changes the audio). The documented workaround,
Connection mode → Offline → Save, wrote an **empty** file, because seeding the
`VirtualDSP` from the live configuration never filled a slot.

The manufacturer's editor saves a complete file while connected. A USB capture of
that action (`capture_20261026_221454_editor_startup__save_unt` in the protocol
library) shows how: `0x19` reads a 34-byte header block, then for each preset
`0x24 [slot]` selects the **stored** slot and `0x28` ×9 reads its pages, followed by
one `0x12`. No preset is recalled. The library decoded this, checked it byte for
byte against the file the editor wrote, and now implements it
(`DSPmini.export_unt`, `minidsp.unt.UntFile`; the library's ADR-0025 and ADR-0026).

Three properties of the editor's files decide what "save like the editor" means:

* **Stored, not live.** The active slot holds the preset as stored in flash. In the
  capture, the live configuration differed from the stored active preset by 14
  bytes, and the file held the stored version.
* **Slot choice by name.** Exactly the slots whose `0x29` name is not "Default
  Preset" (the name of a never-stored slot) are saved, in ascending order.
* **Header verbatim.** The header is the `0x19` block, which carries the device's
  lock PIN in plain text.

## Decision Drivers

* Saving must not change the live audio. A user saving a backup during a gig must
  not hear the presets cycle through.
* Files should be interchangeable with the original editor's, byte for byte where
  possible, so they load there and compare cleanly.
* Unsaved edits must not vanish silently. That is the one place where copying the
  editor exactly would surprise users of this GUI.
* The protocol library owns the device's formats (ADR-0001), so the GUI must not
  grow a second copy of the read sequence or the file layout (ADR-0016's
  amendment moved the layout upstream in the same change).
* Device I/O stays in the worker thread (ADR-0005) and config operations in its
  FIFO (ADR-0007).

## Considered Options

* Read the stored presets with the library's `export_unt`, like the editor, and
  ask when the live settings differ from the stored active preset
* Recall every named slot in turn (`0x20` + `0x27` ×9), then recall the original
* Keep a session cache of every preset whose parameters passed through the GUI
* Save only a snapshot of the live configuration in the active slot

## Decision Outcome

Chosen option: **read the stored presets via `export_unt`, like the editor, and ask
about unsaved edits**.

* **Worker operation.** `DeviceThread.request_export_unt()` queues `export_unt` on
  the config FIFO. The handler flushes pending writes, reads the live configuration
  (`read_config`), then calls `dsp.export_unt(live["preset_names"])`, and emits
  `unt_exported(unt, live)`, or `(None, None)` on any device error. It always
  answers once, so the UI's busy state always ends.
* **One path for both modes.** `VirtualDSP.export_unt` returns its stored slots as
  a `UntFile`, so the offline save goes through the same worker operation and the
  same prompt.
* **Unsaved edits.** `minidspqt.unt_files.differs_from_stored` compares the live
  preset parameters with the stored active slot, ignoring the test-tone generator,
  which is transient state. If they differ, the user picks **Save stored version**
  (editor-identical), **Include current changes** (`include_live_changes` patches
  the live parameters into that slot of the file only; the device is not
  changed), or **Cancel**. With F00 active there is no prompt, because F00 is not a
  file slot.
* **Header and PIN copied** as the editor does. The user guide warns that the file
  reveals the PIN.
* **Availability.** The action is enabled while the worker holds a session and,
  when connected, once a device configuration has been read. A disconnect or mode
  switch during an export ends the busy state, and a late answer is ignored.

### Consequences

* Good, because connected Save produces the editor's file byte for byte when there
  are no unsaved edits, without touching the live audio.
* Good, because the GUI contains no protocol or file-layout code for this; a fix to
  the read sequence or the format reaches it through a library bump.
* Good, because unsaved edits are surfaced instead of dropped, while the default
  button keeps the editor's behaviour.
* Neutral, because a save takes a moment per stored preset (about 0.3 s each in the
  capture), during which the poll loop pauses and the meters freeze.
* Bad, because the file carries the device PIN in clear text. This is deliberate,
  for compatibility, and documented rather than prevented.
* Bad, because the feature is tied to a protocol library release: it needs v1.5.0
  or newer, so the PEP 508 pin (ADR-0003) moved from v1.4.0 to v1.5.0 with this
  change, and an older library does not even import.

### Confirmation

`tests/test_save_unt_connected.py` covers the worker operation (file and live
config emitted, pending writes flushed first, `(None, None)` on errors), the
comparison and patch helpers (test tone ignored, F00 never prompts, unstored slots
named from the device), and the window flow (enablement, busy cursor, each prompt
choice, a failed export, an abandoned request). `tests/test_unt_files.py` checks
offline round trips. On hardware, a file saved by the GUI while connected must be
byte-identical to the library CLI's `minidsp save-unt` output.

## Pros and Cons of the Options

### Stored presets via `export_unt`, with a prompt

* Good, because it matches the editor and leaves the audio untouched
* Good, because it reuses the library's verified sequence
* Bad, because it depends on a library release

### Recall sweep

* Good, because it needs no new protocol knowledge
* Bad, because the audio switches through every preset while it runs
* Bad, because recalling away from the active preset discards its unsaved edits on
  the device

### Session cache

* Good, because it costs no extra device traffic
* Bad, because it misses every named preset not recalled in this session, so files
  differ from the editor's (both editor files in the library's `analysis/` folder
  contain non-active presets it never recalled)

### Live snapshot only

* Good, because it is trivial
* Bad, because it saves one preset out of up to 30, and the live rather than the
  stored version, so it neither backs up the device nor matches the editor

## More Information

* Capture and decoding: the protocol library's
  `analysis/usb_captures/capture_20261026_221454_editor_startup__save_unt.pcapng`,
  the editor's file `analysis/miniDSP current settings 261026.unt`, and its
  `analysis/protocol.md`.
* Reverses the earlier "Save .unt is offline-only" behaviour (user guide).
* Related: ADR-0001 (the library owns protocol and formats), ADR-0003 (pin and
  local override), ADR-0005 / ADR-0007 (worker and FIFO), ADR-0010 (VirtualDSP as
  a drop-in), ADR-0016 (byte-preserving files, now in the library).
* Restoring a `.unt` to the device (`DSPmini.restore_unt`, which rewrites preset
  flash and reboots the device) is available in the library but deliberately out
  of scope here.
