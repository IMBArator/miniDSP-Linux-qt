#!/usr/bin/env bash
# Build minidspqt as a self-contained AppImage with its own CPython.
#
# Pipeline:
#   1. Verify build prerequisites are present (do NOT install them).
#   2. Fetch pyenv's `python-build` helper (cached under build/cache/pyenv/).
#   3. Compile CPython from source into build/AppDir/usr (relocatable shared build).
#   4. Use that Python to pip-install the project and its deps.
#   5. Stage AppRun, .desktop, and icon into build/AppDir/.
#   6. Run linuxdeploy (+ qt plugin) to bundle system libs and fix up Qt plugins.
#   7. Run appimagetool to produce dist/minidspqt-<version>-x86_64.AppImage.
#
# Run from the repo root. The Makefile target `make appimage` does that for you.

set -euo pipefail

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

PYTHON_VERSION="${PYTHON_VERSION:-3.11.11}"
PYTHON_SHORT="${PYTHON_VERSION%.*}"            # e.g. "3.11"

LINUXDEPLOY_URL="https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage"
APPIMAGETOOL_URL="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
PYENV_GIT_URL="https://github.com/pyenv/pyenv.git"
# Pin pyenv to a specific tag for reproducible recipe versions. Bump occasionally.
PYENV_REF="${PYENV_REF:-v2.4.23}"

# Paths (relative to repo root, which is the script's CWD)
REPO_ROOT="$(pwd)"
PACKAGING_DIR="${REPO_ROOT}/packaging/appimage"
BUILD_DIR="${REPO_ROOT}/build"
CACHE_DIR="${BUILD_DIR}/cache"
APPDIR="${BUILD_DIR}/AppDir"
DIST_DIR="${REPO_ROOT}/dist"

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

log()   { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m!!\033[0m  %s\n' "$*" >&2; }
fail()  { printf '\033[1;31mxx\033[0m  %s\n' "$*" >&2; exit 1; }

need_cmd() {
    command -v "$1" >/dev/null 2>&1 \
        || fail "missing command: $1 (run packaging/appimage/init_environment.sh)"
}

# Download a URL into the cache (skips if already present). Args: url dest_filename.
fetch() {
    local url="$1" dest="${CACHE_DIR}/$2"
    if [[ -f "${dest}" ]]; then return 0; fi
    log "fetching $(basename "${dest}")"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --retry 3 -o "${dest}.part" "${url}"
    else
        wget -q -O "${dest}.part" "${url}"
    fi
    mv "${dest}.part" "${dest}"
    chmod +x "${dest}" 2>/dev/null || true
}

# -----------------------------------------------------------------------------
# Step 1 — prerequisites
# -----------------------------------------------------------------------------

step_check_prereqs() {
    log "checking build prerequisites"
    need_cmd gcc
    need_cmd make
    need_cmd pkg-config
    need_cmd file
    need_cmd git
    if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
        fail "need either curl or wget"
    fi
    need_cmd desktop-file-validate   # part of desktop-file-utils

    # Headers required for a complete CPython stdlib. Probe via pkg-config where
    # possible; fall back to header path probes for libs without .pc files.
    local missing=()
    for pc in openssl libffi zlib; do
        pkg-config --exists "${pc}" 2>/dev/null || missing+=("${pc}")
    done
    for hdr in /usr/include/bzlib.h /usr/include/lzma.h /usr/include/sqlite3.h \
               /usr/include/readline/readline.h /usr/include/uuid/uuid.h; do
        [[ -f "${hdr}" ]] || missing+=("$(basename "${hdr}")")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        fail "missing dev headers: ${missing[*]} — run packaging/appimage/init_environment.sh"
    fi
}

# -----------------------------------------------------------------------------
# Step 2 — fetch tools (linuxdeploy + pyenv/python-build)
# -----------------------------------------------------------------------------

step_fetch_tools() {
    log "fetching AppImage tools and pyenv"
    mkdir -p "${CACHE_DIR}"

    fetch "${LINUXDEPLOY_URL}"    linuxdeploy-x86_64.AppImage
    fetch "${APPIMAGETOOL_URL}"   appimagetool-x86_64.AppImage

    local pyenv_dir="${CACHE_DIR}/pyenv"
    if [[ ! -d "${pyenv_dir}/.git" ]]; then
        log "cloning pyenv ${PYENV_REF} (for python-build)"
        git clone --depth 1 --branch "${PYENV_REF}" "${PYENV_GIT_URL}" "${pyenv_dir}"
    fi
    export PATH="${pyenv_dir}/plugins/python-build/bin:${PATH}"
    need_cmd python-build
}

# -----------------------------------------------------------------------------
# Step 3 — compile Python into AppDir/usr
# -----------------------------------------------------------------------------

step_build_python() {
    if [[ -x "${APPDIR}/usr/bin/python${PYTHON_SHORT}" ]]; then
        log "Python ${PYTHON_VERSION} already installed in AppDir (skipping)"
        return 0
    fi

    log "building CPython ${PYTHON_VERSION} into AppDir/usr (this takes a few minutes)"
    mkdir -p "${APPDIR}/usr"

    # --enable-shared is the python-build default. The rpath in PYTHON_LDFLAGS
    # makes the installed bin/python<X.Y> find lib/libpython<X.Y>.so.1.0
    # relative to its own location, so the AppDir is fully relocatable.
    # No PGO/LTO: shaves several minutes off, ~10% perf loss is invisible for
    # a desktop Qt app dominated by event-loop time.
    CONFIGURE_OPTS="--enable-shared --with-ensurepip=install" \
    PYTHON_LDFLAGS='-Wl,-rpath,$$ORIGIN/../lib' \
    MAKE_OPTS="-j$(nproc)" \
        python-build "${PYTHON_VERSION}" "${APPDIR}/usr"

    # Sanity-check: every commonly used stdlib extension should import. If any
    # of these fails, a -dev header was missing at compile time — fail loudly
    # now rather than ship a half-broken Python.
    log "verifying CPython stdlib modules"
    "${APPDIR}/usr/bin/python${PYTHON_SHORT}" - <<'PY'
import importlib, sys
required = ["ssl", "sqlite3", "lzma", "bz2", "zlib", "ctypes",
            "hashlib", "readline", "uuid", "decimal"]
missing = []
for name in required:
    try:
        importlib.import_module(name)
    except Exception as exc:
        missing.append(f"{name} ({exc!s})")
if missing:
    sys.stderr.write("stdlib modules missing: " + ", ".join(missing) + "\n")
    sys.exit(1)
PY
}

# -----------------------------------------------------------------------------
# Step 4 — install the project into AppDir's Python
# -----------------------------------------------------------------------------

step_pip_install() {
    log "installing project wheel + dependencies into AppDir"
    local py="${APPDIR}/usr/bin/python${PYTHON_SHORT}"

    # Locate the prebuilt project wheel produced by `make build` (uv build).
    # Run this outside the container so uv is not required here.
    local wheel
    wheel="$(ls -t "${REPO_ROOT}/dist/"minidsp_linux_qt-*.whl 2>/dev/null | head -1 || true)"
    if [[ -z "${wheel}" ]]; then
        fail "no project wheel found in dist/. Run 'make build' on the host first, then re-run 'make appimage'."
    fi
    log "using wheel: $(basename "${wheel}")"

    "${py}" -m pip install --upgrade pip wheel

    # The wheel declares minidsp-linux via a PEP 508 direct URL
    # (`minidsp-linux @ git+https://...`), so pip pulls it from GitHub during
    # this single install — no separate manual `pip install git+...` step needed.
    "${py}" -m pip install --no-warn-script-location "${wheel}"

    # The console_script shim pip writes to AppDir/usr/bin/minidspqt embeds the
    # build-host's absolute path in its shebang and would break at runtime. The
    # AppRun calls `python -m minidspqt.cli` directly, so the shim isn't needed.
    rm -f "${APPDIR}/usr/bin/minidspqt"

    # PySide6-Essentials ships Qt plugins for features our desktop DSP control
    # app doesn't use. Several of them are orphaned (their .so files reference
    # Qt6 libraries that live in PySide6-Addons, which we deliberately don't
    # install) and would make linuxdeploy fail when it walks their deps.
    # Strip them upfront — the AppImage gets smaller and the dep walk stays
    # within the Essentials universe.
    local site_pkg
    site_pkg="$("${py}" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
    local qt_plugins="${site_pkg}/PySide6/Qt/plugins"
    for unused in \
        designer \
        egldeviceintegrations \
        networkinformation \
        platforminputcontexts \
        printsupport \
        qmllint \
        qmltooling \
        sqldrivers \
        tls; do
        rm -rf "${qt_plugins}/${unused}"
    done

    # platformthemes/libqgtk3.so brings in libgtk-3 + 20+ MB of GTK/glib/pango/
    # cairo/harfbuzz. We use our own QSS, so GTK theming is dead weight.
    # Keep libqxdgdesktopportal.so for native file-dialog integration on Wayland.
    rm -f "${qt_plugins}/platformthemes/libqgtk3.so"

    # Wayland *server*-side compositor plugins are for apps that BUILD a
    # compositor (i.e. embed QtWaylandCompositor). A regular Qt client app
    # only needs the wayland-shell-integration + wayland-decoration-client +
    # wayland-graphics-integration-client plugins.
    rm -rf "${qt_plugins}/wayland-graphics-integration-server"

    # Trim image format plugins we don't use:
    #   libqpdf.so   — orphan, depends on Qt6Pdf which lives in PySide6-Addons.
    #   libqtiff.so  — needs libtiff5 which we don't bundle; the app uses PNG
    #                  and SVG, never TIFF.
    rm -f "${qt_plugins}/imageformats/libqpdf.so"
    rm -f "${qt_plugins}/imageformats/libqtiff.so"

    # PySide6/Qt/qml ships QML modules (QtQuick, QtWayland/Compositor, etc.)
    # Our app is pure QtWidgets, so QML is entirely unused. The tree also
    # contains plugins referencing Addons-only Qt6 libs (Qt6Quick, Qt6Qml,
    # Qt6WaylandCompositorWLShell, …) which would otherwise trip linuxdeploy.
    rm -rf "${site_pkg}/PySide6/Qt/qml"
}

# -----------------------------------------------------------------------------
# Step 5 — stage AppRun, .desktop, icon
# -----------------------------------------------------------------------------

step_stage_assets() {
    log "staging AppRun, .desktop and icon"

    # Catch typos / malformed Categories / missing keys early — costs ~5 ms.
    desktop-file-validate "${PACKAGING_DIR}/minidspqt.desktop"

    install -Dm755 "${PACKAGING_DIR}/AppRun"            "${APPDIR}/AppRun"
    install -Dm644 "${PACKAGING_DIR}/minidspqt.desktop" "${APPDIR}/usr/share/applications/minidspqt.desktop"
    install -Dm644 "${PACKAGING_DIR}/minidspqt.png"     "${APPDIR}/usr/share/icons/hicolor/256x256/apps/minidspqt.png"

    # Host-environment shims (e.g. xdg-open) used by Qt to launch external
    # tools without leaking the AppImage's bundled lib paths to children.
    install -Dm755 "${PACKAGING_DIR}/host-wrappers/xdg-open" \
        "${APPDIR}/usr/bin/host-wrappers/xdg-open"

    # AppImage spec requires the .desktop and icon to *also* live at the AppDir root.
    cp "${PACKAGING_DIR}/minidspqt.desktop" "${APPDIR}/minidspqt.desktop"
    cp "${PACKAGING_DIR}/minidspqt.png"     "${APPDIR}/minidspqt.png"
    # And linuxdeploy expects a .DirIcon (a copy of the icon).
    cp "${PACKAGING_DIR}/minidspqt.png" "${APPDIR}/.DirIcon"
}

# -----------------------------------------------------------------------------
# Step 6 — linuxdeploy (system libs + Qt plugin fix-ups)
# -----------------------------------------------------------------------------

step_linuxdeploy() {
    log "running linuxdeploy"
    local py="${APPDIR}/usr/bin/python${PYTHON_SHORT}"

    # Inside an unprivileged container, /dev/fuse isn't available, so
    # AppImages can't self-mount. APPIMAGE_EXTRACT_AND_RUN=1 makes every
    # AppImage extract itself to a temp dir instead. On a host with FUSE
    # we let linuxdeploy/appimagetool mount themselves directly (a few
    # seconds faster, no /tmp churn).
    if [[ ! -c /dev/fuse ]] || ! command -v fusermount >/dev/null 2>&1; then
        export APPIMAGE_EXTRACT_AND_RUN=1
    fi

    # We DO NOT use linuxdeploy-plugin-qt. That plugin needs `qmake` to
    # discover Qt's install layout, which we don't have (Ubuntu 20.04 doesn't
    # package Qt 6 and we don't want to install the full Qt SDK just to
    # satisfy the plugin). PySide6 already ships its own Qt under
    # site-packages/PySide6/Qt with plugins/, qml/, translations/ at known
    # relative paths; AppRun points QT_PLUGIN_PATH at them. The plain
    # linuxdeploy ELF walk handles all the system library bundling we need
    # (libxcb, libssl, libffi, …) and fixes up rpaths on PySide6's own .so
    # files so they find each other inside the AppDir.
    #
    # Whether the tool extracts or self-mounts is decided by the
    # APPIMAGE_EXTRACT_AND_RUN env var set above. Don't also pass
    # --appimage-extract-and-run on the CLI: that would force extraction
    # even on hosts with FUSE.
    "${CACHE_DIR}/linuxdeploy-x86_64.AppImage" \
        --appdir "${APPDIR}" \
        --executable "${py}"
}

# -----------------------------------------------------------------------------
# Step 7 — appimagetool
# -----------------------------------------------------------------------------

step_appimagetool() {
    log "packaging AppDir into .AppImage"
    mkdir -p "${DIST_DIR}"

    # Use the bundled CPython (always present at this point) to parse
    # pyproject.toml properly, so quote style or whitespace tweaks can't
    # silently break version extraction.
    local py version
    py="${APPDIR}/usr/bin/python${PYTHON_SHORT}"
    version="$("${py}" -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' \
        "${REPO_ROOT}/pyproject.toml")"
    local out="${DIST_DIR}/minidspqt-${version}-x86_64.AppImage"

    # ARCH must be set; appimagetool refuses to infer it from a relative path.
    # Extract-vs-mount is governed by APPIMAGE_EXTRACT_AND_RUN (set in
    # step_linuxdeploy when no FUSE is available) — no CLI flag here.
    ARCH=x86_64 "${CACHE_DIR}/appimagetool-x86_64.AppImage" \
        "${APPDIR}" "${out}"

    chmod +x "${out}"
    log "produced ${out}"
    du -h "${out}"
}

# -----------------------------------------------------------------------------
# Step 8 — smoke test (no display required)
# -----------------------------------------------------------------------------

step_smoke_test() {
    local img
    img="$(ls -t "${DIST_DIR}"/minidspqt-*-x86_64.AppImage | head -1)"

    # Pass 1: `--help` exits 0 without needing a display — proves the bundled
    # Python boots, imports the package, and resolves the entry point.
    log "smoke-testing the AppImage (--help)"
    if ! "${img}" --help >/dev/null 2>&1; then
        warn "--help smoke test failed; re-running with output:"
        "${img}" --help || fail "AppImage --help failed"
    fi

    # Pass 2: actually start Qt. --help bails before Qt is initialised, so it
    # can't catch a missing platform plugin or a libQt6*.so version mismatch.
    # We boot the app in offline mode (no hardware needed) under the Qt
    # offscreen QPA (no display needed) and let timeout kill it after a few
    # seconds. With --preserve-status, that produces exit 143 (128+SIGTERM)
    # which is what we want: the event loop ran long enough to be killed.
    # Anything else (segfault, traceback, plugin load failure) is a real
    # failure.
    log "smoke-testing the AppImage (Qt offscreen boot)"
    local rc=0
    QT_QPA_PLATFORM=offscreen timeout --preserve-status 5 \
        "${img}" --offline >/dev/null 2>&1 || rc=$?
    case "${rc}" in
        0|124|143) log "Qt offscreen smoke test passed (exit ${rc})" ;;
        *)
            warn "Qt offscreen smoke test failed (exit ${rc}); re-running with output:"
            QT_QPA_PLATFORM=offscreen timeout --preserve-status 5 \
                "${img}" --offline || true
            fail "AppImage Qt smoke test failed"
            ;;
    esac
}

# -----------------------------------------------------------------------------
# Orchestration
# -----------------------------------------------------------------------------

main() {
    step_check_prereqs
    step_fetch_tools
    step_build_python
    step_pip_install
    step_stage_assets
    step_linuxdeploy
    step_appimagetool
    step_smoke_test
    log "done."
}

main "$@"
