UV := uv

.PHONY: sync install test build clean docs docs-serve docs-clean appimage appimage-clean

sync:
	$(UV) sync --extra dev

install: sync   ## alias kept for muscle memory

# Run the test suite
test:
	QT_QPA_PLATFORM=offscreen $(UV) run pytest -v

# Build the package (sdist and wheel into dist/)
build:
	$(UV) build

# Build a self-contained AppImage with bundled CPython + PySide6.
# Prereqs are listed in packaging/appimage/init_environment.sh — run that once
# on a fresh host or inside an Ubuntu 20.04 container before invoking this.
appimage:
	bash packaging/appimage/build.sh

# Remove only AppImage artifacts (keeps the python-build / linuxdeploy cache).
appimage-clean:
	rm -rf build/AppDir build/Python-* dist/*.AppImage

# Remove all build artifacts (sdist/wheel + AppImage + caches)
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
