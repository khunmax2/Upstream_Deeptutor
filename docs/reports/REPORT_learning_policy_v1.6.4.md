# Learning accounts in upstream v1.6.4 — what breaks, what is by design

**Date** 2026-09-03 · fork at `0b2ea368` (not pushed) · upstream `93df3d48` (v1.6.4)

Reported by Attapon from two browsers side by side, then reproduced by Claude on
this machine and independently by Attapon on a second machine running a **clean
upstream checkout with none of this fork's work in it**. Everything below is
upstream behaviour unless stated otherwise.

## The one-line finding

v1.6.4's backend enforces learning-account restrictions correctly and
consistently. Its frontend was never taught that "denied" is a normal state, so
every surface that meets a 403 fails as if something were broken. Six separate
defects, all in upstream files.

`/api/auth/status` has always returned `learning_policy` with `allowed_surfaces`,
and `web/lib/auth.ts` has always typed it. **Nothing in the app read it.**

## Trigger

A learning policy becomes active when either:

- an admin ticks **Enable learning policy** on any account, or
- the account uses the **`learner` preset**, which gets `learner_grant`'s policy
  automatically (`deeptutor/multi_user/grants.py`).

Other presets are unaffected until the box is ticked — which matches what
Attapon observed.

## Fixed in this fork

| # | Defect | Effect before |
|---|---|---|
| 1 | Sidebar ignored `allowed_surfaces` | Every restricted feature was offered; clicking gave a raw 403 |
| 2 | `SettingsStore` treated 403 as fatal | Red "Settings fetch failed: HTTP 403" above controls that work |
| 3 | `MemorySettingsSection` cast a 403 body to its DTO | `settings.update.l2_budget` threw → **whole settings page died** |
| 4 | Guardian visibility keyed off preset only | A section whose every endpoint 403s was offered |
| 5 | `co-writer-api` dumped the response envelope | `Request failed (403): {"detail":…}` instead of a sentence |
| 6 | Two background fetches for denied routers | Noise; 21 requests per chat load → 17 |

Defect 3 was the reported crash. Which fix mattered was **measured**: reverting
4 and keeping only 3 leaves the page loading. Defect 3 is the sharpest of the
set — `res.json() as Promise<T>` with no `res.ok` check, where the `as` hides
from the type checker that an error body is being handed to the component.

A regression Claude introduced while fixing 2 — an early `return` that also
skipped the system-status fetch, leaving the Backend indicator on "checking" —
is fixed in `0b2ea368`.

## Not fixed: by design

**The `learner` preset cannot have its policy removed.**
`lockLearningPolicy={user.preset === "learner"}` disables the checkbox on
purpose. A learner *is* the restricted preset; the control is shown for
consistency and locked because the preset defines it. Working as intended,
though a disabled checkbox with no explanation reads as a bug.

## Not fixed: needs a backend decision

**A restricted account can never choose a model.**

`app/main.py` mounts the settings router with the guard:

    app.include_router(settings.router, prefix="/api/settings",
                       tags=["settings"], dependencies=_auth)

`/api/settings/llm-options` lives there, so it answers 403 for any account with
a policy. Only `settings.public_router` (`/api/settings/ui`) is exempt, mounted
first on purpose.

Measured on the same account, same machine:

| learning policy | `/api/settings/llm-options` | model visible in chat |
|---|---|---|
| off | 200, returns the assigned model | yes |
| on | 403 | no |

The line is byte-identical to upstream's. This fork changed nothing in it.

**Consequence:** the `learner` preset — the one preset that always carries a
policy, and cannot have it removed — is the one preset that can never select a
model. An admin can assign an LLM to a learner and the learner will not see it.

**Fixed here** by mapping the one route to the surface it belongs to, in
`_learning_surface_for_path`:

    ("/api/settings/llm-options", "chat"),

Choosing which model answers a chat turn *is* part of the chat surface. Safe by
construction and by upstream's own design — `get_llm_options` already returns
the grant-filtered `allowed_llm_options()` to every non-admin, so a learner sees
only what was assigned to it. Deliberately the full path: that loop matches on
prefix, so an `/api/settings` entry would open every settings write sharing the
router. Two tests cover it, and both fail when the line is removed.

Two alternatives were rejected. Moving the route to `settings.public_router`
loses the user context `allowed_llm_options()` needs — that router exists for
pre-session bootstrap. Adding `settings` to `allowed_surfaces` opens the whole
router, including admin writes.

### Upstream's own issues confirm the intent

`#1111` (closed, shipped as this feature) states the design outright: *"Expose
the effective public policy through auth status **so clients can render the
learner experience** without trusting client-side restrictions."* The policy was
exposed; no client ever read it. Every frontend fix above implements upstream's
stated design rather than inventing a new one.

No open issue reports any of this. `#992`, the umbrella for the learner work,
is still open with no comments.

## Upstream-PR candidates after this work

Five now, in value order:

1. **`/api/settings/llm-options` behind the learning guard** — makes the
   `learner` preset unusable. The heaviest of everything found.
2. **`PYTHONIOENCODING: utf-8` on `import-check`** — their Windows leg dies
   printing a `✅`, and `python-tests` needs it, so **two consecutive releases
   shipped with no Python test signal**.
3. **`MemorySettingsSection` unchecked response** — one `res.ok` check between a
   403 and a dead settings page.
4. **Three `reading-*` audits broken in v1.6.4** — proven on a clean upstream
   worktree; invisible to them because `npm run check` exits on their own
   `/knowledge-bases` budget before Playwright runs.
5. **`book-reader-sequential.audit.ts`** — stale assertion, plus the real scroll
   bug it was masking.

## Should this fork roll back?

No. The backend design is coherent and complete; the gaps are frontend-only and
six of them are now closed. The broken path is opt-in — an admin has to enable
it — and rolling back would discard v1.6.4 plus the Thai localisation work that
landed with it. Residual risk was measured rather than guessed: 26 sites share
the unchecked-`json()` shape, but 16 sit in areas now hidden from restricted
accounts, leaving 10 reachable ones in `features/settings` and `lib/`.
