> **Draft for HKUDS/DeepTutor — not yet posted.** Open it with the **Bug Report**
> template (blank issues are disabled). Fields below map to that form. Every
> claim was verified against a clean upstream v1.6.4 checkout, not a fork.

---

## Field: Title

```
[Bug]: Learning accounts — the policy reaches the client but nothing reads it, and CI cannot see the fallout
```

## Field: Related Module

```
Frontend/Web
```

(The root cause is frontend; two items are backend/CI and are called out as such.)

## Field: Steps to reproduce

```
1. Enable auth and sign in as admin.
2. Create a `learner` account, or open /admin/users and tick
   "Enable learning policy" on an existing standard account.
3. Sign in as that account.
4. GET /api/auth/status → learning_policy present,
   allowed_surfaces: ["chat", "reading"].
5. Open the sidebar, then /settings, and scroll to any anchor below Memory.
```

## Field: Expected Behavior

```
The navigation and settings render from the policy the server already sends, so
the account is offered what it can use and nothing else. A denied endpoint is a
normal state for these accounts, not an error condition: it should produce an
absence, or at worst a sentence — never a red banner over working controls, and
never an unhandled throw that unmounts the page.

Concretely:
  - the sidebar lists only surfaces in allowed_surfaces
  - settings shows the redacted page the docs describe (theme, language,
    granted-model summaries, learner profile, guardian when authorized)
  - the conversation list survives a 403 from an unrelated fetch
  - the model selector shows the model that turns already use
```

## Field: Describe the bug

```markdown
Enabling a learning policy on an account (or creating a `learner` preset) leaves
the UI in a state where most of what it offers answers 403. The backend guard is
correct and consistent; the frontend was never taught that "denied" is a normal
state, so the restriction surfaces as errors after a click rather than as an
absence.

`GET /api/auth/status` already returns `learning_policy` with `allowed_surfaces`,
and `web/lib/auth.ts` types it. As of v1.6.4 the only reference to that field in
the whole frontend is its own type declaration — `useAuthStatus` drops it.

That is exactly the contract #1111 set out:

> "Expose the effective public policy through auth status **so clients can render
> the learner experience** without trusting client-side restrictions."

The policy is exposed. Nothing renders from it.

### What happens

Nine distinct symptoms. Grouped by cause rather than by screen:

**The policy is delivered and ignored**

1. The sidebar offers all twelve features. Co-Writer, Books, Mastery Path,
   Partners, My Agents, Learner Anima, Learning Space, Memory and Knowledge
   Center each answer 403 on click.
2. Settings renders Network, Models, Knowledge Base, Chat and Memory. Each
   fetches and fails — the visible result is `Failed to load tools: HTTP 403`
   and `Couldn't load capability settings`.
3. The Guardian section is shown whenever `preset` is `standard` or `custom`,
   without checking whether a learning policy is present. Everything it reads
   is under `/api/multi-user/*`, which is guarded.

**Code that assumes the request succeeded**

4. `web/features/settings/sections/MemorySettingsSection.tsx` does
   `.then((res) => res.json() as Promise<MemorySettingsDTO>)` with no `res.ok`
   check. On 403 the error body is cast to the DTO — the `as` hides this from
   `tsc` — the component's own `if (!settings)` guard passes because the object
   is truthy, and the first read of `settings.update.l2_budget` throws out of
   render. **The whole settings page unmounts to "This page couldn't load".**
   Reachable by scrolling to any anchor below Memory.
5. `SettingsStore` treats the 403 from `/api/settings` as fatal and paints
   `Settings fetch failed: HTTP 403` above controls that work — `/api/settings/ui`
   answers 200 and carries theme, both languages and code-block preferences.
6. `WorkspaceSidebar` and `UtilitySidebar` load the conversation list with
   `Promise.all([listSessions, listCourses, fetchMasteryTopicIndex, fetchReadingCollectionIndex])`.
   `/api/courses` answers 403, and that single rejection discards the sessions
   that loaded fine: **the learner sees "No conversations yet" with a full
   history on the server.** `fetchMasteryTopicIndex` already has a `.catch` for
   this reason; the other two do not.
7. `co-writer-api` throws `Request failed (403): {"detail":"…"}` — the envelope
   and status drown the one part a reader needs.

**Two places disagreeing about one fact**

8. `request_preparer` pins the first granted-and-available model when a turn
   arrives with no selection, while `allowed_llm_options()` returns
   `{"active": None, …}`. The model selector therefore shows "Select model"
   even though every turn already uses that model.
9. `/api/settings/llm-options` sits on the settings router, which carries
   `dependencies=_auth`, so it answers 403 for any account with a policy.
   **A learning account can never see any model.** Since the `learner` preset
   always carries a policy and (correctly, per #1112) cannot disable it, that
   preset cannot pick a model at all.

Measured on one account, same machine:

| learning policy | `/api/settings/llm-options`     | model visible |
| --------------- | ------------------------------- | ------------- |
| off             | 200, returns the assigned model | yes           |
| on              | 403                             | no            |

`get_llm_options` already returns the grant-filtered `allowed_llm_options()` to
every non-admin, and `GET /api/settings` carries a non-admin branch whose own
comment says model choices come from that route — code the router-level guard
makes unreachable.

### Why CI has not caught any of this

Two independent blind spots, both worth fixing on their own:

**Python tests have not run for two releases.** `import-check` on
`windows-latest` prints `✅` to a cp1252 console, so every step raises
`UnicodeEncodeError` _after_ importing cleanly. `python-tests` declares
`needs: import-check`, so the whole matrix is skipped. v1.6.3 and v1.6.4 both
shipped with no Python signal. A `PYTHONIOENCODING: utf-8` at **job** scope
fixes it — step scope is not enough, since v1.6.4 added a second ✅-printing
step.

**Playwright never runs.** `npm run check` exits first on `perf:check`:
`/knowledge-bases` measures 541KB against its own 540KB budget in v1.6.4. Behind
that gate, three `reading-*` audits fail on a clean v1.6.4 checkout —
`reading-citation-material`, `reading-location-history`,
`reading-w3c-annotations` — and `book-reader-sequential` asserts
`toHaveURL(/page=page-2/)` two lines after navigating to the path form, left
behind by the canonical-routes rename. Correcting that assertion reveals a real
one underneath: after ArrowLeft the reader's `scrollTop` stays 0 instead of
landing mid-chapter.

### Suggested direction

Only #9 involves a judgement call. Mapping `/api/settings/llm-options` to the
`chat` surface in `_learning_surface_for_path` reads naturally — choosing which
model answers a chat turn is part of that surface, and the handler is already
grant-filtered. The full path matters: that loop matches on prefix, so an
`/api/settings` entry would open every settings write on the same router.

The rest are mechanical: read `allowed_surfaces` before rendering navigation and
settings categories, check `res.ok` before casting, and `.catch` the fetches
whose failure should not discard their siblings.

### Offer

I have all of this working against v1.6.4 with tests, each verified to fail when
its fix is reverted. Happy to open focused PRs — the CI encoding fix first, since
it restores your own Python signal — or to leave it here if you would rather take
a different direction. Several of these areas have PRs in flight (#1110, #1112,
#1124), so I did not want to send patches that collide with work in progress.

Related: #992, #1111, #1112.
```

## Field: Configuration Used

```
DeepTutor v1.6.4 (upstream `93df3d48`), source install, Python 3.13, macOS.
Nothing from a fork — reproduced again on a second machine running a clean
upstream checkout.

data/user/settings/auth.json
  enabled: true          # multi-user mode

Account under test: an ordinary `user` created from /admin/users, either
- preset `learner`, or
- preset `standard` with "Enable learning policy" ticked in the grant editor.

Both resolve to the same effective policy, straight from GET /api/auth/status:

{
  "age_band": "13-15",
  "locked_persona": "teacher",
  "allowed_capabilities": ["chat", "immersive_reading"],
  "default_capability": "immersive_reading",
  "allowed_surfaces": ["chat", "reading"],
  "reading": { "allow_upload": false, "material_ids": [], "extensions": [] }
}

One LLM model assigned to the account through the grant editor.
```

## Field: Logs and screenshots

```
**The settings page unmounting (symptom 4).** Scrolling /settings to any anchor
below Memory replaces the page with Next's "This page couldn't load":

Uncaught TypeError: Cannot read properties of undefined (reading 'l2_budget')

Preceded by the 403 whose body was cast to the DTO:

GET /api/memory/settings 403 (Forbidden)
{"detail":"This learning account cannot use the requested server surface."}

**What the account can and cannot reach.** Probed from the signed-in browser:

  /api/settings/ui               200
  /api/sessions                  200
  /api/reading/workspaces        200
  /api/settings                  403
  /api/settings/llm-options      403   <-- no model can ever be selected
  /api/tools                     403
  /api/knowledge-bases           403
  /api/memory/overview           403
  /api/multi-user/me/guardianships  403
  /api/system/status             403
  /api/courses                   403   <-- discards the loaded session list

**The conversation list (symptom 6).** With one session on the server, the
sidebar shows "No conversations yet" and the console logs:

Failed to load sessions  Error: Request failed: 403

**CI blind spots.** Your own Tests run for v1.6.4 (`93df3d48`):

  failure   Import Check (Python 3.14, windows-latest)
  skipped   Python Tests (Python ${{ matrix.python-version }})
  failure   Web Node Tests
  skipped   Four-worker browser acceptance
  failure   Test Summary

The skipped Python matrix is the `needs: import-check` chain described above.
```
