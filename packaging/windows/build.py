#!/usr/bin/env python3
"""Build the Windows distribution of minidspqt on a Linux host.

The recipe is the AppImage one (``packaging/appimage/build.sh``) transposed to
Windows: bundle an interpreter, install the project wheel and its dependencies
into a real ``site-packages`` next to it, throw away the parts of Qt the
application never loads, and wrap the result. Nothing is compiled on Windows
and nothing is frozen — Qt stays a set of ordinary, replaceable DLLs, which is
what keeps the LGPL notice in ADR-0004 true.

Pipeline:
  1. Verify build prerequisites (uv, makensis, mingw-w64) — never install them.
  2. Fetch python.org's *embeddable* CPython zip (cached under build/cache/),
     verify its SHA-256, unpack it, and write the ``._pth`` search path.
  3. Export the locked dependency set and install it *for Windows* with
     ``uv pip install --python-platform x86_64-pc-windows-msvc --target``, then
     install the project wheel from dist/ on top.
  4. Prune PySide6 down to the Qt modules the application imports, then prove
     from the PE import tables that no kept DLL needs a DLL that was removed.
  5. Cross-compile the ``minidspqt.exe`` launcher with mingw-w64.
  6. Stage the icon, licence, and debug launcher.
  7. Zip the tree into dist/minidspqt-<version>-win_amd64.zip.
  8. Build dist/minidspqt-<version>-win_amd64-setup.exe with NSIS.
  9. Smoke-test: structural checks on the zip (always) and a Qt offscreen boot
     under Wine (only when ``wine`` is installed; never a release gate).

Run from the repo root; ``make windows`` does that for you. Environment knobs:

  MINIDSP_LINUX_WHEEL   Path to a locally built protocol-library wheel. Replaces
                        the locked ``minidsp-linux`` pin for this build only and
                        marks the result as an *unlocked dev build* — for trying
                        unreleased library changes, never for a release.
  MINIDSPQT_WIN_PYTHON  Embeddable CPython version to bundle (default below).
                        Versions not listed in PYTHON_EMBED_SHA256 also need
                        MINIDSPQT_WIN_PYTHON_SHA256.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
import tomllib
import urllib.request
import zipfile
from collections.abc import Callable, Iterable
from pathlib import Path

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

#: Embeddable CPython to bundle. 3.13 rather than the AppImage's 3.11 because
#: python.org stopped publishing Windows binaries for 3.11 at 3.11.9 — only
#: branches still in bugfix status get an embeddable zip.
PYTHON_VERSION = os.environ.get("MINIDSPQT_WIN_PYTHON", "3.13.15")

#: SHA-256 of ``python-<version>-embed-amd64.zip`` for every version this
#: script knows. Bumping PYTHON_VERSION means adding a row here.
PYTHON_EMBED_SHA256 = {
    "3.13.15": "d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf",
}

PLATFORM = "x86_64-pc-windows-msvc"  # uv's target triple
ARCH_TAG = "win_amd64"  # appears in the artifact names
EMBED_ARCH = "amd64"  # appears in python.org's file name

#: Qt modules the application imports. ``qt_modules_used`` re-derives this from
#: the installed package so the list cannot silently fall behind the code.
QT_MODULES = ("QtCore", "QtGui", "QtWidgets")

#: Qt libraries to keep. Qt6Svg has no Python module here but the SVG icon
#: engine and image-format plugins need it for the window logo.
QT_LIBS = ("Qt6Core", "Qt6Gui", "Qt6Widgets", "Qt6Svg")

#: Qt plugins to keep, by plugin directory. ``qoffscreen`` is what the Wine
#: smoke test boots against; ``qmodernwindowsstyle`` is Qt's default Windows
#: style, instantiated before the application switches to Fusion.
QT_PLUGINS = {
    "platforms": ("qwindows", "qoffscreen"),
    "styles": ("qmodernwindowsstyle",),
    "iconengines": ("qsvgicon",),
    "imageformats": ("qsvg", "qico", "qjpeg", "qgif"),
}

#: Files every valid build must contain, relative to the zip's top-level folder.
#: ``{sv}`` is the short Python version (``3.13``), ``{version}`` the project's.
REQUIRED_ZIP_ENTRIES = (
    "minidspqt.exe",
    "minidspqt-debug.cmd",
    "python{sv}.dll",
    "python{sv}._pth",
    "python{sv}.zip",
    "Lib/site-packages/minidspqt/resources/blank.unt",
    "Lib/site-packages/minidsp_linux_qt-{version}.dist-info/METADATA",
    "Lib/site-packages/PySide6/QtWidgets.pyd",
    "Lib/site-packages/PySide6/Qt6Widgets.dll",
    "Lib/site-packages/PySide6/plugins/platforms/qwindows.dll",
    "Lib/site-packages/shiboken6/shiboken6.abi3.dll",
)

#: Patterns that must match at least one zip entry (native wheel names carry
#: the interpreter tag, so they cannot be spelled out).
REQUIRED_ZIP_PATTERNS = (r"Lib/site-packages/hid\..*\.pyd$",)

#: Entries whose presence proves the prune step did not run.
FORBIDDEN_ZIP_PATTERNS = (
    r"/PySide6/qml/",
    r"/PySide6/designer\.exe$",
    r"/PySide6/opengl32sw\.dll$",
    r"/PySide6/Qt6Quick\.dll$",
)

REPO_ROOT = Path.cwd()
PACKAGING_DIR = REPO_ROOT / "packaging" / "windows"
BUILD_DIR = REPO_ROOT / "build"
CACHE_DIR = BUILD_DIR / "cache"
WORK_DIR = BUILD_DIR / "windows"
APP_DIR = WORK_DIR / "app"
DIST_DIR = REPO_ROOT / "dist"


class BuildError(RuntimeError):
    """A step found a condition that must stop the build."""


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def log(msg: str) -> None:
    """Print a progress line in the same style as the AppImage script."""
    print(f"\033[1;34m==>\033[0m {msg}", flush=True)


def warn(msg: str) -> None:
    """Print a warning line to stderr."""
    print(f"\033[1;33m!!\033[0m  {msg}", file=sys.stderr, flush=True)


def fail(msg: str) -> None:
    """Abort the build with a message on stderr."""
    raise BuildError(msg)


def need_cmd(name: str) -> str:
    """Return the path of a required executable or abort with a hint.

    Args:
        name: Executable to look up on ``PATH``.
    """
    path = shutil.which(name)
    if path is None:
        fail(f"missing command: {name} (run packaging/windows/init_environment.sh)")
    return path  # type: ignore[return-value]


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command, echoing it, and abort the build if it fails."""
    print("    $ " + " ".join(str(c) for c in cmd), flush=True)
    try:
        return subprocess.run(cmd, check=True, **kwargs)
    except subprocess.CalledProcessError as exc:
        fail(f"command failed with exit {exc.returncode}: {cmd[0]}")
        raise  # unreachable, keeps type checkers calm


def sha256_of(path: Path) -> str:
    """Return the hex SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, dest: Path) -> None:
    """Download ``url`` to ``dest`` unless it is already there."""
    if dest.exists():
        return
    log(f"fetching {dest.name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as resp, part.open("wb") as out:
        shutil.copyfileobj(resp, out)
    part.rename(dest)


# -----------------------------------------------------------------------------
# Pure helpers (unit-tested in tests/test_windows_build.py)
# -----------------------------------------------------------------------------


def project_version(pyproject: Path) -> str:
    """Read ``[project].version`` from a pyproject.toml.

    The same rule the AppImage script uses, so both artifacts of a release
    carry the same version string.
    """
    with pyproject.open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def version_tuple(version: str) -> tuple[int, int, int]:
    """Return the numeric ``MAJOR, MINOR, PATCH`` of a semver string.

    A pre-release suffix such as ``-rc1`` is dropped: Windows VERSIONINFO
    fields are four integers, so ``1.2.0-rc1`` is encoded as ``1,2,0,0``.
    """
    core = version.split("-", 1)[0].split("+", 1)[0]
    parts = [int(p) for p in core.split(".")]
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def short_version(python_version: str) -> str:
    """``"3.13.15"`` → ``"3.13"`` (the digits used in ``python313.dll``)."""
    major, minor = python_version.split(".")[:2]
    return f"{major}.{minor}"


def dll_digits(python_version: str) -> str:
    """``"3.13.15"`` → ``"313"`` (the digits used in ``python313.dll``)."""
    return short_version(python_version).replace(".", "")


def pth_content(python_version: str) -> str:
    """Return the ``python3xx._pth`` file for the bundled interpreter.

    A ``._pth`` file next to ``python3xx.dll`` puts CPython in isolated mode:
    ``sys.path`` is exactly these entries, ``PYTHONPATH``/``PYTHONHOME`` are
    ignored, and ``site`` is not imported. That is what we want — a user's own
    Python installation can never leak into the bundle. The two entries are
    the stdlib zip and the tree ``uv pip install --target`` produced.
    """
    return f"python{dll_digits(python_version)}.zip\nLib\\site-packages\n"


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def filter_requirements(text: str, drop: str) -> str:
    """Remove one package from a ``uv export`` requirements listing.

    ``uv export`` writes each requirement on its own line followed by indented
    ``# via …`` comments; both go. Used for the ``MINIDSP_LINUX_WHEEL``
    override, where the locked ``minidsp-linux`` pin is replaced by a local
    wheel that brings its own (unlocked) dependencies.

    Args:
        text: The requirements file contents.
        drop: Distribution name to remove (any PEP 503 spelling).
    """
    target = _normalize(drop)
    out: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        if line[:1].isspace() and line.lstrip().startswith("#"):
            if skipping:
                continue
            out.append(line)
            continue
        skipping = False
        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(==|@|;|$|\[)", line)
        if match and _normalize(match.group(1)) == target:
            skipping = True
            continue
        out.append(line)
    return "".join(out)


def qt_modules_used(package_dir: Path) -> set[str]:
    """Return every ``PySide6.Qt*`` module referenced by a package's sources."""
    found: set[str] = set()
    for source in package_dir.rglob("*.py"):
        found.update(re.findall(r"PySide6\.(Qt\w+)", source.read_text("utf-8")))
    return found


def pe_imports(path: Path) -> list[str]:
    """Return the DLL names a PE file imports (normal and delay-load).

    A deliberately small reader of the PE format: enough to walk the import
    and delay-import directories of the DLLs, ``.pyd`` and ``.exe`` files in
    the bundle. Non-PE files yield an empty list.
    """
    data = path.read_bytes()
    if data[:2] != b"MZ" or len(data) < 0x40:
        return []
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_off : pe_off + 4] != b"PE\0\0":
        return []
    coff = pe_off + 4
    n_sections = struct.unpack_from("<H", data, coff + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    if magic == 0x20B:  # PE32+
        dd_off = opt + 112
    elif magic == 0x10B:  # PE32
        dd_off = opt + 96
    else:
        return []
    n_dirs = struct.unpack_from("<I", data, dd_off - 4)[0]

    sections = []
    sec = opt + opt_size
    for i in range(n_sections):
        vsize, vaddr, rsize, rptr = struct.unpack_from("<IIII", data, sec + i * 40 + 8)
        sections.append((vaddr, max(vsize, rsize), rptr))

    def rva_to_offset(rva: int) -> int:
        for vaddr, size, rptr in sections:
            if vaddr <= rva < vaddr + size:
                return rptr + (rva - vaddr)
        raise ValueError(f"RVA {rva:#x} outside every section of {path.name}")

    def cstring(rva: int) -> str:
        off = rva_to_offset(rva)
        end = data.index(b"\0", off)
        return data[off:end].decode("ascii", "replace")

    def directory(index: int) -> tuple[int, int]:
        if index >= n_dirs:
            return 0, 0
        return struct.unpack_from("<II", data, dd_off + index * 8)

    names: list[str] = []
    imp_rva, _ = directory(1)  # IMAGE_DIRECTORY_ENTRY_IMPORT
    if imp_rva:
        off = rva_to_offset(imp_rva)
        while True:
            lookup, _, _, name_rva, _ = struct.unpack_from("<IIIII", data, off)
            if lookup == 0 and name_rva == 0:
                break
            names.append(cstring(name_rva))
            off += 20
    delay_rva, _ = directory(13)  # IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT
    if delay_rva:
        off = rva_to_offset(delay_rva)
        while True:
            _, name_rva = struct.unpack_from("<II", data, off)
            if name_rva == 0:
                break
            names.append(cstring(name_rva))
            off += 32
    return names


def binary_inventory(root: Path) -> dict[str, Path]:
    """Map lower-cased DLL/PYD/EXE file names under ``root`` to their paths."""
    return {
        p.name.lower(): p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in (".dll", ".pyd", ".exe")
    }


def prune_site_packages(
    site_packages: Path,
    *,
    qt_modules: Iterable[str] = QT_MODULES,
    qt_libs: Iterable[str] = QT_LIBS,
    qt_plugins: dict[str, tuple[str, ...]] = QT_PLUGINS,
) -> list[Path]:
    """Reduce PySide6 and shiboken6 to what a QtWidgets application loads.

    Works as an allow-list: everything under ``PySide6/`` and ``shiboken6/``
    that is not named here is deleted — the QML/Quick stack, the Qt tool
    executables, headers, typesystems, ``.pyi`` stubs, translations (the
    application installs no ``QTranslator``), the WebEngine ICU data, and the
    20 MB software-OpenGL fallback. The console-script shims uv wrote to
    ``bin/`` go too; they embed build-host paths.

    The Windows wheel layout differs from Linux (no ``PySide6/Qt/`` level), so
    the function asserts the layout it expects before deleting anything.

    Args:
        site_packages: The ``--target`` directory uv installed into.
        qt_modules: ``Qt*`` Python modules to keep.
        qt_libs: ``Qt6*`` DLLs to keep.
        qt_plugins: Plugin directory → plugin base names to keep.

    Returns:
        The files that were removed.

    Raises:
        BuildError: If the tree does not look like a Windows PySide6 install,
            or a file that must be kept is missing.
    """
    pyside = site_packages / "PySide6"
    shiboken = site_packages / "shiboken6"
    sentinel = pyside / "plugins" / "platforms" / "qwindows.dll"
    if not sentinel.is_file():
        fail(f"unexpected PySide6 layout: {sentinel} is missing")

    def runtime(d: Path) -> set[Path]:
        """MSVC runtime DLLs, shipped by both packages."""
        return set(d.glob("msvcp140*.dll")) | set(d.glob("vcruntime140*.dll")) | {d / "concrt140.dll"}

    required: set[Path] = set()
    optional: set[Path] = set()

    optional |= {pyside / n for n in ("PySide6_Essentials.json", "py.typed")}
    required |= {pyside / n for n in ("__init__.py", "_config.py", "_git_pyside_version.py")}
    required |= {pyside / f"{m}.pyd" for m in qt_modules}
    required |= {pyside / f"{lib}.dll" for lib in qt_libs}
    required.add(pyside / "pyside6.abi3.dll")
    optional |= runtime(pyside)
    for sub, names in qt_plugins.items():
        required |= {pyside / "plugins" / sub / f"{n}.dll" for n in names}

    required |= {
        shiboken / n
        for n in ("__init__.py", "_config.py", "Shiboken.pyd", "shiboken6.abi3.dll")
    }
    optional |= {shiboken / n for n in ("_git_shiboken_module_version.py", "py.typed")}
    optional |= runtime(shiboken)

    missing = sorted(str(p.relative_to(site_packages)) for p in required if not p.is_file())
    if missing:
        fail("files that must be kept are missing: " + ", ".join(missing))

    keep = required | optional
    removed: list[Path] = []
    for root in (pyside, shiboken):
        # Deepest paths first so directories are empty by the time we reach them.
        for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if path.is_dir():
                if not any(path.iterdir()):
                    path.rmdir()
            elif path not in keep:
                path.unlink()
                removed.append(path)

    for shim_dir in ("bin", "Scripts"):
        target = site_packages / shim_dir
        if target.is_dir():
            removed.extend(p for p in target.rglob("*") if p.is_file())
            shutil.rmtree(target)
    return removed


def check_dll_closure(
    root: Path,
    before: Iterable[str],
    imports_of: Callable[[Path], list[str]] = pe_imports,
) -> dict[str, list[str]]:
    """Find kept binaries that import a DLL the prune step removed.

    The rule needs no list of Windows system DLLs: a dependency only counts as
    broken if it *was* in the tree before pruning and is not there now. ICU,
    DirectWrite and friends were never in the tree, so they are ignored.

    Args:
        root: The bundle directory after pruning.
        before: Lower-cased binary names present before pruning.
        imports_of: Import-table reader (injectable for tests).

    Returns:
        ``{importer file name: [missing DLL names]}``, empty when consistent.
    """
    before_set = {n.lower() for n in before}
    present = set(binary_inventory(root))
    problems: dict[str, list[str]] = {}
    for name, path in sorted(binary_inventory(root).items()):
        for dep in imports_of(path):
            key = dep.lower()
            if key in before_set and key not in present:
                problems.setdefault(name, []).append(dep)
    return problems


def render_template(template: str, values: dict[str, str]) -> str:
    """Replace ``@KEY@`` placeholders; unknown placeholders are an error."""
    out = template
    for key, value in values.items():
        out = out.replace(f"@{key}@", value)
    leftover = re.findall(r"@[A-Z_]+@", out)
    if leftover:
        raise BuildError(f"unfilled template placeholders: {', '.join(sorted(set(leftover)))}")
    return out


def artifact_names(version: str) -> tuple[str, str, str]:
    """Return ``(zip name, installer name, top-level folder)`` for a version."""
    top = f"minidspqt-{version}"
    return f"{top}-{ARCH_TAG}.zip", f"{top}-{ARCH_TAG}-setup.exe", top


def check_zip_layout(
    names: Iterable[str], top: str, python_version: str, version: str
) -> list[str]:
    """Validate the member list of a built zip.

    Args:
        names: Zip member names.
        top: Expected top-level folder.
        python_version: Bundled CPython version.
        version: Project version.

    Returns:
        Human-readable problems; empty when the layout is complete.
    """
    members = set(names)
    sv = dll_digits(python_version)
    problems = []
    for rel in REQUIRED_ZIP_ENTRIES:
        entry = f"{top}/{rel.format(sv=sv, version=version)}"
        if entry not in members:
            problems.append(f"missing {entry}")
    for pattern in REQUIRED_ZIP_PATTERNS:
        if not any(re.search(pattern, m) for m in members):
            problems.append(f"no member matches {pattern}")
    for pattern in FORBIDDEN_ZIP_PATTERNS:
        hits = [m for m in members if re.search(pattern, m)]
        if hits:
            problems.append(f"prune failed, found {hits[0]}")
    stray = {m.split("/", 1)[0] for m in members} - {top}
    if stray:
        problems.append(f"entries outside {top}/: {sorted(stray)[:3]}")
    return problems


# -----------------------------------------------------------------------------
# Steps
# -----------------------------------------------------------------------------


def step_check_prereqs(version: str) -> Path:
    """Check tools and locate the project wheel; return the wheel path."""
    log("checking build prerequisites")
    for tool in ("uv", "makensis", "x86_64-w64-mingw32-gcc", "x86_64-w64-mingw32-windres"):
        need_cmd(tool)
    if PYTHON_VERSION not in PYTHON_EMBED_SHA256 and not os.environ.get(
        "MINIDSPQT_WIN_PYTHON_SHA256"
    ):
        fail(
            f"no known SHA-256 for embeddable Python {PYTHON_VERSION}; "
            "add it to PYTHON_EMBED_SHA256 or set MINIDSPQT_WIN_PYTHON_SHA256"
        )
    wheels = sorted(DIST_DIR.glob(f"minidsp_linux_qt-{version}-*.whl"))
    if not wheels:
        fail(
            f"no project wheel for {version} in dist/. "
            "Run 'make build' first, then re-run 'make windows'."
        )
    log(f"using wheel: {wheels[-1].name}")
    override = os.environ.get("MINIDSP_LINUX_WHEEL")
    if override and not Path(override).is_file():
        fail(f"MINIDSP_LINUX_WHEEL points to a missing file: {override}")
    return wheels[-1]


def step_fetch_python() -> None:
    """Download, verify and unpack the embeddable CPython; write the ``._pth``."""
    name = f"python-{PYTHON_VERSION}-embed-{EMBED_ARCH}.zip"
    archive = CACHE_DIR / name
    fetch(f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{name}", archive)
    expected = os.environ.get("MINIDSPQT_WIN_PYTHON_SHA256") or PYTHON_EMBED_SHA256[PYTHON_VERSION]
    actual = sha256_of(archive)
    if actual != expected:
        archive.unlink()
        fail(f"SHA-256 mismatch for {name}: expected {expected}, got {actual}")

    log(f"unpacking CPython {PYTHON_VERSION} (embeddable) into {APP_DIR.relative_to(REPO_ROOT)}")
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR)
    APP_DIR.mkdir(parents=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(APP_DIR)
    (APP_DIR / f"python{dll_digits(PYTHON_VERSION)}._pth").write_text(
        pth_content(PYTHON_VERSION), newline="\r\n"
    )


def step_install_packages(project_wheel: Path) -> None:
    """Install the locked dependencies and the project wheel for Windows."""
    requirements = WORK_DIR / "requirements.txt"
    log("exporting the locked dependency set")
    result = run(
        ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes"],
        stdout=subprocess.PIPE,
        text=True,
    )
    text = result.stdout
    extra: list[str] = []
    override = os.environ.get("MINIDSP_LINUX_WHEEL")
    if override:
        warn("MINIDSP_LINUX_WHEEL is set: this is an UNLOCKED DEV BUILD.")
        warn(f"  the locked minidsp-linux pin is replaced by {override}")
        warn("  and its dependencies are resolved fresh, not from uv.lock.")
        text = filter_requirements(text, "minidsp-linux")
        extra = [str(Path(override).resolve())]
    requirements.write_text(text)

    site_packages = APP_DIR / "Lib" / "site-packages"
    common = [
        "uv", "pip", "install",
        "--python", sys.executable,
        "--python-platform", PLATFORM,
        "--python-version", short_version(PYTHON_VERSION),
        "--only-binary", ":all:",
        "--link-mode", "copy",
        "--target", str(site_packages),
    ]  # fmt: skip
    log(f"installing dependencies for {PLATFORM}")
    run([*common, "-r", str(requirements), *extra])
    log("installing the project wheel")
    run([*common, "--no-deps", str(project_wheel)])

    if not list(site_packages.glob("hid.*.pyd")):
        fail(
            "hidapi was not installed — the minidsp-linux wheel in use does not "
            "declare it; set MINIDSP_LINUX_WHEEL to a wheel with the Windows transport"
        )


def step_prune() -> None:
    """Prune PySide6 and prove the remaining DLL graph is closed."""
    site_packages = APP_DIR / "Lib" / "site-packages"
    used = qt_modules_used(site_packages / "minidspqt")
    unexpected = used - set(QT_MODULES)
    if unexpected:
        fail(f"minidspqt imports Qt modules not in QT_MODULES: {sorted(unexpected)}")

    before = set(binary_inventory(APP_DIR))
    size_before = sum(p.stat().st_size for p in APP_DIR.rglob("*") if p.is_file())
    log("pruning PySide6 to the modules the application imports")
    removed = prune_site_packages(site_packages)
    size_after = sum(p.stat().st_size for p in APP_DIR.rglob("*") if p.is_file())
    log(f"removed {len(removed)} files: {size_before / 2**20:.0f} MB -> {size_after / 2**20:.0f} MB")

    log("checking DLL import closure of the pruned tree")
    problems = check_dll_closure(APP_DIR, before)
    if problems:
        lines = [f"  {k}: {', '.join(v)}" for k, v in problems.items()]
        fail("pruning removed DLLs that kept binaries import:\n" + "\n".join(lines))


def step_build_launcher(version: str) -> None:
    """Cross-compile ``minidspqt.exe`` with mingw-w64."""
    log("cross-compiling the launcher")
    obj_dir = WORK_DIR / "launcher"
    obj_dir.mkdir(parents=True, exist_ok=True)
    major, minor, patch = version_tuple(version)
    rc_text = render_template(
        (PACKAGING_DIR / "launcher.rc.in").read_text(),
        {
            "VERSION": version,
            "MAJOR": str(major),
            "MINOR": str(minor),
            "PATCH": str(patch),
            "ICON": (PACKAGING_DIR / "minidspqt.ico").resolve().as_posix(),
            "MANIFEST": (PACKAGING_DIR / "minidspqt.manifest").resolve().as_posix(),
        },
    )
    rc_file = obj_dir / "launcher.rc"
    rc_file.write_text(rc_text)
    res_obj = obj_dir / "launcher.res.o"
    run(["x86_64-w64-mingw32-windres", "-O", "coff", "-o", str(res_obj), str(rc_file)])
    run(
        [
            "x86_64-w64-mingw32-gcc",
            "-municode",
            "-mwindows",
            "-O2",
            "-Wall",
            "-Wextra",
            f'-DPYTHON_DLL=L"python{dll_digits(PYTHON_VERSION)}.dll"',
            "-o",
            str(APP_DIR / "minidspqt.exe"),
            str(PACKAGING_DIR / "launcher.c"),
            str(res_obj),
            "-lshell32",
        ]
    )


def step_stage_assets() -> None:
    """Copy the icon, licence, and debug launcher into the tree."""
    log("staging icon, licence and debug launcher")
    shutil.copy2(PACKAGING_DIR / "minidspqt.ico", APP_DIR / "minidspqt.ico")
    shutil.copy2(PACKAGING_DIR / "minidspqt-debug.cmd", APP_DIR / "minidspqt-debug.cmd")
    shutil.copy2(REPO_ROOT / "LICENSE", APP_DIR / "LICENSE.txt")


def step_zip(version: str) -> Path:
    """Write the portable zip and return its path."""
    zip_name, _, top = artifact_names(version)
    out = DIST_DIR / zip_name
    log(f"writing {out.relative_to(REPO_ROOT)}")
    DIST_DIR.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(APP_DIR.rglob("*")):
            if path.is_file():
                zf.write(path, f"{top}/{path.relative_to(APP_DIR).as_posix()}")
    log(f"produced {out} ({out.stat().st_size / 2**20:.1f} MB)")
    return out


def step_installer(version: str) -> Path:
    """Build the NSIS installer and return its path."""
    _, setup_name, _ = artifact_names(version)
    out = DIST_DIR / setup_name
    log(f"building {out.relative_to(REPO_ROOT)} with NSIS")
    run(
        [
            "makensis",
            "-V2",
            f"-DVERSION={version}",
            f"-DSRCDIR={APP_DIR}",
            f"-DOUTFILE={out}",
            f"-DICON={PACKAGING_DIR / 'minidspqt.ico'}",
            f"-DLICENSE={REPO_ROOT / 'LICENSE'}",
            str(PACKAGING_DIR / "minidspqt.nsi"),
        ]
    )
    log(f"produced {out} ({out.stat().st_size / 2**20:.1f} MB)")
    return out


def step_smoke_test(zip_path: Path, setup_path: Path, version: str) -> None:
    """Structural checks (always) plus a Qt offscreen boot under Wine (optional)."""
    log("smoke-testing the zip layout")
    _, _, top = artifact_names(version)
    with zipfile.ZipFile(zip_path) as zf:
        problems = check_zip_layout(zf.namelist(), top, PYTHON_VERSION, version)
    if problems:
        fail("zip layout check failed:\n  " + "\n  ".join(problems))
    if setup_path.stat().st_size < 2**20:
        fail(f"{setup_path.name} is implausibly small")

    wine = shutil.which("wine")
    if wine is None:
        log("skipping the Wine boot test (wine is not installed)")
        return
    # Mirrors the AppImage test: --help proves the interpreter and package
    # import; the offline boot under the offscreen platform proves Qt loads.
    # timeout --preserve-status yields 143 when the event loop had to be killed.
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "WINEDEBUG": "-all"}
    python_exe = str(APP_DIR / "python.exe")
    log("smoke-testing under Wine (--help)")
    help_run = subprocess.run(
        [wine, python_exe, "-m", "minidspqt.cli", "--help"], env=env, check=False
    )
    if help_run.returncode:
        fail("Wine smoke test: --help failed")
    log("smoke-testing under Wine (Qt offscreen boot)")
    rc = subprocess.run(
        ["timeout", "--preserve-status", "15", wine, python_exe, "-m", "minidspqt.cli", "--offline"],
        env=env,
        check=False,
    ).returncode
    if rc not in (0, 124, 143):
        fail(f"Wine smoke test: offline boot exited {rc}")
    log(f"Wine smoke test passed (exit {rc})")


# -----------------------------------------------------------------------------
# Orchestration
# -----------------------------------------------------------------------------


def main() -> int:
    """Run every step in order; return a process exit code."""
    try:
        version = project_version(REPO_ROOT / "pyproject.toml")
        wheel = step_check_prereqs(version)
        step_fetch_python()
        step_install_packages(wheel)
        step_prune()
        step_build_launcher(version)
        step_stage_assets()
        zip_path = step_zip(version)
        setup_path = step_installer(version)
        step_smoke_test(zip_path, setup_path, version)
    except BuildError as exc:
        print(f"\033[1;31mxx\033[0m  {exc}", file=sys.stderr)
        return 1
    log("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
