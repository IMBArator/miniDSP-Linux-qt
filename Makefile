UV := uv

.PHONY: sync install test build clean

sync:
	$(UV) sync --extra dev

install: sync   ## alias kept for muscle memory

# Run the test suite
test:
	$(UV) run pytest -v

# Build the package (sdist and wheel into dist/)
build:
	$(UV) build

# Remove build artifacts
clean:
	rm -rf dist build *.egg-info
