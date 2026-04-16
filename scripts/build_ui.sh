#!/usr/bin/env bash
# Compile all Qt Designer .ui files to Python modules via pyside6-uic.
# Run from the project root; regenerate whenever forms/*.ui change.

set -euo pipefail

cd "$(dirname "$0")/.."

shopt -s nullglob
for ui in minidspqt/forms/*.ui; do
    base=$(basename "$ui" .ui)
    out="minidspqt/ui/ui_${base}.py"
    echo "Compiling $ui -> $out"
    pyside6-uic "$ui" -o "$out"
done
