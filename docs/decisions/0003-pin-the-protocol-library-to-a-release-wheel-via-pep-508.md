---
status: accepted
date: 2026-05-26
decision-makers: Maximilian Zettler
---

# Pin the protocol library to a published release wheel via a PEP 508 direct URL

## Context and Problem Statement

`minidsp-linux` (ADR-0001) is not published on PyPI. Something has to tell every
installer where to get it — and "every installer" is the crux, because this
project is consumed in four different ways: `uv sync` for development, `pip
install <wheel>` from a GitHub Release, plain `pip` inside the AppImage build
container, and `uv pip install --reinstall ../miniDSP-Linux/` when someone is
hacking on the protocol library itself.

Three successive mechanisms were tried before one satisfied all four.

## Decision Drivers

* A fresh clone must `uv sync` with no co-located sibling checkout.
* The built wheel must be installable by plain `pip`, because the AppImage build
  container has no `uv` (ADR-0027).
* Installation should not require `git` on `PATH`.
* Versions must be reproducible and hash-pinned in the lockfile.
* Developing against a local protocol checkout must stay possible.

## Considered Options

* A local filesystem path to a sibling wheel
* `[tool.uv.sources]` pointing at the upstream git tag
* A PEP 508 direct URL in `project.dependencies`, targeting a git tag
* A PEP 508 direct URL targeting a published release wheel over HTTPS

## Decision Outcome

Chosen option: **a PEP 508 direct URL to a published release wheel**, declared in
`project.dependencies` in
[pyproject.toml](https://github.com/IMBArator/miniDSP-Linux-qt/blob/main/pyproject.toml):

```toml
dependencies = [
    "PySide6-Essentials>=6.8",
    "minidsp-linux @ https://github.com/IMBArator/miniDSP-Linux/releases/download/v1.2.0/minidsp_linux-1.2.0-py3-none-any.whl",
]
```

The path there is worth recording, because each step failed for a specific and
non-obvious reason.

The original local sibling-wheel path meant a fresh clone could not sync without
a co-located `miniDSP-Linux` checkout, so it moved to the published v1.0.0 git
tag (`43bbfe3`).

That tag was expressed via `[tool.uv.sources]`, which turned out to be the real
trap: **the uv-sources block is honoured only by uv and is not propagated into
wheel metadata**. Any non-uv consumer of the built wheel — notably plain `pip`
inside the AppImage container — saw a bare `minidsp-linux>=1.0.0` requirement and
tried to resolve it from PyPI, where the package does not exist. Moving the
reference into `project.dependencies` as a PEP 508 direct URL records it in the
wheel's `Requires-Dist`, so a single `pip install <wheel>` now works (`6b25d8d`).
Hatchling refuses to emit direct-URL references into wheel metadata unless
explicitly permitted, which is why `[tool.hatch.metadata] allow-direct-references
= true` exists — the comment in `pyproject.toml` records that.

Finally the target changed from a `git+https` tag reference to the prebuilt
release wheel (`8c2ceb3`), removing the need for `git` on `PATH` at install time
and speeding installation up. The resolved wheel is hash-pinned in `uv.lock`.

### Consequences

* Good, because one declaration serves `uv sync`, `pip install <wheel>`, and the
  AppImage container identically.
* Good, because the version is exact and hash-pinned, which matters for a
  dependency whose wire encodings the application depends on precisely (ADR-0001).
* Bad, because upgrading is a manual edit of a URL containing the version three
  times, and forgetting one produces a confusing mismatch.
* Bad, because a hard pin means a GUI feature can be blocked pending an upstream
  release. This is not hypothetical: PEQ marker dragging needed `freq_hz_to_raw`,
  absent from the pinned 1.0.1, so for a period `make test` failed at import and
  only a local override worked. Bumping to 1.1.0 restored the standard workflow
  (`99e539e`).
* Bad, because the local-development override is fragile enough to need its own
  documentation. `uv pip install --reinstall --no-cache ../miniDSP-Linux/` is
  reverted by the next plain `uv run`, `uv sync`, or `make test`, all of which
  resync to the pin. `--no-cache` is required because the local version string
  does not change between edits, so uv would otherwise rebuild from its wheel
  cache and silently ignore fresh changes. Both traps are documented in the
  [development guide](../development.md#developing-against-a-local-protocol-library)
  (`2a4e854`).

### Confirmation

The wheel's `Requires-Dist` carries the direct URL — verifiable by inspecting the
built wheel's metadata. The AppImage pipeline installs the project wheel with
plain `pip` and would fail at resolution if the reference regressed to a bare
version specifier.

## Pros and Cons of the Options

### PEP 508 direct URL to a release wheel

* Good, because it is recorded in wheel metadata, so every installer sees it
* Good, because no `git` is needed at install time and it is faster than a VCS clone
* Neutral, because it requires `allow-direct-references` in Hatchling
* Bad, because the version appears redundantly in the URL

### PEP 508 direct URL to a git tag

* Good, because it is also recorded in wheel metadata
* Bad, because it requires `git` on `PATH` and builds from source on every install

### `[tool.uv.sources]`

* Good, because it is the idiomatic uv mechanism and supports clean local overrides
* Bad, because it is **not** propagated into wheel metadata, silently breaking
  every non-uv consumer — the defect that motivated this ADR

### Local sibling path

* Good, because it is ideal while co-developing both projects
* Bad, because a fresh clone cannot install at all

## More Information

* `43bbfe3` → `6b25d8d` → `8c2ceb3` → `99e539e` — the full progression
* Related: ADR-0001 (why the dependency exists), ADR-0026 (uv and Hatchling),
  ADR-0027 (the AppImage container that exposed the uv-sources defect)
