# School roles — teacher, student, IT: design

Decided with the user on 2026-09-20, after the admin lifecycle design
(`../admin-roles/`) went live in `deploy-2026-09-19`. Phases 1–3 were built
the same day on `feat/school-phase1` (unmerged, lab-tested; see
`../../reports/REPORT_school_roles_phases_1_to_3_2026-09-20.md`); Phase 3's
own design is `DESIGN_teacher_dashboard.md`.
This document is the agreement that the phases at the end implement, and it
records what was checked in the code before each decision was made.

## Why

DeepTutor is a personal, lifelong tutor. The user wants to run it for a
school, with three kinds of people: **students** (secondary school), the
**teachers** responsible for them, and the **IT administrator** who runs the
deployment. The question was whether the accounts that exist today can carry
those roles. Checked on 2026-09-20:

- **Accounts today are really three kinds.** `admin`; an ordinary `user` with
  no learning policy (presets `standard` and `custom`); and an ordinary `user`
  with a learning policy (preset `learner`).
- **`standard` and `custom` are identical on the server.** No code branches on
  `custom` except the enum validation in `identity.py` and the `/status`
  mapping. The web tells them apart in three cosmetic places: the admin
  dashboard lists `custom` and `learner` accounts as "assignment users", the
  user's own dashboard shows an "assigned" card layout for `custom`, and the
  create dialog's copy. `custom` means "an account whose grants IT intends to
  curate", not a permission level. Neither reaches the admin sections of
  Settings (`adminOnly` in `settings-nav.ts`, `require_admin` on the server),
  but both reach their **own** settings: personal providers and keys
  (`personal_models`), tools, capabilities, network, models, knowledge, chat,
  memory.
- **`learner` is the child mode upstream designed.** A learning policy can
  only open two surfaces (`LEARNING_SURFACES = {"chat", "reading"}`) and two
  capabilities (`chat`, `immersive_reading`); age bands stop at 13–15; the
  persona is locked to `teacher`; everything else answers 403, and the Course
  Studio gatekeeper refuses the account outright. A secondary student would
  lose Mastery Path, Books, Question Bank, Learning Space and their own
  knowledge base. Upstream issue #1222 (filed by this fork) records that the
  learner UI still offers what the policy denies; it is open and unanswered.
- **Guardians exist and are the right seam for "my students".**
  `multi_user/guardians.py` links a guardian account to a learner with four
  permissions: `assign_materials`, `manage_restrictions`, `view_reports`,
  `reset_credentials`. Today the report behind `view_reports` is thin
  (assigned-material count, grant summary) and every read is audited
  (`guardian_report_view`).
- **Upstream is not working on this.** v1.6.7–v1.6.8 and the commits after
  them touch nothing in `multi_user/`, `routers/auth.py` or guardians; there is
  no upstream issue about teachers, classrooms or schools. What upstream *is*
  doing is consolidating learning evidence: #1504 (merged 2026-09-19) gives
  Mastery Path, Book Focus-Check and Immersive Reading one Question Bank write
  path, `record_assessment`, with type, result and provenance. It is 58 files
  and +7.2k/−1.4k over `learning/`, `sqlite_store.py`, `mastery_path.py` and
  `reading_extensions.py` — not cherry-pickable, and the user does not want
  to sync now (the deployment is stable after weeks of fixes). **Everything
  the evidence needs already exists at our v1.6.6 baseline**, just in three
  places instead of one: Mastery Path progress (`learning/policy.py`,
  `service.py`, `storage.py`: `mastery_levels` per objective, gate kind and
  threshold, `objective_report`, review due), the Question Bank
  (`sqlite_store.py` `question_bank_*` with `is_correct`, categories,
  `question_bank_stats`; `tools/question_bank.py`), reading quizzes, books,
  sessions and the learner profile. #1504 adds one write path and moves
  reading-quiz grading to the server; it adds no data we lack.
- **Memory is per user and owner-only.** `services/memory/` keeps three
  layers in the user's own workspace; `/api/memory/*` serves only the owner,
  and the tutor reads L3 through the `read_memory` tool. What each layer
  holds is in §5.

## Decisions (2026-09-20)

| # | Question | Decision |
|---|---|---|
| 1 | Pilot size? | 1–3 classes, at most about 100 students. Teacher↔student links are made one at a time with the existing guardian relationship; classrooms and CSV import come in a later phase. |
| 2 | Who creates accounts? | Admins only, as upstream has it (`POST /api/auth/users`). Teachers do not create accounts. CSV import is the relief for term start, later. |
| 3 | A new role for teachers? | **No.** A teacher is an ordinary `user` with preset `teacher` — the same behaviour as `custom` — plus guardian links to the students they are responsible for. A role is referenced everywhere (`require_admin`, `is_admin`); a preset is referenced in five places. |
| 4 | What is a secondary student? | A new preset `student`: the **full product** of a `standard` user with **no learning policy**, so upstream treats it as an ordinary user everywhere. Three groups are closed by fork code: personal providers/keys/tools/MCP/capabilities settings; partners, MCP connections and sandbox exec; the admin sections (already closed). Everything else — every chat capability, Deep Research, Reading with upload, Books, Mastery Path, Question Bank, Learning Space, Co-Writer, Memory, own knowledge bases, persona choice — stays open. |
| 5 | Why not widen `learning_policy`? | It is upstream's child mode, hard-wired to two surfaces and the area of #1222. Extending it would conflict on every sync and bend its intent. `learner` stays as it is for young children. |
| 6 | What does a teacher see? | **Learning evidence only**: mastery per objective, Question Bank results, reading progress and quizzes, books finished, sessions/time/regularity, the learner profile the student filled in, the *topics* asked about as categories. **Never** chat transcripts, Memory, personal knowledge bases, Co-Writer or partners. |
| 7 | Memory and the dashboard? | The dashboard's spine is structured, always-fresh data (Mastery Path, Question Bank, reading, sessions). Memory contributes one derived document, `teacher.md`, built only from the sections in §5 that are learning signals, with no footnotes and a prompt that forbids personal facts. L1 is never read for a teacher. |
| 8 | Does the student see what the teacher sees? | **No per-file marker.** The student's Memory page is upstream's, unchanged; `teacher.md` is not listed there. Transparency is given **once, at the policy level**: a two-line notice on the `student` account's first sign-in ("your conversations with the tutor are private; your teacher sees your learning progress"), and in the consent the school collects from parents. Every teacher read is audited so the school can answer a parent. |
| 9 | Defaults for a class? | IT (later a teacher) can set a class's starting persona, granted models and shared knowledge bases. A student can change the persona; the default is a direction, not a lock. |
| 10 | Studio for students? | Deferred. When it comes it is one more surface in the same shape (a learner mode that reads published courses, never creates or uses keys) and a gatekeeper contract change. Not part of the phases below. |
| 11 | Sync v1.6.8 first, for `record_assessment`? | **No.** The evidence is read through one fork-only module, `learning_evidence.py`, from the sources v1.6.6 already has. When a later sync brings #1504, only that module's inside changes; the dashboard and the guardian routes do not. Reading-quiz grading stays client-side until then — acceptable for a pilot, and every read is audited. The sync moves to "when convenient, nothing waits on it". |

## Design

### 1. Presets

`AccountPreset` becomes `standard | custom | learner | student | teacher`.
The two new values are labels: identity validation, the `/status` mapping,
the create dialog and the users page learn them; nothing else upstream branches
on a preset. `teacher` behaves as `custom` (listed among assignment users on
the admin dashboard). `student` behaves as `standard` except for §2.

### 2. What a student cannot do

A fork-only module, `deeptutor/multi_user/student_policy.py`, decides for one
account whether a request is one of the closed groups, and one FastAPI
dependency applies it to the routers concerned:

- **own settings writes**: `PUT/POST /api/settings/*` that change personal
  providers, keys, tools, MCP, capabilities (reads stay, so the pages can
  render read-only), and `personal_models` sign-ins;
- **partners**: creating or editing partners and channels; **MCP** user
  config; **exec** in the sandbox (`exec_enabled` stays false in the grant);
- the admin sections, already closed by `require_admin`.

The sidebar and Settings hide the same entries from `preset === "student"`
(one fork component check, no `learning_policy`). The server refuses with 403
and a message that says the account is a student account managed by the
school; the audit records refusals the way `account_change_refused` does.

Everything not listed is untouched, which is the point: the tutor's
personalisation (Memory, learner profile, Mastery Path, Question Bank) works
exactly as for any user.

### 3. Teachers and their students

A teacher is a `user` with preset `teacher` and guardian links. The existing
permissions map onto the school:

| guardian permission | what the teacher does with it |
|---|---|
| `view_reports` | opens the student's learning dashboard (§4) |
| `assign_materials` | assigns reading materials and, later, courses |
| `manage_restrictions` | sets the student's learning restrictions within what IT allows |
| `reset_credentials` | resets a student's device pairing / PIN |

Admins create the links from the users page (as today, with the
`GuardianRelationshipsEditor`). Phase 3 replaces one-by-one linking with a
classroom.

### 4. The teacher dashboard (shape only; designed in its own document)

One page per teacher: the students linked to them, and for each student the
learning evidence of decision 6, read through routes that check the guardian
link and audit the read. Sources, in order of trust:

1. Mastery Path progress (`learning/policy.py`: mastery per objective, gate
   kind, status, review due) and the Question Bank (`sqlite_store.py`:
   entries with `is_correct`, categories, stats);
2. reading progress, quizzes and finished books;
3. session counts, time on task, regularity — counts, never content;
4. the learner profile the student filled in;
5. `teacher.md` from Memory (§5), as an AI-written summary beside the
   numbers.

All five are read through **one fork-only module,
`deeptutor/multi_user/learning_evidence.py`**, which returns one evidence
record per student and is the only thing the guardian routes and the
dashboard call. It reads the three sources v1.6.6 keeps separately; when a
sync brings upstream's `record_assessment` (#1504), the module's inside
changes and nothing above it does. This is the fork rule — new files over
edited upstream files — applied to data as well as code.

Details (layout, aggregation per class, alerts) are for
`DESIGN_teacher_dashboard.md`, written before Phase 3.

### 5. Memory: what may reach a teacher

`services/memory/` keeps, per user:

| layer | what it holds | for the teacher |
|---|---|---|
| **L1** | per-surface snapshots — `chat` is the **full transcript** of every conversation; `quiz` is question / answer / correct / right-or-wrong; `book` pacing and re-opened pages; `kb` queries; `notebook`, `cowriter`, `partner` content — plus an append-only trace | **never** read for a teacher; quiz evidence comes from the Question Bank instead |
| **L2** | one LLM-consolidated markdown per surface with footnotes into L1: `chat` → Misconceptions / Mastery / Topics; `quiz` → Error patterns / Strong / Struggling topics; `book` → Pacing / Sticking points / Annotation themes; `kb` → Interests / Frequent queries / Library gaps; `notebook`, `cowriter`, `partner` → themes and style | **allowed sections**: all of `quiz`; `chat.Mastery`, `chat.Misconceptions`; `book.Pacing`, `book.Sticking points`. **Not allowed**: `chat.Topics`, `kb`, `notebook`, `cowriter`, `partner`. Footnotes are never followed. |
| **L3** | four cross-surface slots: `recent` (timeline), `profile` (Identity / Learning style / Knowledge level), `scope` (concepts tagged familiar / practicing / unsure), `preferences` | **allowed**: `scope` whole; `profile.Learning style`, `profile.Knowledge level`. **Not allowed**: `profile.Identity`, `preferences`, `recent`. |

Two facts about the layers shape the design:

- **L2 and L3 do not refresh by themselves.** Consolidation is a run the
  user starts from Settings ▸ Memory, and each run costs LLM calls. A
  dashboard that leaned on L3 alone would show stale text for a student who
  never pressed the button. Phase 2 therefore adds a scheduled consolidation
  for `student` accounts (nightly, IT-configurable, IT pays the cost), and
  the dashboard's spine stays the structured sources.
- **L2 and L3 are free text.** They are a summary beside the numbers, not
  the numbers.

**`teacher.md`.** A fifth L3 document that exists only in this fork, written
by a new consolidator mode that reads only the allowed sections above, with a
prompt that forbids personal facts and produces no footnotes. It is not one of
`L3_SLOTS`, so the student's Memory page does not list it, the `read_memory`
tool does not inject it, and the owner-only memory API does not serve it. A
teacher reads it through a guardian route that requires `view_reports` and
writes an audit line, the same way `guardian_report_view` does today.

### 6. Transparency and audit

- The `student` account's first sign-in shows a two-line notice once:
  conversations with the tutor are private; the teacher sees learning
  progress. The same sentence goes into the school's parent consent.
- Every teacher read of a student's evidence or `teacher.md` is audited with
  actor, student and time (`guardian_report_view` exists; the dashboard
  routes reuse it).
- Nothing in the student's own UI marks what a teacher can see.

### 7. Kept for later, on purpose

- **Lifelong data.** A student who leaves should be able to take their tutor
  with them: an export of the workspace, or a transfer to another account.
  Today the only end is the bin and the purge.
- **Classrooms and CSV import** (Phase 3).
- **Studio learner mode** (decision 10).
- **Upstream #1222.** The `learner` UI still offers what it denies; that fix
  is needed regardless of this design if `learner` is used for young children.

## Phases

**Phase 1 — accounts.** Presets `student` and `teacher`; `student_policy.py`
with its dependency on the settings, partners, MCP and exec routers; sidebar
and Settings hiding; the first-sign-in notice; tests red before each. No
studio change, no host contract change: one `deeptutor2` rebuild.

**Phase 2 — evidence.** `learning_evidence.py` over the v1.6.6 sources,
the guardian evidence routes (mastery, question bank, reading, sessions,
profile), the `teacher.md` consolidator mode and its scheduled run, the
audit lines. Still DeepWitya only; no upstream sync required.

**Phase 3 — teacher dashboard and classrooms.** Its own design document
first (`DESIGN_teacher_dashboard.md`): the page, per-class aggregation,
classroom as a group with a home-room teacher, CSV import.

Each phase: one PR per step, tested locally on the real image before the
host, as the admin-roles work was done.
