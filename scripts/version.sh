#!/usr/bin/env bash
#
# Bump the project version, regenerate the changelog, commit, and tag.
# The companion of scripts/publish.sh — this prepares the release
# locally; publish.sh sends it to GitHub.
#
# Usage:
#   scripts/version.sh X.Y.Z
#   make version VERSION=X.Y.Z
#
# Requires: git, uv (for uvx git-cliff), sed.

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

# --- 1. preconditions --------------------------------------------------------

for cmd in git uv sed; do
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

# --- 3. prepare release ------------------------------------------------------

c_grn "Preparing release $TAG"
[[ "$PRERELEASE" == "true" ]] && c_dim "  (prerelease — publish.sh will set the prerelease flag automatically)"

# Bump pyproject.toml — only the first `version = "..."` line at top of file.
sed -i "0,/^version = \".*\"/{s/^version = \".*\"/version = \"$VERSION\"/}" "$PYPROJECT"

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

# --- 4. preview --------------------------------------------------------------

c_dim "pyproject.toml diff:"
git --no-pager diff --color "$PYPROJECT" | sed 's/^/  /'

c_dim "CHANGELOG.md (first 25 lines of the new section):"
sed -n "/^## \[${VERSION//./\\.}\]/,/^## /p" "$CHANGELOG" | head -25 | sed 's/^/  /'

if ! confirm "Commit and tag $TAG?"; then
    c_yel "Reverting working-tree changes..."
    git checkout -- "$PYPROJECT" "$CHANGELOG" uv.lock
    die "aborted by user"
fi

# --- 5. commit + tag ---------------------------------------------------------

git add "$PYPROJECT" "$CHANGELOG" uv.lock
git commit -m "chore(release): $TAG"
git tag -a "$TAG" -m "Release $TAG"

# --- 6. summary --------------------------------------------------------------

echo ""
c_grn "Tagged $TAG"
git log --oneline -1 | sed 's/^/  /'
git tag -n1 "$TAG" | sed 's/^/  /'

# --- 7. optional push --------------------------------------------------------

echo ""
if confirm "Push commit + tag to origin?"; then
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
