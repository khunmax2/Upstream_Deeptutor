# PROMPT — Execute Upstream Sync v1.4.15 (Thai fork)

> **Paste this into the code/terminal agent running inside the repo.** It performs a
> real `git merge` of upstream **v1.4.15** into `main` and re-applies the fork's Thai
> i18n + LINE customizations. Companion diagnosis: `REPORT_impact_v1.4.15.md`
> (go decision = **SYNC NOW**, CI green: Tests #538 on `bca6f6e9` = Success).

---

## 0. Facts (do not re-derive)

- Repo: `Upstream_DeepTutor/DeepTutor`. Remotes: `origin` = fork (`khunmax2`, push here),
  `upstream` = `HKUDS/DeepTutor` (**never** push, never touch its `main`).
- **BASE (ours):** `main` = v1.4.8 + Thai i18n + LINE.
- **TARGET:** `upstream/main` = **v1.4.15** (`bca6f6e9`). **merge-base = `88c25653`** (v1.4.8).
- Model: `main` is customized → this is a **`git merge upstream/main` with conflicts**,
  NOT ff-only, NOT rebase. Resolve with **"upstream structure wins + Thai re-applied."**
- CI gate: **already green** — no need to re-check.

## 1. Preconditions — STOP if any fail

```bash
git -C . rev-parse --abbrev-ref HEAD          # note where you are now
git status -s                                 # working tree
git fetch upstream --tags                     # refresh; expect upstream/main = bca6f6e9
git rev-parse upstream/main                    # must == bca6f6e9836f21a0ec9d38c8838dce68d4eacd92
git rev-list --left-right --count main...origin/main   # must be "0   0" (main clean & pushed)
```

- If the working tree is dirty with **unrelated** work (e.g. `voice_prototype/`,
  `web/next-env.d.ts`), **commit or stash it on its own branch first**. Do NOT carry it
  into the sync. `web/next-env.d.ts` is generated — safe to `git checkout --` or ignore.
- The untracked `REPORT_impact_v1.4.15.md` should ride along; you'll commit it in §7.

## 2. Branch off main (isolate the sync)

```bash
git switch main
git switch -c sync/v1.4.15        # all merge work happens here; main stays put until §6
```

Do **not** run the merge on `feat/voice-prototype` or `feature/LINE_Integration`.

## 3. Merge

```bash
git merge --no-ff --no-commit upstream/main
git status                        # enumerate conflicts vs auto-merged
```

Large diff (210 files, +13,848 / −3,438) but mostly **net-new non-colliding surface**
(LightRAG-server integration, user-profile+avatar, admin User-Management, MCP-grant
gating, docker/rootless hardening, provider updates, **new native Mattermost partner
channel**). Only the files below need attention.

## 4. Conflicts — NONE (dry-merge verified)

An isolated dry-merge (`REPORT_dry_merge_v1.4.15.md`) confirmed **`git merge` produces
zero textual conflicts** — all 8 collision files auto-merge. You do **not** hand-resolve
anything. Two light touches only:

- **Eyeball `deeptutor/agents/chat/agentic_pipeline.py`** after the merge — it
  auto-resolves, but confirm both the Thai `normalize_agent_language` path and the new
  upstream logic survived and read correctly (sanity, not conflict resolution).
- Everything else (`ServiceConfigEditor.tsx` LightRAG UI, `settings.py`, `ConnectedAgents.tsx`,
  `QuizViewer.tsx`, `mastery/loop.py`, `en/app.json`, `zh/app.json`) is taken as
  auto-merged — no action.

If `git status` shows **any** unmerged path, STOP — that contradicts the dry-run;
re-fetch and re-verify you're merging `bca6f6e9` onto a clean `main`.

## 5. The only real work: apply the i18n delta **+27 / −2**

Dry-merge pinned this exactly: after the merge, `th/app.json` needs **27 new keys added**
and **2 orphaned keys removed** → `set(th) == set(en)` = 2668 (parity exact, verified).
The translations are pre-drafted in **`th_i18n_delta_v1.4.15.json`** — **review the Thai
wording**, then apply:

```bash
python3 - <<'PY'
import json
d=json.load(open('th_i18n_delta_v1.4.15.json',encoding='utf-8'))
p='web/locales/th/app.json'
th=json.load(open(p,encoding='utf-8'))
th.update(d['add'])
for k in d['remove']: th.pop(k,None)
json.dump(th,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
print('applied',len(d['add']),'adds',len(d['remove']),'removes ->',len(th),'keys')
PY
```

- **+27** new keys: Profile/avatar · LightRAG server config · Partners-assigned /
  loading / settings-tour (full EN+ZH references in the delta file's header).
- **−2** orphaned keys upstream deleted (`"PDF limit: {{size}}"`,
  `"PDF files must be smaller than {{size}}."`).

### `Lang`-requires-`th` sweep — verified clean, keep as a guard
The dry-merge swept every changed `.tsx`/`.ts` and found **no** genuine `{zh,en}`-only
`Lang` missing `th` (the one flag, `settings/tools/page.tsx`, was a false positive on a
`ToolHints` *type* field, and upstream didn't touch that file). `npm run build` in §6 is
the backstop — if `tsc` still complains about a missing `th`, add the arm there.

> The **new Mattermost partner channel** (`deeptutor/partners/channels/`) is net-new and
> non-colliding — same extension point as our LINE channel. If it surfaces user-visible
> strings, give them `th` (not required for parity).

## 6. Verify — all must pass before touching `main`

```bash
git commit                                    # finish the merge commit on sync/v1.4.15
cd web && npm run build                        # tsc + Next — catches the Lang-th trap
npm run i18n:check                             # parity th == en + audit
cd .. && ruff check . && ruff format --check .
pytest -q tests deeptutor/learning/tests       # expect the same ~10 optional-dep partner
                                               #   failures as clean main (telegram/slack/
                                               #   msteams SDKs absent) — NOT a regression
deeptutor run chat "อธิบายเรื่องเศษส่วนให้หน่อย" -l th   # live Thai smoke → must reply in Thai
```

If anything Thai-related regresses, fix on `sync/v1.4.15` and re-verify. Do not proceed
until build + parity + ruff are green and the Thai smoke test replies in fluent Thai.

## 7. Land it + compliance (Apache §4(b) / repo CLAUDE.md §1)

```bash
# fast-forward main to the verified sync branch
git switch main
git merge --ff-only sync/v1.4.15
git push origin main

# catch up the feature branches (do NOT let them drift)
git switch feature/LINE_Integration && git merge main && git push origin feature/LINE_Integration
git switch feat/voice-prototype     && git merge main     # push when you're ready

# cleanup
git branch -d sync/v1.4.15
```

**Required records (never skip):**
1. `CHANGES.md` → **"Upstream syncs"** — new entry `### v1.4.15 (bca6f6e9) — merged <date>`:
   what came in, the 8 collisions + how resolved, the +28 Thai keys, verification result,
   and `> next sync merge-base = bca6f6e9`.
2. `REPORT_sync_v1.4.15.md` — the execute report (mirror `REPORT_sync_v1.4.8.md`).
3. Commit messages: Conventional Commits. Keep `NOTICE` current.
4. After code settles: `graphify update .` to refresh `graphify-out/`.

## 8. Rollback (if it goes sideways)

The sync is quarantined on `sync/v1.4.15` and `main` is untouched until §7, so:
`git merge --abort` (mid-merge) or just `git switch main && git branch -D sync/v1.4.15`.
`main` and `origin/main` are unaffected.

---

### One-glance summary
Branch off `main` → `sync/v1.4.15` · merge `upstream/main` (bca6f6e9) · resolve 8
collisions (1 real hand-merge = `agentic_pipeline.py`) · sweep `Lang`-needs-`th` ·
translate ~28 keys · verify (build/parity/ruff/pytest/Thai smoke) · ff `main` + push ·
catch up LINE + voice branches · record `CHANGES.md` + `REPORT_sync_v1.4.15.md`.
