#!/usr/bin/env bash
# One-shot setup for a Debian 12+/Ubuntu 24.04+ host or container that builds
# the Windows distribution (`make windows`) on Linux.
#
# It installs:
#   - nsis                        makensis, builds the setup.exe
#   - gcc-mingw-w64-x86-64        cross-compiles the minidspqt.exe launcher
#   - binutils-mingw-w64-x86-64   windres, embeds icon/version/manifest
#   - curl, ca-certificates       downloads (embeddable CPython, wheels)
#   - make                        the `make windows` target itself
#   - uv                          only if missing (containers); on a dev host
#                                 uv is already the project tool (ADR-0026)
#
# It does NOT install Wine. The optional Wine smoke test in build.py runs only
# when `wine` happens to be on PATH; the Windows 11 checklist in
# docs/development.md is the real verification.

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    SUDO="sudo"
    if ! command -v sudo >/dev/null 2>&1; then
        echo "error: this script needs root (run as root, or install sudo)" >&2
        exit 1
    fi
else
    SUDO=""
fi

export DEBIAN_FRONTEND=noninteractive

${SUDO} apt-get update
${SUDO} apt-get install -y --no-install-recommends \
    nsis gcc-mingw-w64-x86-64 binutils-mingw-w64-x86-64 \
    curl ca-certificates make

${SUDO} rm -rf /var/lib/apt/lists/*

if ! command -v uv >/dev/null 2>&1; then
    echo "uv not found — installing to /usr/local/bin"
    curl -LsSf https://astral.sh/uv/install.sh \
        | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 ${SUDO} sh
fi

echo
echo "init_environment.sh: done. You can now run 'make windows' from the repo root."
