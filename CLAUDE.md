# miniDSP-Linux-qt

## IMPORTANT

- stick to the architecture decisions recorded in [docs/decisions/](docs/decisions/index.md) — never contradict one silently; if a change would conflict with an ADR, or makes a new ADR-worthy decision, stop and ask whether to record it.
- commit using conventional commits, grouped by feature: a feature's implementation, its tests, and its documentation all go together in one commit (not split into separate test/docs commits).
- do NOT add `Co-Authored-By: Claude …` trailers or AI-generated footers to commit messages or PR bodies.
- use uv to manage the python project; run tests with `uv run pytest`.
- new features add tests in `tests/`, matching the existing one-file-per-feature pattern.
- automatically commit after significant changes.
- always feel free to suggest improvements to the code and to the process!
- be more explanative so the humans can learn along the way.
- always have a look at the protocol documentation of miniDSP-Linux ... it is located at analysis/protocol.md
- suggest fixes for the miniDSP-Linux lib if they make sense
- always create documentation for newly created code as Google-Style doc strings

## Project Goal

Create a Python QT Interface using PySide6 for the t.racks DSP 4x4 Mini

## Repository Layout

This repo's own layout is documented in the [README](README.md#repository-structure).

## Upstream protocol library

The protocol documentation lives here:

../miniDSP-Linux/analysis/protocol.md
