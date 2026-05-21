#!/usr/bin/env bash
# One-shot setup for an Ubuntu 20.04 / Debian 11+ build environment.
# Run this once inside a fresh container or VM before `make appimage`.
#
# It installs:
#   - build-essential + the -dev headers CPython 3.11 needs for a complete stdlib
#   - the system libraries linuxdeploy will look for when bundling Qt/XCB/OpenSSL
#   - libfuse2 so the downloaded AppImage tools can run normally
#
# It does NOT install Python (we build that from source in build.sh) and it
# does NOT invoke the build itself.

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
    build-essential pkg-config wget curl ca-certificates file make git \
    desktop-file-utils \
    libssl-dev libffi-dev zlib1g-dev libbz2-dev liblzma-dev \
    libsqlite3-dev libreadline-dev libncursesw5-dev uuid-dev libgdbm-dev \
    tk-dev \
    libxcb1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-sync1 \
    libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1 \
    libxkbcommon-x11-0 libdbus-1-3 \
    libfontconfig1 libegl1 libgl1 libglib2.0-0 \
    libwayland-client0 libwayland-cursor0 libwayland-egl1 libwayland-server0 \
    fuse libfuse2

${SUDO} rm -rf /var/lib/apt/lists/*

echo
echo "init_environment.sh: done. You can now run 'make appimage' from the repo root."
