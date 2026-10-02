# REPORT — school roles, Phases 1–3 built on a branch (2026-09-20)

Implements `docs/planning/school-roles/DESIGN_teacher_student_it.md`
(decisions 1–11, PR #121) and `DESIGN_teacher_dashboard.md` (decided the same
day). Everything here is on **`feat/school-phase1`**, pushed, **not merged and
without a PR** by the user's choice ("ทำใน branch แยกไปก่อน"). Nothing has
touched the host; every step was run on the **lab stack** (a second local
stack on 4782/9001/9090 beside the UAT one, `deploy/docker-compose.lab.yml`),
rebuilt from the branch before each browser check.

## What was built

| step | commits | server | web | tests |
|---|---|---|---|---|
| lab stack | `a9c18cefc` | — | — | — |
| **1.1 presets** | `67a649ae6` `d021e0947` | `student` / `teacher` in `models.py`, `identity.PRESETS`, `/status` | 5-preset create dialog, `lib/account-presets.ts`, th/zh labels | 4 + node |
| **1.2 student policy** | `1bc8aff56` `b92b085ee` | `multi_user/student_policy.py`: one CLOSED table applied through `_auth`; 403 + audit `student_write_refused` | `lib/student-access.ts`, sidebar / Space / Settings hiding, `StudentNotice.tsx` once per account | 24 + 5 |
| **2 evidence** | `bdf40bd57` `ef1902824` | `learning_evidence.py` (read-only `mode=ro`, five sources, no words), `teacher_summary.py` (`memory/school/teacher.md` from allowed L2/L3 sections, one LLM call, deployment language), `school_jobs.py` (nightly, `settings/school.json`), `api/routers/school.py`; `guardians.GUARDABLE_PRESETS` | guardian editor for `student` too | 12 |
| **3 design** | `b51e02f52` `7021cfb3b` | `DESIGN_teacher_dashboard.md` | — | — |
| **3a classrooms + CSV** | `9fa3b3bf6` `f2f4a857a` | `classrooms.py` (derived links, own ids only, defaults on join), `school_import.py`, 7 routes | `/admin/classrooms`, import dialog with one-time credentials download, users page link + "Class:" | 9 + 3 |
| **3b teacher's pages** | `59a59a319` | `school_alerts.py` (`summary_row`, five rules, `class_totals`), `GET …/roster` | Dashboard tab "Students", `/dashboard/students`, `/dashboard/students/<id>`, `school-parts.tsx` | 15 + 5 |
| **3c IT switch** | (this commit) | — | nightly summary panel on `/admin/classrooms` | +1 |

Totals on the branch: pytest for the school work 64 (all green, whole
`tests/multi_user` 318 + new), `web` node suite 1260/1260, ruff / prettier /
tsc / eslint / i18n parity clean.

## What the lab proved (browser and API, real image each time)

- **Student** (`lab-student`): notice once; no Partners / MCP / CLI apps /
  Models / Network / Agents; every other surface; after the user granted a
  model, a real chat turn answered "4"; the memory page lists no
  `teacher.md`.
- **Teacher** (`lab-teacher`): 403 on a student until linked; through a
  hand-made link and then through a classroom, `GET /learners/{id}/evidence`
  200 with numbers only — the planted chat text is absent; `teacher.md`
  written by the real model, in **Thai** after the language fix; the
  Students tab, the roster with alerts, the student's page with the summary
  as cards; no tab and a bounce for a student or an ordinary user.
- **IT** (`standard`, the primary admin): classroom created with a home-room
  teacher; adding the student created 0 new links because a hand-made one
  existed (correct); CSV of four rows → 2 created, 1 skipped, 1 error, the
  credentials CSV downloaded, the new account logged in with its generated
  password and sits in the class with preset `student`.

Probe scripts live in this session's scratchpad (`uat_student_probe.py`,
`uat-student-page.cjs`, `uat-student-chat.cjs`, `uat_phase2_probe.py`,
`uat_phase2_summary.py`, `uat-classrooms-page.cjs`, `uat-teacher-page.cjs`);
they are throwaway and not committed.

## Found on the way

- **Guardian links required preset `learner`** (`guardians._require_ordinary_user`).
  The parent design says a teacher's link *is* the guardian record, so
  `GUARDABLE_PRESETS = {"learner", "student"}` — the one upstream line this
  work edits, and the "preset assumption" spot of this design, as
  CLAUDE.md asks to flag.
- **`teacher.md` came out in English on a Thai deployment**: `current_language()`
  in a teacher's request reads the *teacher's* `interface.json` (absent →
  `en`) while the nightly run reads the deployment's. Both now use
  `school_jobs.deployment_language()`; pinned by a test.
- **`get_llm_config()` is process-wide**, so a teacher's refresh and the
  nightly run both bill the deployment default model — which is what the
  design wanted ("IT pays"), stated in the docstrings.
- **Class defaults merge by profile**: grant llm items are one per profile
  with `model_ids`, and the users page finds a profile by its first item, so
  a naive append would have hidden the class's model behind the student's
  own; merged by profile, ids unioned.
- **A read-only SQLite open still creates `-wal` / `-shm`** for a WAL
  database; the "read-only" test ignores those two sidecars and nothing
  else.

## Steps A and B, the same day

After a look at what Khan Academy, Google Classroom, Canvas, Microsoft
Insights, IXL and Moodle put in front of a teacher (official docs only),
the user chose to grow the *shared evidence record* rather than either
page on its own:

| step | commits | what |
|---|---|---|
| **A — richer evidence** | `5d6f66d66` `415c44a99` | estimated minutes (message gaps, 10-minute cap), an eight-week trend, five positive spotlights beside the five alerts, class medians beside a student's own numbers (`?classroom_id=`). Teacher pages show all four. |
| **B — "My learning"** | `e490a927d` + 2 fixes → `926bb112d` | `GET /me/evidence` (own record, teacher's part withheld, not audited) rendered on the student's own dashboard; and the dashboards report's five open items closed as the user decided: Anima paced for a term (three days, not 75 s), the always-refused catalog request dropped (banner gone), `เส้นทางสู่ความเชี่ยวชาญ` → `เส้นทางฝึกฝน`, the Quiz mode says it does not count toward a Mastery Path; plus the preset chip now names student/teacher accounts. |

Lab: `uat-teacher-page.cjs` 18/18 on A (bars were transparent on the first
image -- Tailwind v3 cannot alpha an arbitrary `var()` colour -- fixed with
`color-mix` inline; two label keys collided with existing nav words),
`uat-my-learning.cjs` 14/14 on B (a policy-bound account was first asked
for its own evidence and refused; now not asked).

**Not exercised on the lab, unit-tested only:** the four spotlights other
than "back", the four alerts other than "inactive", class defaults landing
in a grant on join, archiving a classroom and saving teachers/defaults from
the page, the CSV *file* input (the paste path was used), a teacher with
several classrooms, the pet's three-day pacing (wall-clock; a pet that was
already sick under the demo tuning stays sick until a correct answer --
true on the host too, once deployed).

## Open, by design

- The branch is unmerged and has no PR; opening one runs CI on 3.11–3.14 —
  the user's call.
- No host round: the image would be a `deeptutor2` rebuild only (no studio,
  no gatekeeper change), but Phase 3 is the first thing a school would use,
  so it should go with a real pilot class, not before.
- Decision 9's class defaults cover models / knowledge bases / skills; a
  default *persona* needs a place in the grant that does not exist yet.
- Parents (a guardian who is not a teacher), assignments from the dashboard,
  export / print, Studio for students, lifelong export: parent design §7 and
  dashboard design §5, all deferred on purpose.

## Merged and live — 2026-10-02

The branch went up as **PR #122** and merged as `31c4599a1` after two fixes
CI asked for: the app-shell route budget raised to 435 KB for the 162 new
`en` keys (`8adebac79`), and the student policy made to let an unreadable
account store through unchecked rather than refuse on it (`6908d1a69`). A
claim made during review and withdrawn: the branch does **not** introduce a
500 on an unreadable `users.json` — upstream's `require_learning_surface`
already does that on `main`, and a test written to pin the fork's behaviour
is what showed it.

**Local UAT of the merged image, before the host round.** The question was
not whether the school work works — the lab had answered that — but whether
the four accounts that predate it still behave. They do:

* 24 API calls across `admin2`, `standard` (admins), `student` (preset
  learner) and `custom`: no 5xx anywhere. The learner is refused every new
  school route by its learning policy; `custom` reads its own evidence and
  gets an empty classroom list, correctly filtered to classrooms it teaches.
* The learner's dashboard has no "temporarily unavailable" banner and no
  "My learning"; `custom` has the section and its eight-week trend; both new
  admin pages and the third dashboard tab render in Thai.
* A learner typing `/dashboard/students` is sent to `/dashboard`, and
  `/admin/classrooms` to `/chat`.
* 15 page loads over three accounts — chat, settings, mastery, memory,
  questions, notebooks, anima, users — no crash, no 5xx.

Two non-blockers stand: the learner still draws two console-only 403s
(`mastery-paths/topics/index`, `settings`), and `/dashboard/students` tells
an admin who is in no classroom to "ask an admin to add you".

*Technique worth keeping:* none of this needed anyone's password. A JWT
minted inside the container with `create_token` and injected as the HttpOnly
`dt_token` cookie through Playwright's `addCookies` opens any account's own
view, which page JS cannot do and a login form would have required
credentials for.

**Host round `deploy-2026-10-02`** (= `d7a65c395`) went up the same day: a
`deeptutor2` rebuild only, no studio, gatekeeper, postgres, nginx or compose
change. Image `03ce974ec252` → `28599e6c9353`, 8/8 healthy, `RestartCount=0`,
~6 minutes of build and ~1 of downtime. The check that proves the new code is
live is the API, not a page: `/api/multi-user/school/classrooms` answers
**401** while an invented sibling route answers **404**, so the router is
mounted. A page cannot prove it — the middleware answers 307 for every path
under `/admin` and `/dashboard` whether or not it exists.

There are no school accounts on the host yet, so what changed for its users
is only the five dashboard leftovers: `เส้นทางฝึกฝน`, the shorter quiz hint,
the learner banner gone, "My learning" for accounts that are not
policy-bound, and the pet's three-day pacing — under which a pet already
sick stays sick until a correct answer.
