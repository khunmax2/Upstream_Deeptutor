# REPORT — Dashboards (admin + unified user), round 1

- **Date:** 2026-09-04
- **Branch:** `feat/dashboards` (cut from `main` @ `4f8c7fcb`; **not merged**)
- **Commit:** `8e35d865` feat(web): fold the dashboards into the Learner Anima menu
- **Status:** built and gated; **not yet exercised against a live backend**

---

## 1. What was asked

Build the two dashboards described in `D:\Vscode\DeepTutor\DASHBOARD_HANDOFF.md`
— an admin dashboard and a unified user dashboard — on an experimental branch,
and fold them into the fork's existing **Learner Anima** menu: rename that entry
to *Dashboard*, put Learner Anima inside it, keep the two as separate pages, and
disturb as few upstream files as possible.

## 2. What was actually there

The reference work already existed in the sibling `DeepTutor` workspace but was
**entirely uncommitted** — ~2,900 lines of dashboard code plus unrelated
multi-user policy work, all dirty on `main`, unprotected. That repo's own
convention is *never commit to `main`*.

First action there was therefore to branch (`feat/dashboard-admin-user`) and
commit the work in five grouped commits, leaving `main` untouched at `93df3d48`.
That workspace is a **reference only**; no further work is planned in it.

The two repositories had diverged:

| | `DeepTutor` (reference) | `Upstream_Deeptutor` (this fork) |
|---|---|---|
| Dashboards | present | absent |
| Learner Anima | absent | present (`/anima`, pet feature) |
| Multi-user (presets, learning policy, guardians) | present | present |

Learner Anima exists only here, and "don't disturb upstream files" is this
fork's policy — so this fork is where the real build belongs. Confirmed with the
user before porting.

## 3. Shape of the result

The sidebar gains **no** net entry. The fork-only Learner Anima slot is renamed
*Dashboard* and holds two pages:

```
/dashboard         unified user dashboard   (components/dashboard/UserDashboard)
/dashboard/anima   learning companion       (components/dashboard/LearnerAnimaPanel)
/admin             admin dashboard          (components/admin/AdminDashboard)
```

A shared `app/(utility)/dashboard/layout.tsx` renders the tab strip once, so
switching pages does not remount it. The tabs are real links with
`aria-current`, not an ARIA tablist, because these are real navigations.

Admin dashboard answers what an operator must act on: provisioning health,
per-account readiness, accounts needing attention, assignments in use, and the
assignable resource inventory. Per-user grants load through `Promise.allSettled`
so one failed grant cannot take down the page.

User dashboard widens or narrows by preset and learning policy: momentum over
the last 7 days, rule-based next steps, continue-where-you-left-off, available
modes from the capability registry, and an access / assigned-learning panel. A
learner never calls the API groups its policy forbids; `safeLoad` degrades a
failed group to partial data instead of an empty page.

No metric is simulated — every number comes from an API or persisted state that
already existed. Business rules stay in the pure helpers in
`web/lib/{admin,user}-dashboard.ts`.

## 4. Keeping it mergeable (fork policy §3)

12 of the 18 files are **new**. Learner Anima moved by `git mv` (page → panel
component) so its history follows the file.

Only six existing files change:

| File | Why |
|---|---|
| `web/components/sidebar/nav-entries.ts` | the renamed entry (fork-only line) |
| `web/components/voice/VoiceCallWidget.tsx` | declares `/dashboard`; excludes `/admin` as an operator surface |
| `web/tests/voice-manifest-parity.test.ts` | resolves a declared path at any depth — Anima is no longer top-level |
| `web/components/pet/AnimaTour.tsx`, `web/lib/pet-api.ts` | doc comments naming the old route |
| `web/locales/{en,th,zh}/app.json` | new strings |

Two deliberate avoidances of upstream churn:

- **`CapabilityAccessContext` was not widened.** The reference version added
  `policyResolved` / `allowsLearningSurface` to that shared context. Here the
  same view is derived from auth status in a new `features/dashboard/
  useLearningPolicy.ts`, leaving the upstream file untouched. Its pure core is
  exported separately so the rules stay testable without React.
- **`lib/auth.ts` was not changed.** The reference added a `{ force: true }`
  option to `fetchAuthStatus`; the fork already exports
  `invalidateAuthStatusCache()`, which the dashboard calls instead for the same
  effect.

## 5. i18n

139 keys added to **en**, **th** and **zh**:

- 107 user/dashboard strings ported from the reference (`en`, `zh`), Thai authored here;
- 32 admin strings authored in all three — the reference implementation has no
  locale entries for these and renders them as raw English keys.

`Chat tooltip` from the reference was dropped: it belongs to that repo's
`/chat` relabel, which this fork does not adopt.

After the merge, `i18n:audit` reports exactly one t() literal with no locale
entry — `contextBudget.note.deferredTools`, pre-existing and unrelated.

## 6. Verification

| Gate | Result |
|---|---|
| `npm run typecheck` | pass |
| `npx eslint app components lib features tests` | **0 errors**, 74 warnings (all pre-existing style warnings) |
| `npm run architecture:check` (dependency-cruiser) | pass — no violations |
| `npm run i18n:check` (parity + audit) | pass |
| `npm run test:unit` (vitest) | **22/22 pass** |
| `npm run test:node` | 5 failures — see below |

The 5 node-test failures were **confirmed identical on a pristine `main`
checkout** (`git checkout main` → same run): the known Windows path-separator
contract failures in `architecture-contracts` and `internal-route-contract`,
which flag untouched upstream files (`app\(auth)\login\page.tsx`, `partners`,
`ThemeScript.tsx`). **No new failure is introduced by this work.**

Both voice-manifest parity tests did fail initially and were genuinely caused by
this change; both now pass.

## 7. Not done yet

- **No live-backend run.** Nothing here has been rendered against a real server.
  The pages must still be opened while logged in as Standard, Custom, a Learner
  with no material, a Learner with material and reading extensions, and under
  Reading-only / Chat-only policies. Do not add dev-only impersonation or a
  role-bypass query parameter to shortcut this — use real accounts or component
  tests that mock the API boundary.
- **Nav position.** Dashboard sits where Learner Anima sat (after Immersive
  Reading), not first in the sidebar. Reusing the slot in place was the
  lowest-churn reading of the request; promoting it is a one-line move in
  `nav-entries.ts`.
- **Backend untouched.** The reference branch also carries a learner-surface
  policy fix and a capability-catalog filter (`DeepTutor` commit `c57718b5`).
  Those are backend changes and were **not** ported; if learner accounts here hit
  403s on Chat/Reading bootstrap, that is the fix to evaluate next.
- **Known data limits** (inherited, documented in the reference handoff): no
  cross-user learning analytics, no last-login data, no learning-duration events;
  the activity chart counts conversations updated per day, not turns; assignment
  counts are references, not unique resources.

## 8. Branch policy

`feat/dashboards` is **not** merged into `main` and must not be until the user
says so.
