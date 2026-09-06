#!/usr/bin/env bash
#
# Prepare the OpenMAIC source tree that `deploy/docker-compose.openmaic.yml`
# builds from.
#
# The compose file builds from `context: ../OpenMAIC`, a sibling checkout. On a
# deploy host that directory does not exist, and there is no second repository
# to clone it from: OpenMAIC stays a **pristine mirror of upstream** and
# everything of ours lives in this repository as patches. This script is the
# step that turns those two facts into a buildable tree.
#
#   this repo (git)  ──┐
#                      ├──► ../OpenMAIC, at the pinned commit, patched
#   THU-MAIC (git) ────┘
#
# Deliberately NOT a fork. Committing our changes into that checkout would turn
# every future OpenMAIC release into a merge with conflicts — the position this
# fork is already in with HKUDS. Patches break loudly instead, which is what you
# want from a change you intend to send upstream.
#
# Requires only git and docker. The `pnpm install` step runs in a throwaway
# container rather than on the host, because a deploy host should not need a
# Node toolchain to reconcile a lockfile.
#
#   ./deploy/openmaic-fetch.sh                 # prepare ../OpenMAIC
#   ./deploy/openmaic-fetch.sh --dest /srv/x   # somewhere else
#   ./deploy/openmaic-fetch.sh --host-pnpm     # use the host's pnpm instead
#   ./deploy/openmaic-fetch.sh --strict        # also refuse on untracked files
#
# Untracked files in the checkout are reported and then tolerated: they cannot
# be built over, and on a working machine they are ordinary debris. Modified
# tracked files are refused, because those are edits to upstream source that a
# build would silently absorb. --strict refuses on both, which is what you want
# before generating a patch or opening an upstream PR.
#
# Then, from the repository root:
#
#   docker compose -f docker-compose.yml -f deploy/docker-compose.openmaic.yml \
#     build openmaic
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATCH_DIR="$REPO_ROOT/deploy/openmaic-patches"
PIN="$PATCH_DIR/openmaic-pin.json"

DEST="$REPO_ROOT/../OpenMAIC"
USE_HOST_PNPM=0
SKIP_DEPS=0
STRICT=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dest) DEST="$2"; shift 2 ;;
    --host-pnpm) USE_HOST_PNPM=1; shift ;;
    --skip-deps) SKIP_DEPS=1; shift ;;
    --strict) STRICT=1; shift ;;
    -h|--help) sed -n '2,39p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# The pin is the whole point: this reproduces one verified commit, not "latest".
# Parsed without jq so the deploy host needs nothing extra. The `"commit"` key
# is matched with its closing quote so it cannot also hit commit_short/_date.
# ---------------------------------------------------------------------------
[ -f "$PIN" ] || die "pin file not found: $PIN"
json_str() {
  sed -n "s/^[[:space:]]*\"$1\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" "$PIN" | head -1
}
UPSTREAM_URL="$(json_str repo)"
COMMIT="$(json_str commit)"
COMMIT_DATE="$(json_str commit_date)"
[ -n "$UPSTREAM_URL" ] || die "could not read \"repo\" from $PIN"
[ -n "$COMMIT" ]       || die "could not read \"commit\" from $PIN"

say "Pin"
info "$UPSTREAM_URL"
info "$COMMIT  ($COMMIT_DATE)"

command -v git >/dev/null || die "git is required"

# ---------------------------------------------------------------------------
# Clone, or move an existing checkout onto the pin.
# ---------------------------------------------------------------------------
if [ ! -d "$DEST/.git" ]; then
  say "Cloning into $DEST"
  git clone "$UPSTREAM_URL" "$DEST"
else
  say "Using existing checkout at $DEST"
  # A dirty tree is expected on a re-run — this script's own patches make it
  # dirty, and the apply loop below already recognises what it has applied
  # before. What must not be silently built over is somebody *else's* change.
  #
  # So the test is not "is it dirty" but "is anything dirty that is not ours".
  # Ours is derived from the patches themselves plus the files we generate, so
  # it cannot drift out of step with the patch set the way a hardcoded list would.
  OURS_RE="$(
    {
      sed -n 's|^diff --git a/\(.*\) b/.*|\1|p' "$PATCH_DIR"/0*.patch
      printf '%s\n' \
        'lib/i18n/locales/th-TH.json' \
        'lib/video-export/emit-hyperframes/noto-script-font-assets.ts' \
        'public/vendor/video-export/fonts/noto-sans-thai-thai-400-normal.woff2' \
        'pnpm-lock.yaml'
    } | sort -u | sed 's/[].[^$\\*/]/\\&/g' | paste -sd'|' -
  )"
  # Modified and untracked are not the same risk, and treating them alike was
  # wrong. A *modified* tracked file is somebody's edit to upstream source: build
  # over it and their change is in the image with no record of it, so that is
  # worth stopping for. An *untracked* file cannot be built over — it can only be
  # added — and on a working machine these are ordinary debris: editor backups,
  # a local compose override, an agent's notes. Refusing on those turns the guard
  # into something to be worked around, which is how a guard stops being read.
  #
  # Untracked files are still named, because an untracked *source* file can
  # genuinely change a Next build — a stray `app/**/page.tsx` becomes a route.
  # Being told is the point; being blocked is not.
  STATUS="$(git -C "$DEST" status --porcelain)"
  FOREIGN_MOD="$(printf '%s\n' "$STATUS" | grep -v '^??' | sed 's/^...//' \
      | grep -Ev "^($OURS_RE)$" || true)"
  FOREIGN_NEW="$(printf '%s\n' "$STATUS" | grep '^??' | sed 's/^...//' \
      | grep -Ev "^($OURS_RE)$" || true)"

  if [ -n "$FOREIGN_NEW" ]; then
    printf '\n\033[33m    untracked files present — not built over, but they are in the build context:\033[0m\n'
    printf '%s\n' "$FOREIGN_NEW" | while IFS= read -r f; do printf '      %s\n' "$f"; done
    printf '    (pass --strict to refuse on these too, e.g. before an upstream PR)\n'
    if [ "$STRICT" = "1" ]; then
      die "--strict given, and the checkout carries untracked files that are not ours."
    fi
  fi

  if [ -n "$FOREIGN_MOD" ]; then
    printf '\n'
    printf '%s\n' "$FOREIGN_MOD" | while IFS= read -r f; do printf '    %s\n' "$f"; done
    die "the checkout has modified files this script did not make.

These are edits to upstream source. Building over them would fold somebody's
work into the image with no record of it. Deal with them deliberately — this
script will not run 'git checkout --' or 'git reset --hard' on your behalf.

To reverse only what this script applied:

    for p in \$(ls -r $PATCH_DIR/0*.patch); do
        git -C \"$DEST\" apply -R \"\$p\" 2>/dev/null || true
    done
    rm -f \"$DEST/lib/i18n/locales/th-TH.json\""
  fi
  git -C "$DEST" fetch origin --tags
fi

CURRENT="$(git -C "$DEST" rev-parse HEAD)"
if [ "$CURRENT" != "$COMMIT" ]; then
  say "Checking out the pinned commit"
  info "$CURRENT -> $COMMIT"
  git -C "$DEST" checkout --detach "$COMMIT" 2>/dev/null \
    || die "commit $COMMIT not found. If the pin was bumped, run 'git -C $DEST fetch origin' and retry."
else
  info "already at the pinned commit"
fi

# ---------------------------------------------------------------------------
# Our patches, in order. A failure here names the file and line, which is the
# reason these are patches and not commits — they break loudly rather than
# merging into something subtly wrong.
# ---------------------------------------------------------------------------
say "Applying patches"
shopt -s nullglob
PATCHES=("$PATCH_DIR"/0*.patch)
[ ${#PATCHES[@]} -gt 0 ] || die "no patches found in $PATCH_DIR"

for p in "${PATCHES[@]}"; do
  name="$(basename "$p")"
  if git -C "$DEST" apply --check "$p" 2>/dev/null; then
    git -C "$DEST" apply "$p"
    info "applied   $name"
  elif git -C "$DEST" apply --reverse --check "$p" 2>/dev/null; then
    info "already   $name"
  else
    die "$name does not apply to $COMMIT.

Upstream most likely reorganised the file. Regenerate the patch against the new
source rather than hand-editing it — see deploy/OPENMAIC_SYNC.md."
  fi
done

# ---------------------------------------------------------------------------
# The Thai locale is generated, not patched: it is a whole new file, so it can
# never conflict, and merging it over en-US is what keeps untranslated keys
# rendering in English instead of falling back to OpenMAIC's zh-CN default.
# ---------------------------------------------------------------------------
say "Building the Thai locale"
# Ask each candidate to prove it runs. `command -v` is not enough on Windows,
# where python3.exe is a Microsoft Store stub that resolves on PATH and then
# refuses to execute — found the hard way, on the first run of this script.
PY=""
for candidate in python3 python; do
  if "$candidate" -c 'import sys' >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -n "$PY" ]; then
  "$PY" "$PATCH_DIR/build_th_locale.py" --openmaic "$DEST" \
      --out "$DEST/lib/i18n/locales/th-TH.json"
else
  info "no python on PATH — running it in a container"
  docker run --rm \
    -v "$REPO_ROOT:/repo:ro" -v "$DEST:/openmaic" \
    -w /repo python:3.12-alpine \
    python /repo/deploy/openmaic-patches/build_th_locale.py \
      --openmaic /openmaic --out /openmaic/lib/i18n/locales/th-TH.json
fi

# ---------------------------------------------------------------------------
# Dependencies. This is not optional and not a habit:
#
# 0002 adds a dependency while deliberately leaving pnpm-lock.yaml out of the
# patch (that one package churns 2,934 lines of it, and lockfile hunks conflict
# on every upstream dependency change). The Dockerfile then runs
# `pnpm install --frozen-lockfile`, which fails on a lockfile that does not
# match package.json. So the lockfile has to be reconciled here, before build.
#
# Done in a container by default so a deploy host needs no Node toolchain.
#
# CI=true is load-bearing, not decoration. When `node_modules` was created by a
# pnpm running on the host — which is the normal state of any machine that
# followed "Trying it locally first" — the store path recorded inside it is a
# host path that does not exist in the container. pnpm wants to remove and
# rebuild the directory, asks for confirmation, finds no TTY, and aborts with
# ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY. CI=true is how pnpm is told there
# is nobody to ask. Found by someone following the runbook, not by writing it.
# ---------------------------------------------------------------------------
if [ "$SKIP_DEPS" = "1" ]; then
  say "Skipping dependencies (--skip-deps)"
  info "the image build WILL fail on --frozen-lockfile unless you do this yourself"
else
  say "Reconciling the lockfile and generating font assets"
  DEPS_CMD='corepack enable && pnpm install --no-frozen-lockfile && pnpm run gen:video-export-noto-script-fonts'
  if [ "$USE_HOST_PNPM" = "1" ]; then
    command -v pnpm >/dev/null || die "--host-pnpm given but pnpm is not on PATH"
    # Measured, not cautionary: on Windows this path hung at rollup for thirteen
    # minutes at 0% CPU and left pnpm-lock.yaml 1,934 lines shorter. The
    # container path exists because it is the one that works, not because it is
    # tidier.
    case "$(uname -s)" in
      MINGW*|MSYS*|CYGWIN*)
        printf '
[33m    --host-pnpm on Windows has hung at rollup and damaged pnpm-lock.yaml.[0m
'
        printf '    The containerised path is the supported one. Continuing because you asked.
' ;;
    esac
    ( cd "$DEST" && pnpm install --no-frozen-lockfile && pnpm run gen:video-export-noto-script-fonts )
  else
    command -v docker >/dev/null || die "docker is required (or pass --host-pnpm)"
    # Match the host user on Linux so the tree does not come back root-owned.
    USER_FLAG=()
    if [ "$(uname -s)" = "Linux" ]; then USER_FLAG=(--user "$(id -u):$(id -g)"); fi
    # MSYS_NO_PATHCONV stops Git Bash rewriting the container-side paths into
    # Windows ones: without it `-w /w` reaches docker as `W:/` and the run dies
    # on "the working directory 'W:/' is invalid". Ignored everywhere else.
    MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' \
    docker run --rm "${USER_FLAG[@]}" \
      -e HOME=/tmp -e COREPACK_ENABLE_DOWNLOAD_PROMPT=0 -e CI=true \
      -v "$DEST:/openmaic" -w /openmaic node:22-alpine sh -c "$DEPS_CMD"
  fi
fi

# ---------------------------------------------------------------------------
say "Verifying"
if [ -n "$PY" ]; then
  "$PY" "$PATCH_DIR/check_openmaic_contract.py" --openmaic "$DEST" || true
else
  info "skipped the contract check (no python on PATH)"
fi

cat <<EOF

$(printf '\033[1m==> Ready\033[0m')

    $DEST is at $COMMIT with $(printf '%s' "${#PATCHES[@]}") patch(es) applied.

Build it:

    docker compose -f docker-compose.yml -f deploy/docker-compose.openmaic.yml build openmaic

Set DEEPTUTOR_PUBLIC_ORIGIN first if this is not localhost. It is a build
argument, not a runtime one — Next inlines the frame-ancestors header into the
image, so changing the public origin later means rebuilding, not restarting:

    DEEPTUTOR_PUBLIC_ORIGIN=https://your.host docker compose ... build openmaic

To take the patches back out (before pulling a new OpenMAIC release):

    for p in \$(ls -r $PATCH_DIR/0*.patch); do git -C "$DEST" apply -R "\$p"; done
    rm -f "$DEST/lib/i18n/locales/th-TH.json"
EOF
