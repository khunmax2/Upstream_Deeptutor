# HANDOFF — Dashboards live-run round 2 (`feat/dashboards`)

- **Date:** 2026-09-04
- **Branch:** `feat/dashboards`, cut from `main` @ `4f8c7fcb` — **not merged, must not be until the user says so**
- **Base commit:** `5260e2df` docs(changes): record the dashboards folded into the Learner Anima menu
- **Working tree:** **9 files changed, +238 / −51, all uncommitted**
- **Predecessor:** `docs/reports/REPORT_dashboards_2026-09-04.md` (round 1 — build + gates, closed with *"No live-backend run"*)

This round **is** that live-backend run. Everything below was observed against a
real server with real logins, not reasoned from source.

---

## 1. Read this first

Round 1 shipped the two dashboards and passed every gate — typecheck, eslint,
dependency-cruiser, i18n, vitest — and was still **broken on the main page for
every non-admin account**. The unified user dashboard never rendered once. The
gates could not see it: the defect was a React closure identity across renders,
and the helper it lived in is a pure function whose unit tests all pass.

The lesson for whoever picks this up: **on this feature, a green suite means
nothing until the page has been opened in a browser under each account preset.**

---

## 2. Environment — how to get back to a running system

Both servers must be up; the frontend alone shows a login page and nothing else.

```bash
# backend (repo root) — API on :8001
./.venv/Scripts/deeptutor.exe serve --port 8001

# frontend — Next dev on :3782 (the port data/user/settings/system.json declares)
npm --prefix web run dev -- -p 3782
```

`.claude/launch.json` was added this round with exactly that frontend command, so
an agent with browser/preview tooling can start it by name (`web-dev`).

Settings that matter: `data/user/settings/auth.json` has `enabled: true`, so
every route redirects to `/login`; `data/user/settings/system.json` sets
`backend_port: 8001`, `frontend_port: 3782`.

### Accounts (`data/system/auth/users.json`)

| email | role | preset | notes |
|---|---|---|---|
| `admin@example.com` | admin | standard | the only account that reaches `/admin` |
| `standard@example.com` | user | standard | no learning policy |
| `student@example.com` | user | **learner** | policy: chat + reading, 5 reading extensions, **0 assigned materials** |
| `custom@example.com` | user | **custom** | grant assigns **1 model + 5 skills**; policy was toggled on and off by the user during this session — **check its current state before testing** |

**The agent cannot log in.** Entering passwords into a form is off limits, so
every account switch in this round was done by the user on request. Plan for
that: do all the reading and code work first, then ask for one login at a time.

Check an account's real policy without the browser:

```bash
./.venv/Scripts/python.exe -c "
from deeptutor.multi_user.learning_access import learning_policy_for_user
print(learning_policy_for_user('u_5d5b3e97abca43a4a1df231ec227f561'))"
```

Backend request log is the cheapest oracle in this whole workflow — it shows
every 403 and every runaway poll. Tail it while the page loads.

---

## 3. What was found and fixed this round

Six defects, all confirmed live, all fixed and re-verified in the browser except
where noted. No backend file and no upstream file was touched.

### 3.1 `/dashboard` never rendered, and hammered the API at ~67 req/s — `useLearningPolicy.ts`

The headline bug. Every non-admin account got a blank page forever.

`useLearningPolicy()` returned `{...learningPolicyAccessFor(status)}` computed
fresh on every render, so `allowsLearningSurface` was a new closure each time.
`UserDashboard`'s `load` is a `useCallback` that depends on it, and
`useEffect(..., [load])` therefore re-fired on its own result — `setStatus`/`setData`
always store new objects, so the loop never settled. `loading` stayed `true`, the
page stayed on `DashboardSkeleton`, and the fan-out re-ran forever.

Measured: **334 requests in 5 s** before, **0 in 8 s** after.

Fixed by memoising on the status object — one line, no change to the consumer:

```ts
const access = useMemo(() => learningPolicyAccessFor(status), [status]);
```

### 3.2 `/admin` could not scroll — 64% of the page unreachable — `AdminDashboard.tsx`

`h-full overflow-y-auto` under a parent (`app/(admin)/layout.tsx`) that is
`min-h-screen` with no definite height: `h-full` collapses to content height, the
overflow never engages, and the global `body { overflow: hidden }` clips at the
viewport. Everything below *Account distribution* was unreachable by any means.

Proven in the DOM (`clientHeight === scrollHeight === 2989`, viewport 1069;
setting `height:100vh` made it scrollable) and fixed to `h-screen`, matching the
sibling `app/(admin)/admin/users/page.tsx:191` that had it right all along.

### 3.3 `/admin` was a dead end — `AdminDashboard.tsx`

The `(admin)` route group renders no sidebar and the new page had no way back.
Added the same `← Back` → `/` link `admin/users` has always carried.

### 3.4 An admin could not reach Learner Anima at all — `AdminDashboard.tsx`

`UserDashboard.tsx` redirects admins from `/dashboard` to `/admin`, and this
branch removed Anima's own sidebar slot — so for an administrator the companion
had no door left in the UI. **The user chose option ค:** keep the redirect, add a
*Learner Anima* card to the `/admin` Quick actions grid pointing at
`/dashboard/anima`. Reuses existing keys `"Learner Anima"` + `"Anima tooltip"`,
so no new i18n. Rejected: removing the redirect (the user dashboard assumes a
preset and a policy that admins do not have), and making the sidebar entry
role-aware (`nav-entries.ts` is a static array; making it auth-aware costs more
on every upstream sync).

### 3.5 Anima showed a fabricated empty pet to accounts it was denied — `LearnerAnimaPanel.tsx`, `pet-api.ts`

`GET /api/v1/pet/dashboard` answers **403** for any learning account
(`main.py:575` puts the pet router behind `require_learning_surface`, and
`_learning_surface_for_path()` has no mapping for `/api/v1/pet`, so it
default-denies). The panel caught that and set `offline`, with the comment
*"keep the last-good view"* — but a learner has no last-good view, so it showed a
complete pet UI at 0% hunger / 0% happiness that read as a sick or broken pet
rather than as *"you do not have access"*. It also re-polled the denial **every
4 seconds, forever**.

Added `PetRequestError` (carries `status`) in `pet-api.ts`; the panel now tells a
403 apart from a hiccup, stops the interval, and returns a plain locked notice
before the pet UI and before the first-visit tour. Verified: **0 pet requests in
20 s** after, and the learner sees an honest message.

### 3.6 The learner dashboard reported numbers derived from denied requests — `UserDashboard.tsx`, `user-dashboard.ts`, locales

Four separate wrongs on `student@example.com`, all fixed:

- **"Available modes: 1"** came from `/api/capabilities/registered` (403 → `[]`,
  then one injected entry) while the card's own caption said *"Set by your
  learning plan"* — and the plan says **2**, printed further down the same page.
  Now derived from `learning_policy.allowed_capabilities` when a policy exists,
  which is what the server actually enforces.
- **The mode chips** showed only *Immersive Reading*; chat was missing although
  the policy allows it and the sidebar offers it. Same fix.
- **The partial-data banner** said *"temporarily unavailable"* for a permanent
  policy denial. `safeLoad` now records `denied` separately, via a
  `failureStatus()` helper that reads both `ApiError.status` and the
  `new Error(\`HTTP ${status}\`)` convention used by
  `features/capabilities/api.ts` — deliberately *reading* that upstream file's
  error shape instead of editing it.
- **Eight English labels on a fully Thai page** in *Your learning plan*
  (Immersive Reading, Chat, Reading, Guided Learning, Vocabulary, Read Aloud,
  Translation, Quiz). `formatCapabilityLabel()` returns a **locale key**, not a
  finished label — it is now documented as such and every one of its five call
  sites passes it through `t()`.

Locale work: 4 new keys in all three locales, plus `th`'s pre-existing
`"Reading": "Reading"` translated to `"การอ่าน"` (`zh` already had 阅读). That
last one is a **shared key with 3 other call sites** (ChatComposer,
CourseResources, ChatMessageList) — flagged to the user, revert if the English
term was deliberate the way `"Knowledge Base"` is.

### 3.7 A policy-bound non-learner got the wide dashboard — `UserDashboard.tsx` — **NOT yet verified in the browser**

The last fix of the round, and the only one whose visual confirmation is
outstanding, because the browser tooling disconnected right after it was applied.

Reproduced live on `custom@example.com` with a learner policy assigned: the
**sidebar narrowed to 2 entries** (it reads `allowedSurfaces`), while the
**dashboard rendered the full non-learner layout** (it read `preset`). Seven API
groups 403'd on one page load — notebooks, books, skills, knowledge-bases,
partners, tools, capabilities.

Worst symptom: the panel titled *"Permissions assigned to you"* printed
**"Assigned skills: 0"** with a footnote telling the user to ask an
administrator for more — while the grant assigns **5 skills**
(`docx, pdf, pptx, skill-creator, xlsx`). The panel counts `/api/skills/list`
(403) instead of the grant.

Fixed by choosing the layout the way the sidebar and the server already do:

```ts
const restricted = preset === "learner" || Boolean(status.learning_policy);
```

Used for both the data fan-out (the denied groups are no longer requested at
all) and the layout choice. `NextSteps` and `ContinueCard` now take
`restricted: boolean` instead of `preset: UserPreset`; `preset` survives only
where it still means the preset — the account badge.

Rejected alternative: keep the wide layout and render "—" instead of `0` on
denied cards. It still shows an account features it cannot reach, and still
fires seven denied requests per load.

---

## 4. Do this next

1. **Verify §3.7 in the browser.** Log in as `custom@example.com` **with a
   learning policy assigned** (confirm with the python one-liner in §2 — the
   user removed and re-added it during this session) and load `/dashboard`.
   Expect: *Assigned learning* + *Your learning plan* panels replacing
   *Permissions assigned to you* + *Your library*, and the seven 403s gone from
   the backend log. This is the only unverified change in the working tree.
2. **Close out the round** per `CLAUDE.md` §1 — none of it is done:
   - `CHANGES.md` entry under the dashboards section,
   - a `docs/reports/REPORT_*.md` for round 2,
   - `graphify update .`,
   - commit. Suggested split: one commit for the two `/admin` layout fixes, one
     for the render loop, one for the policy-vs-preset truthfulness work
     (§3.5–3.7), one for docs.
3. Re-run the gates before committing: `npm run typecheck`, `npx eslint`,
   `npm run i18n:check`, `npm run test:unit`. All four pass as of this handoff.

---

## 5. Open questions for the user — do not decide these alone

- **A brand-new companion is born sick.** `deeptutor/pet/tuning.py` sets
  `initial_hunger = 70` against `sick_threshold = 75`, decaying `+1 / 15 s`, so a
  pet becomes sick **~75 seconds after creation**; happiness bleeds from birth
  because it starts above `hunger_unhappy = 60`. The only cure is `QUIZ_PASS`
  from a real mastery gate, so **any account without a Mastery Path has a
  permanently sick pet from its first visit** — `admin@example.com`'s stored pet
  is already at `hunger 100 / happy 0`. The code calls this a demo tuning
  (`"demo: hungry"`); for a product aimed at children it is a product decision,
  not a bug. Changing it is a few constants.
- **Anima should probably never get its own assignable surface.** The user asked
  about letting an admin grant it. Recommendation given and accepted: **do not**.
  Anima is fed exclusively by mastery gates, and `/api/mastery-paths/*` is itself
  default-denied for every learning account — so granting the pet API alone would
  ship a companion stuck at 0 forever. The correct order is: make mastery
  assignable first; then map `/api/v1/pet` to whatever surface mastery lands on —
  one line — and Anima follows for free.
- **`/admin/users` "Back" goes to `/`, not to `/admin`.** Small, untouched.
- **Nav position.** Dashboard still sits where Learner Anima sat, after Immersive
  Reading. Promoting it is a one-line move in `nav-entries.ts`.

---

## 6. Facts worth carrying forward

- **Role changes do not take effect until the user logs in again.**
  `auth_status()` reads `role` / `is_admin` from the **JWT payload**, while
  `preset` comes from the live user record. With `token_expire_hours: 24`,
  **revoking an admin can take up to 24 hours** unless that person signs out.
  Promotion is equally inert in the other direction. `set_role()` touches only
  the `role` field, so a grant — and its policy — survives a promote/demote round
  trip intact. **This was established from source and never exercised live**; a
  live check needs permission first, since it mutates a real account.
- **A learning policy is not tied to the `learner` preset.**
  `learning_policy_for_user()` returns whatever the grant holds for any non-admin;
  the preset is only a fallback when the grant carries no policy. So a `custom`
  or `standard` account can be made to behave exactly like a learner — which is
  precisely what §3.7 is about.
- **Pets are per-user, despite appearances.** `petId: "anima_001"` is a constant
  default field, not a shared identity; state lives at
  `data/users/<user_id>/user/pet_state.json`, one file per account. Checked, so
  nobody has to check it twice.
- **A fuller-looking screen is not a healthier one.** Anima looked *complete* for
  the learner only because every fetch failed and the placeholder grid rendered;
  it looks *emptier* for a working account with no mastery paths because the real
  empty state is honest. Do not "fix" that back.
- **`npm run typecheck` fails while `next dev` is running**, with 6 syntax errors
  inside `.next/dev/types/routes.d.ts` — a torn concurrent write of a generated
  file, not your code. Delete it and re-run.
- **`npm run test:node` has 5 pre-existing Windows path-separator failures** on a
  pristine `main` checkout. Not introduced here (round 1 confirmed this).
- **Writing regexes into `.tsx` via a Python heredoc will silently corrupt them.**
  `\b` in a normal Python string is a literal backspace, so `/\bHTTP (\d{3})\b/`
  reached the file as two control characters and never matched — costing a
  debugging detour this round. Use raw strings, and scan edited files for
  `[\x00-\x08\x0b\x0c\x0e-\x1f]` afterwards.

---

## 7. Branch policy

`feat/dashboards` is **not** merged into `main` and must not be until the user
says so.
