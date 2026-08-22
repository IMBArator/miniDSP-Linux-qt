---
status: accepted
date: 2026-04-16
decision-makers: Maximilian Zettler
---

# Manage the project with uv, Hatchling, ruff, and a Makefile

## Context and Problem Statement

The project needs an environment manager, a build backend, a formatter and linter,
and some way for a contributor to discover how to run things. It also has one
constraint most Python projects do not: its main dependency is not on PyPI and must
be installed from a URL (ADR-0003), which not every tool handles well.

## Decision Drivers

* The non-PyPI dependency must be expressible and lockable.
* Environment setup should be a single command on a fresh clone.
* The built wheel must be installable by plain `pip` in a minimal container (ADR-0027).
* Commands should be discoverable without reading documentation.
* The sibling `miniDSP-Linux` project already has conventions worth matching.

## Considered Options

* uv, Hatchling, ruff, and a Makefile
* Poetry with its own build backend
* pip and `venv` with `requirements.txt`
* PDM or Hatch as an all-in-one workflow tool

## Decision Outcome

Chosen option: **uv for environments and locking, Hatchling as build backend, ruff
for linting and formatting, and a Makefile as the task interface.**

**uv** manages the virtual environment and resolves the lockfile, including
hash-pinning the direct-URL dependency. Python floor is 3.11, matching
`.python-version`.

**Hatchling** builds the wheel and sdist. It is required to opt in to direct-URL
references via `[tool.hatch.metadata] allow-direct-references = true`, which is
what lets the PEP 508 URL reach wheel metadata (ADR-0003).

**ruff** covers both linting and formatting, at its default 88-column width. It was
adopted retroactively across existing code in two deliberately separate commits — a
lint pass fixing 17 findings (`94b7d06`, and earlier `62b2d77`), then a pure
mechanical `ruff format` pass across 18 files (`60f9675`, `7a51882`). Keeping the
mechanical reformat isolated from semantic changes made both reviewable.

**A Makefile** fronts everything, deliberately mirroring the sibling
`miniDSP-Linux` project's target layout so the two repositories feel the same
(`9f27742`). Targets: `sync`, `install`, `test`, `build`, `version`, `publish`,
`clean`, `docs`, `docs-serve`, `docs-clean`, `appimage`, `appimage-clean`.

The Makefile is not merely aliasing — several targets encode knowledge that would
otherwise be lost. `test` sets `QT_QPA_PLATFORM=offscreen` so the suite is headless
by default (ADR-0025); `sync` uses `--extra dev` so test dependencies are actually
installed, which an early version got wrong (`f6f8217`); and the docs targets use
`uv sync --extra docs --inexact` so installing documentation tooling does not evict
the dev extras.

### Consequences

* Good, because a fresh clone is `uv sync` and nothing else, including the
  non-PyPI dependency.
* Good, because `make test` is correct by default — a contributor cannot forget the
  offscreen platform and get confusing failures.
* Good, because one tool covers lint and format, so there is no
  formatter-versus-linter disagreement to configure around.
* Good, because matching the sibling project's targets means muscle memory carries
  between the two repositories.
* Bad, because uv is a comparatively young tool, so the project inherits its
  release cadence and any behavioural changes.
* Bad, because the Makefile is a second place where workflow knowledge lives, and it
  can drift from the [development guide](../development.md). Both describe the same
  commands, so both need updating together.
* Bad, because `make` is an odd interface for a pure-Python project and offers no
  discoverability beyond reading the file — there is no `make help` target.
* Neutral, because ruff's defaults are accepted wholesale. There is no ruff
  configuration section, which keeps things simple at the cost of no project-specific
  rules.

### Confirmation

`ruff check .` reports no findings, and the suite passes via `make test`. The
release and AppImage pipelines both drive Makefile targets, so the targets are
exercised on every release rather than only in development.

## Pros and Cons of the Options

### uv, Hatchling, ruff, Make

* Good, because uv is fast and handles the direct-URL dependency and lockfile cleanly
* Good, because Hatchling produces a wheel plain `pip` can install in the AppImage container
* Good, because ruff replaces several tools with one
* Bad, because it is four tools rather than one integrated workflow
* Bad, because `make` has no built-in discoverability

### Poetry

* Good, because it integrates environment, build, and publish in one tool
* Neutral, because it supports URL dependencies
* Bad, because it is substantially slower to resolve
* Bad, because its build backend has historically been awkward about direct
  references, which is the project's core packaging constraint

### pip and venv with requirements.txt

* Good, because it needs no tooling beyond the standard library
* Bad, because there is no real lockfile, so hash-pinning a URL dependency is manual
* Bad, because dev-versus-docs dependency groups become several files by convention

### PDM or Hatch as workflow tool

* Good, because Hatch pairs naturally with the Hatchling backend already in use
* Neutral, because both are capable and standards-forward
* Bad, because neither matches uv's resolution speed
* Bad, because the sibling project already established the uv-plus-Make pattern,
  and diverging would cost consistency for little gain

## More Information

* `c430c5c` — initial scaffold; `9f27742` — the Makefile mirroring the sibling
  project; `f6f8217` — the `--extra dev` fix; `62b2d77`, `94b7d06`, `60f9675`,
  `7a51882` — ruff adoption, lint and format separated
* Related: ADR-0003 (the direct-URL dependency), ADR-0025 (`make test`),
  ADR-0027 (the AppImage targets), ADR-0028 (release targets)
