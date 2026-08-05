#!/usr/bin/env bash
# Derive every fact about the current sync from git — nothing is hardcoded, so a
# new fork feature shows up here on its own without anyone updating a manifest.
# (The previous prose playbook hardcoded "59 Thai files" and silently went stale
# the moment LINE, voice_realtime and pet were added.)
#
# Usage: sync_state.sh [OURS] [TARGET]      defaults: main upstream/main
# Exit:  0 ok · 1 preconditions failed (caller must stop)
set -uo pipefail

OURS="${1:-main}"
TARGET="${2:-upstream/main}"
fail=0

say() { printf '%s\n' "$*"; }
hdr() { printf '\n## %s\n' "$*"; }

hdr "remotes"
origin=$(git remote get-url origin 2>/dev/null || echo "MISSING")
upstream=$(git remote get-url upstream 2>/dev/null || echo "MISSING")
say "origin   (push here)  = $origin"
say "upstream (never push) = $upstream"
[ "$upstream" = "MISSING" ] && { say "!! no upstream remote"; fail=1; }

git fetch upstream --tags -q 2>/dev/null || { say "!! fetch upstream failed"; fail=1; }
git fetch origin -q 2>/dev/null || true

hdr "positions"
if ! git rev-parse -q --verify "$TARGET" >/dev/null; then
  say "!! target '$TARGET' not found"; fail=1
fi
MB=$(git merge-base "$OURS" "$TARGET" 2>/dev/null)
say "ours       = $(git rev-parse --short "$OURS" 2>/dev/null) ($OURS)"
say "target     = $(git rev-parse --short "$TARGET" 2>/dev/null) — $(git log -1 --format=%s "$TARGET" 2>/dev/null)"
say "merge-base = ${MB:0:8} — $(git log -1 --format=%s "$MB" 2>/dev/null)"
say "upstream is ahead by $(git rev-list --count "$MB".."$TARGET" 2>/dev/null) commits"

hdr "working tree"
dirty=$(git status --porcelain | grep -vc '^??' || true)
say "tracked files modified: $dirty"
if [ "$dirty" != "0" ]; then
  say "   -> use an isolated worktree; do not disturb this checkout"
  git status --porcelain | grep -v '^??' | sed 's/^/   /'
fi

hdr "ours vs origin (must be in sync before syncing)"
if git rev-parse -q --verify "origin/$OURS" >/dev/null 2>&1; then
  counts=$(git rev-list --left-right --count "$OURS...origin/$OURS")
  say "ahead/behind origin: $counts"
  [ "$counts" != "$(printf '0\t0')" ] && { say "!! $OURS and origin/$OURS diverge — push or pull first"; fail=1; }
else
  say "(no origin/$OURS)"
fi

hdr "fork-owned areas (derived, not a hand-written list)"
git diff --name-only "$MB".."$OURS" 2>/dev/null \
  | grep -E '^(deeptutor|web|tests|scripts)/' \
  | awk -F/ '{print $1"/"$2 (NF>2 ? "/"$3 : "")}' | sort | uniq -c | sort -rn | head -20 | sed 's/^/  /'

hdr "collisions (files the fork changed AND upstream changed)"
git diff --name-only "$MB".."$OURS" 2>/dev/null | sort > /tmp/_sync_ours.txt
git diff --name-only "$MB".."$TARGET" 2>/dev/null | sort > /tmp/_sync_up.txt
comm -12 /tmp/_sync_ours.txt /tmp/_sync_up.txt | tee /tmp/_sync_collide.txt | sed 's/^/  /'
say "  -> $(wc -l < /tmp/_sync_collide.txt | tr -d ' ') colliding files"

hdr "fork files upstream DELETED or RENAMED (highest-severity signal)"
git diff --name-status "$MB".."$TARGET" 2>/dev/null | grep -E '^[DR]' \
  | grep -Ff /tmp/_sync_ours.txt | sed 's/^/  /' || say "  (none)"

hdr "files upstream added that this fork gitignores"
# v1.5.9 shipped 4,322 files of committed Next.js build output (106 MB), which
# made the raw diff read 4,395 files when only 73 were source. gitignore does not
# protect you here: it is ignored for untracked files, and upstream tracked them.
# Decide before merging whether to carry them or strip them from the index.
git diff --name-only "$MB..$TARGET" 2>/dev/null > /tmp/_sync_added.txt
ignored=$(git check-ignore --stdin < /tmp/_sync_added.txt 2>/dev/null | wc -l | tr -d ' ')
if [ "${ignored:-0}" != "0" ]; then
  say "  !! $ignored incoming files match this fork's .gitignore:"
  git check-ignore --stdin < /tmp/_sync_added.txt 2>/dev/null \
    | sed 's|/[^/]*$||' | sort | uniq -c | sort -rn | head -5 | sed 's/^/     /'
  say "     -> git rm -r --cached <dir> after merging, or take them deliberately"
else
  say "  (none)"
fi

hdr "toolchain pins changed by upstream"
# A silent CI-only ruff bump turned the Lint job red on an otherwise clean sync:
# local passed because the venv had an older ruff that ignores Markdown.
git diff "$MB".."$TARGET" -- .github/workflows/ .pre-commit-config.yaml 2>/dev/null \
  | grep -E '^[+-].*(ruff|node-version|python-version|==)' | sed 's/^/  /' || say "  (unchanged)"

hdr "result"
if [ "$fail" != "0" ]; then say "PRECONDITIONS FAILED — stop here"; exit 1; fi
say "preconditions ok"
