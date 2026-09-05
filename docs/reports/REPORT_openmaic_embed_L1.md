# REPORT — OpenMAIC embed, level 1 (`/maic`)

**Date:** 2026-09-05
**Branch:** `feat/openmaic-embed`
**Scope:** make OpenMAIC reachable from DeepTutor as a sidebar entry, without
merging its codebase.

---

## 1. Why level 1

The request was "bring the whole thing in as another sidebar menu." Assessment
first, because "the whole thing" is not a feature — it is a second application:

| | OpenMAIC | DeepTutor `web/` |
|---|---|---|
| LOC (app+components+lib+packages) | 90,011 | 44,987 |
| Next API routes | 69 | 2 |
| workspace packages | 6 (`workspace:*`) | 0 |
| Tailwind | **v4** (CSS-first) | **v3.4.17** (JS config) |
| package manager | pnpm 10.28 | npm |
| extra infra | Postgres + Chromium/FFmpeg render service | — |
| locales | 12, **no Thai** | en / zh / **th** |

Two of those are hard blockers for a merge, not cost items:

1. **Tailwind v4 vs v3.** One Next app has one PostCSS pipeline. OpenMAIC's
   `globals.css` is v4-only (`@import 'tailwindcss'`, `@theme inline`,
   `@custom-variant`, `@source`) on top of `shadcn/tailwind.css`; this app is v3
   with a JS config. One side would have to be rewritten.
2. **`/api/*` collision.** `web/lib/proxy-policy.ts:28` forwards every `/api/*`,
   `/ws/*` and `/files/*` path to FastAPI. All 69 of OpenMAIC's routes would be
   swallowed.

So: run it beside us, frame it, and give it one nav entry. Reversible — deleting
the nav entry removes the feature.

## 2. What shipped

New: `web/lib/openmaic-embed.ts`, `web/app/(workspace)/maic/page.tsx`,
`web/components/maic/MaicWorkspace.tsx`, `web/tests/openmaic-embed.test.ts`,
`deploy/docker-compose.openmaic.yml`, `deploy/OPENMAIC_EMBED.md`.

Changed, three upstream files, one insertion each:
`components/sidebar/nav-entries.ts`, `components/voice/VoiceCallWidget.tsx`,
`locales/{en,th,zh}/app.json`.

## 3. What testing found

**a. `integrations.json` silently eats unknown keys.** The first design put the
embed URL at `integrations.openmaic.embed_url`. It worked once, then the value
vanished — `_normalize_integrations`
(`deeptutor/services/config/runtime_settings.py:1192`) returns a hardcoded dict
literal on every load *and* save, so anything not on its allow-list is deleted
the next time the backend touches the file. Moved to a fork-owned
`data/user/settings/openmaic.json`. Static review would not have caught this.

**b. The page would have been frozen at build time.** It calls no dynamic API, so
`next build` would prerender it once and bake in the build-time value — inside a
Docker image, permanently "unconfigured". Fixed with `export const dynamic =
"force-dynamic"`.

**c. A top-level page must be declared to the voice agent.**
`tests/voice-manifest-parity.test.ts` failed on the new route until `/maic` was
added to `UI_PAGES`. Registered rather than excluded, so "ไปหน้าสตูดิโอสร้างคอร์ส"
now navigates there.

## 4. Verification

| Check | Result |
|---|---|
| `npm run check:fast` | **exit 0** |
| node tests | 1105 passed, 0 failed (incl. 8 new) |
| vitest | 22 passed |
| eslint | 0 errors (76 pre-existing warnings, none in new files) |
| i18n parity | OK — en/th/zh at 4,893 keys each; sidebar's 25 label/tooltip keys resolve |
| typecheck / contracts / dependency-cruiser | pass |

Runtime, both servers live (DeepTutor `:3000`, OpenMAIC `:3100`):

- Unconfigured → the setup panel renders, not a broken frame.
- Wrong origin → reproduced `net::ERR_BLOCKED_BY_RESPONSE`, i.e. OpenMAIC's
  `frame-ancestors` correctly refusing an un-listed parent.
- Configured, origin allowed → OpenMAIC's full UI renders inside the DeepTutor
  shell; 78 of its own requests answer 200 (`/api/access-code/status` → 200,
  confirming the access gate is off); typing into its composer works.
- Header check: `Content-Security-Policy: frame-ancestors 'self' …:3000 …:3782`
  with `X-Frame-Options` correctly omitted.

The one pre-existing audit note (`contextBudget.note.deferredTools`, 1 missing
key per locale) is unchanged from before this branch.

### Second pass — production build, auth, and a real course

Run after the first commit, with the backend up (`deeptutor serve --port 8001`):

- **Production build.** `rm -rf .next && npm run build` lists the route as
  **`ƒ /maic`** — server-rendered on demand. Every other plain page is `○`
  (static), so without `force-dynamic` this one really would have been frozen at
  build time. `npm run perf:check` passes every budget; the root shell measures
  395KB against its 410KB budget, i.e. the 8 new locale keys cost nothing
  meaningful.
- **Auth gate, measured with `auth.enabled = true`.** `GET /maic` with no cookie
  answers `307 -> /login?next=%2Fmaic`, exactly like `/chat` and `/settings`.
  With a valid `dt_token` it answers 200. The page is properly gated.
- **The gap, also measured.** `GET http://localhost:3100/` with no cookie at all
  answers **200**, as does its `/api/access-code/status`. The framed service is
  independently reachable — the limitation in §5.1 is now a measurement, not a
  prediction.
- **A real course, end to end.** Through the iframe, prompt "Photosynthesis for
  grade 8" against OpenMAIC's configured Google provider: it generated three
  classroom roles (teacher / assistant / student, each with written personas), a
  rendered slide ("Introduction to Photosynthesis" — Definition / Energy Source /
  Who Performs It?) and opening teacher dialogue. Its own IndexedDB persisted the
  draft prompt across a full server restart, inside the frame.

Two dev-environment traps hit along the way, neither a defect in this branch and
both worth knowing:

- A stale `.next` (production artifacts left over from an earlier `npm run
  build`, plus dev state from two runs with different env) served **404** for the
  new route until the file was touched. `rm -rf .next` is the reliable reset.
- The backend caches `auth.json` in memory at startup, so restoring
  `enabled: false` on disk did nothing until the backend was restarted — the UI
  kept redirecting to `/login` while the file said otherwise.

## 5. Not done — deliberately

1. **The page is gated, the service behind it is not** — both now measured (see
   above). `/maic` redirects to `/login` without a cookie; OpenMAIC's own address
   answers 200 to anyone. Must be solved (nginx `auth_request`, or same-origin +
   `ACCESS_CODE`) before any public deployment.
2. **No Thai in OpenMAIC.** A Thai learner lands in English.
3. **Nothing shared but the shell** — no common session, data, theme, model
   config; a course built there does not reach Learning Space or Mastery.
4. **Nav entry always visible**, even unconfigured. Gating it needs the setting
   threaded into the client sidebar; left as a product call.
5. **Same-origin deployment merges `localStorage`**, where OpenMAIC stores
   provider `apiKey` values. Key names do not collide today (this app namespaces
   `deeptutor-*` / `dt:*`), but that is luck. Cross-origin avoids it entirely and
   is the recommended default.

## 6. Next decision

Level 1 answers "will anyone use it" cheaply. If yes, the next rung is a data
bridge (courses visible in Learning Space / Mastery, ~2–4 weeks); if the answer
is that it must feel native — Thai, shared theme, shared auth — that is a port
to a Level-2 Capability in Python, and a different order of work.
