#!/usr/bin/env bash
# Replay the checks against syncs that already happened and compare to what was
# recorded at the time. This is how you tell a check that works from one that
# merely sounds convincing: two drafts of the seam check reported a confident
# "0 findings" on a merge that had definitely gone wrong, and an early draft of
# this very script asserted the wrong conflict count for v1.4.8 — the script was
# right and the expectation was wrong. Both are why the numbers below cite their
# source report.
#
# Every completed sync preserves its pre-merge state and its target as the two
# parents of its merge commit, so this suite grows by itself: the next sync is
# case 4.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(git rev-parse --show-toplevel)"
RESULT=$(mktemp)

record() { printf '%s\n' "$1" >> "$RESULT"; }

run_case() { # label before target expect_conflicts expect_grep
  local label="$1" before="$2" target="$3" want_n="$4" want_grep="$5"
  printf '\n## %s  (%s..%s)\n' "$label" "${before:0:8}" "${target:0:8}"
  local wt="/tmp/backtest-${before:0:8}"
  rm -rf "$wt"
  if ! git -C "$REPO" worktree add -q --detach "$wt" "$before" 2>/dev/null; then
    printf '  SKIP  %s not reachable\n' "$before"; return
  fi

  ( cd "$wt" && git merge --no-commit --no-ff "$target" >/dev/null 2>&1 )
  local n
  n=$(cd "$wt" && git diff --name-only --diff-filter=U | wc -l | tr -d ' ')
  if [ "$n" = "$want_n" ]; then
    printf '  PASS  %-22s %s\n' "conflict count" "$n"; record PASS
  else
    printf '  FAIL  %-22s got %s, report says %s\n' "conflict count" "$n" "$want_n"; record FAIL
  fi

  if [ -n "$want_grep" ]; then
    local mb out
    mb=$(cd "$wt" && git merge-base "$before" "$target")
    out=$(cd "$wt" && python3 "$HERE/invariants.py" --merge-base "$mb" --scope changed 2>&1)
    if printf '%s' "$out" | grep -qF "$want_grep"; then
      printf '  PASS  %-22s found %s\n' "invariant" "$want_grep"; record PASS
    else
      printf '  FAIL  %-22s did not find %s\n' "invariant" "$want_grep"; record FAIL
    fi
  fi

  ( cd "$wt" && git merge --abort >/dev/null 2>&1 )
  git -C "$REPO" worktree remove "$wt" --force >/dev/null 2>&1
}

# Expectations cite the report that recorded them, so a mismatch is either a
# broken check or a misread report — both worth stopping for.

# REPORT_sync_v1.4.8.md §2: "4 content conflicts + 2 auto-merged HIGH files"
run_case "v1.4.8"  5c33a557 88c25653 4 ""

# REPORT_dry_merge_v1.4.15.md: zero textual conflicts, predicted before the merge
run_case "v1.4.15" b6bd04c0 bca6f6e9 0 ""

# REPORT_sync_v1.5.8.md §2: 8 conflicts. §3: the silent 422 nothing else caught.
run_case "v1.5.8"  e7e6795c 44fa7a15 8 "settings.py:120"

# CHANGES.md v1.5.9: zero conflicts. The interesting part is not the conflict
# count but that 4,322 of the 4,395 changed files were upstream's committed
# build output — see the build-artifact guard in sync_state.sh.
run_case "v1.5.9"  cfcdd0c8 37c3db6d 0 ""

p=$(grep -c '^PASS$' "$RESULT" 2>/dev/null); p=${p:-0}
f=$(grep -c '^FAIL$' "$RESULT" 2>/dev/null); f=${f:-0}
rm -f "$RESULT"
printf '\n%s passed, %s failed\n' "$p" "$f"
[ "$f" -eq 0 ]
