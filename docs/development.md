# Development

How to work on miniDSP-Linux-qt from a checkout: set it up, run it, test,
check and build it, and package it for Linux and Windows. `make help` lists
every target. How changes get in is in [CONTRIBUTING.md](../CONTRIBUTING.md);
how the code is built inside, and why, is in [architecture.md](architecture.md).

## Requirements

- Python 3.11 or newer, and [uv](https://docs.astral.sh/uv/), which manages
  the virtual environment and the dependencies. On Windows,
  `winget install astral-sh.uv` installs it, and uv provisions Python itself.
- GNU make: the targets are the way to set up, test, check and build. On
  Windows: `winget install ezwinports.make`.
- For a real device on Linux, read and write access to `/dev/hidraw*` (see
  [Permissions](../README.md#permissions) in the README). Windows needs no
  driver and no set-up.

The [miniDSP-Linux](https://github.com/IMBArator/miniDSP-Linux) protocol
library is installed from the release wheel pinned in `pyproject.toml`
([ADR-0003](decisions/0003-pin-the-protocol-library-to-a-release-wheel-via-pep-508.md)).
On Windows it brings hidapi along, through a platform marker, so the same
`make sync` sets up both platforms.

## Setting up

```bash
git clone https://github.com/IMBArator/miniDSP-Linux-qt.git
cd miniDSP-Linux-qt
make sync            # .venv with all dependencies, including the dev tools
```

On Windows the same commands run in PowerShell. A sibling checkout of the
protocol library (`../miniDSP-Linux`) is optional on every platform: it is what
[Developing against a local protocol library](#developing-against-a-local-protocol-library)
installs on top of the pinned wheel, and it supplies the real `.unt` fixture the
round-trip tests use, which they skip when it is absent.

## Running from the checkout

```bash
uv run minidspqt              # connect to the DSP
uv run minidspqt --offline    # virtual DSP, no hardware needed
uv run minidspqt -vv          # debug logging, including the USB frame traces
```

In VS Code, `.vscode/launch.json` has the same two ways to start, connected
and offline, under the debugger.

## Tests and checks

```bash
make test            # the test suite
make check           # ruff (lint) and ty (types); also make check-ruff, make check-ty
make fix-ruff        # apply ruff's safe automatic fixes
```

No hardware is needed: the tests drive `FakeDSPmini`, which is built on the
offline mode's `VirtualDSP`. `tests/conftest.py` sets `QT_QPA_PLATFORM=offscreen`
before Qt loads, so the widgets always run headless, without a display server
and the same on every platform. It uses `os.environ.setdefault`, so if you
export `QT_QPA_PLATFORM=xcb` yourself, you can watch a test drive a real
window. The suite also switches Qt's standard paths to test mode, so your own
settings, such as the theme you picked, stay untouched.

If ty reports that it can't resolve the `PySide6` modules, the environment has
lost files of PySide6-Essentials, which happens when an environment that once
had the full `PySide6` package uninstalls it. Remove `.venv` and run
`make sync` again.

### Developing against a local protocol library

By default `minidsp-linux` is pulled from the pinned upstream release wheel.
When hacking on the protocol library in a sibling checkout, reinstall it on top
of the synced env from your local source tree:

```bash
uv pip install --reinstall --no-cache ../miniDSP-Linux/
```

`--no-cache` matters: the local version string doesn't change between edits, so
without it `uv` rebuilds from its wheel cache and your fresh changes are
silently ignored.

> **Important — run tests with `--no-sync`.** A plain `uv run pytest` (and the
> `make test` target) first resyncs the env to the lockfile, which reverts the
> override back to the pinned release wheel. While testing against local protocol
> changes, run with sync disabled so your reinstall sticks:
>
> ```bash
> uv run --no-sync pytest
> ```

The override is reverted by the next `uv sync` / `uv lock` (or any plain
`uv run`). Re-run the reinstall whenever you want to test fresh local changes.

## Building

```bash
make build           # wheel and sdist into dist/
make docs            # the docs site into site/ (MkDocs Material)
make docs-serve      # live preview at http://127.0.0.1:8000
make clean           # remove the build output; make docs-clean removes site/
```

## Building the AppImage

A self-contained AppImage — a single executable file bundling its own CPython 3.11 and PySide6 — can be built locally. End users only need to download the resulting `.AppImage`, make it executable, and run it. No Python, no `uv`, no virtualenv on the user's machine.

Two steps: build the project wheel on the host with `uv` (fast, uses your dev venv), then build the AppImage in a container which downloads pyenv's `python-build`, compiles CPython from source into an `AppDir`, installs that wheel, and runs `linuxdeploy` + `appimagetool`.

**Step 1 — build the wheel on the host:**

```bash
make build      # produces dist/minidsp_linux_qt-<version>-py3-none-any.whl via uv
```

**Step 2a — Docker/Podman build** (recommended for releases — Ubuntu 20.04, glibc 2.31):

```bash
podman run --rm -v "$PWD":/src -w /src docker.io/library/ubuntu:20.04 bash -c \
    "bash packaging/appimage/init_environment.sh && make appimage"
# AppImage lands in ./dist/ on the host.
```

Replace `podman` with `docker` if that's what you have. With rootless Podman, add `--userns=keep-id` so `dist/` ends up owned by your host user.

For an interactive session (faster iteration, keeps the apt/pyenv install warm):

```bash
podman run --rm -it -v "$PWD":/src -w /src docker.io/library/ubuntu:20.04 bash
# inside the container, once:
bash packaging/appimage/init_environment.sh
# then, every time you want to (re)build (after `make build` on the host):
make appimage
exit
```

**Step 2b — native build** (without a container, whatever your host glibc is — fine for development):

```bash
bash packaging/appimage/init_environment.sh   # one-time, may prompt for sudo
make appimage                                  # produces dist/minidspqt-<version>-x86_64.AppImage
```

The resulting AppImage only runs on systems with a glibc at least as new as your build host.

`make appimage-clean` removes only the AppDir, the Python build tree, and `dist/*.AppImage`, leaving the `python-build` and `linuxdeploy` downloads cached under `build/cache/` so subsequent rebuilds are fast.

### Delta updates (optional)

Set `APPIMAGE_UPDATE_INFO` before `make appimage` to embed update metadata into the AppImage and emit a sibling `.zsync` file. AppImageUpdate-aware clients can then download only the chunks that changed between versions instead of the full ~160 MB.

For a GitHub-Releases-hosted artifact, run a native build with:

```bash
APPIMAGE_UPDATE_INFO="gh-releases-zsync|<owner>|<repo>|latest|minidspqt-*-x86_64.AppImage.zsync" \
    make appimage
# dist/ now also contains minidspqt-<version>-x86_64.AppImage.zsync
```

…or, inside the Podman/Docker container, pass the value via `-e` **without** adding inner double quotes (the single quotes around the whole `-e` argument already protect the `|` and `*` from the host shell — extra inner quotes end up *inside* the env var and `appimagetool` rejects the result as "unknown format"):

```bash
podman run --rm \
    -e 'APPIMAGE_UPDATE_INFO=gh-releases-zsync|<owner>|<repo>|latest|minidspqt-*-x86_64.AppImage.zsync' \
    -v "$PWD":/src -w /src docker.io/library/ubuntu:20.04 bash -c \
    "bash packaging/appimage/init_environment.sh && make appimage"
```

Upload both files (`.AppImage` and `.AppImage.zsync`) as release assets. Without `APPIMAGE_UPDATE_INFO`, no `.zsync` is produced and the AppImage carries no update info — that's the right choice for one-off local builds.

## Building the Windows distribution

The Windows build — a per-user installer and a portable zip — is assembled **on
Linux** by `packaging/windows/build.py`
([ADR-0031](decisions/0031-build-the-windows-distribution-on-linux-from-embeddable-cpython-and-wheels.md)).
Nothing is compiled on Windows and nothing is frozen. The script:

1. downloads python.org's *embeddable* CPython zip (SHA-256 pinned) and writes
   the `._pth` file that puts it in isolated mode with exactly the stdlib zip,
   the application directory (home of the stdlib's `.pyd` extension modules)
   and `Lib\site-packages` on `sys.path`, then checks that search path covers
   every loose extension module;
2. exports the locked dependency set and installs it **for Windows** with
   `uv pip install --python-platform x86_64-pc-windows-msvc --target …` — uv
   evaluates markers against the target, so the protocol library's
   `hidapi ; sys_platform == 'win32'` lands in the tree — then installs the
   project wheel from `dist/` on top;
3. prunes PySide6 by allow-list to the Qt modules the application imports, and
   then reads the import tables of every remaining DLL to prove nothing that is
   still needed was removed;
4. cross-compiles the `minidspqt.exe` launcher with mingw-w64 (icon, version
   info, GUI subsystem — no console window);
5. zips the tree and runs NSIS for the installer;
6. checks its own zip for the files that must and must not be there.

Qt stays a set of ordinary DLLs next to a real `site-packages`, so the
dynamic-linking statement in the licence notice
([ADR-0004](decisions/0004-license-under-gplv3-with-lgpl-and-interop-notices.md))
holds on Windows exactly as it does in the AppImage.

**Prerequisites** (Debian 12+/Ubuntu 24.04+): `nsis`, `gcc-mingw-w64-x86-64`,
`binutils-mingw-w64-x86-64`, and `uv`. `packaging/windows/init_environment.sh`
installs them (and `uv`, when it is missing — for containers).

**Step 1 — build the wheel on the host** (same as for the AppImage):

```bash
make build      # produces dist/minidsp_linux_qt-<version>-py3-none-any.whl via uv
```

**Step 2a — container build:**

```bash
podman run --rm -v "$PWD":/src -w /src -v ~/.cache/uv:/root/.cache/uv \
    docker.io/library/debian:13 bash -c \
    "bash packaging/windows/init_environment.sh && make windows"
# dist/minidspqt-<version>-win_amd64.zip
# dist/minidspqt-<version>-win_amd64-setup.exe
```

Mounting `~/.cache/uv` is optional; it saves re-downloading the PySide6 wheel on
every run. Replace `podman` with `docker` if that's what you have.

**Step 2b — native build:**

```bash
bash packaging/windows/init_environment.sh   # one-time, may prompt for sudo
make windows
```

`make windows-clean` removes `build/windows/` and the two artifacts; the
embeddable CPython download stays cached under `build/cache/`.

### Building against an unreleased protocol library

A release build installs the protocol library from the lock, like everything
else. To try unreleased library changes in a bundle, point the build at a wheel
built from the sibling checkout instead:

```bash
make -C ../miniDSP-Linux build
make windows MINIDSP_LINUX_WHEEL=../miniDSP-Linux/dist/minidsp_linux-<version>-py3-none-any.whl
```

In the container, mount the wheel and pass the variable with `-e`:

```bash
podman run --rm -v "$PWD":/src -w /src -v ~/.cache/uv:/root/.cache/uv \
    -v "$PWD/../miniDSP-Linux/dist":/upstream:ro \
    -e MINIDSP_LINUX_WHEEL=/upstream/minidsp_linux-<version>-py3-none-any.whl \
    docker.io/library/debian:13 bash -c \
    "bash packaging/windows/init_environment.sh && make windows"
```

The build then prints an **UNLOCKED DEV BUILD** warning: that one requirement and
its dependencies come from outside `uv.lock`. Such a build is for trying things
out on a Windows machine.

### What the build checks, and what it cannot

On Linux every build verifies its own output: the interpreter search-path check
(every stdlib `.pyd`, the stdlib zip and `site-packages` reachable from the
`._pth`), the DLL import-closure check after pruning, and a layout check of the
zip (launcher, interpreter, `._pth`, a stylesheet from the package data, the
hidapi extension, Qt's `qwindows.dll`, the project's `.dist-info` — and none of
the pruned trees). If `wine` is on `PATH`, the script additionally runs `--help`
and boots the offline mode under Qt's offscreen platform, the same two-pass
smoke test the AppImage gets. That step is optional.

What Linux cannot check is the real thing: before a release that ships Windows
artifacts, the maintainer walks through the
[Windows check](../CONTRIBUTING.md#windows-check) on a Windows 11 machine.

### Code signing

Neither the launcher nor the installer is signed, hence the SmartScreen dialog
on first start. `osslsigncode` can sign both from Linux once a code-signing
certificate exists; until then the README documents the click-through.

## Windows notes

`sync`, `install`, `test`, `check`, `check-ruff`, `check-ty`, `fix-ruff`,
`build`, `docs` and `docs-serve` work in PowerShell as they are. `version`,
`publish` and `appimage` run bash scripts, `windows` needs `makensis` and a
mingw-w64 cross-compiler, and `clean`, `docs-clean`, `appimage-clean` and
`windows-clean` use `rm -rf`; those need Linux, or for the scripts and `rm` a
POSIX shell such as Git Bash, which comes with Git for Windows.

The downloadable Windows build is assembled on Linux, not on Windows; see
[Building the Windows distribution](#building-the-windows-distribution).
