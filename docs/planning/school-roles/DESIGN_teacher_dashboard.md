# Teacher dashboard and classrooms — design (school roles, Phase 3)

Drafted 2026-09-20 on `feat/school-phase1`, after Phase 1 (accounts) and
Phase 2 (evidence) were built and tested on the lab stack. The parent
design is `DESIGN_teacher_student_it.md`; this document is what its Phase 3
sentence — "the page, per-class aggregation, classroom as a group with a
home-room teacher, CSV import" — means in detail. The decisions marked
**(proposed)** are for the user to confirm or change before the code is
written; everything else follows from the parent design.

## What exists now, and what the pilot still lacks

After Phase 2 a teacher can, through the API only:

- list the students linked to them (`GET /api/multi-user/me/guardianships`);
- read one student's evidence record (`GET /learners/{id}/evidence`):
  Mastery Path, Question Bank, reading, activity counts, intake profile and
  `teacher.md`;
- ask for a fresh `teacher.md` (`POST /learners/{id}/summary`).

An admin links a teacher to a student one at a time on the users page, and
grants each student a model one at a time. For three classes that is three
hundred clicks before the first lesson, and a teacher has no page to open.
Phase 3 closes that gap in three pieces:

| piece | who uses it | what it adds |
|---|---|---|
| **3a — classrooms and CSV import** | IT | a classroom record; bulk account creation; membership that *derives* the guardian links and the model grant |
| **3b — the teacher's page** | teachers | the roster with one line per student, a student's detail, `teacher.md`, plain-rule alerts |
| **3c — class view** | teachers, IT | per-class numbers and the same alerts rolled up; the admin's switch for the nightly summary |

3a comes first because 3b is useless without students to show.

## 1. Classroom (3a)

### 1.1 The record

`data/system/school/classrooms.json` — a fork-only store beside
`guardians.json`, same shape of code (`multi_user/classrooms.py`, a list of
records, a write lock, atomic writes):

```json
{
  "id": "cls_<hex>",
  "name": "ม.4/1",
  "term": "2569/1",
  "home_room_teacher_id": "u_…",
  "teacher_ids": ["u_…"],
  "student_ids": ["u_…", "u_…"],
  "defaults": { "grant": { "models": { "llm": [ … ] }, "knowledge_bases": [ … ] } },
  "created_at": "…", "archived_at": null
}
```

- `home_room_teacher_id` is one of `teacher_ids`; it names who answers for
  the class. It carries no extra permission in the pilot.
- `teacher_ids` are accounts with preset `teacher`; `student_ids` are
  accounts with preset `student`. Both are validated on every write, the
  way `guardians._require_ordinary_user` validates presets.
- `defaults.grant` is decision 9 of the parent design, scoped to the
  classroom: the grant fragment applied to a student **when they join**
  (models, knowledge bases, skills, persona). It is a starting point, not a
  lock — the student's grant can be edited afterwards on the users page as
  today, and leaving the class does not take it away. **(proposed)**

### 1.2 Membership derives the guardian links

The guardian record stays the *only* authorization path — the evidence
routes of Phase 2 check `guardian_can_access` and nothing else. A classroom
is a bulk editor of those records:

- adding a teacher to a class, or a student to a class, creates the missing
  guardian links (`view_reports`, `assign_materials`) between every teacher
  of the class and every student of it, with `granted_via: "cls_<id>"` on
  the record;
- removing one revokes the links that were granted *via this class* and no
  other class still justifies; a link an admin made by hand on the users
  page (`granted_via` absent) is never touched;
- archiving a class revokes its derived links the same way.

This keeps the users page, the guardian audit lines and the Phase 2 routes
exactly as they are. `granted_via` is one optional field on the guardian
record — a fork addition, defaulting to absent, ignored by upstream code.

### 1.3 CSV import

`POST /api/multi-user/school/import` (admin only, multipart) takes a CSV:

```
username,password,classroom
somchai.k,,ม.4/1
naree.p,Temp-1234!,ม.4/1
```

- `username` follows `RegisterRequest`'s rule (3–64 of `A-Za-z0-9_-.`);
  `password` may be empty, in which case one is generated (12 characters,
  letters and digits) and returned **once**, in the response, as a CSV the
  admin downloads; it is never written to the audit log or the server log;
- `classroom` is a name; an unknown name is an error for that row unless
  `create_classrooms=true`;
- every account is created with preset `student` through the same code as
  `POST /api/auth/users` (no second creation path), then added to the
  classroom, which applies the class defaults and derives the links;
- the import is idempotent per row: an existing username is reported as
  `skipped`, not an error, so a file can be re-run after fixing one line;
- the response is a report: `created`, `skipped`, `errors` with line
  numbers, and the credentials CSV for the created rows. One audit line,
  `school_import`, with counts and the classroom name — no usernames.

Teachers are not imported; there are few and IT creates them by hand.

### 1.4 Routes and UI (admin)

```
GET    /api/multi-user/school/classrooms                admin: all; teacher: theirs
POST   /api/multi-user/school/classrooms                admin
PUT    /api/multi-user/school/classrooms/{id}           admin: name, term, home-room teacher, defaults
DELETE /api/multi-user/school/classrooms/{id}           admin: archive (never hard-delete)
PUT    /api/multi-user/school/classrooms/{id}/teachers  admin: the full list
PUT    /api/multi-user/school/classrooms/{id}/students  admin: the full list
POST   /api/multi-user/school/import                    admin
```

Audit: `classroom_create`, `classroom_update`, `classroom_archive`,
`classroom_members_update` (counts, not names), `school_import`.

UI: a new admin page `/admin/classrooms` beside `/admin/users`: the list of
classes, a class editor (name, term, teachers with the home-room star,
students as a two-column picker over `student` accounts, defaults as a cut
of the existing `GrantEditor`), an "Import CSV" dialog that shows the
report and offers the credentials download. The users page gets one column
"Class". Strings in en, th, zh.

## 2. The teacher's page (3b)

### 2.1 Where

`/dashboard/students`, a third tab of the existing Dashboard beside the
account's own overview and Learner Anima — `DashboardTabs` already carries
the pattern, and the Dashboard entry is "unrestricted" in the sidebar, so
no navigation code changes. The tab appears for preset `teacher` and for
admins; anyone else who types the URL gets the existing dashboard. Admins
see every class; a teacher sees the classes they are in. **(proposed;
the alternative is a sidebar entry "My students", which needs a
teacher-only filter beside the student one and a new top-level route)**

### 2.2 The roster

One table per class (a class selector when the teacher has several), one
row per student, sortable, from one call:

```
GET /api/multi-user/school/classrooms/{id}/roster
```

which returns, per student, a **summary row** — a fixed subset of the
evidence record, computed server-side by `learning_evidence.summary_row()`
so the page never needs the full record for forty students:

| column | source |
|---|---|
| student | username |
| last active | `activity.last_active_at` |
| active days (30 d) | `activity.active_days_30` |
| questions (30 d) | `question_bank.recent` total and correct → accuracy |
| unresolved wrong | `question_bank.unresolved` |
| mastery | sum of `counts.mastered` / `counts.total` over paths |
| reviews due | sum of `due_reviews` |
| reading | materials started / finished |
| summary | whether `teacher.md` exists and its date |
| alerts | §2.4 |

One audit line per roster read, `classroom_roster_view`, with the class id
and the number of students — not one line per student, which would make
the audit unreadable at forty rows and say nothing a parent would ask.

### 2.3 The student

Clicking a row opens the student's detail, rendered from the existing
`GET /learners/{id}/evidence` (audited per student, as today, because this
is the read a parent would ask about):

1. **Summary** — `teacher.md` as four cards (Strengths / Working on /
   Learning style / Suggested next steps), its date, and a "Refresh"
   button that calls `POST /learners/{id}/summary`. When there is none: one
   sentence saying the student has no consolidated memory yet.
2. **Mastery paths** — one card per path: name, progress bar
   (mastered/total), reviews due, then the modules with their knowledge
   points and status chips (mastered / learning / new).
3. **Questions** — accuracy overall and last 30 days, by source (Deep
   Question, Mastery Path, reading quizzes), by material, by category with
   wrong counts — the categories are the "topics asked about" of decision 6.
4. **Reading** — per material: title, progress bar, finished, last read,
   annotation and bookmark counts.
5. **Activity** — sessions, active days 7/30, turns 30, by capability.
6. **Profile** — the intake fields (prior knowledge, target level, time
   budget) per goal, and the account profile if IT set one.

Nothing else. No link into the student's chat, Memory, knowledge bases or
Co-Writer exists on this page, and the page does not fetch from any route
outside `/api/multi-user/`.

### 2.4 Alerts (plain rules, no model)

Computed in `summary_row()`, shown as chips on the roster and as a line at
the top of the detail. Thresholds are constants in one fork module
(`multi_user/school_alerts.py`) so the pilot can tune them:

| alert | rule (proposed defaults) |
|---|---|
| **inactive** | no user turn in 7 days (or never) |
| **struggling** | ≥ 10 questions in 30 days and accuracy < 50 % |
| **backlog** | ≥ 10 unresolved wrong answers |
| **reviews due** | ≥ 5 Mastery Path reviews due |
| **reading stalled** | a material started (> 0 %, not finished) and not opened in 14 days |

An alert is a nudge to look, never a grade: the roster sorts by the number
of alerts, and nothing is sent anywhere.

## 3. The class view (3c)

On the same tab, above the roster: the class in numbers, from the same
roster call so it costs nothing extra —

- students, active this week, active this month;
- median accuracy (30 d) and the count of students under 50 %;
- reviews due in total; materials finished in total;
- the alert counts (how many inactive, struggling, …);
- the three most common wrong-answer categories across the class, from
  `question_bank.categories` (counts summed, names as the students' own
  categories — a pilot finding will be whether students categorise at all).

For IT, the admin page gets the nightly summary switch
(`summaries_enabled`, `summaries_hour`) and a "Run now" button with the
last report — the routes exist since Phase 2.

## 4. Privacy and audit, restated for this page

- A teacher reaches a student only through a classroom or a hand-made
  guardian link; the page shows nothing the evidence route would refuse.
- Roster reads are audited per class, student detail reads per student,
  summary refreshes per student; imports and class edits by the admin.
- No export, no print view, no sharing in the pilot. **(proposed)**
- `teacher.md` stays in the deployment's language; column headings and
  chips are translated by the page.

## 5. Not in Phase 3

- Parents (a guardian who is not a teacher) — the guardian record supports
  it today; a parent page would be this page with one student.
- Assignments from the dashboard (materials, courses) — `assign_materials`
  exists on the guardian record; the button can come once the page is in
  use.
- Studio for students (decision 10). Lifelong export (parent §7).
- Per-teacher model catalogs or costs.

## 6. Decisions to confirm

| # | Question | Proposed |
|---|---|---|
| 1 | Where does the teacher's page live? | A third Dashboard tab, `/dashboard/students`, for preset `teacher` and admins. |
| 2 | Does a classroom hold class defaults (decision 9)? | Yes: a grant fragment applied on join, editable per student afterwards, not removed on leave. |
| 3 | Membership derives guardian links? | Yes, with `granted_via` on the record; hand-made links are never touched. |
| 4 | CSV columns? | `username,password,classroom`; empty password → generated, returned once as a downloadable CSV. |
| 5 | Alert thresholds? | Inactive 7 d; struggling < 50 % on ≥ 10 questions/30 d; backlog ≥ 10; reviews ≥ 5; reading stalled 14 d. |
| 6 | Audit granularity? | Roster per class; detail and refresh per student. |
| 7 | Export / print? | Not in the pilot. |
| 8 | Order of work? | 3a (classrooms + import + admin page) → 3b (roster, detail, alerts) → 3c (class numbers, IT switch). Each step: pytest + node tests, lab UAT on the real image, one commit on `feat/school-phase1`. |
