"""Generate API reference pages and SUMMARY.md for mkdocstrings at build time.

Walks the source packages and writes one virtual Markdown page per module
(plus an ``index.md`` per package) into the in-memory docs tree. The nav
for the API section is generated as ``api/SUMMARY.md`` and picked up by
``mkdocs-literate-nav``.

Following the official mkdocstrings recipe:
https://mkdocstrings.github.io/recipes/
"""
from pathlib import Path

import mkdocs_gen_files

PACKAGES = ("minidspqt",)
ROOT = Path(__file__).resolve().parent.parent

# Landing page for the whole API Reference section. Needed so the
# mkdocs-section-index plugin binds it to the "API Reference" nav entry
# instead of promoting the first package's index page (which would orphan
# that package's submodules from the sidebar).
with mkdocs_gen_files.open("api/index.md", "w") as fd:
    fd.write(
        "# API Reference\n\n"
        "Auto-generated reference for the "
        "[`minidspqt`](minidspqt/index.md) Qt GUI package.\n"
    )

nav = mkdocs_gen_files.Nav()

for pkg in PACKAGES:
    for path in sorted((ROOT / pkg).rglob("*.py")):
        module_path = path.relative_to(ROOT).with_suffix("")
        doc_path = path.relative_to(ROOT).with_suffix(".md")
        full_doc_path = Path("api", doc_path)

        parts = tuple(module_path.parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts = parts[:-1]
            doc_path = doc_path.with_name("index.md")
            full_doc_path = full_doc_path.with_name("index.md")
        elif parts[-1].startswith("__"):
            continue

        nav[parts] = doc_path.as_posix()
        identifier = ".".join(parts)
        with mkdocs_gen_files.open(full_doc_path, "w") as fd:
            fd.write(f"# `{identifier}`\n\n::: {identifier}\n")
            if is_package:
                # Each submodule has its own page; don't duplicate them here.
                fd.write("    options:\n      show_submodules: false\n")
        mkdocs_gen_files.set_edit_path(full_doc_path, path.relative_to(ROOT))

with mkdocs_gen_files.open("api/SUMMARY.md", "w") as nav_file:
    # Listing index.md first lets mkdocs-section-index bind it as the
    # "API Reference" landing page, instead of absorbing minidspqt/index.md.
    nav_file.write("* [Overview](index.md)\n")
    nav_file.writelines(nav.build_literate_nav())
