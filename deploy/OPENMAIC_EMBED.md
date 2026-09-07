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

## The same-origin shape, measured

Everything below was run rather than reasoned about: DeepTutor on :3000, OpenMAIC
on :3100 with `NEXT_PUBLIC_BASE_PATH=/maic-app`, and a throwaway Node reverse
proxy on :3080 standing in for nginx.

**What same-origin buys, and it is a lot**

| | result |
|---|---|
| iframe loads with **no** `ALLOWED_FRAME_ANCESTORS` | `frame-ancestors 'self'` is already satisfied |
| `iframe.contentWindow.location.origin` | same as the parent |
| `iframe.contentDocument` | reachable — the parent can inject CSS, verified by hiding OpenMAIC's own control pill |
| `localStorage` | one store. The parent wrote `locale=th-TH` and `theme=dark`, reloaded the frame, and OpenMAIC came up Thai and dark |

That last row is the whole integration story: **language and theme sync need no
patch to OpenMAIC's logic at all.** It reads both from bare `localStorage` keys
on mount (`lib/hooks/use-i18n.tsx`, `lib/hooks/use-theme.tsx`), and on a shared
origin those are the same keys we can write.

**What it costs, and this is the part that is easy to miss**

`basePath` (patch `0003`) fixes `/_next/` assets and router links. It does **not**
prefix `fetch('/api/...')`, and OpenMAIC makes **53** such calls from the browser
with no central helper to patch. On a shared origin they land on whatever else
owns `/api` — here, DeepTutor's proxy, which forwards everything to FastAPI.

The first symptom was not an error page. It was OpenMAIC showing a **login box
that was never configured**: `/api/access-code/status` failed, and its guard
defaults to "locked" on error rather than open. Fails closed, which is the right
default and a confusing one to debug.

Raw `/public` references have the same gap — `/logo-horizontal.png`,
`/avatars/*.png` — exactly what this fork documents for itself in
`web/lib/basePath.ts`.

**A reverse proxy can resolve it, by asking who is calling**

Routing shared-root paths by `Referer` — a request whose referring page is under
`/maic-app` came from inside the frame — works. Measured over a full page load:

```
/api routing — frame:6  host:14  no-referer:0
```

No request was unclassifiable, and the phantom login box disappeared.

Treat that as a demonstration, not a recommendation. It leans on a header that
referrer policy can strip, and it means the routing rule for `/api` is no longer
a path prefix but a heuristic — the kind of thing that works until the day it
does not, and fails in a way that looks like an application bug.

**So the choice is a real one**

| | cross-origin (today) | same-origin |
|---|---|---|
| language / theme sync | ✗ | ✓ |
| hide their chrome, look like one module | ✗ | ✓ |
| `/api/*` | clean | collides; needs Referer routing |
| `localStorage` isolation | ✓ | ✗ — shared, and OpenMAIC keeps provider API keys there |
| patches to OpenMAIC | none | `0003-basepath.patch` |
| reverse proxy | simple prefix | prefix + a heuristic |

Cross-origin is what ships today and it is honest about being two systems.
Same-origin is what makes it read as one module, and it buys that with a shared
storage boundary and a proxy rule that has to be right.

---

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
