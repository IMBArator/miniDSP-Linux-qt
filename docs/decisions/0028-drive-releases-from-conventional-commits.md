---
status: accepted
date: 2026-05-26
decision-makers: Maximilian Zettler
---

# Drive changelog and releases from Conventional Commits

## Context and Problem Statement

A release means several coordinated steps: bump the version, produce release notes,
tag, build a wheel, an sdist, and an AppImage, create a GitHub Release with the
right assets, and deploy the documentation site. Doing that by hand is error-prone
in ways that are annoying to fix after the fact — a mistyped tag or a changelog
missing an entry.

Release notes are the part that rots fastest. Hand-maintained changelogs drift
because the information needed to write an entry exists at commit time and is
reconstructed at release time.

## Decision Drivers

* Release notes should derive from work already recorded, not be rewritten later.
* The release sequence must be repeatable, since it spans several artifacts
  including a containerised AppImage build (ADR-0027).
* Not every commit is user-visible; a changelog is for humans.
* The sibling `miniDSP-Linux` project already had a working release flow.

## Considered Options

* Conventional Commits as machine-readable input, with git-cliff generating a
  Keep a Changelog file, driven by scripts behind `make` targets
* A hand-maintained `CHANGELOG.md`
* A hosted release tool such as semantic-release
* No changelog; rely on GitHub's auto-generated release notes

## Decision Outcome

Chosen option: **Conventional Commits as the input, git-cliff as the generator,
and two shell scripts behind `make` targets.**

Commit messages follow Conventional Commits. `cliff.toml` maps types to
Keep a Changelog 1.0.0 categories: `feat` → Added, `fix` → Fixed, `refactor` and
`perf` → Changed, `docs` → Documentation. Everything else is **explicitly skipped**
— `chore`, `build`, `test`, `ci`, `style`, and `chore(release)` — because a
changelog is for users, not a commit log.

`scripts/version.sh` bumps `pyproject.toml`, regenerates `CHANGELOG.md`, commits
`chore(release): vX.Y.Z`, and tags, with preflight checks for a clean tree, the
right branch, tag uniqueness, and version monotonicity.
`scripts/publish.sh` creates the GitHub Release from an existing tag, uploads the
wheel, sdist, AppImage, and optional `.zsync`, and deploys documentation to GitHub
Pages. Release notes are extracted from the matching `## [X.Y.Z]` section of the
changelog, and tags containing `-rc`, `-beta`, or `-alpha` are automatically flagged
as prereleases. Both are fronted by `make version` and `make publish` (ADR-0026),
and both were ported from the sibling project (`bd61f58`).

Two related conventions, recorded in [CLAUDE.md](https://github.com/IMBArator/miniDSP-Linux-qt/blob/main/CLAUDE.md):

* **A feature's implementation, tests, and documentation go in one commit**, not
  split into separate test and docs commits. Since `test` and `docs` types are
  skipped by the changelog, splitting them would put a feature's tests and
  documentation outside the release notes while the code appeared alone. The
  convention keeps a commit a complete unit of work — and, incidentally, made these
  ADRs writable, because each feature commit carries its full rationale.
* **No AI-generated attribution trailers or footers** in commit messages or pull
  request bodies (`6509c99`).

### Consequences

* Good, because release notes are a byproduct of committing, so they cannot be
  forgotten.
* Good, because the type prefix is a small, immediate discipline at the moment the
  author knows what the change is.
* Good, because the release sequence is scripted with preflight checks, so a bad
  tag or dirty tree fails before anything is published.
* Good, because the commit convention produces genuinely informative history — the
  main source for this entire decision log.
* Bad, because changelog quality is bounded by commit-subject quality. A vague
  subject line becomes a vague changelog entry, and fixing it after tagging means
  rewriting history.
* Bad, because the skip list is a judgement encoded in configuration. A
  user-visible change committed as `chore` silently vanishes from the changelog.
* Bad, because releases are not fully automated: `make version`, push, `make build`,
  `make appimage`, `make publish` are separate manual steps, with the AppImage
  needing a container. Deliberate — the AppImage build is heavy enough to want a
  human in the loop — but it means the sequence must be followed correctly.
* Neutral, because `publish.sh` requires a `GITHUB_TOKEN` with `repo` scope in the
  environment, so releasing depends on a personal access token rather than CI
  credentials.

### Confirmation

`CHANGELOG.md` is generated rather than edited, and `docs/changelog.md` transcludes
it into the site (ADR-0029). `version.sh`'s preflight checks are the enforcement
point: a dirty tree, wrong branch, duplicate tag, or non-monotonic version aborts
before any commit or tag is created.

## Pros and Cons of the Options

### Conventional Commits with git-cliff and scripts

* Good, because notes derive from existing records and cannot drift
* Good, because the release sequence is scripted and validated
* Bad, because entry quality equals subject-line quality
* Bad, because the skip list can silently omit a user-visible change

### Hand-maintained CHANGELOG.md

* Good, because entries can be written for users, in whatever voice suits
* Good, because there is no constraint on commit-message format
* Bad, because it drifts; it is the failure mode this replaced
* Bad, because writing entries at release time means reconstructing weeks-old context

### A hosted tool such as semantic-release

* Good, because it fully automates versioning and publishing from commit types
* Neutral, because it also relies on Conventional Commits
* Bad, because automatic version inference is undesirable here — the AppImage build
  needs a human, and version bumps are deliberate
* Bad, because it is heavier machinery than a two-script flow needs

### GitHub auto-generated notes only

* Good, because it requires no configuration at all
* Bad, because output is a flat commit or PR list with no user-versus-internal
  distinction
* Bad, because there would be no changelog in the repository or on the docs site

## More Information

* `bd61f58` — the scripts and `make` targets; `6509c99` — the commit conventions in
  `CLAUDE.md`; [cliff.toml](https://github.com/IMBArator/miniDSP-Linux-qt/blob/main/cliff.toml) — the type mapping
* [Releasing](../development.md#releasing)
* Related: ADR-0026 (`make` targets), ADR-0027 (the AppImage asset),
  ADR-0029 (changelog transclusion)
