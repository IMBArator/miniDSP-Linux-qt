---
status: accepted
date: 2026-04-21
decision-makers: Maximilian Zettler
---

# Preserve unknown .unt bytes by writing field-level overwrites onto a template

## Context and Problem Statement

The manufacturer's editor stores configurations in `.unt` files: a fixed 13,010-byte
binary format holding 30 preset slots. Supporting them means users can move
configurations between this application and the official software, and gives
offline mode somewhere to persist work (ADR-0010).

The format is reverse-engineered and **only partially understood**. The modelled
fields — gains, mutes, phases, gates, crossovers, compressors, PEQ bands, routing,
names — account for some of each slot's 429-byte blob. The rest is unknown: padding,
reserved space, or fields nobody has decoded yet.

Writing a file means deciding what happens to the bytes nobody understands.

## Decision Drivers

* Unknown bytes may be meaningful to the official editor; discarding them could
  produce a file it rejects or silently misreads.
* A load-then-save cycle with no edits should be a no-op, so users can trust the
  writer.
* Editing one field should not perturb anything else in the file.
* The format understanding will improve over time, so today's unknown bytes may
  become tomorrow's modelled fields.

## Considered Options

* Overwrite modelled fields onto an existing byte buffer, preserving everything else
* Serialise a fresh file from the model, zero-filling anything unmodelled
* Refuse to write `.unt` files and support reading only

## Decision Outcome

Chosen option: **overwrite modelled fields onto a byte buffer.** `save_unt` in
`minidspqt/unt_writer.py` starts from a template — either one supplied by the
caller or the bundled `minidspqt/resources/blank.unt` — validates its length
against the expected 13,010 bytes, then patches only explicitly named offsets.

The mechanism that makes it work is in `_write_slot`: it reads the *existing*
429-byte blob out of the buffer, patches the modelled fields within it, and writes
it back. That read-modify-write of existing bytes is what preserves unknown and
reserved fields. Slots passed as `None` are skipped entirely, so untouched slots
keep the template's bytes verbatim. Layout constants are imported from
`unt_loader` rather than redefined, so reader and writer cannot disagree about
offsets.

**The byte-identical guarantee is a property of the round-trip path, not of the
writer alone.** On a load-then-save cycle the "template" *is* the original file:
`VirtualDSP.load_from_unt_bytes` retains all 13,010 source bytes and
`export_to_unt_args` hands them back as the template argument. So a no-edit
round-trip is byte-identical because the writer is patching the very buffer it was
read from. Understanding this matters — the guarantee would not survive someone
"simplifying" the writer to always start from `blank.unt`.

The writer is a pure function with no Qt or `VirtualDSP` dependency, which is what
makes it directly testable.

**Two caveats belong on the record.** Name encoding uses `errors="replace"`, so
non-ASCII channel or preset names are lossy — a round-trip through a non-ASCII
name will not reproduce the source bytes. And slots absent from the `slots`
argument are left as-is rather than cleared, which is the right default for
editing but means the writer cannot express "delete this slot".

### Consequences

* Good, because a no-edit round-trip is byte-identical, so users can trust the
  writer not to quietly damage files.
* Good, because editing one field provably cannot perturb another, which matters
  in a format where an unknown byte might be a checksum or a flag.
* Good, because improving format understanding is additive — a newly decoded field
  becomes another patched offset, with no migration.
* Good, because the pure-function design makes the guarantee directly assertable
  in tests.
* Bad, because a template is always required. There is no path to writing a
  `.unt` from nothing, so the bundled `blank.unt` is a hard runtime dependency
  shipped as package data.
* Bad, because non-ASCII names are silently lossy, which contradicts the
  byte-identical claim for that specific case.
* Neutral, because the writer cannot clear a slot. Not currently needed.

### Confirmation

`tests/test_unt_writer.py` asserts byte-identical round-trip directly
(`saved == raw`), plus a double round-trip, targeted single-field edits leaving
all other bytes untouched, and writing onto the blank template.
`tests/test_unt_loader.py` covers parsing, bad magic, and wrong file size.

## Pros and Cons of the Options

### Field-level overwrites onto a template

* Good, because unknown bytes survive untouched and round-trips are exact
* Good, because partial format understanding is sufficient, and improves additively
* Bad, because a template is mandatory, so a bundled blank must ship

### Serialise fresh from the model

* Good, because it needs no template and the writer is self-contained
* Bad, because every unmodelled byte is lost, and in a reverse-engineered format
  that risks producing files the official editor mishandles
* Bad, because it makes a no-edit round-trip lossy, which users would rightly
  consider data loss

### Read-only support

* Good, because there is no risk of writing a malformed file
* Bad, because offline mode would have no way to persist work, undercutting ADR-0010
* Bad, because interoperability would be one-directional

## More Information

* `a3c1950` — the parser, with magic-header and size validation
* `ea601d6` — the writer and `load_unt_all_slots`
* `8b54dcb` — blanking all 30 slots in `blank.unt` so it mimics a never-used
  device and stops competing with factory defaults (ADR-0014)
* Related: ADR-0010 (offline persistence), ADR-0014 (the blank template)
