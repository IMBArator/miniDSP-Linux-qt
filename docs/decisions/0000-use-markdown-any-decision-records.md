---
status: accepted
date: 2026-08-22
decision-makers: Maximilian Zettler
---

# Record architectural decisions as MADR files

## Context and Problem Statement

By the time this record was written the project had roughly 186 commits behind
it and a substantial amount of design rationale — much of it genuinely
non-obvious, some of it compensating for undocumented firmware behaviour. That
rationale lived in three places: unusually detailed commit messages, the
[user guide](../user-guide.md) and [development guide](../development.md), and
inline comments.

That is fine for a reader who already knows what to look for, and poor for
everyone else. `git log` is not discoverable — nobody greps 186 commit bodies
before changing the theme resolver — and the reasoning behind a decision tends
to be attached to the commit that *implemented* it rather than the commit that
*chose* it. Several decisions had also been reversed (Qt Designer files, the
biquad sample rate, the dependency pinning mechanism), leaving the repository
with no single place stating what the current position is and why the previous
one was abandoned.

## Decision Drivers

* Decisions with lasting consequences should be findable without archaeology.
* Reversals need to be recorded, not silently overwritten, so nobody
  re-litigates a settled question or reinstates a known-bad approach.
* Several decisions exist to work around firmware behaviour that is not
  documented anywhere else; losing that context would be expensive.
* The project already publishes a documentation site, so records should render
  there at no extra cost.

## Considered Options

* Markdown Any Decision Records (MADR)
* Michael Nygard's original lightweight ADR template
* A single long `DECISIONS.md` file
* Continue relying on commit messages and prose documentation

## Decision Outcome

Chosen option: **MADR**, because its template explicitly asks for the *options
considered* and the *pros and cons of each* — not merely the outcome. Most of
this project's interesting decisions are interesting precisely because a
plausible alternative existed and was rejected for a concrete reason, and a
template that prompts for that captures more of the value than one that only
records the conclusion.

One file per decision under `docs/decisions/`, numbered sequentially, following
the MADR 4.x naming convention (`NNNN-title-with-dashes.md`).

### Consequences

* Good, because each decision has a stable, linkable identity, so code comments
  and other records can reference `ADR-0007` instead of restating the reasoning.
* Good, because the `status` field gives reversals a first-class representation:
  a superseded record stays readable and states what replaced it.
* Good, because the records render into the MkDocs site (see ADR-0029) and are
  indexed by its search.
* Neutral, because the initial batch was written retrospectively. The records
  describe decisions accurately and cite the commits that made them, but they
  document reasoning reconstructed from those commits rather than deliberation
  captured at the time.
* Bad, because records go stale silently. Nothing enforces that a behavioural
  change updates the record that governs it.

### Confirmation

A decision is recorded if `docs/decisions/` contains a file for it and
[index.md](index.md) lists it. Keeping records current is a review
responsibility, not an automated one.

## Pros and Cons of the Options

### Markdown Any Decision Records (MADR)

* Good, because the template prompts for considered options and their trade-offs
* Good, because YAML frontmatter carries status and date in a machine-readable way
* Good, because it is a widely recognised convention, so the layout needs no explanation
* Neutral, because the full template is verbose; short decisions warrant trimmed sections

### Nygard's original template

* Good, because it is very short, so records are cheap to write
* Bad, because it has no dedicated place for rejected alternatives, which is the
  part most worth preserving here

### A single DECISIONS.md

* Good, because there is only one file to find
* Bad, because per-decision status and supersession become conventions inside prose
* Bad, because it grows without bound and produces merge conflicts on unrelated edits

### Commit messages and prose documentation only

* Good, because it is the status quo and costs nothing
* Bad, because it is undiscoverable and scatters one decision's rationale across
  the several commits that implemented it

## More Information

* [MADR project](https://adr.github.io/madr/)
* [adr-template.md](adr-template.md) — the template for new records
