---
name: upstream-sync
description: Merge a new HKUDS/DeepTutor upstream release into this fork without losing the Thai i18n, LINE, pet or voice work. Use this whenever the user wants to sync, merge, catch up with, or pull in upstream — including "upstream ออกเวอร์ชันใหม่", "อัปเดตจาก upstream", "sync v1.5.x", "เราตามหลัง upstream แค่ไหน", asking how far behind the fork is, or asking to bring a feature branch up to date with main after a sync. Also use it when planning a sync (impact analysis, dry-merge, go/no-go) even if no merge will happen yet.
---

# Upstream sync

This fork carries Thai i18n, a LINE channel, the Anima Habitat pet and a realtime
voice / in-page agent stack on top of HKUDS/DeepTutor. Upstream moves fast — 157
commits landed between v1.4.15 and v1.5.8, about a month apart — so each sync is
a real merge with conflicts, never a fast-forward.

The merge itself is the easy part. What makes these syncs expensive is a specific
failure mode: **an upstream change that breaks fork behaviour while every gate
stays green.** Several have already shipped past `git`, `tsc`, i18n parity and CI
— a pydantic model that silently 422'd Thai users, a CI-only lint bump, a fix
orphaned by a refactor that touched none of its files. The stages below exist to
catch that class; everything else is bookkeeping.

Size is not the signal. v1.5.8 was 516 files and took a day; v1.5.9 was 11
commits and took an hour — but its raw diff read 4,395 files because upstream had
committed their build output. Read what preflight tells you, not the headline.

## Config for this repo

Everything repo-specific lives here so the rest of the playbook stays generic.

| | |
|---|---|
| ours / upstream | `main` · `upstream/main` (HKUDS/DeepTutor) — **never push to upstream** |
| push remote | `origin` (khunmax2/Upstream_Deeptutor) |
| language guard | `th` — must appear in every `Lang` object and language `Literal` |
| locales | `web/locales/{en,th,zh}/app.json`, exact key parity vs `en` |
| verify | `npm run build` · `npm run test:node` · `npm run i18n:check` · `ruff check`/`format` · `pytest -q tests deeptutor/learning/tests` |
| lint version | whatever `.github/workflows/tests.yml` pins — **not** whatever the venv has |
| known-failing | the `[partners]` extra (`mcp`, `telegram`, `slack_sdk`, `PyJWT`) is not installed locally; those failures are expected, CI installs `.[all]` |
| records | `CHANGES.md` → "Upstream syncs" · `docs/reports/REPORT_sync_*.md` · `FORK_TOUCHPOINTS.txt` · `graphify update .` |

## Stage 0-1 — preflight and the CI gate

```bash
bash .claude/skills/upstream-sync/scripts/sync_state.sh          # main vs upstream/main
```

It prints remotes, merge-base, how far upstream is ahead, fork-owned areas,
colliding files, fork files upstream deleted, **incoming files this fork
gitignores**, and any toolchain pin upstream moved.

Everything is derived from git, so a new fork feature appears without anyone
updating a manifest — which is precisely how the previous prose playbook went
stale (it hardcoded "59 Thai files" and never learned about LINE, voice or pet).

That gitignore line matters more than it looks: `.gitignore` only protects
*untracked* files, so anything upstream tracks arrives regardless. v1.5.9 brought
4,322 build artifacts (106 MB) that way. Decide before merging whether to strip
them (`git rm -r --cached <dir>` inside the merge commit) or carry them — and if
you strip, exclude that path when regenerating `FORK_TOUCHPOINTS.txt`, which
otherwise counts every deletion as a fork change.

Then check the target's CI and **stop if anything is red**:

```bash
gh api repos/HKUDS/DeepTutor/commits/<TARGET_SHA>/check-runs \
  --jq '.check_runs[] | "\(.conclusion // .status)\t\(.name)"' | sort | uniq -c
```

Syncing onto a red release means debugging their breakage and yours at once. If
`gh` cannot answer, treat that as red — a check that fails open is worse than no
check. Note that release tags are annotated, so `git rev-parse v1.5.8` differs
from the commit; compare `v1.5.8^{commit}` before concluding they diverge.

## Stage 2-3 — dry-merge, then decide

Do this in a throwaway worktree so the user's checkout is never touched. That is
not a nicety: syncs have run start-to-finish while the user had uncommitted work
on another branch.

```bash
git worktree add -q --detach /tmp/dry-run main
cd /tmp/dry-run && git merge --no-commit --no-ff upstream/main
git diff --name-only --diff-filter=U          # the real conflict list
```

Then run the invariant checks and the seam review:

```bash
python3 <skill>/scripts/invariants.py --scope changed
python3 <skill>/scripts/invariants.py --seams main upstream/main
```

Clean up with `git merge --abort` and `git worktree remove --force`.

**Resolve during the dry run, not after it — `rerere` makes it free.** This
playbook merges the same merge twice: once here to size it up, once for real in
Stage 4. With `rerere.enabled` (preflight checks it; `autoUpdate` also stages
what it replays) every resolution recorded in the throwaway worktree is replayed
automatically on the real merge, because `rr-cache` lives in the common git dir
that all worktrees share. Without it you hand-resolve everything twice — v1.5.16
was 22 conflicts, so that is the whole difference between one pass and two.

Do not expect it to carry across *different* syncs: upstream's side of the hunk
has moved by then, so a v1.5.17 conflict rarely matches the v1.5.16 recording
byte-for-byte. The guaranteed win is within one sync.

**Deciding.** Conflict count alone is a poor signal — v1.4.15 had 210 changed
files and zero conflicts, while a much smaller release needed two hand-merges.
Weigh instead: are Tier-1 language pillars involved (`core/i18n.py`,
`services/prompt/manager.py`, `config/loader.py`, `app-shell-storage.ts`)? Did
upstream delete or move anything the fork owns? How much of the conflict volume
is locale JSON, which is nearly free to resolve? Read `references/decisions.md`
for how the four completed syncs actually went — the numbers there calibrate
better than a threshold.

## Stage 4 — resolve

The principle that has held across every sync: **take upstream's structure, then
re-apply the fork's behaviour on top.** Upstream generalises things the fork had
special-cased (v1.5.8 replaced a hand-rolled `parse_language` with a passthrough
that handles any locale) and their version is usually the better base — it just
drops the Thai-specific arm, which you add back.

Two traps worth naming, both hit for real:

- git can mis-align hunks so that "our side" is the tail of a function upstream
  deleted. Taking it would have left a `NameError` on a variable that no longer
  exists in scope. Read the surrounding function, not just the hunk.
- A conflict resolved by taking upstream can silently delete a fork fix. When
  upstream removed the `LoopHost` hook the Gemini `thought_signature` fix relied
  on, the fork's override merged cleanly and became unreachable. The fix was
  ported into upstream's new canonical builder instead — one implementation, in
  their file, which is also the most mergeable place for it.

**Re-run `invariants.py` after resolving.** Counts taken while conflict markers
are present are meaningless (the script says so rather than reporting a number),
and new violations routinely appear in the auto-merged regions nobody reviewed —
v1.5.8 had 24 of them in files that never conflicted.

For the locale delta, compute it, validate it, then apply:

```bash
python3 <skill>/scripts/i18n_delta.py --plan     # what to add/remove
python3 <skill>/scripts/i18n_delta.py --apply    # writes th/app.json
```

It refuses to apply if any `{{placeholder}}` set diverges from `en`, and checks
that the result is exact key parity rather than merely "no missing keys".

## Stage 5 — verify

Run the full matrix from the config table. Two details that have burned us:

- Use the ruff version CI pins, not the venv's. A CI-only bump to `ruff==0.16.0`
  turned Lint red on an otherwise perfect sync, because 0.16 formats Python
  blocks inside Markdown and the local 0.15 does not. `pip install ruff==<pin>`
  into a scratch venv if they differ, and consider aligning
  `.pre-commit-config.yaml` too.
- Classify pytest failures instead of counting them. The `[partners]` extra is
  not installed locally, so a stable set fails every run; the count grows when
  upstream adds tests to that extra. A failure is only a regression if it is
  absent from the same run against `main`. Prove it by rerunning the failing
  subset in a worktree at `main` rather than asserting it.

Finish with a live Thai turn — `deeptutor run chat "…" -l th` — because prompt
plumbing can break in ways no unit test covers.

## Stage 6 — land

Only after the matrix is green: `git switch main && git merge --ff-only sync/vX`,
then **stop and confirm before pushing**. Pushing and opening PRs are outward
facing; the user says when.

**Reinstall dependencies on the real checkout, not just the worktree.** Stage 5's
`npm ci` ran inside the throwaway dry-merge worktree — that satisfies the verify
matrix but leaves the user's actual `web/node_modules` exactly as it was before
the sync. v1.5.16 landed cleanly and CI was green, but the next `deeptutor start`
on the real checkout failed with `Module not found: pdfjs-dist` — a dependency
upstream had added to `package.json` that only ever got installed in the
worktree. Run `npm ci --legacy-peer-deps` in the real `web/` right after the
ff-only land, before telling the user the sync is done.

The skill's own scripts live in the repo, so the repo's linters cover them —
run `ruff format` over `.claude/skills/` before landing, or Lint fails on files
that have nothing to do with the merge.

Then catch up the other branches, and record the sync — `CHANGES.md` entry,
`REPORT_sync_vX.md`, regenerate `FORK_TOUCHPOINTS.txt` against the new
merge-base, `graphify update .`. Apache-2.0 §4(b) requires the fork to state what
changed, and a local-only note was silently lost on a re-branch once already.

## Stage 7 — feed back what you learned

**First, ask what should go the other way.** The cheapest fork is a smaller
fork, and this is the one lever that actually shrinks it: a fix that lands
upstream stops being a touchpoint forever and can never be orphaned again. It
has already worked here — PR #813 (MCP credential-reload + transport errors
masked as timeouts) was merged into HKUDS on 2026-08-11, and by v1.5.16
`services/mcp/manager.py` was byte-identical to upstream, dropping out of
`FORK_TOUCHPOINTS.txt`.

The counter-example is `channels/manager.py`: the fork's empty-`allowFrom` guard
was flagged as an upstream-PR candidate back in June and never sent. Upstream
wrote the same fix independently by v1.5.16, so the divergence closed anyway —
but on their schedule, not ours, and the fork carried a redundant method plus its
tests until this sync deleted them. Converging by luck costs more than
converging on purpose.

So at the end of every sync, run through the fork's own diff and ask which
pieces are candidates. A candidate is:

- a **bug fix, not a fork preference** — it would help any DeepTutor user, and
  is not about Thai, LINE, the pet or the voice stack;
- **separable** into a small diff against a clean upstream checkout;
- **not already upstream** — check first, since upstream sometimes writes the
  same fix independently (this sync found exactly that in `mcp/manager.py`).

Prepare it as its own branch off `upstream/main` (the existing convention is
`upstream-pr/<topic>`), never as a slice of a fork merge commit. `CHANGES.md`
keeps an "Upstream bug fixes" section for these, written so each stays
cherry-pickable. **Opening the PR is the user's call** — outward-facing, same
rule as pushing.

**Then fold back what this sync taught the skill.**
If this sync surfaced a failure mode none of the checks covered, that is the most
valuable output of the whole exercise. Add it to `references/decisions.md` and,
when it is mechanically checkable, to `invariants.py`. The three checks that
exist all came from a sync that had already gone wrong once.

Be honest about what is *not* checkable. Two automated attempts at detecting
orphaned fork fixes failed their backtest — reference counting saw nothing
because the symbol kept its name and all 12 references while only its binding
moved. That is why `--seams` reports a list to read rather than a verdict.

## Trusting this skill

The four completed syncs are a regression suite: each merge commit preserves the
pre-merge state and the target, and `docs/reports/REPORT_sync_*.md` records what
actually happened. Replaying a check against those and comparing to the record is
how you tell a working check from a confident-sounding one.

```bash
bash .claude/skills/upstream-sync/scripts/backtest.sh
```

Every check here earned its place that way, and two drafts were thrown out when
they failed. If you change a check, rerun this before trusting it.
