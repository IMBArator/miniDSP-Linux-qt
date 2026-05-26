"""mkdocs hooks: post-process transcluded pages and clean up SUMMARY.

Several pages (``docs/index.md``, ``docs/changelog.md``) transclude
source Markdown from outside the docs tree via
mkdocs-include-markdown-plugin with ``rewrite_relative_urls=true``. That
rewrites docs-tree-relative paths correctly, but the README also points
at ``../LICENSE`` and ``../CHANGELOG.md`` — files outside the docs tree
that mkdocs cannot render. Remap them to the GitHub URL (or the in-site
changelog page) so the links work on the rendered site and MkDocs' link
checker stops warning.

The second hook drops ``api/SUMMARY.md`` from the build after
mkdocs-literate-nav has consumed it (otherwise it would render as an
orphan page and pollute the search index).
"""
from __future__ import annotations

import re

# Pages that transclude an upstream Markdown file and therefore need
# their relative links rewritten. Any page not listed here is passed
# through unchanged.
_TRANSCLUDED_PAGES = {"index.md", "changelog.md", "user-guide.md"}

_LINK_MAP = {
    "../LICENSE": "https://github.com/IMBArator/miniDSP-Linux-qt/blob/main/LICENSE",
    "../CHANGELOG.md": "changelog.md",
    "../README.md": "index.md",
}


def on_page_markdown(markdown: str, *, page, config, files) -> str:
    if page.file.src_uri not in _TRANSCLUDED_PAGES:
        return markdown
    for old, new in _LINK_MAP.items():
        markdown = re.sub(
            r"\]\(" + re.escape(old) + r"(#[^)]*)?\)",
            lambda m, new=new: f"]({new}{m.group(1) or ''})",
            markdown,
        )
    return markdown


def on_files(files, config):
    """Drop api/SUMMARY.md from the build after literate-nav has read it.

    literate-nav consumes the file during its own ``on_files`` to build the
    API reference nav tree. We then remove it so MkDocs doesn't render it as
    an orphan HTML page (also keeping it out of sitemap.xml and the search
    index). Hooks run after plugins, so the ordering is safe.
    """
    summary = files.get_file_from_path("api/SUMMARY.md")
    if summary is not None:
        files.remove(summary)
    return files
