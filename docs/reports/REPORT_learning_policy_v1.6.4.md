# Learning accounts in upstream v1.6.4 — nine defects, one root cause

**Date** 2026-09-03 · fork `abe32e93` · upstream `93df3d48` (v1.6.4)

Reported by Attapon from two browsers side by side — an admin console and a
restricted learner — then reproduced here, and independently on a second machine
running a **clean upstream checkout with none of this fork's work in it**. Every
defect below is in an upstream file. None was caused by this fork.

---

## 1. Summary

v1.6.4's backend enforces learning-account restrictions correctly and
consistently. **Its frontend was never taught that "denied" is a normal state.**
Nine separate defects follow from that, ranging from cosmetic noise to a settings
page that unmounts itself.

The `learner` preset is hit hardest because it is the only preset that always
carries a policy and cannot have it removed, so it meets every one of these at
once. Before this work it could not hold a conversation at all.

---

## 2. Reproducing

A learning policy becomes active when either:

- an admin ticks **Enable learning policy** on any account (its label says
  "Teacher persona; Chat and Immersive Reading only"), or
- the account uses the **`learner` preset**, which receives `learner_grant`'s
  policy automatically (`deeptutor/multi_user/grants.py`).

Accounts on other presets are unaffected until the box is ticked, which matches
what was observed.

Confirm the state with `GET /api/auth/status`: `learning_policy` present and
`allowed_surfaces: ["chat", "reading"]`.

---

## 3. Root cause

`deeptutor/api/main.py` mounts most routers with a default-deny guard:

```python
_auth = [Depends(require_learning_surface)]
app.include_router(co_writer.router, prefix="/api", dependencies=_auth)
# …book, knowledge, notebook, dashboard, mastery-paths, memory,
#   multi-user, imports, question, settings, tools, system
```

`require_learning_surface` maps a request path to a surface and denies anything
outside the account's `allowed_surfaces`. Unmapped paths resolve to `""` and are
therefore denied. This is deliberate and sound.

**The policy reaches the browser and nothing read it.** `/api/auth/status` has
always returned `learning_policy` with `allowed_surfaces`, and `web/lib/auth.ts`
has always typed it. The only reference to that field in the entire frontend was
its own type declaration — `useAuthStatus` dropped it on the floor.

Upstream's own issue #1111, which shipped this feature, states the intent
plainly:

> "Expose the effective public policy through auth status **so clients can
> render the learner experience** without trusting client-side restrictions."

Everything fixed here implements that stated design rather than inventing one.

The nine defects fall into three shapes:

| shape                                      | what it looks like                                                                      |
| ------------------------------------------ | --------------------------------------------------------------------------------------- |
| **A. The policy is delivered and ignored** | Restricted features are offered; the restriction only appears as an error after a click |
| **B. Code assumes the request succeeds**   | An error body is parsed as data, or one rejection discards unrelated results            |
| **C. Two places disagree about one fact**  | The server acts on X while telling the browser "no X"                                   |

---

## 4. The nine defects

| #   | Shape | Defect                                                    | Effect before                                                                  |
| --- | ----- | --------------------------------------------------------- | ------------------------------------------------------------------------------ |
| 1   | A     | Sidebar ignored `allowed_surfaces`                        | All 12 features offered; clicking gave a raw 403                               |
| 2   | A     | Settings visibility had no "restricted" dimension         | Network / Models / Knowledge / Chat / Memory rendered, fetched, 403'd          |
| 3   | A     | Guardian visibility keyed off preset only                 | A panel whose every endpoint 403s was offered                                  |
| 4   | B     | `MemorySettingsSection` cast a 403 body to its DTO        | `settings.update.l2_budget` threw → **whole settings page unmounted**          |
| 5   | B     | `SettingsStore` treated 403 as fatal                      | Red "Settings fetch failed: HTTP 403" above controls that work                 |
| 6   | B     | `Promise.all` in both sidebars had no `.catch` on courses | One 403 discarded loaded sessions → "No conversations yet" with a full history |
| 7   | B     | `co-writer-api` dumped the response envelope              | `Request failed (403): {"detail":…}` instead of a sentence                     |
| 8   | C     | `allowed_llm_options()` returned `active: null`           | Selector showed "Select model" while every turn used the assigned one          |
| 9   | —     | `/api/settings/llm-options` behind the guard              | A learning account could never see any model                                   |

### The sharpest one (#4)

```js
.then((res) => res.json() as Promise<MemorySettingsDTO>)
```

No `res.ok` check and no `.catch`. The 403 body `{"detail": …}` is parsed and
**cast** to the DTO — the `as` hides that from the type checker — and the
component's own `if (!settings)` guard passes, because the object is truthy. The
first read of a nested field throws out of render and React unmounts the tree.

Which fix mattered was **measured, not assumed**: reverting #3 and keeping only
#4 leaves the page loading. #4 was the crash; #3 is a separate correctness fix.

### The most consequential one (#9)

`/api/settings/llm-options` lives on the guarded settings router, so it answered
403 for any account with a policy. Only `settings.public_router`
(`/api/settings/ui`) is exempt, mounted first on purpose.

The guard was **broader than the handlers it fronts**. Upstream wrote a
non-admin path for this exact case:

```python
@router.get("")
async def get_settings():
    user = get_current_user()
    if not user.is_admin:
        # Non-admins never see the catalog (provider URLs/keys); their model
        # choices come from /settings/llm-options (grant-filtered).
        return {"ui": load_ui_settings()}
```

That code was unreachable for learning accounts.

### The disagreement (#8)

`request_preparer` pins "the first granted-and-available model" when a turn
arrives with no selection, while `allowed_llm_options()` told the browser
`active: null`. The model was working; the selector said none was chosen.

---

## 5. What was fixed

### Layer 1 — read the policy

`useAuthStatus` now carries `allowedSurfaces` (null for unrestricted accounts,
which changes nothing for them). Two consumers act on it:

- **Navigation** — `nav-entries.ts` gains a `surface` field mirroring
  `_learning_surface_for_path`; `filterNavBySurfaces` filters both the primary
  nav and the secondary consoles. An entry with **no declared surface is hidden**
  from restricted accounts — the safe direction, so a new feature stays out until
  someone decides where it belongs. `Settings` opts back in as `"unrestricted"`,
  measured: `/api/settings/ui` answers 200 while `/api/settings` answers 403, so
  the account can still change its own language and theme.
- **Settings** — `settings-access.ts` gains `restricted`; categories gain
  `learningSafe`; `isSettingsCategoryVisible` hides the rest. `page.tsx` uses the
  same predicate to decide which sections **mount**, so navigation and content
  cannot disagree. Appearance, Learner profile and About opt in, each checked
  against the running server.

### Layer 2 — stop assuming success

- `MemorySettingsSection` checks `res.ok`, catches, and renders a translated
  sentence.
- `SettingsStore` falls back to `/api/settings/ui` on 403 instead of erroring —
  a scoped account is not in a failure state, it has a narrower surface.
- Both sidebars `.catch` the courses and reading-collection fetches, matching
  what upstream already did for mastery topics.
- `co-writer-api` extracts `detail` rather than dumping the envelope.
- `StarterSuggestions` and `VersionBadge` skip fetches they cannot use.

### Layer 3 — one source of truth

- `default_llm_selection_for_user` is now the single rule. `request_preparer`
  and `allowed_llm_options()` both read it, so the selector renders exactly what
  the turn will do.
- `_learning_surface_for_path` maps `("/api/settings/llm-options", "chat")` —
  choosing which model answers a chat turn is part of the chat surface. Safe by
  construction: `get_llm_options` already returns the grant-filtered
  `allowed_llm_options()` to every non-admin. Deliberately the full path, never
  the `/api/settings` prefix, because that loop matches on prefix and a shorter
  entry would open every settings write on the same router.

---

## 6. Not a defect

**The `learner` preset cannot have its policy removed.**
`lockLearningPolicy={user.preset === "learner"}` disables the checkbox on
purpose. A learner _is_ the restricted preset; the control is shown for
consistency and locked because the preset defines it. Working as intended,
though a disabled checkbox with no explanation reads as a bug.

---

## 7. Verification

Measured on the reported account, before and after (Attapon signed in; the
credentials were never handled by the assistant):

|                            | before                    | after                                       |
| -------------------------- | ------------------------- | ------------------------------------------- |
| Sidebar entries            | 12, most 403 on click     | 3 — Chat, Immersive Reading, Settings       |
| Settings sections rendered | 10, five with 403 banners | 3 — overview, appearance, about; no banners |
| `/settings#guardian`       | "This page couldn't load" | loads                                       |
| Backend status strip       | stuck on "Checking"       | not shown (not a learner's concern)         |
| Sessions in sidebar        | "No conversations yet"    | 1, matching the API                         |
| Model selector             | "Select model"            | `gemini-3.1-flash-lite`                     |
| Requests per chat load     | 21                        | 17                                          |

Gates: `scripts/precheck.sh` green (ruff, pytest, `npm run check`); 1,082 node
tests; four `invariants.py` checks clean; skill backtest 5/5; **CI green on all
13 jobs**, including Python 3.11–3.14 and the Windows import check.

New tests, each verified to fail when its fix is removed:

- `tests/multi_user/test_default_llm_selection.py` — the active default matches
  what the turn pins.
- `tests/multi_user/test_account_presets.py` — the surface mapping, plus an
  end-to-end check that a real learner account passes
  `require_learning_surface` for that route while the rest of the settings
  router stays denied.
- `web/tests/learning-surface-nav.test.ts` — navigation filtering, both
  directions.
- `web/tests/guardian-management.test.ts` — settings visibility for a restricted
  account versus a plain standard one.

### One regression, introduced and fixed here

The 403 branch in `SettingsStore` first landed as an early `return`, which also
skipped the system-status fetch below it — leaving the Backend indicator on
"checking" for exactly the accounts the branch was meant to help. Caught by
looking at the running page, fixed in `0b2ea368`.

---

## 8. Upstream-PR candidates

Not yet prepared as branches. Convention: `upstream-pr/<topic>` cut from
`upstream/main`. Opening a PR is the maintainer's call.

1. **`/api/settings/llm-options` behind the learning guard** (#9) — makes the
   `learner` preset unusable. One line plus two tests.
2. **`PYTHONIOENCODING: utf-8` on `import-check`** — their Windows leg dies
   printing a `✅` to a cp1252 console, and `python-tests` declares
   `needs: import-check`, so **two consecutive releases shipped with no Python
   test signal**. Must be job-scoped: v1.6.4 added a second ✅-printing step.
3. **`MemorySettingsSection` unchecked response** (#4) — one `res.ok` between a
   403 and a dead settings page.
4. **`Promise.all` without `.catch` in both sidebars** (#6) — a 403 on one
   fetch discards unrelated loaded data.
5. **Three `reading-*` audits broken in v1.6.4** — proven on a clean upstream
   worktree; invisible to upstream because `npm run check` exits on their own
   `/knowledge-bases` route budget before Playwright runs.
6. **`book-reader-sequential.audit.ts`** — stale assertion left by their
   canonical-routes rename, plus the real scroll bug it was masking.

No open issue reports any of this. #992, the umbrella for the learner work, is
open with no comments.

---

## 9. Should this fork roll back?

**No.** The backend design is coherent and complete; the gaps were frontend-only
and are now closed. The broken path is opt-in — an admin has to enable it — and
rolling back would discard v1.6.4 along with the Thai localisation work that
landed with it.

Residual risk was measured rather than guessed: 26 call sites share the
unchecked-`json()` shape, but 16 sit in areas now hidden from restricted
accounts, leaving 10 reachable ones in `features/settings` and `lib/`. A
`json-unchecked` invariant, in the style of the existing `th-read` check, would
catch both those and anything a future sync brings in.

---

## 10. Method notes

Three things here were only found by driving the running application, and would
have been missed by reading diffs or trusting green gates:

- **The crash attribution was wrong at first glance.** The stack pointed at a
  chunk that a rebuild left byte-identical, which nearly led to "the fix did not
  land". Chunk hashes are not evidence; behaviour is.
- **A gate can be defeated by timing.** The first version of the
  `StarterSuggestions` skip still fired, because `allowedSurfaces` is null both
  for an unrestricted account _and_ for one whose status has not arrived yet.
  Only measuring the request count exposed it.
- **A/B beats inference.** Reverting one fix at a time is what established that
  #4, not #3, was the crash — and that the fork was not the cause of the missing
  model.

## Change log

| commit     | what                                                |
| ---------- | --------------------------------------------------- |
| `57af19b6` | Hide surfaces a learning account cannot reach       |
| `bf602b04` | Settings error banner; two pointless fetches        |
| `7669d4b7` | Unchecked 403 body crashing the settings page       |
| `0b2ea368` | The status-fetch regression from the line above     |
| `834a2e44` | First version of this report                        |
| `b6bad598` | Let a learning account read its own model list      |
| `abe32e93` | Settings visibility, sidebar sessions, active model |
