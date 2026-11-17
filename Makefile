UV := uv

.DEFAULT_GOAL := build

.PHONY: sync install test check check-ruff check-ty fix-ruff build clean version publish help \
        appimage appimage-clean windows windows-clean docs docs-serve docs-clean

help:
	@echo "Usage: make [target] [VAR=value]"
	@echo ""
	@echo "Build"
	@echo "  build                   Build sdist and wheel (default)"
	@echo "  version VERSION=X.Y.Z   Bump version, generate changelog, tag"
	@echo "  publish [VERSION=X.Y.Z] Create GitHub Release + deploy docs (prompts if VERSION omitted)"
	@echo "  clean                   Remove build artifacts (dist/, build/, *.egg-info)"
	@echo ""
	@echo "Development"
	@echo "  sync                    Install all dependencies (incl. dev extras)"
	@echo "  install                 Alias for sync"
	@echo "  test                    Run test suite with pytest"
	@echo "  check                   check-ruff and check-ty"
	@echo "  check-ruff              Lint the code base with ruff"
	@echo "  check-ty                Type-check the code base with ty"
	@echo "  fix-ruff                Apply ruff's automatic fixes"
	@echo ""
	@echo "Packaging  (both need the wheel from 'make build')"
	@echo "  appimage                Build the AppImage into dist/"
	@echo "  appimage-clean          Remove AppImage build output (keeps the download cache)"
	@echo "  windows                 Build the Windows installer and portable zip into dist/"
	@echo "  windows-clean           Remove Windows build output (keeps the download cache)"
	@echo ""
	@echo "Documentation"
	@echo "  docs                    Build HTML docs into site/ (MkDocs Material)"
	@echo "  docs-serve              Live-reload docs preview at http://127.0.0.1:8000"
	@echo "  docs-clean              Remove generated site/ directory"

sync:
	$(UV) sync --extra dev

install: sync

# Run the test suite (headless: tests/conftest.py sets QT_QPA_PLATFORM=offscreen,
# so this recipe needs no POSIX env prefix and works under Windows GNU make too)
test:
	$(UV) run pytest -v

check: check-ruff check-ty

# Lint (ruff: pyflakes, pycodestyle, isort, pyupgrade, bugbear; config in pyproject.toml)
check-ruff:
	$(UV) run ruff check minidspqt tests packaging

# Type check (ty, Astral's checker; Python version from requires-python)
check-ty:
	$(UV) run ty check minidspqt tests packaging

# Apply ruff's safe automatic fixes (import order, future import, pyupgrade)
fix-ruff:
	$(UV) run ruff check --fix minidspqt tests packaging

build:
	$(UV) build

# Remove build artifacts (sdist/wheel, AppImage and Windows output, download caches)
clean:
	rm -rf dist build *.egg-info

# Create a release (usage: make version VERSION=X.Y.Z)
version:
	@bash scripts/version.sh $(VERSION)

# Publish an already-tagged version to GitHub Releases + Pages
# (usage: make publish               -> prompts for version
#         make publish VERSION=X.Y.Z -> non-interactive)
# Requires GITHUB_TOKEN env var with `repo` scope.
publish:
	@bash scripts/publish.sh $(VERSION)

# Build a self-contained AppImage with bundled CPython + PySide6.
# Prereqs are listed in packaging/appimage/init_environment.sh — run that once
# on a fresh host or inside an Ubuntu 20.04 container before invoking this.
appimage:
	bash packaging/appimage/build.sh

# Remove only AppImage artifacts (keeps the python-build / linuxdeploy cache).
appimage-clean:
	rm -rf build/AppDir build/Python-* dist/*.AppImage

# Build the Windows distribution (portable zip + NSIS installer) on Linux.
# Prereqs are listed in packaging/windows/init_environment.sh — run that once on
# the host or inside a Debian container. Needs the wheel from `make build`.
# `--no-project` keeps this off the dev venv: the script only needs a stdlib
# interpreter plus `uv` on PATH, so it also runs in a container that has no venv.
# To try unreleased protocol-library changes, point the build at a locally built
# wheel (the result is an unlocked dev build, not for publishing):
#   make windows MINIDSP_LINUX_WHEEL=../miniDSP-Linux/dist/minidsp_linux-X.Y.Z-py3-none-any.whl
windows:
	$(UV) run --no-project python packaging/windows/build.py

# Remove only Windows artifacts (keeps the embeddable-Python download cache).
windows-clean:
	rm -rf build/windows dist/*-win_amd64.zip dist/*-win_amd64-setup.exe

# Build HTML documentation (MkDocs Material) into site/
docs:
	$(UV) sync --extra docs --inexact
	$(UV) run mkdocs build

# Live-reload docs preview (http://127.0.0.1:8000)
docs-serve:
	$(UV) sync --extra docs --inexact
	$(UV) run mkdocs serve

# Remove generated docs output
docs-clean:
	rm -rf site
