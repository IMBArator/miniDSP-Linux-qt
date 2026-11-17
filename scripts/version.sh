#!/usr/bin/env bash
#
# Bump the project version (pyproject.toml and the package's __version__),
# regenerate the changelog (with a chance to edit the new section), commit,
# and tag. The companion of scripts/publish.sh — this prepares the release
# locally; publish.sh sends it to GitHub. The final push is optional and
# needs an explicit yes.
#
# Usage:
#   scripts/version.sh X.Y.Z
#   make version VERSION=X.Y.Z
#
# Requires: git, uv (for uvx git-cliff), sed, awk; an editor ($VISUAL, then
# $EDITOR, then vi) to edit the changelog section.

set -euo pipefail

# --- helpers -----------------------------------------------------------------

c_red() { printf '\033[31m%s\033[0m\n' "$*" >&2; }
c_yel() { printf '\033[33m%s\033[0m\n' "$*"; }
c_grn() { printf '\033[32m%s\033[0m\n' "$*"; }
c_dim() { printf '\033[2m%s\033[0m\n' "$*"; }

die() { c_red "Error: $*"; exit 1; }

confirm() {
    local prompt="$1" reply
    [[ -t 0 ]] || return 0  # non-interactive: skip prompts, proceed
    read -r -p "$prompt [y/N] " -n 1 reply
    echo ""
    [[ "$reply" =~ ^[Yy]$ ]]
}

# Like confirm, but without a terminal the answer is no: the push must only
# happen after an explicit yes from the maintainer.
confirm_explicit() {
    local prompt="$1" reply
    [[ -t 0 ]] || return 1  # non-interactive: no explicit yes, so no
    read -r -p "$prompt [y/N] " -n 1 reply
    echo ""
    [[ "$reply" =~ ^[Yy]$ ]]
}

# --- 1. preconditions --------------------------------------------------------

for cmd in git uv sed awk; do
    command -v "$cmd" >/dev/null 2>&1 || die "$cmd is required on PATH"
done

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
    die "usage: scripts/version.sh X.Y.Z (or 'make version VERSION=X.Y.Z')"
fi

# Strip optional leading 'v' so both '0.2.0' and 'v0.2.0' work
VERSION="${VERSION#v}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
    die "invalid semantic version: $VERSION (expected X.Y.Z or X.Y.Z-prerelease)"
fi

TAG="v$VERSION"
PYPROJECT="pyproject.toml"
CHANGELOG="CHANGELOG.md"
# Packages whose __version__ follows pyproject.toml (tests/test_version.py).
PACKAGE_INITS=("minidspqt/__init__.py")

PRERELEASE=false
[[ "$TAG" =~ -(rc|beta|alpha) ]] && PRERELEASE=true

# --- 2. sanity checks --------------------------------------------------------

# Working tree must be clean — otherwise the release commit would silently
# sweep up unrelated changes alongside the version bump.
if ! git diff-index --quiet HEAD --; then
    git status --short >&2
    die "working tree is not clean — commit or stash changes before tagging"
fi
if [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
    c_yel "Warning: untracked files present (they won't be committed)"
    git ls-files --others --exclude-standard | sed 's/^/  /' >&2
fi

# Branch check — warn if not on main.
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" != "main" ]]; then
    c_yel "Warning: current branch is '$BRANCH', not 'main'"
    confirm "Tag from '$BRANCH' anyway?" || die "aborted"
fi

# Up-to-date with origin? — warn only; user may be offline.
if git rev-parse --verify "origin/$BRANCH" >/dev/null 2>&1; then
    LOCAL="$(git rev-parse HEAD)"
    REMOTE="$(git rev-parse "origin/$BRANCH")"
    BASE="$(git merge-base HEAD "origin/$BRANCH")"
    if [[ "$LOCAL" != "$REMOTE" && "$BASE" == "$LOCAL" ]]; then
        c_yel "Warning: local '$BRANCH' is behind 'origin/$BRANCH' (run 'git pull' first?)"
    fi
fi

# Tag uniqueness.
if git rev-parse "$TAG" >/dev/null 2>&1; then
    die "tag $TAG already exists locally"
fi
if git ls-remote --tags origin "refs/tags/$TAG" 2>/dev/null | grep -q "$TAG"; then
    die "tag $TAG already exists on origin (delete it remotely first)"
fi

# Version-regression check — warn if the new version isn't greater than the
# previous tag. `sort -V` puts versions in ascending order; the highest of
# (latest, new) should be the new one.
LATEST_TAG="$(git tag --sort=-v:refname | grep -E '^v[0-9]' | head -1 || true)"
if [[ -n "$LATEST_TAG" ]]; then
    HIGHEST="$(printf '%s\n%s\n' "$LATEST_TAG" "$TAG" | sort -V | tail -1)"
    if [[ "$HIGHEST" != "$TAG" ]]; then
        c_yel "Warning: $TAG is not greater than the latest tag $LATEST_TAG"
        confirm "Tag $TAG anyway?" || die "aborted"
    fi
fi

# Refuse to add a second section for a version that's already in the
# changelog (e.g. a hand-curated initial release). Without this guard,
# git-cliff --prepend would create a duplicate `## [X.Y.Z]` heading.
if [[ -f "$CHANGELOG" ]] && grep -qE "^## \[${VERSION//./\\.}\]" "$CHANGELOG"; then
    die "$CHANGELOG already has a [${VERSION}] section — commit that and tag manually instead of running this script"
fi

# Every package must have a __version__ line to bump, checked before any
# file is touched.
for init in "${PACKAGE_INITS[@]}"; do
    grep -q '^__version__ = ' "$init" || die "$init has no __version__ line to bump"
done

# --- 3. prepare release ------------------------------------------------------

c_grn "Preparing release $TAG"
[[ "$PRERELEASE" == "true" ]] && c_dim "  (prerelease — publish.sh will set the prerelease flag automatically)"

# Bump pyproject.toml — only the first `version = "..."` line at top of file.
sed -i "0,/^version = \".*\"/{s/^version = \".*\"/version = \"$VERSION\"/}" "$PYPROJECT"

# Keep the packages' __version__ in step with pyproject.toml.
for init in "${PACKAGE_INITS[@]}"; do
    sed -i "s/^__version__ = \".*\"/__version__ = \"$VERSION\"/" "$init"
done

# Refresh uv.lock so it reflects the new project version. Folded into
# the release commit below so the tag covers a self-consistent tree.
uv lock --quiet

# Update the changelog. When CHANGELOG.md already exists (the usual case
# after the first release), prepend the unreleased commits as a new
# section under the existing entries — this preserves any hand-curated
# initial-release content. Only the very first invocation, with no
# CHANGELOG.md present, regenerates the whole file.
if [[ -f "$CHANGELOG" ]]; then
    uvx --quiet git-cliff --tag "$TAG" --unreleased --prepend "$CHANGELOG"
else
    uvx --quiet git-cliff --tag "$TAG" -o "$CHANGELOG"
fi

# --- 4. preview and edit -----------------------------------------------------

# Undo the version bump, the lock refresh and the new changelog section.
revert_release_files() {
    c_yel "Reverting working-tree changes..."
    git checkout -- "$PYPROJECT" "$CHANGELOG" uv.lock "${PACKAGE_INITS[@]}"
}

# Print the new changelog section, from its heading up to the next one.
show_section() {
    c_dim "CHANGELOG.md, the new [$VERSION] section:"
    awk -v head="## [$VERSION]" '
        index($0, head) == 1 { inside = 1; print; next }
        inside && /^## /     { exit }
        inside               { print }
    ' "$CHANGELOG" | sed 's/^/  /'
}

c_dim "pyproject.toml and __version__ diff:"
git --no-pager diff --color "$PYPROJECT" "${PACKAGE_INITS[@]}" | sed 's/^/  /'

show_section

# The generated section can be curated before it is committed and tagged, for
# example to drop entries for changes that were added and removed again before
# the release. Editing needs an explicit yes, so a run without a terminal never
# waits for an editor. The editor setting may carry arguments ("code --wait"),
# so it is split into words.
read -r -a editor_cmd <<< "${VISUAL:-${EDITOR:-vi}}"
while confirm_explicit "Edit the changelog section in ${editor_cmd[0]}?"; do
    "${editor_cmd[@]}" "$CHANGELOG" || c_yel "Warning: ${editor_cmd[0]} exited with an error"
    if ! grep -qE "^## \[${VERSION//./\\.}\]" "$CHANGELOG"; then
        revert_release_files
        die "the [$VERSION] section is gone from $CHANGELOG"
    fi
    show_section
done

if ! confirm "Commit and tag $TAG?"; then
    revert_release_files
    die "aborted by user"
fi

# --- 5. commit + tag ---------------------------------------------------------

git add "$PYPROJECT" "$CHANGELOG" uv.lock "${PACKAGE_INITS[@]}"
git commit -m "chore(release): $TAG"
git tag -a "$TAG" -m "Release $TAG"

# --- 6. summary --------------------------------------------------------------

echo ""
c_grn "Tagged $TAG"
git log --oneline -1 | sed 's/^/  /'
git tag -n1 "$TAG" | sed 's/^/  /'

# --- 7. optional push (explicit yes only) -------------------------------------

echo ""
if confirm_explicit "Push commit + tag to origin?"; then
    git push
    git push origin "$TAG"
    c_grn "Pushed."
    echo ""
    c_dim "Next: make publish (or make publish VERSION=$VERSION)"
else
    c_dim "Not pushed. To push manually:"
    echo "  git push"
    echo "  git push origin $TAG"
    echo ""
    c_dim "Then: make publish"
fi
