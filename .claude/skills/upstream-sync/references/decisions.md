# What the completed syncs actually cost

Calibration for the go/no-go call in Stage 3. Read this instead of trusting a
conflict-count threshold — the relationship between "size of the release" and
"work required" is weak, and these three show why.

| | v1.4.8 | v1.4.15 | v1.5.8 | v1.5.9 |
|---|---|---|---|---|
| files / lines | 146 · +11.7k | 210 · +13.8k | **516 · +52k** | 73 source · +3k |
| upstream commits | — | — | 157 | 11 |
| colliding files | 11 | 8 | 27 | 7 |
| **real conflicts** | **4** | **0** | **8** | **0** |
| Tier-1 pillars hit | 0 | 0 | 4 (3 auto-merged) | 1 (auto-merged) |
| th keys +/− | +29 / −2 | +27 / −3 | +246 / −3 | +9 / −0 |
| actual effort | ~half day | ~half day | ~1 day | ~1 hour |

The lesson from v1.4.15: 210 changed files produced **zero** conflicts, because
almost all of it was net-new surface. And v1.5.8 — three times larger again —
produced only 8, of which the two "HIGH risk" files predicted by file-level
analysis both auto-merged cleanly. **Overlap in file names is a weak predictor;
what matters is whether upstream rewrote a seam the fork sits on.**

Better signals, in rough order of how much they should worry you:

1. Upstream deleted or renamed a file the fork owns (never happened yet — treat
   it as a stop-and-think).
2. Upstream refactored a module the fork hooks into. This is what actually costs
   time, and it does not show up as a conflict.
3. Tier-1 language pillars touched (`core/i18n.py`, `services/prompt/manager.py`,
   `config/loader.py`, `web/context/app-shell-storage.ts`).
4. New locale keys — predictable, roughly an hour per 100.
5. Raw conflict count — mostly noise on its own.

## Resolutions worth remembering

**Upstream generalises what the fork special-cased.** v1.5.8 replaced the fork's
hand-rolled `parse_language` alias table with a passthrough that keeps any locale
code intact (their #712). Taking their version wholesale would have silently
started returning `"thai"` instead of `"th"` for the spelled-out alias, breaking
every `== "th"` comparison downstream. The fix was to keep their structure and
re-add one arm. Expect more of this shape: their design is usually the better
base, and the fork's contribution shrinks to a few lines inside it.

**Follow upstream's information architecture, don't fight it.** Twice now
upstream has moved a page the fork had linked into navigation — `/space/agents`
in v1.4.8, `/settings/mcp` in v1.5.8. Both times the right call was to drop the
fork's nav entry rather than keep a link to a page upstream had relocated.

**git can mis-align a hunk.** In v1.5.8 the "ours" side of a conflict in
`agentic_pipeline.py` was the tail of a function upstream had refactored away;
taking it would have left a `NameError` on a variable no longer in scope. Read
the whole function before choosing a side.

**A clean merge can still delete a fix.** The Gemini `thought_signature` fix
hung on a `LoopHost` hook that upstream removed while introducing an equivalent
canonical builder. The fork's override merged byte-for-byte and became
unreachable — no conflict, no failing test. It was ported into upstream's new
builder instead: one implementation, in their file, which is also where it is
least likely to be orphaned again.

## Failures that no gate caught

Each of these is why a check exists — or, in the last case, why one deliberately
does not.

**A new pydantic model with `Literal["zh", "en"]`** (v1.5.8). Upstream added
`UISettingsUpdate` for `PUT /api/v1/settings/ui`. It auto-merged cleanly because
the class was entirely new; the fork's existing `"th"` arms elsewhere in the file
survived, so nothing looked wrong. The frontend sends `"th"`, so saving a
language would have returned 422. `tsc` cannot see Python, i18n parity only
compares catalogs, and there was no conflict to review. → `invariants.py --only th-py`.

**A CI-only toolchain bump** (v1.5.8). Upstream changed `pip install ruff` to
`ruff==0.16.0`. Local checks passed because the venv had 0.15, which does not
format Python blocks inside Markdown; CI failed on files nobody had touched. →
`sync_state.sh` diffs the workflow pins, and Stage 5 uses the pinned version.

**Orphaned fork fixes** — *not* automated, on purpose. Two attempts failed their
backtest: reference counting saw nothing because the symbol kept its name and all
12 references while only its binding moved, and a size-threshold heuristic missed
the 16-line edit that caused it. `--seams` therefore lists the files to read
(ranked with shared-ownership files first, since "merged clean" is exactly where
this hides) and leaves the judgement to a person.

**Upstream can commit files you gitignore.** v1.5.9 shipped 4,322 files of
Next.js build output (106 MB) — the raw diff read 4,395 files when only 73 were
source. `.gitignore` does not save you: it applies to *untracked* files, and
upstream tracked these, so a plain merge takes them. The choice is to strip them
(`git rm -r --cached` in the merge commit, which is what was done — it matches
the fork's declared intent) or carry them. Stripping means every later sync shows
them as deleted-by-us until upstream stops; that was accepted as the cheaper
side. `sync_state.sh` now reports incoming files matching `.gitignore` at
preflight, so this is a decision made before the merge rather than a surprise
after it.

Second-order effect worth knowing: `FORK_TOUCHPOINTS.txt` is generated from
`merge-base..main`, so anything the fork *deletes* counts as a fork change. After
stripping the build output the file ballooned from 152 to 4,471 entries until the
regeneration was taught to exclude that path.

## Test-failure baseline

`pytest` has a stable set of failures locally because the `[partners]` extra
(`mcp`, `telegram`, `slack_sdk`, `PyJWT[crypto]`) is not installed; CI installs
`.[all]` and they pass there. The count grows when upstream adds tests to that
extra — 10 at v1.4.8, 25 at v1.5.8 — so **never compare counts across releases**.
A failure is a regression only if it does not also fail on `main` in the same
environment. Prove that by rerunning the subset in a worktree at `main`.

One more that looks alarming and is not: `tests/runtime/test_api_import_memory_boundary.py`
parses a subprocess's stdout as JSON, and this project logs to stdout once
settings exist. It fails on `main` too whenever `data/user/settings/` is
populated.


## What the first skill-driven sync found (v1.5.9)

Running the playbook as a skill rather than from memory changed the outcome in
one concrete way: the build-artifact anomaly surfaced at preflight, as a count
that did not match the commit log, instead of after the merge as a mysteriously
enormous diff.

It also found three bugs in the skill itself, which is the honest argument for
Stage 7 existing at all:

- `invariants.py` flagged **itself** — its own source contains the literal
  conflict-marker sequence it searches for. Marker detection is now anchored to
  the start of a line, since git writes markers at column 0 and any tooling that
  discusses them does not.
- The skill's scripts live in the repo, so `ruff format --check .` covers them.
  They were not formatted to the CI-pinned ruff and would have failed the Lint
  gate. Run the repo's own linters over `.claude/skills/` like any other source.
- `FORK_TOUCHPOINTS.txt` regeneration needed the exclusion described above.

None of these were catchable by thinking harder about the design; they showed up
the moment the thing ran against a real release.

## What v1.5.16 found: verify happens in a worktree, `deeptutor start` happens on the real checkout

Everything in Stage 5 — `npm ci`, build, node tests, i18n, pytest, the live Thai
chat turn — ran green inside the throwaway dry-merge worktree, and CI on `origin`
was green after push. The first `deeptutor start` on the user's actual checkout
still failed: `Module not found: pdfjs-dist`. Upstream had added it to
`package.json` as part of a new reading feature; the worktree's `npm ci` installed
it there, but the real `web/node_modules` — untouched since before the sync —
never saw it. A green verify matrix proves the *code* merged correctly; it says
nothing about whether the environment the user actually runs matches what was
verified. Stage 6 now runs `npm ci --legacy-peer-deps` on the real checkout
as part of landing, not as an afterthought triggered by the user hitting the
error.

## v1.6.4 — a clean sync, and two method corrections

370 files, six conflicts, nothing fork-owned deleted. The merge was easy; the two
things worth keeping are both about *how the checks were read*, not what they found.

**A worktree baseline is not the real checkout.** The first regression count came
back at 32 and was wrong. `pytest` ran the merge in a throwaway worktree — whose
`data/user/settings/model_catalog.json` is the git-tracked one, with no active
model — and the baseline in the user's real checkout, which has a configured
catalog. 29 of the 32 were `LLMConfigError`, i.e. the environment differing, not
the code. Re-running the baseline **in an identical worktree at `main`** left
three real regressions. The playbook already said to prove a regression this way;
this is the sync that shows what happens when you don't. Treat any failure
mentioning configuration, credentials or an active model as environment-suspect
until the like-for-like run says otherwise.

**A fix's scope should anticipate upstream's next edit.** v1.6.3's follow-up put
`PYTHONIOENCODING` on the one workflow step that printed a `✅`. v1.6.4 added
*another* step printing two more, in the same job, which would have reproduced the
Windows failure exactly. The fix was correct and still nearly useless one release
later. When patching a shared upstream file, ask where upstream will plausibly add
the next line and place the fix so it is covered — job scope over step scope, the
loader over the call site.

**Converging by luck, again.** The fork's Gemini `thought_signature` passthrough
was independently rewritten by upstream (#1181) and deleted here — the second
time after `mcp/manager.py` in v1.5.16. Both had been flagged as upstream-PR
candidates and never sent. The cost is not the deletion, it is everything carried
in between: the mechanism, its tests, and its share of every merge conflict until
upstream's version lands. Stage 7 is not paperwork.

