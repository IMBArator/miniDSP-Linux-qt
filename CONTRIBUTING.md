# Contributing to miniDSP-Linux-qt

This guide is about how a change gets into miniDSP-Linux-qt: branches, commits,
what to check before you commit, and the conventions the code follows.
Everything else lives elsewhere and isn't repeated here: how to install and use
the application is in the [README](README.md) and the
[user guide](docs/user-guide.md), how to set it up and work on it from a
checkout is in the [developer guide](docs/development.md), and how it is built
inside, and why, is in [docs/architecture.md](docs/architecture.md).

## Branches

Finished work lives on `main`, and every release is tagged there. For anything
bigger than a small fix, such as a feature or a larger refactoring, start a
branch from `main` called `feature/<name>` and merge it back when it's done.

`gh-pages` is different: it holds the published docs site and is written by
`make publish`, so nobody edits it by hand.

Before you change anything, check which branch you're on.

## Commits

Keep each commit to one topic. A feature's code, its tests and the docs that
describe it go into one commit, not into separate test and docs commits;
unrelated changes go into separate commits. That keeps every commit a complete,
revertable change, and it keeps a feature's tests and docs next to it in the
history: the changelog leaves out `test` and `docs`-only commits of a feature
it would otherwise list.

Commit subjects follow [Conventional Commits](https://www.conventionalcommits.org/):
`type(scope): subject`, in lower case and without a full stop, for example
`fix(peq): keep the band marker inside the graph`. The scope names the module,
the view or the kind of document (`readme`, `decisions`).

| Type | Use it for |
|---|---|
| `feat` | new behaviour |
| `fix` | a bug fix |
| `refactor`, `perf` | changes that don't alter behaviour |
| `docs` | documentation |
| `test` | tests only |
| `build`, `chore` | tooling, dependencies, packaging, housekeeping; `chore(release)` is the release commit |

Add a body when the reason for a change isn't obvious from the diff.

Stage files by name rather than with `git add .`, so nothing generated slips
in: build output (`dist/`, `build/`, `site/`), caches and virtual environments
never belong in a commit. Keep local paths, home directories and personal tool
settings out of documents, code, comments and commit messages, too; not
everybody who reads the project can see them.

## Before you commit

Run `make test` and `make check`; both have to pass. Always go through the make
targets, in your shell as well as in docs and commit messages, rather than
calling pytest, ruff or ty yourself: the Makefile is the one place that decides
the flags and paths, so everybody runs the same thing. How to set it all up is
in the [developer guide](docs/development.md).

Some things belong in the same commit as your change:

- **Tests.** When behaviour changes, the tests change with it. A new feature
  gets its own test module, `tests/test_<feature>.py`. A regression test says
  which bug it guards against.
- **Docs.** Update the README when installation, commands or the feature list
  change, the [user guide](docs/user-guide.md) when the way the application is
  used changes, the developer guide when the development setup changes, and
  [docs/architecture.md](docs/architecture.md) when the design, a module's job
  or an invariant changes. Please don't state the number of tests anywhere; it
  is out of date with the next commit.
- **A decision record**, when the change makes or reverses a decision (see
  [Architecture decisions](#architecture-decisions)).

The changelog is written from the commit subjects by git-cliff when a release
is made: `feat` becomes "Added", `fix` "Fixed", `refactor` and `perf`
"Changed", `docs` "Documentation", and the other types are left out. So choose
the type by what a reader of the changelog should learn, and write the subject
for them. Whatever is edited by hand in `CHANGELOG.md` survives later releases.

## Code

The project uses Python 3.11 (set in `pyproject.toml`), uv for the environment
and Hatchling for the build; `uv.lock` is committed. The application is the
`minidspqt/` package, the tests live in `tests/`, and the AppImage and Windows
builds in `packaging/`.

- Every module that contains code starts with
  `from __future__ import annotations` (ruff checks this), and docstrings use
  the Google style, because the API reference on the docs site is generated
  from them.
- Modules log through `log = logging.getLogger(__name__)` and never configure
  logging themselves; only the entry point does that.
- Fix ruff and ty findings instead of silencing them: no `# noqa`, no
  `# type: ignore` or `# ty: ignore`, and no settings that switch a check off.
  When ty complains that a value might be `None`, check it with an `assert`;
  when it doesn't accept a test fake, make the fake a subclass of the real
  class or `cast` it where it is passed in.
- Tests are plain `test_*` functions in modules that have a docstring and are
  divided by `# --- section ---` comments. They drive the code against
  `FakeDSPmini` from `tests/conftest.py` and use pytest-qt's `qtbot` for
  widgets; small fakes and `monkeypatch` are preferred over new fixtures.
- Which files a new device command, feature panel, widget or colour touches is
  described under
  [How things plug in](docs/architecture.md#how-things-plug-in).

## The device, the protocol library and releases

The [invariants](docs/architecture.md#invariants) in the architecture document
are the rules no change may break, for example that only the device worker
talks to the DSP. Please read them before you change the code they protect: a
change that breaks one is wrong even when every test passes.

Try changes in offline mode (`--offline`) first. On a real DSP, storing a
preset writes the device's flash, and a PIN, once set, can't be removed: there
is no known factory reset.

Everything about the protocol and the `.unt` file format belongs to the
[miniDSP-Linux](https://github.com/IMBArator/miniDSP-Linux) library. When the
GUI needs something the library doesn't have, or the library gets something
wrong, change the library, release it, and then move this project's pin (the
wheel URL in `pyproject.toml`, and `uv.lock`) to the new release in a commit of
its own.

Releases and publishing are done by the maintainer:

1. `make version VERSION=X.Y.Z` sets the new version (in `pyproject.toml`,
   `uv.lock` and `minidspqt/__init__.py`), adds the changelog section, and
   commits and tags the release. Before it commits, it shows the new changelog
   section and offers to open it in your editor, so you can drop or reword
   entries (for example ones for changes that never reached a release). The
   script refuses to run on a dirty working tree, for an existing tag or for a
   version that already has a changelog section. It asks before tagging from a
   branch other than `main` or a version below the latest, and it pushes only
   after an explicit yes, never when it doesn't run in a terminal.
2. Push the commit and the tag, if the script didn't.
3. `make build` puts the wheel and the sdist into `dist/`.
4. `make appimage` builds the AppImage, for a release in an Ubuntu 20.04
   container, and `make windows` the Windows installer and portable zip; the
   [developer guide](docs/development.md#building-the-appimage) has the
   commands.
5. Before a release that ships the Windows files, walk through the
   [Windows check](#windows-check) below on a Windows 11 machine.
6. `make publish` (with a `GITHUB_TOKEN` that has `repo` scope) creates the
   GitHub Release from the changelog section, attaches the wheel, the sdist,
   the AppImage (and its `.zsync`, if there is one) and the two Windows files,
   and deploys the docs to GitHub Pages. It refuses to publish without the
   Windows files; `SKIP_WINDOWS=1 make publish` is the deliberate exception for
   a Linux-only release. Versions with `-rc`, `-beta` or `-alpha` become
   prereleases.

A Windows build made with `MINIDSP_LINUX_WHEEL` uses a library wheel from
outside `uv.lock` and prints an **UNLOCKED DEV BUILD** warning; never publish
it.

### Windows check

The Linux build checks its own output, but it can't run the real thing. Before
a release that ships Windows files, on a Windows 11 machine:

1. Run the installer: SmartScreen → **More info → Run anyway**; licence page;
   the installation lands in `%LOCALAPPDATA%\Programs\minidspqt`; a Start Menu
   entry appears.
2. Start it from the Start Menu, and `minidspqt.exe --offline` from a terminal:
   the window appears, the theme switches, a `.unt` loads and saves.
3. Connect the DSP: the configuration is read, the level meters move, a gain
   edit reaches the device.
4. Start a second instance while the first is connected: it shows
   **Device busy**; closing the first makes the second connect.
5. `minidspqt-debug.cmd` opens a console with `-vv` output;
   `%LOCALAPPDATA%\miniDSP\minidspqt\minidspqt.log` exists after a normal
   start.
6. Uninstall via *Settings → Apps → Installed apps*: the program folder and
   the shortcut are gone.
7. Extract the portable zip from the Downloads folder (so Mark-of-the-Web
   applies) and double-click `minidspqt.exe`.

## Architecture decisions

Decisions with lasting consequences are recorded in
[docs/decisions/](docs/decisions/index.md), one Markdown file per decision in
the [MADR](https://adr.github.io/madr/) format. They answer "why is it like
this?" without digging through the commit history, and they keep settled
questions from being reopened by accident. Several of them document a position
the project tried and abandoned; the index lists those separately. Before you
propose a change in an area, read its records.

Write a record when a change chooses between real alternatives that someone
might later question (a library, a toolkit, a file format, a UI pattern, a way
of distributing the application), when it constrains future work, or when it
reverses an earlier decision. If you're unsure, ask yourself whether undoing it
later would be costly or confusing without knowing why it was made. Bug fixes,
refactorings and small features don't need a record, and neither does anything
that only follows the conventions in this guide; records are for the project's
own choices and for every deviation from these conventions.

To write one, copy [the template](docs/decisions/adr-template.md) to the next
free number (`NNNN-title-with-dashes.md`) and fill it in. Keep it to one
decision and about a page: the problem, the options you really had, the choice
and its consequences. Date it with the day the decision was made; if you write
it later, say so and name the commit that made it. The current design and
how-tos don't belong in a record; link to where they live. Then add the record
to the [index](docs/decisions/index.md), and update
[docs/architecture.md](docs/architecture.md) if it changes the picture there.

An accepted record is never rewritten. When a decision changes, write a new
record, mark the old one `superseded by ADR-NNNN` and link both ways. Small
additions that don't change the decision, such as a follow-up commit or a
known limitation, go into the old record's "More Information".
