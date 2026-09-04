# REPORT — Dashboards, live-backend run (round 2)

- **Date:** 2026-09-04
- **Branch:** `feat/dashboards` (cut from `main` @ `4f8c7fcb`) — **not merged into `main`**
- **Base commit:** `5260e2df` docs(changes): record the dashboards folded into the Learner Anima menu
- **Predecessor:** `docs/reports/REPORT_dashboards_2026-09-04.md` (round 1 — build + gates)
- **Working handoff:** `docs/reports/REPORT_dashboards_handoff_2026-09-04.md`

---

## 1. Why this round existed

Round 1 shipped both dashboards and passed **every** gate — typecheck, eslint,
dependency-cruiser, i18n parity + audit, vitest 22/22 — and `/dashboard` still
rendered nothing at all for every non-admin account. The unified user dashboard
had never once been seen working.

The gates could not have caught it. The defect was React closure identity across
renders; the helper it lived in is a pure function whose unit tests pass on both
the broken and the fixed version.

**The rule this establishes for this feature: a green suite means nothing until
the page has been opened in a browser under each account preset.**

---

## 2. Environment

Both servers must run; the frontend alone shows a login page and nothing else.

```bash
# backend (repo root) — API on :8001
./.venv/Scripts/deeptutor.exe serve --port 8001

# frontend — Next dev on :3782 (the port data/user/settings/system.json declares)
npm --prefix web run dev -- -p 3782
```

A `.claude/launch.json` holding exactly that frontend command (config name
`web-dev`) exists locally so agent preview tooling can start it by name. It is
**not committed** — `.gitignore:19` excludes `.claude/*` — so the command above is
the durable record.

Settings that matter: `data/user/settings/auth.json` has `enabled: true`, so every
route redirects to `/login`; `data/user/settings/system.json` sets
`backend_port: 8001`, `frontend_port: 3782`.

### Accounts (`data/system/auth/users.json`)

| email | id | role | preset | policy |
|---|---|---|---|---|
| `admin@example.com` | `u_9a6487b4…` | admin | standard | — |
| `standard@example.com` | `u_ab700544…` | user | standard | none |
| `student@example.com` | `u_9bf7be9f…` | user | **learner** | chat + reading, 5 reading extensions, **0 assigned materials** |
| `custom@example.com` | `u_5d5b3e97…` | user | **custom** | chat + reading, 5 reading extensions — grant also assigns 1 model + 5 skills |

**The agent cannot log in** — entering a password into a form is off limits — so
every account switch was performed by the user on request. Plan accordingly: do
all reading and code work first, then ask for one login at a time.

Reading an account's real policy without a browser:

```bash
./.venv/Scripts/python.exe -c "from deeptutor.multi_user.learning_access import learning_policy_for_user; print(learning_policy_for_user('u_5d5b3e97abca43a4a1df231ec227f561'))"
```

The backend request log is the cheapest oracle in this workflow — it shows every
403 and every runaway poll. Tail it while the page loads.

---

## 3. Defects found and fixed

Six, all confirmed live, all fixed and re-verified in the browser. No backend
file and no upstream file was touched.

### 3.1 `/dashboard` never rendered, and hammered the API at ~67 req/s

`web/features/dashboard/useLearningPolicy.ts`

`useLearningPolicy()` returned a spread of `learningPolicyAccessFor(status)`
computed fresh on every render, so `allowsLearningSurface` was a new closure each
time. `UserDashboard`'s `load` is a `useCallback` that depends on it, and
`useEffect(..., [load])` therefore re-fired on its own result — `setStatus` /
`setData` always store new objects, so the loop never settled. `loading` stayed
`true`, the page stayed on `DashboardSkeleton`, and the fan-out re-ran forever.

Measured: **334 requests in 5 s** before, **0 in 8 s** after. Fixed by memoising
on the status object, one line, no change to the consumer:

```ts
const access = useMemo(() => learningPolicyAccessFor(status), [status]);
```

### 3.2 `/admin` could not scroll — 64% of the page unreachable

`web/components/admin/AdminDashboard.tsx`

`h-full overflow-y-auto` under a parent (`app/(admin)/layout.tsx`) that is
`min-h-screen` with no definite height: `h-full` collapses to content height, the
overflow never engages, and the global `body { overflow: hidden }` clips at the
viewport. Everything below *Account distribution* was unreachable by any means.

Proven in the DOM (`clientHeight === scrollHeight === 2989`, viewport 1069;
setting `height:100vh` made it scrollable) and fixed to `h-screen`, matching the
sibling `app/(admin)/admin/users/page.tsx:191` that had it right all along.

### 3.3 `/admin` was a dead end

`web/components/admin/AdminDashboard.tsx`

The `(admin)` route group renders no sidebar and the new page had no way back.
Added the same `← Back` → `/` link `admin/users` has always carried.

### 3.4 An admin could not reach Learner Anima at all

`web/components/admin/AdminDashboard.tsx`

`UserDashboard` redirects admins from `/dashboard` to `/admin`, and this branch
removed Anima's own sidebar slot — so for an administrator the companion had no
door left in the UI.

**User chose:** keep the redirect, add a *Learner Anima* card to the `/admin`
Quick actions grid pointing at `/dashboard/anima`. Reuses existing keys
`"Learner Anima"` + `"Anima tooltip"`, so no new i18n.

Rejected: removing the redirect (the user dashboard assumes a preset and a policy
admins do not have); making the sidebar entry role-aware (`nav-entries.ts` is a
static array — making it auth-aware costs more on every upstream sync).

### 3.5 Anima showed a fabricated empty pet to accounts it was denied

`web/components/dashboard/LearnerAnimaPanel.tsx`, `web/lib/pet-api.ts`

`GET /api/v1/pet/dashboard` answers **403** for any learning account
(`main.py:575` puts the pet router behind `require_learning_surface`, and
`_learning_surface_for_path()` has no mapping for `/api/v1/pet`, so it
default-denies). The panel caught that and set `offline` with the comment *"keep
the last-good view"* — but a learner has no last-good view, so it showed a
complete pet UI at 0% hunger / 0% happiness that reads as a **sick or broken pet**
rather than as *"you do not have access"*. It also re-polled the denial every
4 seconds, forever.

Added `PetRequestError` (carrying `status`) in `pet-api.ts`; the panel now tells a
403 apart from a hiccup, stops the interval, and returns a plain locked notice
before the pet UI and before the first-visit tour. Verified: **0 pet requests in
20 s** after, and the learner sees an honest message.

### 3.6 The learner dashboard reported numbers derived from denied requests

`web/components/dashboard/UserDashboard.tsx`, `web/lib/user-dashboard.ts`, locales

Four separate wrongs on `student@example.com`:

- **"Available modes: 1"** came from `/api/capabilities/registered` (403 → empty,
  then one injected entry) while the card's own caption said *"Set by your
  learning plan"* — and the plan says **2**, printed further down the same page.
  Now derived from `learning_policy.allowed_capabilities`, which the server
  actually enforces.
- **The mode chips** showed only *Immersive Reading*; chat was missing although
  the policy allows it and the sidebar offers it. Same fix.
- **The partial-data banner** said *"temporarily unavailable"* for a permanent
  policy denial. `safeLoad` now records `denied` separately via a
  `failureStatus()` helper reading both `ApiError.status` and the
  `HTTP <status>` message convention of `features/capabilities/api.ts` —
  deliberately *reading* that upstream file's error shape instead of editing it.
- **Eight English labels on a fully Thai page** in *Your learning plan*
  (Immersive Reading, Chat, Reading, Guided Learning, Vocabulary, Read Aloud,
  Translation, Quiz). `formatCapabilityLabel()` returns a **locale key**, not a
  finished label — now documented as such, with all five call sites passing it
  through `t()`.

### 3.7 A policy-bound non-learner got the wide dashboard

`web/components/dashboard/UserDashboard.tsx`

Reproduced live on `custom@example.com` with a learning policy assigned: the
**sidebar narrowed to 2 entries** (it reads `allowedSurfaces`), while the
**dashboard rendered the full non-learner layout** (it read `preset`). Seven API
groups 403'd on one page load — notebooks, books, skills, knowledge-bases,
partners, tools, capabilities.

Worst symptom: the panel titled *"Permissions assigned to you"* printed
**"Assigned skills: 0"** with a footnote telling the user to ask an administrator
for more — while the grant assigns **5 skills** (`docx, pdf, pptx, skill-creator,
xlsx`). The panel counted `/api/skills/list` (403) instead of the grant.

Fixed by choosing the layout the way the sidebar and the server already do:

```ts
const restricted = preset === "learner" || Boolean(status.learning_policy);
```

Used for both the data fan-out and the layout choice. `NextSteps` and
`ContinueCard` now take `restricted: boolean` instead of `preset: UserPreset`;
`preset` survives only where it still means the preset — the account badge.

Rejected: keeping the wide layout and rendering "—" instead of `0` on denied
cards. It still shows an account features it cannot reach, and still fires seven
denied requests per load.

---

## 4. Live verification of §3.7 — the round's outstanding item

§3.7 was applied at the very end of the previous session and its visual
confirmation was outstanding when the browser tooling disconnected. **It is now
verified.**

Account: `custom@example.com`, `preset: custom`, policy present and unchanged
(`allowed_surfaces: ["chat","reading"]`,
`allowed_capabilities: ["chat","immersive_reading"]`, 5 reading extensions,
`allow_upload: true`, `age_band: 9-12`, `locked_persona: teacher`) — confirmed
with the python one-liner in §2 **before** the login, since the handoff warned the
policy had been toggled during the previous session.

Observed on a clean load of `/dashboard`:

| Expectation | Result |
|---|---|
| *Assigned learning* + *Your learning plan* replace *Permissions assigned to you* + *Your library* | **yes** — both restricted panels render, neither wide panel appears |
| *"Assigned skills: 0"* and its "ask an administrator" footnote gone | **yes** — the panel is not rendered at all |
| *Available modes* agrees with the plan | **yes — 2**, matching *Learning modes: 2* lower on the same page |
| Mode chips show the whole policy | **yes** — *Chat* **and** *Immersive Reading* |
| Denial banner reads as permanent, not transient | **yes** — *"Some dashboard data is not open to this account…"* |
| Restricted copy on the header | **yes** — *"Continue your assigned learning and reading activities."* |
| The seven denied groups are no longer requested | **six of seven** — see §5.1 |

Remaining 403s in the trace, and where they come from:

- `/api/capabilities/registered` — **still requested**; see §5.1.
- `/api/courses`, `/api/mastery-paths/topics/index`, `/api/settings` — fired by the
  app shell and sidebar, **not** by the dashboard. Pre-existing, out of scope for
  this branch, and unchanged by it.

Gone entirely, as intended: notebooks, books, skills, knowledge-bases, partners,
tools.

(Requests appear twice in the trace — React StrictMode double-invocation in dev,
not a regression.)

---

## 5. Known residue

### 5.1 One guaranteed 403 per load remains, by construction

`fetchCapabilityCatalog()` sits in the dashboard's **base** fan-out, above the
`restricted` branch, so a policy-bound account still asks for a catalog the server
will always refuse. Its result is then discarded: the capability memo returns from
`learningPolicy.allowed_capabilities` before touching it. The rendered page is
already correct — this is one wasted request, not a wrong number.

Hoisting `restricted` above the base fan-out would remove it in one line, but it
has a **user-visible side effect**: with no failed group left, `unavailable` goes
empty and the amber *"not open to this account"* banner disappears for restricted
accounts entirely. That is arguably the more truthful end state — nothing on the
page is actually missing — but it is a product call, so it is **left for the user
to decide** rather than changed silently. Raised, not fixed.

### 5.2 `th` `"Reading"` is a shared key

Translating `"Reading": "Reading"` → `"การอ่าน"` also changes **ChatComposer**,
**CourseResources** and **ChatMessageList**. Flagged in the handoff and again
here: revert if the English term was deliberate the way `"Knowledge Base"` is.
(`zh` already had 阅读.)

### 5.3 Pre-existing, untouched

- `npm run test:node` has 5 Windows path-separator failures, confirmed identical
  on a pristine `main` checkout in round 1.
- `i18n:audit` reports 1 unlocalized literal per locale
  (`contextBudget.note.deferredTools`) — unrelated to this branch.
- `npm run typecheck` fails while `next dev` is running, with syntax errors inside
  the generated `.next/dev/types/routes.d.ts` (a torn concurrent write). Delete
  that file and re-run.

---

## 6. Gates

Re-run at close of round, with the dev server's generated types cleared first:

| Gate | Result |
|---|---|
| `npm run typecheck` | **pass** (clean) |
| `npx eslint` on the changed areas | **pass**, 0 errors |
| `npm run i18n:check` | **pass** — parity OK vs `en` for `th`, `zh`; audit unchanged at 1 pre-existing literal |
| `npm run test:unit` | **pass** — 10 files, 22/22 |

One extra locale change this round: the new `zh` denial string used 仪表**板**
while every neighbouring key uses 仪表**盘**; aligned, and its second clause
re-worded to match the sibling string it sits beside.

Edited `.tsx` / `.ts` files were scanned for control characters — clean. (The
previous round lost time to a `\b` written through a non-raw Python string
reaching a regex literal as a backspace; the scan is now routine.)

---

## 7. Open questions for the user — not decided here

- **A brand-new companion is born sick.** `deeptutor/pet/tuning.py` sets
  `initial_hunger = 70` against `sick_threshold = 75`, decaying `+1 / 15 s`, so a
  pet becomes sick **~75 seconds after creation**; happiness bleeds from birth
  because it starts above `hunger_unhappy = 60`. The only cure is `QUIZ_PASS` from
  a real mastery gate, so **any account without a Mastery Path has a permanently
  sick pet from its first visit** — `admin@example.com`'s stored pet is already at
  `hunger 100 / happy 0`. The code calls this a demo tuning (`"demo: hungry"`);
  for a product aimed at children it is a product decision, not a bug. Changing it
  is a few constants.
- **Anima should probably never get its own assignable surface.** Recommendation
  given and accepted: **do not**. Anima is fed exclusively by mastery gates, and
  `/api/mastery-paths/*` is itself default-denied for every learning account — so
  granting the pet API alone ships a companion stuck at 0 forever. Correct order:
  make mastery assignable first; then map `/api/v1/pet` to whatever surface
  mastery lands on — one line — and Anima follows for free.
- **The §5.1 banner trade-off**, above.
- **`/admin/users` "Back" goes to `/`, not to `/admin`.** Small, untouched.
- **Nav position.** Dashboard still sits where Learner Anima sat, after Immersive
  Reading. Promoting it is a one-line move in `nav-entries.ts`.

---

## 8. Facts worth carrying forward

- **Role changes do not take effect until the user logs in again.**
  `auth_status()` reads `role` / `is_admin` from the **JWT payload**, while
  `preset` comes from the live user record. With `token_expire_hours: 24`,
  **revoking an admin can take up to 24 hours** unless that person signs out.
  `set_role()` touches only the `role` field, so a grant — and its policy —
  survives a promote/demote round trip intact. Established from source, **never
  exercised live**; a live check needs permission first, since it mutates a real
  account.
- **A learning policy is not tied to the `learner` preset.**
  `learning_policy_for_user()` returns whatever the grant holds for any non-admin;
  the preset is only a fallback when the grant carries no policy. A `custom` or
  `standard` account can therefore behave exactly like a learner — which is what
  §3.7 is about.
- **Pets are per-user, despite appearances.** `petId: "anima_001"` is a constant
  default field, not a shared identity; state lives at
  `data/users/<user_id>/user/pet_state.json`, one file per account.
- **A fuller-looking screen is not a healthier one.** Anima looked *complete* for
  the learner only because every fetch failed and the placeholder grid rendered;
  it looks *emptier* for a working account with no mastery paths because the real
  empty state is honest. Do not "fix" that back.
- **Writing regexes into `.tsx` via a Python heredoc silently corrupts them.**
  `\b` in a normal Python string is a literal backspace. Use raw strings, and scan
  edited files for control characters afterwards.

---

## 9. Branch policy

`feat/dashboards` is **not** merged into `main` and must not be until the user
says so.
