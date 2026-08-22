---
status: accepted
date: 2026-05-24
decision-makers: Maximilian Zettler
---

# Publish documentation as an MkDocs Material site with a generated API reference

## Context and Problem Statement

Documentation had accumulated as loose Markdown in a `doc/` directory: a long
README, a user guide, and two historical planning documents whose ideas had long
since shipped. The README had grown to carry both end-user material (installation,
usage, permissions) and contributor material (dev setup, testing, packaging,
releasing), so neither audience could scan it.

There was also no API documentation, despite the codebase having accumulated
docstrings across every module.

## Decision Drivers

* End users and contributors need different documents, not one long file.
* Content already in the README and `CHANGELOG.md` should not be duplicated to
  appear on a site.
* An API reference should derive from docstrings, since maintaining a parallel one
  is not realistic.
* Source Markdown should stay readable on GitHub, not just in rendered form.
* The sibling `miniDSP-Linux` project already had a working documentation pipeline.

## Considered Options

* MkDocs Material with mkdocstrings, transclusion, and a generated API reference
* Sphinx with autodoc
* Loose Markdown on GitHub with no site
* A hand-written API reference page

## Decision Outcome

Chosen option: **MkDocs Material**, with the pipeline adapted from the sibling
project (`7ff4a0c`).

`doc/` was renamed to `docs/` via `git mv` to preserve history, putting Markdown
where MkDocs looks by default. The plugin set is `search`, `include-markdown`,
`gen-files`, `literate-nav`, `section-index`, and `mkdocstrings`.

Four decisions inside that choice are worth recording.

**Content is transcluded, not duplicated.** `docs/index.md` transcludes the README
and `docs/changelog.md` transcludes `CHANGELOG.md`, so the site has no second copy
to keep in sync — which matters especially for the generated changelog (ADR-0028).
The cost is a `docs/hooks.py` that rewrites repo-root-relative links so they resolve
both on the rendered site and in GitHub's view of the source: the README's `LICENSE`
link becomes a GitHub URL, and `../CHANGELOG.md` and `../README.md` are remapped.

**The API reference is generated.** `docs/gen_ref_pages.py` walks the `minidspqt`
package and emits one virtual Markdown page per module plus an `api/SUMMARY.md` for
`literate-nav`, which `hooks.py` then drops from the rendered output once consumed.
mkdocstrings is configured for Google-style docstrings with `show_source` and
`merge_init_into_class`, and filters private members.

**Google-style docstrings are the required style.** Getting there was a deliberate
five-commit pass across the whole codebase before the site went live — library
layer, widgets, panels, views — which also normalised pre-existing
reStructuredText and NumPy-style sections into a single style so `help()` and IDE
tooltips render consistently (`ad38b33`, `b2e4383`, `58490a7`, `072b0f8`). A
follow-up fixed docstring indentation and added missing type annotations so griffe's
strict parser is clean (`7ca07ff`). The convention is recorded in `CLAUDE.md`.

**Historical planning documents were deleted rather than published.**
`architecture-plan.md` and `offline-mode-unt-read-write.md` were implementation
plans whose content had shipped; publishing them would have put stale designs in the
rendered site and its search index (`0d76381`). This decision log is the intended
replacement — records of decisions, not plans for them.

The README was then trimmed to an end-user document, with all contributor material
relocated to `docs/development.md` (`8273c7a`). Duplication was removed where the
user guide repeated the README's installation and USB-permissions sections, replaced
by links (`0246dc0`).

### Consequences

* Good, because each audience has a document scoped to it, and neither has to skim
  the other's.
* Good, because transclusion means the README and changelog have exactly one copy.
* Good, because the API reference cannot go stale relative to the code; it is
  regenerated on every build.
* Good, because the docstring pass improved in-editor experience as much as the
  site — the reference is a byproduct.
* Good, because `make publish` deploys the site, so documentation ships with each
  release (ADR-0028).
* Bad, because `hooks.py` is bespoke glue that exists only to reconcile
  GitHub-relative links with site-relative ones. It is the fragile part of the
  pipeline and will need attention whenever cross-document links move.
* Bad, because the generated `site/` directory and the docs dependency group add
  build surface; `make docs` uses `--inexact` so installing docs tooling does not
  evict dev extras.
* Neutral, because docstring style is now load-bearing. A NumPy-style docstring
  renders incorrectly rather than failing loudly, so the convention needs review
  attention.

### Confirmation

`uv run mkdocs build --strict` is clean, which catches broken internal links and
navigation problems. Griffe's strict parsing surfaces docstring defects at build
time — the indentation fixes in `7ca07ff` came from exactly that signal.

## Pros and Cons of the Options

### MkDocs Material with mkdocstrings

* Good, because source stays plain Markdown, readable directly on GitHub
* Good, because transclusion avoids duplication, and the API reference is generated
* Good, because it matches the sibling project's pipeline
* Bad, because reconciling GitHub-relative and site-relative links needs custom hooks

### Sphinx with autodoc

* Good, because it is the most capable Python documentation tool, with strong
  cross-referencing
* Neutral, because MyST would allow Markdown sources
* Bad, because reStructuredText is the native format, and the project's docs are
  Markdown meant to read well on GitHub
* Bad, because it is heavier configuration than this project needs

### Loose Markdown, no site

* Good, because there is no build step or tooling at all
* Bad, because there is no API reference and no search
* Bad, because one long README serving both audiences was the actual problem

### A hand-written API reference

* Good, because prose could be tailored beyond what docstrings express
* Bad, because it would drift from the code immediately
* Bad, because it duplicates docstrings that already exist

## More Information

* `7ff4a0c` — the pipeline; `0d76381` — removing historical plans;
  `8273c7a` — splitting the developer guide out of the README;
  `ad38b33`, `b2e4383`, `58490a7`, `072b0f8`, `7ca07ff` — the docstring pass
* Related: ADR-0000 (these records render through this pipeline),
  ADR-0026 (`make docs` targets), ADR-0028 (changelog generation and deployment)
