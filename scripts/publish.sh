#!/usr/bin/env bash
#
# Publish an already-tagged version: create a GitHub Release with the
# wheel + sdist attached, and deploy the rendered docs to GitHub Pages.
#
# Usage:
#   scripts/publish.sh             # prompts for version (default: latest tag)
#   scripts/publish.sh 0.1.0       # publishes v0.1.0
#   make publish                   # same as above
#   make publish VERSION=0.1.0     # passes argument
#
# Requires: curl, jq, git, uv. GITHUB_TOKEN env var must hold a PAT
# with `repo` scope. The tag (vX.Y.Z) must already exist on origin
# and `dist/` must contain matching wheel + sdist (run `make build`
# first).

set -euo pipefail

# --- helpers -----------------------------------------------------------------

c_red()   { printf '\033[31m%s\033[0m\n' "$*" >&2; }
c_yel()   { printf '\033[33m%s\033[0m\n' "$*"; }
c_grn()   { printf '\033[32m%s\033[0m\n' "$*"; }
c_dim()   { printf '\033[2m%s\033[0m\n' "$*"; }

die() { c_red "Error: $*"; exit 1; }

# --- 1. preconditions --------------------------------------------------------

for cmd in curl jq git uv; do
    command -v "$cmd" >/dev/null 2>&1 || die "$cmd is required on PATH"
done

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
    c_red "Error: GITHUB_TOKEN is not set"
    cat >&2 <<'EOF'

Create a Personal Access Token with the `repo` scope at
  https://github.com/settings/tokens
then export it before running:
  export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
EOF
    exit 1
fi

# --- derive owner/repo from origin ------------------------------------------

ORIGIN_URL="$(git remote get-url origin)"
# Supports both git@github.com:owner/repo.git and https://github.com/owner/repo(.git)
SLUG="$(echo "$ORIGIN_URL" \
    | sed -E 's#^(git@github\.com:|https://github\.com/)##' \
    | sed -E 's#\.git$##')"
OWNER="${SLUG%%/*}"
REPO="${SLUG##*/}"
API="https://api.github.com/repos/$OWNER/$REPO"

# --- 2. pick version --------------------------------------------------------

INPUT="${1:-}"
if [[ -z "$INPUT" ]]; then
    LATEST_TAG="$(git tag --sort=-v:refname | grep -E '^v[0-9]' | head -1 || true)"
    [[ -n "$LATEST_TAG" ]] || die "no version tags found (expected v[0-9]*); create one with 'make version VERSION=X.Y.Z' first"
    if [[ -t 0 ]]; then
        read -r -p "Publish which version? [$LATEST_TAG] " INPUT
    fi
    [[ -n "$INPUT" ]] || INPUT="$LATEST_TAG"
fi

# Accept "X.Y.Z" or "vX.Y.Z"; normalize to "vX.Y.Z"
INPUT="${INPUT#v}"
[[ "$INPUT" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] \
    || die "invalid semantic version: $INPUT"
TAG="v$INPUT"
VERSION="$INPUT"

c_grn "Publishing $TAG"

# --- 3. sanity checks -------------------------------------------------------

git rev-parse "$TAG" >/dev/null 2>&1 \
    || die "tag $TAG does not exist locally (run 'make version VERSION=$VERSION' first)"

git fetch --tags --quiet origin
git ls-remote --tags origin "refs/tags/$TAG" | grep -q "$TAG" \
    || die "tag $TAG is not on origin (push it first: git push origin $TAG)"

WHEEL="$(ls dist/minidsp_linux_qt-"$VERSION"*.whl 2>/dev/null | head -1 || true)"
SDIST="$(ls dist/minidsp_linux_qt-"$VERSION".tar.gz 2>/dev/null | head -1 || true)"
[[ -f "$WHEEL" ]] || die "no wheel in dist/ for $VERSION (run 'make build')"
[[ -f "$SDIST" ]] || die "no sdist in dist/ for $VERSION (run 'make build')"
c_dim "  wheel: $WHEEL"
c_dim "  sdist: $SDIST"

# AppImage is the user-facing artifact for this project — require it.
# The optional sibling .zsync file is only produced when APPIMAGE_UPDATE_INFO
# was set during the AppImage build, so upload it only if present.
APPIMAGE="dist/minidspqt-${VERSION}-x86_64.AppImage"
ZSYNC="${APPIMAGE}.zsync"
[[ -f "$APPIMAGE" ]] || die "no AppImage in dist/ for $VERSION (run 'make appimage')"
c_dim "  AppImage: $APPIMAGE"
[[ -f "$ZSYNC" ]] && c_dim "  zsync:    $ZSYNC"

# Probe: release must not already exist
EXISTING="$(curl -sS \
    -H "Authorization: Bearer $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github+json" \
    "$API/releases/tags/$TAG")"
if [[ "$(echo "$EXISTING" | jq -r '.id // empty')" != "" ]]; then
    URL="$(echo "$EXISTING" | jq -r '.html_url')"
    die "release for $TAG already exists: $URL (delete it on github.com to re-publish)"
fi

# --- 4. release notes -------------------------------------------------------
#
# CHANGELOG.md is the authoritative source — it may include hand-curated
# content (typical for milestone releases like v1.0.0). Extract the
# `## [X.Y.Z]` section verbatim. The version heading itself is skipped
# (GitHub already shows the release title) and leading/trailing blank
# lines are trimmed.

c_dim "Extracting release notes from CHANGELOG.md..."
CHANGELOG="CHANGELOG.md"
[[ -f "$CHANGELOG" ]] || die "$CHANGELOG not found (run 'make version VERSION=$VERSION' or create one by hand)"

NOTES="$(awk -v ver="$VERSION" '
    index($0, "## [" ver "]") == 1 { in_section = 1; next }
    in_section && /^## \[/ { exit }
    in_section {
        if (!started && /^[[:space:]]*$/) next
        started = 1
        lines[++n] = $0
    }
    END {
        while (n > 0 && lines[n] ~ /^[[:space:]]*$/) n--
        for (i = 1; i <= n; i++) print lines[i]
    }
' "$CHANGELOG")"

[[ -n "$NOTES" ]] || die "no [$VERSION] section in $CHANGELOG — add it (or run 'make version VERSION=$VERSION') before publishing"

PRERELEASE=false
[[ "$TAG" =~ -(rc|beta|alpha) ]] && PRERELEASE=true

# --- 5. create release ------------------------------------------------------

c_dim "Creating GitHub Release..."
PAYLOAD="$(jq -n \
    --arg tag "$TAG" \
    --arg name "$TAG" \
    --arg body "$NOTES" \
    --argjson prerelease "$PRERELEASE" \
    '{tag_name:$tag, name:$name, body:$body, draft:false, prerelease:$prerelease}')"

RESP="$(curl -sS \
    -H "Authorization: Bearer $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github+json" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    "$API/releases")"

REL_ID="$(echo "$RESP" | jq -r '.id // empty')"
REL_URL="$(echo "$RESP" | jq -r '.html_url // empty')"
UPLOAD_URL_TEMPLATE="$(echo "$RESP" | jq -r '.upload_url // empty')"
if [[ -z "$REL_ID" ]]; then
    c_red "Release creation failed. API response:"
    echo "$RESP" | jq . >&2
    exit 1
fi
# strip the {?name,label} template suffix
UPLOAD_BASE="${UPLOAD_URL_TEMPLATE%\{*\}}"
c_grn "  created: $REL_URL"

# --- 6. upload assets -------------------------------------------------------

upload_asset() {
    local file="$1" name
    name="$(basename "$file")"
    c_dim "  uploading $name ..."
    curl -sS --fail \
        -H "Authorization: Bearer $GITHUB_TOKEN" \
        -H "Accept: application/vnd.github+json" \
        -H "Content-Type: application/octet-stream" \
        --data-binary "@$file" \
        "$UPLOAD_BASE?name=$name" >/dev/null \
        || die "upload failed for $name"
}

upload_asset "$WHEEL"
upload_asset "$SDIST"
upload_asset "$APPIMAGE"
[[ -f "$ZSYNC" ]] && upload_asset "$ZSYNC"

# --- 7. deploy docs ---------------------------------------------------------

c_grn "Building and deploying docs..."
uv sync --quiet --extra docs --inexact
uv run --quiet mkdocs build
uv run --quiet mkdocs gh-deploy \
    --force \
    --message "docs: deploy $TAG" \
    --remote-branch gh-pages

# --- 8. summary -------------------------------------------------------------

PAGES_URL="$(grep -E '^site_url:' mkdocs.yml | sed -E 's/^site_url:[[:space:]]*//')"
echo ""
c_grn "Published $TAG"
echo "  Release: $REL_URL"
echo "  Pages:   $PAGES_URL"
c_dim "(Pages may take 1-2 minutes to flush its cache on first deploy.)"
