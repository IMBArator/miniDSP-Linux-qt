UV := uv

.PHONY: sync install test build clean docs docs-serve docs-clean

sync:
	$(UV) sync --extra dev

install: sync   ## alias kept for muscle memory

# Run the test suite
test:
	QT_QPA_PLATFORM=offscreen $(UV) run pytest -v

# Build the package (sdist and wheel into dist/)
build:
	$(UV) build

# Remove build artifacts
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
