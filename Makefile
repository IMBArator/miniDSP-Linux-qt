UV := uv

.PHONY: sync install test build version publish clean docs docs-serve docs-clean appimage appimage-clean windows windows-clean

sync:
	$(UV) sync --extra dev

install: sync   ## alias kept for muscle memory

# Run the test suite (headless: tests/conftest.py sets QT_QPA_PLATFORM=offscreen,
# so this recipe needs no POSIX env prefix and works under Windows GNU make too)
test:
	$(UV) run pytest -v

# Build the package (sdist and wheel into dist/)
build:
	$(UV) build

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

# Remove all build artifacts (sdist/wheel + AppImage + Windows + caches)
clean:
	rm -rf dist build *.egg-info

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
