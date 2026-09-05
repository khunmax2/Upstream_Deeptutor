# OpenMAIC embed (`/maic` — "Course Studio")

How the OpenMAIC course studio is reached from this app, what it is *not*, and
the two things to fix before this goes anywhere public.

- **Upstream:** https://github.com/THU-MAIC/OpenMAIC (MIT)
- **Shape:** a sibling service, framed. Not merged into `web/`.

---

## Why it is a separate service and not part of `web/`

Two blockers, neither removable by effort:

1. **Tailwind v4 vs v3.** OpenMAIC's `app/globals.css` is CSS-first v4
   (`@import 'tailwindcss'`, `@theme inline`, `@custom-variant`, `@source`) and
   pulls `shadcn/tailwind.css` + `tw-animate-css`. This app is v3 with a JS
   config (~50 custom colors, CJK font stacks). One Next app has one PostCSS
   pipeline, so one of the two would have to be rewritten.
2. **`/api/*` is already taken.** `web/lib/proxy-policy.ts` routes every
   `/api/*`, `/ws/*` and `/files/*` path to FastAPI. OpenMAIC ships **69** Next
   API routes under `/api/*`; all of them would be swallowed.

Beyond that it is not a library at all: ~90k LOC, 6 pnpm workspace packages
(`workspace:*`, which `npm ci` cannot resolve), its own Postgres, and a separate
Node 22 + Chromium + FFmpeg render service.

## Configure it

The frontend reads the embed target at **request time** (the page is
`force-dynamic`), so changing it needs no rebuild.

Either the environment — this is how Docker supplies it:

```
DEEPTUTOR_OPENMAIC_URL=http://localhost:3100
```

or `data/user/settings/openmaic.json`:

```json
{ "embed_url": "http://localhost:3100" }
```

> **Do not put this in `integrations.json`.**
> `_normalize_integrations` in `deeptutor/services/config/runtime_settings.py`
> rebuilds that payload from a hardcoded dict literal on every load *and* save,
> so an unknown key is not merely ignored — it is silently deleted the next time
> the backend touches the file. `openmaic.json` is fork-owned and untouched by
> upstream's normalizer.

Only `http(s)` URLs and same-origin paths starting with `/` are accepted;
`javascript:`, `data:` and protocol-relative `//host` values are rejected and
treated as unconfigured (`web/lib/openmaic-embed.ts`, covered by
`web/tests/openmaic-embed.test.ts`). Unconfigured renders a panel explaining how
to set it, never a broken frame.

## Two deployment shapes

### Cross-origin (the dev default, and the safer one)

OpenMAIC on its own port/host; the frame crosses origins.

OpenMAIC must name our origin at **build time** — it compiles the CSP into the
bundle:

```
ALLOWED_FRAME_ANCESTORS="http://localhost:3782"
```

Verified: with that set, OpenMAIC answers
`Content-Security-Policy: frame-ancestors 'self' http://localhost:3782` and
correctly omits `X-Frame-Options` (it only supports `SAMEORIGIN`, which would
otherwise block the frame outright).

- ✅ `localStorage` stays isolated — this matters, see below.
- ❌ `dt_token` does not reach it (it does not want it), and OpenMAIC's own
  access-code cookie is `SameSite=Lax`, so it cannot work through the frame
  either. Leave `ACCESS_CODE` unset.

### Same-origin subpath (production, behind one reverse proxy)

nginx routes e.g. `/maic-app` straight to the OpenMAIC container. Then
`frame-ancestors 'self'` is satisfied with no build arg at all.

Requires adding `basePath` to OpenMAIC's `next.config.ts` — it has none today,
and Next cannot serve a subpath without it. That is a patch to re-apply on every
OpenMAIC upstream sync.

⚠️ It also merges the two apps' `localStorage`. OpenMAIC persists
`providersConfig` — which contains provider **`apiKey`** values — to
`localStorage` under bare keys (`theme`, `locale`, `providersConfig`). On a
shared origin, an XSS anywhere in DeepTutor can read those keys, and vice versa.
Today the key names do not collide (this app namespaces everything as
`deeptutor-*` / `dt:*` / `dt.*`), but that is luck, not design.

## Known limitations of this first cut

1. **The page is gated; the service behind it is not.** Measured with
   `auth.enabled = true`: `GET /maic` with no cookie answers
   `307 -> /login?next=%2Fmaic`, identical to `/chat` and `/settings`, and opens
   normally once `dt_token` is present. But `GET http://<openmaic-host>/` with
   no cookie at all still answers **200** — `web/proxy.ts` guards only what Next
   serves, and a request the reverse proxy hands straight to the OpenMAIC
   container never passes through it.

   So the sidebar route is protected and the upstream service is not. Anyone who
   learns OpenMAIC's own address reaches it directly. Before any public
   deployment, front it with nginx `auth_request` against this app's auth
   status, or accept the same-origin shape and enable `ACCESS_CODE`. Binding the
   container to loopback (as `deploy/docker-compose.openmaic.yml` does) is a
   mitigation, not a fix — it only means the reverse proxy is the sole route in.
2. **No Thai.** OpenMAIC ships 12 locales and Thai is not among them
   (`lib/i18n/locales/`, `lib/i18n/workbench-locales/`). A Thai learner clicking
   Course Studio lands in English.
3. **Nothing is shared but the shell.** No shared session, data, theme, model
   config, or uploaded files. A course built here does not appear in Learning
   Space or Mastery. The theme split is visible, not theoretical: switch this
   app to its light theme and the surrounding chrome turns light while the frame
   stays on whatever theme OpenMAIC is set to, since it owns its own toggle.
4. **The Pro agent workbench needs Postgres.**
   `lib/server/agent-runtime/store.ts` rejects without `DATABASE_URL`. The
   classic one-click generator works browser-side without it. Start it with the
   `openmaic-persistence` profile in `deploy/docker-compose.openmaic.yml`.
5. **The nav entry is always shown**, even when unconfigured. Gating it on
   configuration means threading the setting into the client-side sidebar; left
   as a product decision.

## Run it

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.openmaic.yml up -d
```

Local dev, without Docker (OpenMAIC checked out beside this repo):

```bash
cd ../OpenMAIC && ALLOWED_FRAME_ANCESTORS=http://localhost:3782 pnpm exec next dev -p 3100
```
