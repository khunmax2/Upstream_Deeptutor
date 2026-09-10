# OpenMAIC integration, second attempt — handoff

**Status:** design agreed in outline, not started. No code exists for it yet.
**Written:** 2026-09-10, at the end of a design session with Attapon.
**Read before this:** `docs/maic-fork-export/README.md` — what the first attempt
did and what bit it. This document does not repeat it.

This file exists because the session that produced these decisions ended at a
usage limit. Everything below was either agreed with Attapon in that session or
measured from the code during it. Where something is a measurement, the command
or the file is named so the next agent can re-check rather than trust.

---

## 1. Where the repository stands

`main`'s history was rewritten on 2026-09-09 to take the first OpenMAIC
integration off it. Nothing was lost:

| | |
|---|---|
| `archive/main-2026-09-09` (`5c6ed4295`) | the whole first attempt, including `integration/maic` (2,832 files) and the five files never exported |
| `docs/maic-fork-export/` on `main` | 22 subtree patches + 7 deploy patches + `why.md` / `why-deploy.md` carrying every commit message |
| `deploy/openmaic-patches/` on `main` | 7 tools a rebuild **runs**, above all `th-TH.partial.json` — the Thai translation source. **Not 1,862/1,862; see §5.1b** |

There is no `integration/` directory on `main` and no design document for the
second attempt other than this one.

---

## 2. What Attapon asked for

Quoted where the wording matters.

- **Every account, isolated.** *"ฉันต้องการให้ทุกคนใช้ได้ทั้งหมดทุก user ทุก
  preset ใน deeptutor เข้าถึงได้ แต่ไม่เห็นข้อมูลกัน"* — not a teacher-only tool,
  not a shared workspace.
- **No bridge, no shared configuration.** *"เรื่อง bridge การตั้งค่า ไม่ต้องทำแล้ว
  แยกอิสระกันไปเลย ไม่ต้องมาผูกกัน แค่ดูว่า api ไม่ชน กับ ผูก uid ที่เข้ามาใช้ พอ
  ที่เหลือแยกหมด เพราะรันคนละ container อยู่แล้ว"* The provider bridge
  (`openmaic_bridge.py`, `build_server_providers.py`) is **out of scope**.
  OpenMAIC gets its own provider configuration, entered in its own UI.
- **No LLM in the deploy path.** *"เพราะเราหวังพึ่ง llm ตลอดทุกครั้งที่ deploy หรือ
  build ถูกไหม"* — this killed one option outright, see §3.
- **The brand must be gone, completely.** *"ไม่อยากให้ผู้ใช้สับสนว่าเป็นคนละ
  ผลิตภัณฑ์ มีเหตุผลห้ามโชว์ด้วย ให้ผู้ใช้คิดว่าเป็น 1 ฟีเจอร์ของ deeptutor พอ"*
- **CI from day one.** Agreed in the previous session and re-confirmed: the first
  attempt was abandoned rather than repaired *because* nothing in
  `.github/workflows/` matched `integration/**` or `deploy/**`, so its state was
  never knowable. Re-verified 2026-09-10: `tests.yml`'s `paths:` filter still
  lists only `deeptutor/** deeptutor_cli/** tests/** requirements/**
  requirements.txt pyproject.toml web/** .github/workflows/tests.yml`.
- **Phase 1 may ship un-branded work and in English.** Confirmed explicitly:
  *"ยอมได้"*. Isolation and CI are the things that cannot be wrong; brand and
  language can be fixed later without anyone losing data.

---

## 3. Decisions settled, and the evidence for each

### 3.1 A separate fork of OpenMAIC — not a vendored subtree

`khunmax2/OpenMAIC` forked from `THU-MAIC/OpenMAIC`, the same relationship this
repository already has with `HKUDS/DeepTutor`. DeepWitya pins a commit, builds an
image, and points at the studio **by URL**.

Three options were compared:

| | build / deploy | when OpenMAIC releases |
|---|---|---|
| A — vendored subtree, as last time | deterministic (files are in the repo) | merge conflict, every time |
| B — pin + patch series applied at build | **not deterministic — a reject breaks the build and needs a human** | fix rejects |
| **C — fork, pinned, built to an image** | deterministic (built from a fixed commit) | rebase a branch |

**B is rejected** on Attapon's objection: nothing that needs a person (or an LLM)
to resolve may sit in the deploy path. Deploy pulls an **image by digest**;
nothing is applied or re-applied at deploy time. Rebasing onto a new OpenMAIC is
deliberate work in a branch with CI, never something that happens during a
deploy.

**A is rejected** because its one real advantage turns out to be narrower than it
looks. The archived `deploy/docker-compose.openmaic.yml` states the case for A
plainly — *"a clone of this repo is everything the build needs — no sibling
checkout, no fetch step, no pinned commit to resolve"* — but that is true only on
the Docker path. `deeptutor start` never launched OpenMAIC (verified: only
`model_catalog.py` and `openmaic_bridge.py` mention it on the Python side, and
both are now out of scope). A non-Docker user must run the studio themselves
either way; with A they would still have to `pnpm install && pnpm build` inside
`integration/maic` by hand. On that path A and C differ by one `git clone`.

**C also wins on inspectability.** A imported OpenMAIC as a *squashed* subtree:
you get the files but not their history, and our 22 changes end up interleaved
inside upstream's files. A fork keeps upstream's real history with our commits on
top, so `git log`, `blame` and `bisect` all work and "what did we change" is a
branch diff.

### 3.2 The coupling is one URL

`web/lib/openmaic-embed.ts` resolves the studio from `DEEPTUTOR_OPENMAIC_URL`
or `data/user/settings/integrations.json`, with a test rejecting dangerous URLs
(`javascript:alert(1)`). `MaicWorkspace.tsx` shows configuration instructions
when it is unset.

**Corrected 2026-09-10:** this said "already", which was true of `main` before
the rewrite. None of it was on `main` — the whole surface came off with the
integration on 2026-09-09 and was restored from the archive in phase 1 item 5.
Keep this shape — it is the
loosest possible coupling and it matches *"แยกอิสระกันไปเลย"*.

This also settles how the two run: **they must run separately**. The archived
compose records why, and it is not a preference:

> OpenMAIC ships Tailwind v4 against our v3, and its **69 Next API routes**
> collide with `web/proxy.ts`, which forwards **every** `/api/*` path to FastAPI.

### 3.3 Per-user isolation is achievable — one container, partitioned by owner

This is the most important finding of the session and it reverses an earlier,
**wrong** claim made in conversation ("every document sits in one pile"). That
claim came from reading `lib/persistence/server-auth.ts`, whose *DEVELOPMENT-ONLY*
docstring describes the **runtime/asset** path, not documents.

What is actually true, read from the archived source:

- `lib/persistence/owner-bound-document-store.ts` takes an `ownerId` and there is
  a real `owner_id` column, enforced inside every mutation transaction, with
  ownership modes `create | mutate | read | delete | library`.
- `app/api/persistence/[...path]/route.ts` binds documents to a
  server-resolved owner via `withRequestOwnerId`.
- `lib/server/agent-runtime/owner.ts` — the decisive file — has this signature:

  ```ts
  resolveRequestOwnerId(req, responseHeaders, authenticatedOwnerId?)
  ```

  and this docstring:

  > An explicit `authenticatedOwnerId` (**from the host's auth layer**) is
  > returned verbatim … Current callers (the agent event-stream routes) pass no
  > authenticated owner … **A future auth integration must thread
  > `authenticatedOwnerId` through those call sites**, or sessions created under
  > authenticated identities would be unreachable by their own owner.

  Without it, every browser gets its own anonymous owner from an `anonymous_id`
  cookie — so the model is per-browser today, not one shared pile.

**So a container per user is not needed.** The shape is the same one DeepTutor
already uses — one process, per-user partition — only in SQL rather than
directories. Compare `deeptutor/multi_user/paths.py`:

```
data/user          admin workspace
data/users/<uid>   one workspace per non-admin user
data/partners/<id> partner workspaces
data/system        accounts, grants, audit
```

The work is therefore:

1. **`deploy/openmaic-gatekeeper/`** (336 lines + 198 lines of tests, on
   `archive/main-2026-09-09`) already stands in front of OpenMAIC, verifies a
   DeepTutor session against `/api/auth/status`, and **strips `dt_token` before
   forwarding** so OpenMAIC never sees it. It does **not** currently forward a
   uid, although it already reads `user_id` from the auth status. Add: inject a
   server-controlled identity header, and strip any client-supplied copy of it.
2. **In the fork:** thread that identity into `authenticatedOwnerId` at the call
   sites the docstring names.
3. **Replace `lib/persistence/server-auth.ts`** for the runtime/asset routes —
   upstream says production must, and its `x-learner-key` is client-supplied and
   therefore unenforced today.

**Do not skip step 1's stripping half.** A client-supplied identity header is
exactly the hole `server-auth.ts` warns about, moved one layer out.

### 3.4 PostgreSQL, as a compose service

`OwnerBoundDocumentStore` is built on `PgDocumentStore` — server-side per-owner
documents require a database. The archived compose deliberately left the
`server-persistence` profile off. Attapon confirmed there is no PostgreSQL on the
deploy host but adding one as a compose service is fine.

Browser-side storage was considered and rejected: it isolates trivially but a
learner who opens the studio on a phone would not see their own work. That is
data loss dressed as isolation, and it contradicts *"ทุก user ทุก preset"* —
which is a statement about **accounts**, not browsers.

### 3.5 Upstream is worth contributing to, but must not be depended on

Measured 2026-09-10 against `THU-MAIC/OpenMAIC` (34,299 stars, MIT, pushed that
day):

| | |
|---|---|
| closed PRs, last 100 | **82 merged** |
| authors of the last 30 merged PRs | **20 distinct**, most with one merge each — outside contributors |
| merge latency for outside contributors | 12–169 hours |
| largest outside PR merged | +1,385 / 24 files |
| **but** open PRs | **79**, median age 17 days, oldest 176 |

Read: they accept outside work, including large changes, usually within days —
and a real queue sits for weeks. **Send patches upstream; never block a phase on
their queue.**

Roughly 86% of the first attempt's touched lines are generic work upstream would
plausibly want (Thai locale, basePath, `?lang`/`?theme`/`?embed`, hardcoded-Chinese
i18n bugs, TTS voices, PCM playback, container fixes). Two patches were written
to be upstreamable on purpose: patch 20 is inert when `NEXT_PUBLIC_BASE_PATH` is
unset, and patch 13 made every surface read the `lib/brand/brand-config.ts` that
already existed, overridable through `NEXT_PUBLIC_BRAND_*`.

**Opening PRs on THU-MAIC/OpenMAIC is Attapon's action, not an agent's.** Draft
them; do not send them.

### 3.6 De-branding is required in full — and is the only permanent fork cost

Attapon confirmed both a product reason and a hard requirement. Everything else
in the fork can eventually land upstream; this cannot (nobody merges a PR that
removes their own brand). The first attempt's de-brand is 79 files, +248/−582,
and it reached past the UI — a User-Agent sent to SearXNG, an `MM-API-Source`
header sent to MiniMax, `open.maic.chat` printed on every exported video cover,
and `.maic.zip` on every saved course.

The *refactor* half (making surfaces read the brand config) is upstreamable; the
**values** are env vars.

### 3.7 MIT attribution: files, not UI

**The first attempt shipped OpenMAIC without ever adding it to `NOTICE`** —
verified on both `main` and `archive/main-2026-09-09`, which name Alibaba and
browser-use but not THU-MAIC. The subtree did keep `integration/maic/LICENSE`.

MIT requires the notice be *included* in copies, not *displayed*. Agreed
resolution — no About entry, no UI credit:

- `LICENSE` stays in the fork repo (it is upstream's own file, automatic)
- one `COPY LICENSE …` line so it travels inside the image
- a paragraph in this repository's `NOTICE`, alongside the existing MIT entries

Hosting the studio for users to reach over the web is not distribution of copies;
publishing an image or a public repo is, and both are satisfied by the files
above. (Not legal advice — read the license text.)

### 3.8 CI proves isolation in two halves, joined by a contract

Agreed. The two-account proof does **not** run as one end-to-end job per PR.

| where | asserts | needs |
|---|---|---|
| the fork's CI | an identity header `X` yields owner `X`; owner A cannot read, mutate or delete owner B's document | a Postgres service + OpenMAIC's own `vitest`. **Not DeepWitya** |
| this repository's CI | the gatekeeper injects the *verified* uid, **strips any client-supplied copy**, and sends no header at all for an unverified request | extends the existing 198 lines of gatekeeper tests. **Not OpenMAIC** |
| both | the header's name and shape | one more assertion in `check_openmaic_contract.py` |

Stripping a client-supplied identity header is not optional: without it the hole
`server-auth.ts` warns about has simply moved one layer out.

The contract half matters more than it looks. If either side renames the header
silently, everyone collapses into one owner and **nothing turns red** — the
system keeps working, and every user sees every other user's data. That is the
quietest failure available in this design.

A real end-to-end run belongs on the nightly `schedule: cron "17 3 * * *"` that
`tests.yml` already carries, not on every PR — a job that needs two containers
and a network fails for reasons that are not our code far more often than for
reasons that are.

`tests.yml`'s `paths:` filter must gain the gatekeeper and compose paths, or the
whole thing is invisible again — which is exactly how the first attempt died.
Service containers are not new ground here: `python-tests` already runs Redis
with a health check (`tests.yml:236`).

### 3.9 Schema drift is the only silent data-corrupting path

OpenMAIC has **no versioned migration tool**. Tables are created in code, and
`packages/@openmaic/storage/test/pg-schema-contract.test.ts` says why that
matters:

> Golden pins for the two PostgreSQL schemas this package exports… every
> statement here is guarded by `IF NOT EXISTS`, so PostgreSQL silently accepts
> whatever table already exists under the name. A column type, a nullability, an
> index, or a FK action can drift apart from a downstream migration without a
> single error being raised; the first symptom is a store query failing in
> production, or — **worse — succeeding against the wrong types**.

`DOCUMENT_PG_SCHEMA`, `RUNTIME_PG_SCHEMA` and the rest are public API, so the
defence is to pin them:

1. `check_openmaic_contract.py` gains a DDL assertion beside the checks it
   already makes against `openmaic-pin.json` (pinned commit, locale key count).
   A rebase that changes the DDL then fails at rebase time, with a name, rather
   than when a user cannot open their course.
2. When it does drift, we write the `ALTER TABLE` by hand. Accepted: upstream
   ships no tool for this and will not.
3. **`pg_dump` is a required step before every rebase**, written into the
   procedure rather than left to memory.

### 3.10 Deleted accounts leave data, and a script cleans it up

`deeptutor/multi_user/identity.py:369` — `delete_user()` removes the account
record and revokes guardian relationships, and **leaves `data/users/<uid>/` on
disk**. Since uids are generated, re-registering the same username produces a new
uid and the old tree is orphaned permanently. This is DeepTutor's behaviour
today, not something the studio introduces.

Agreed: match it, and add an **admin-run reconciliation script** — read
DeepTutor's user list, list `owner_id`s in Postgres, report the ones with no
account left, and let an admin purge them. Default is to **export each owner's
rows to a file before deleting**, because deleting the wrong account is not
recoverable.

Rejected: deleting studio rows the moment an account is deleted. That needs a
hook from DeepTutor into the studio, which is the provider bridge again in the
opposite direction — the coupling Attapon cut on purpose. The script reads both
sides only when a person runs it; nothing calls anything during normal operation.

The same script answers the pre-existing DeepTutor gap.

### 3.11 A no-authentication install has a uid already

No design needed. `LOCAL_ADMIN_ID = "local-admin"`
(`deeptutor/multi_user/models.py:89`) and `deeptutor/api/routers/auth.py:511`
returns `user_id="local-admin"` when authentication is off, which the gatekeeper
already reads. A single-user install therefore has one well-defined owner, and
OpenMAIC's anonymous-cookie owner is never reached.

### 3.12 Naming: "Course Studio" at `/studio`

Confirmed. The first attempt named everything after the vendor — `/maic`,
`MaicWorkspace` — which contradicts the de-branding requirement in the most
visible place there is:

| | first attempt | second |
|---|---|---|
| route | `/maic` at the start — **the brand leaks into the address bar** — but `/course-studio` by the end, with a permanent redirect | `/course-studio`, kept (ADR-0005, amended 2026-09-10) |
| menu entry | `MaicWorkspace` | `Course Studio` / `สตูดิโอสร้างคอร์ส` / `课程工作室` |
| env var | `DEEPTUTOR_OPENMAIC_URL` | unchanged — an operator sees it, a user does not, and it says plainly what is behind the door |

### 3.13 Seamlessness: URL parameters at open, and nothing more

Accepted at the middle level. DeepWitya passes `?lang=`, `?theme=` and
`?embed=1` when it opens the studio — the first attempt's patches 4 and 5, 7
files, +206/−116 — so the theme and language match and host-owned chrome is
hidden.

Rejected: two-way state binding over `postMessage`. It buys live theme and
language switching, at the cost of an API between two systems that must be kept
in version step forever and that breaks quietly on a rebase — the same objection
that removed the provider bridge, in a different direction.

The accepted consequence: **changing the interface language while the studio is
open does not reach it until a reload.** Confirmed acceptable.

### 3.14 Where the seven tools go, and what triggers a rebase

`deploy/openmaic-patches/` was written when OpenMAIC was a subtree. Under a fork
some of it is in the wrong repository and some of it has no job left.

| tool | goes | why |
|---|---|---|
| `th-TH.partial.json` | **the fork** | the generated `th-TH.json` lives there; a source sitting in another repository makes the build reach across one |
| `build_th_locale.py` | the fork | it writes a file in the fork |
| `check_openmaic_i18n_gaps.py` | the fork | it reads OpenMAIC's source |
| `check_openmaic_contract.py` | **stays here** | it asserts what *DeepWitya* depends on — URL, `frame-ancestors`, port, pin, and now the DDL |
| `openmaic-pin.json` | **stays here**, naming our fork's commit **and the image digest** | it is this repository's statement of which studio it expects |
| `export_upstream_patches.py` | **retired** | it converted our commits into patches a maintainer could apply; a real fork opens a pull request instead |
| `build_server_providers.py` | **deleted** | it is the provider bridge, cut from scope |

Both deletions were confirmed after being told what they hold.
`build_server_providers.py` is the one worth naming: it carried the knowledge
that a provider URL valid in DeepTutor's settings may be `localhost`, which
inside another container means *that* container, so loopback must be rewritten to
`host.docker.internal`; and that the two products name the same things
differently (`gemini`/`google`, `stt`/`asr`, `search`/`web-search`). If shared
provider configuration is ever wanted again, recover it from
`archive/main-2026-09-09` rather than rediscovering it.

**A rebase happens for a reason, never on a schedule.** A security fix, or a
feature worth having. Every rebase carries the DDL-drift risk of §3.9, so a
calendar would be a way of taking that risk for nothing.
`check_openmaic_contract.py` **reports** the distance — commit, locale-key drift
(roughly 50–90 keys a week upstream), DDL — and must not force the move.

The procedure, in order:

1. `pg_dump`
2. rebase our commits onto the new upstream — commits upstream has since merged
   drop out by themselves, which is the mechanism by which this fork shrinks
3. `check_openmaic_contract.py`; write the `ALTER TABLE` by hand if the DDL moved
4. CI on both sides, including the two-account isolation proof
5. build, then update `openmaic-pin.json` and the compose digest here

This is a **rebase**, where the DeepTutor side is a *merge*: `main` here carries
fork work woven through its history, while the fork will carry a small set of
commits sitting on top, and keeping those a readable set is worth more than
preserving their original parents.

**Write this as a plain checklist in phase 1; promote it to a skill only after
the first real rebase.** The `upstream-sync` skill earns its keep through
`references/decisions.md`, accumulated from syncs that actually happened — a
skill written before the first rebase would be a guess with a table of contents.
It should end up easier than `upstream-sync`, because nearly every check here is
machine-answerable (DDL pin, key count, contract, isolation test) where the Thai
localisation work needs judgement on almost every hunk.

---

## 4. The phased plan

Agreed shape: **do not do everything at once**, which is how the first attempt
became unreviewable. Isolation and CI are the two things that cannot be wrong
later; brand and language can be corrected without data loss.

### Phase 1 — it runs, and data is separated correctly

Ships **with the OpenMAIC brand still visible and in English.** Explicitly
accepted.

- fork `THU-MAIC/OpenMAIC` → `khunmax2/OpenMAIC`, pin a commit

  *Amended 2026-09-11.* The fork lives at **`khunmax2/Ups_openMAIC`** now, and
  it is deliberately *not* a GitHub fork. A repository GitHub classes as a fork
  does not run Actions until someone enables them by hand, and upstream's
  workflow triggers name upstream's branches — so the original fork's CI never
  ran once, and every early change merged on local measurement alone. The move
  cost nothing that matters: all 532 commits went across, `upstream` is still a
  git remote, and the old repository is kept read-only for its pull request
  pages, whose reasoning is also exported under
  `docs/planning/openmaic-integration/fork-pull-requests/`.
- basePath work (first attempt: 36 files, +434) so it serves under a path
- Postgres as a compose service; `server-persistence` profile on
- gatekeeper: inject a server-controlled uid header, strip any client copy
- fork: thread `authenticatedOwnerId`; replace `server-auth.ts`
- `NOTICE` + `COPY LICENSE` into the image
- **CI in both repositories, before any of this is called done**
- a test that proves two accounts cannot see each other's documents — this is
  the phase's actual acceptance criterion, not "it loads"

### Phase 2 — it stops looking like a second product

- de-brand, all 79 files, including the video cover, the `.zip` extension and
  the outbound headers
- `NEXT_PUBLIC_BRAND_*` values

### Phase 3 — Thai

- `build_th_locale.py` generates `th-TH.json` from `th-TH.partial.json`.
  **Not "already written" — measured 2026-09-10 against `29735f10`: 1,687 of
  upstream's 1,801 keys are covered, 114 are missing, and 64 in the partial no
  longer exist upstream.** See §5.1b. **Edit the partial, never the output.**
- `?lang=` / `?theme=` so the studio follows DeepWitya's interface

### In parallel, not on the critical path

Draft upstream PRs for the generic work. Attapon sends them.

---

## 5. What is not decided

All six questions this file originally listed have been answered, in §3.8–§3.14,
and the decision is recorded as **ADR-0005** (`docs/adr/0005-course-studio-sibling-application.md`).

### 5.1 The one estimate has since been measured

**A working checkout of upstream OpenMAIC is on this machine** at
`/Users/attapon/Project/antigravity/OpenMAIC`, `origin` pointing at
`THU-MAIC/OpenMAIC` — a plain clone, **not yet a fork**. Fast-forwarded on
2026-09-10 to `29735f10` (`fix(ssrf): keep cloud metadata endpoints blocked
under ALLOW_LOCAL_NETWORKS`). One local edit is stashed in the working tree:
`.gitignore` gains pnpm store paths. Note the pin file still names `d4ef5faa`
(2026-09-01), so the checkout is already ahead of it.

Threading `authenticatedOwnerId` was measured against that checkout, and it is
smaller than feared:

| | count | files to edit |
|---|---|---|
| call sites reaching it through `withRequestOwnerId` | **33** | **1** — changing the wrapper covers all of them |
| routes calling `resolveRequestOwnerId` directly | 3 | `stages/[id]/freshness`, `agent/owner-events`, `agent/sessions/[id]/events` |
| duplicated cookie logic | 1 | `lib/workbench/workspace-actions.ts`, a server action with no `Request`, so it reads `next/headers` instead |

**About six files.** Three things make it smaller still:

- the third parameter is **still present at upstream HEAD**, not something that
  decayed since the archive was taken;
- **their own test already covers it** — `tests/agent-runtime/owner.test.ts:73`
  asserts `resolveRequestOwnerId(req, headers, 'user-42') === 'user-42'` *and*
  that no cookie is minted;
- their tests establish a naming convention: authenticated owners carry a
  `user:` prefix (`user:mine`, `user:requestor`) against `anon:` for
  cookie-minted ones. **Send `user:<uid>`, not a bare uid.**

### 5.1b The Thai coverage claim was stale, measured 2026-09-10

This document said the translation source is complete at 1,862/1,862. That was
true at the old pin `d4ef5faa` (2026-09-01) and is not true at `29735f10`:

| | |
|---|---|
| `en-US.json` at `29735f10` | **1,801** keys — upstream removed keys as well as adding them |
| `th-TH.partial.json` | 1,751 keys |
| covered | **1,687 of 1,801** (93.7%) |
| **missing** | **114** — e.g. `home.slogan`, `settings.lang_en`, `settings.providerNames.exa` |
| **stale** | **64** in the partial with no upstream key left — e.g. `toolbar.toggleSidebar`, `toolbar.playbackSpeed` |

Phase 3 is therefore not free: 114 keys to translate and 64 to drop. That is
small work, but it is work, and it grows every week upstream moves
(handoff §3.14 puts the drift at roughly 50–90 keys a week).

`build_th_locale.py` already checks exactly this — coverage, interpolation
parity, and keys that no longer exist upstream — so the numbers above are
re-derivable rather than something to trust from this table.
### 5.1a Those measurements re-checked against `29735f10`, 2026-09-10

Verified independently before starting phase 1, against the checkout at
`D:\Vscode\OpenMAIC` (`origin` = `THU-MAIC/OpenMAIC`, HEAD `29735f10`, clean):

| claim | measured | |
|---|---|---|
| the third parameter survives at HEAD | `owner.ts:52-57`, and `if (authenticatedOwnerId) return authenticatedOwnerId;` | ✅ |
| 33 call sites through the wrapper | 34 raw matches minus the definition = **33** | ✅ |
| 3 direct routes + 1 server action | exactly those four files, by name | ✅ |
| upstream's own test covers it | `tests/agent-runtime/owner.test.ts:73` | ✅ |
| `user:` / `anon:` convention | both present (`user:mine`, `user:foreign`, `anon:alice`) | ✅ |
| T3 still true | `SHARED_ASSET_PRINCIPAL = 'shared'` (`server-auth.ts:30`), docstring still says *no user isolation* | ✅ |

**Six files, confirmed.** Nothing decayed between the archive and HEAD.

### 5.2 What is genuinely still open

The design has no threat model. Every isolation guarantee in it rests on one
assumption — that the studio container is reachable *only* through the
gatekeeper, which strips any client-supplied identity header and injects a
verified one. That assumption was reasoned about, never tested against a
framework, and its failure mode is the quiet one: everybody collapses into one
owner and nothing turns red.

**The agreed next step is a STRIDE / data-flow threat model of the whole path**
— browser → nginx → gatekeeper → studio → PostgreSQL — using the
`senior-security` skill. Do that before writing the phase 1 code, not after.

---

## 6. Facts worth not re-deriving

- `deeptutor start` never launches OpenMAIC and never did.
- OpenMAIC cannot be merged into `web/`: Tailwind v4 vs v3, and 69 Next API
  routes against a `web/proxy.ts` that forwards all of `/api/*` to FastAPI.
- The deployment host opens only 443 and already serves `/sansarnnews`,
  `/research-helper`, `/dol`, `/deepwitya`, `/opdc-assistant`, `/deepwitya2`, so
  `/api` at the root belongs to other people's applications. A path, never a
  port, and never a proxy rule at `/api`.
- Next's `basePath` prefixes `<Link>`, the router and `/_next/` assets. It does
  **not** touch the 74 `fetch('/api/...')` calls across 44 files, nor three
  `EventSource` streams. The first symptom of getting this wrong is not a network
  error — it is an access-code login box nobody configured, because
  `/api/access-code/status` fails and the guard reads an error as locked.
- `.github/workflows/docker-release.yml` publishes to `ghcr.io` already, but
  under upstream's name (`ghcr.io/hkuds/deeptutor`) — it has never been renamed
  for this fork.
- Labels built from ternaries survive a literal grep; token substitution across
  ja/th/zh leaves stray spaces. Both cost real time in the first attempt. See
  `docs/maic-fork-export/README.md`.

---

## 7. If you are the agent picking this up

Read in this order: this file → `docs/maic-fork-export/README.md` →
`docs/maic-fork-export/why.md` for any patch you are about to redo. The archived
source is browsable without checking anything out:

```bash
git show archive/main-2026-09-09:integration/maic/lib/server/agent-runtime/owner.ts
git show archive/main-2026-09-09:deploy/openmaic-gatekeeper/README.md
git log archive/main-2026-09-09 -- deploy/openmaic-gatekeeper/
```

The repository rules still apply and are not optional: `CLAUDE.md` §1 (every
change recorded in `CHANGES.md`, and a `docs/reports/REPORT_*.md` closing each
phase), §3 (prefer new files over editing upstream ones), §5 (never commit on
`main` — branch, PR, green CI, merge). `gh` resolves to `HKUDS/DeepTutor`, so
every `gh` command needs `--repo khunmax2/Upstream_Deeptutor`.

Attapon works in Thai. He checks claims, and he has caught unverified assertions
more than once — measure before asserting, and say plainly when something is an
estimate rather than a measurement.
