# Threat model — Course Studio integration

**Method:** STRIDE per DFD element, DREAD-ranked.
**Date:** 2026-09-10. **Design under review:** ADR-0005, and
`OPENMAIC_INTEGRATION_V2_handoff.md` §3.3, §3.8, §3.9.
**Status of the system:** not built. Everything below is a review of a design
plus the code that already exists (`deploy/openmaic-gatekeeper/` on
`archive/main-2026-09-09`, and upstream OpenMAIC at `29735f10`).

Where a claim is measured, the file is named. Where it is inferred, it says so.

---

## 1. Data flow

```
 (E) browser
   │  TLS
   ▼
 (P) nginx :443            ── the only open port; also serves five unrelated apps
   ├──► (P) DeepWitya ──► (P) FastAPI ──► (S) data/users/<uid>
   │
   └──► (P) gatekeeper ──► (P) Course Studio ──► (S) PostgreSQL  (owner_id)
              │                                └► (S) asset store (one 'shared' principal)
              └──► (P) DeepWitya /api/auth/status
```

**Trust boundaries**

| # | boundary | what crosses it |
|---|---|---|
| B1 | browser → nginx | `dt_token` cookie, all request content |
| B2 | nginx → gatekeeper | the request, unmodified |
| B3 | **gatekeeper → studio** | the request **minus `dt_token`**, **plus a server-controlled identity header** |
| B4 | gatekeeper → DeepWitya auth | the bearer token, for a verdict |
| B5 | studio → PostgreSQL | `owner_id` derived from the identity header |
| B6 | browser → studio, **direct** | **this path must not exist** — see T1 |

---

## 2. Findings, DREAD-ranked

Scores are Damage / Reproducibility / Exploitability / Affected / Discoverability,
each 1–10, averaged. **≥ 7 is mandatory for phase 1.**

### T1 — Direct access to the studio container bypasses every control · **9.2** · Spoofing, Elevation

**How.** The identity header is trusted because only the gatekeeper can set it.
If the studio's port is published — a `ports:` line in compose, a stray nginx
`location`, a host firewall gap — anyone sends `X-…-User: user:<victim>` and
becomes that user. Every document, every session.

**Not hypothetical.** `deploy/openmaic-gatekeeper/gatekeeper.mjs` records it as
measured history: *"framing it does not protect it… anyone who learns that
address reaches the app directly. Measured, not assumed — a plain GET with no
cookie answered 200."* That was the state before the gatekeeper existed, and it
is the state again the moment the port is reachable.

**Existing control.** None in code. The compose file's network layout is the
whole defence, and a compose file is one careless line from wrong.

**Controls to add — all three, not one:**
1. The studio publishes **no host port**. It joins an internal compose network;
   only the gatekeeper is published, and only to loopback with nginx in front.
2. A **deploy-time assertion**: fail if the studio's port answers from anywhere
   but the gatekeeper's network namespace. Cheap version — a CI/compose lint
   that rejects a `ports:` key on that service.
3. **Defence in depth inside the studio**: when a `STUDIO_REQUIRE_GATEWAY=1`
   env is set, refuse any request that arrives without the identity header
   rather than falling back to an anonymous owner. Then a direct hit fails
   closed instead of silently creating a fresh anonymous workspace.

Control 3 matters because 1 and 2 both protect a network property, and network
properties are the ones that change without anyone editing code.

---

### T2 — A client-supplied identity header is honoured · **8.8** · Spoofing

**How.** The browser sends `X-…-User: user:admin`. If the gatekeeper *sets* the
header without first *deleting* the incoming one, Node's HTTP layer may forward
both. Most headers are joined with `, `, so the studio sees
`user:admin, user:realuser` — and whichever end a naive parser takes decides who
you are.

**Existing control.** None. The header does not exist yet; this is a
requirement, not a regression.

**Control.** Delete before set, and test both directions:

- a request carrying the header arrives at the upstream **without** the client's
  value (the mirror of the existing `dt_token`-stripping test, which already
  asserts the upstream receives no `dt_token` while unrelated cookies survive);
- a request with no header arrives with exactly one, the verified one.

Reuse the shape of `stripCookie()` in `gatekeeper.mjs` — the same idea, applied
to a header rather than a cookie.

---

### T3 — Assets and runtime sessions stay unprotected after the document work lands · **8.6** · Information disclosure

**This is the finding most likely to be missed**, because the `owner_id` work
looks like it finishes the job and it does not.

**How.** Threading `authenticatedOwnerId` partitions **documents**. Runtime and
asset routes authenticate through a different module,
`lib/persistence/server-auth.ts`, whose own docstring says:

> DEVELOPMENT-ONLY … the token is `NEXT_PUBLIC_PERSISTENCE_TOKEN`, compiled into
> the public browser bundle … **no user isolation — anyone who can load the page
> can read and write EVERY learner partition and all documents** by supplying an
> arbitrary `x-learner-key`.

and assets are stored under a single constant, `SHARED_ASSET_PRINCIPAL =
'shared'`. So after phase 1's document work, a user's **uploaded images, audio
and exported media remain readable by every other user**, and the partition key
for runtime state is whatever the client typed.

**Control.** Replacing `server-auth.ts` is **in phase 1, not after it** — derive
both the asset principal and the learner key from the same server-controlled
identity the documents use, and ignore `x-learner-key` from the client entirely.
Phase 1's acceptance test must cover an asset, not only a document.

---

### T4 — `ALLOW_ANONYMOUS=1` disables the gate completely · **7.8** · Elevation

**How.** `gatekeeper.mjs` reads `ALLOW_ANONYMOUS === '1'` and, when set, does not
gate at all. It exists for local development. One copied `.env`, one inherited
compose override, and production is ungated — with the studio still trusting the
identity header that now nobody sets or strips.

**Existing control.** Its default is off, and that is all.

**Control.** Make the dangerous combination impossible to reach by accident:
refuse to start when `ALLOW_ANONYMOUS=1` and the deployment does not look local,
and log the mode loudly at startup so it appears in the first line of any bug
report.

**Corrected while implementing, 2026-09-10.** This originally said
`NODE_ENV=production`, which was checked before being written and **would never
have fired**: the compose file passes seven variables to the gatekeeper and
`NODE_ENV` is not among them, and `node:22-alpine` does not set it either.

The signal that does exist is the one the compose file already documents as the
difference between the two worlds:

```
local     DEEPTUTOR_AUTH_URL=http://host.docker.internal:3782/api/auth/status
deployed  DEEPTUTOR_AUTH_URL=https://203.185.144.41/deepwitya2/api/auth/status
```

Both are honoured — `NODE_ENV=production` because it is conventional and costs
nothing, and a non-local auth target because it is the one that fires here.
Either refuses to start.

Demonstrated rather than argued: removing the guard fails three assertions, and
keeping **only** the `NODE_ENV` half — the control as originally written — still
fails one.

---

### T5 — The verdict cache holds a boolean, and phase 1 needs an identity · **7.4** · Spoofing

**How.** `cachedVerdict(token)` / `remember(token, ok)` store only whether a
token is good, keyed by the token. Correct today. But phase 1 needs the **uid**
on every request, and the three wrong ways to get it are all easy:

- call `/api/auth/status` per request — turns DeepTutor's auth endpoint into the
  studio's bottleneck, which is exactly what the cache exists to prevent
  (*"one page load is fifty to a hundred requests"*);
- cache the uid under a different key — anything but the token invites one
  user's identity being served for another;
- keep the boolean and resolve the uid from something the client sends — which
  is T2 with extra steps.

**Existing control.** The cache key is already the token, which is the right
key. That part is sound.

**Control.** Widen the cached value to `{ ok, uid }` under the same token key
and the same TTL. Nothing else changes.

**Accepted residual.** A signed-out or deleted account keeps studio access for
up to `AUTH_CACHE_TTL_MS` (default 30 s). That is a deliberate trade already
documented in the gatekeeper, and it should be written down as accepted rather
than rediscovered.

---

### T6 — `dt_token` is delivered to six applications owned by another team · **8.1** · Information disclosure

**Measured 2026-09-10, and it did not collapse — it got worse.** This section was
written as inferred; every claim below is now checked. Re-score from 7.2 to 8.1:
Affected and Discoverability both rise once the neighbours are confirmed to
belong to other people, and Exploitability rises on the `SameSite` finding.

**How.** DeepWitya sets `dt_token` host-only with `path=/`, and the host has no
hostname to separate anything by. Every path below is one origin.

| checked | result |
|---|---|
| `nginx -T` server names | `203.185.144.41` and `_` (catch-all). **No domain name anywhere** |
| TLS certificate | one SAN, `IP Address:203.185.144.41`, no `DNS:` entry |
| the paths | **seven**, not six — `/sansarnnews`, `/sansarn-research-helper`, `/dol`, `/deepwitya`, `/opdc-assistant`, `/deepwitya2`, and the catch-all `/` which answers 200 |
| cookie attributes, live | `Path=/; HttpOnly; Secure; SameSite=none` |
| who owns the neighbours | **another team.** Confirmed by Attapon |

A host-only cookie with `path=/` is sent to **every path on that host**, so each
of those applications receives a valid DeepWitya session token on every request
their users make, and any of them can replay it. Their access logs, error
trackers and APM traces hold it too, and a compromise of any one of them yields
live sessions for every DeepWitya user who has visited it.

Two corrections to the original list: `/research-helper` only redirects — the app
is at `/sansarn-research-helper` — and the catch-all at `/` was missed entirely.

**`Secure` is set, so port 80 does not carry it in the clear.** That sub-concern
is closed: port 80 is open (`/` answers 502, `/deepwitya2` redirects to HTTPS),
but the cookie will not travel over it.

**The `SameSite=none` finding, which is new.** `auth.py:31` reads

```python
_SAMESITE = "none" if _SECURE else "lax"
```

and the comment above it gives a **local-development** reason: the cookie has to
survive a frontend on `127.0.0.1` talking to a backend on `localhost`. Because
the value is derived from `cookie_secure`, production inherits `None` without
anyone choosing it. That changes what T6 means:

- as written: those applications receive the token when *their own users* browse
  them;
- as measured: **any website on the internet** can cause a browser to attach a
  live DeepWitya session to a request against any path on that host — an `<img>`,
  a form post, a credentialed `fetch`. `HttpOnly` stops JavaScript reading the
  cookie; it does not stop the browser sending it.

**This is not caused by the studio.** The gatekeeper's own comment identifies the
mechanism and calls it *"a real leak (an app that should not hold that token
receives it on every request)"* — and then uses it, because it is what makes the
gate cheap. The studio inherits an exposure that already reaches five other
tenants.

**Decision — `SameSite=Lax` in production, taken 2026-09-10.** Of the three
options, this is the one that goes into phase 1:

| | effect | cost |
|---|---|---|
| **chosen — `SameSite=Lax` in production** | removes "any website can trigger it"; the neighbours still receive it on their own users' requests | one line, but `_SAMESITE` is currently *derived* from `cookie_secure`, so the two must be separated. Must first confirm the same-origin embed does not need `None` |
| narrow `path=` | removes the cross-application delivery itself | breaks the mechanism the gatekeeper depends on — it receives `dt_token` precisely *because* the cookie goes everywhere. The two are coupled and must move together |
| a hostname of its own | removes the shared origin entirely | needs a domain; there is none today |

`Lax` still sends the cookie on top-level navigation to that host, so the
neighbours keep receiving it when a user clicks through. **Narrowing `path=` or
moving to a hostname remains the real fix** and stays open with an owner.

One thing to verify before changing the value: the embed is same-origin under the
new design (`/course-studio` on the same host, per ADR-0005 as amended), so
`SameSite=None` should not be needed for it. That is reasoning, not yet a measurement — check it against a running
studio before shipping the change.

---

### T7 — Header drift fails silently, but not the way the design assumed · **6.4** · Tampering

**Correcting something I told Attapon.** I said a renamed identity header would
*collapse every user into one owner*. Reading `resolveRequestOwnerId` again, that
is wrong. With no `authenticatedOwnerId`, it falls back to the `anonymous_id`
cookie and mints a fresh UUID per browser. So the real failure is:

- every user **silently loses sight of their own documents** — the work is still
  in PostgreSQL under `user:<uid>`, and they are now `anon:<uuid>`;
- a shared or kiosk browser gives its occupants **one shared anonymous owner**;
- nothing errors, nothing logs, and the app looks like it is working.

Less severe than I claimed, and still bad: silent data loss from the user's point
of view.

**Control.** The contract assertion in `check_openmaic_contract.py` (handoff
§3.8) is the right home. Add the runtime half too: when
`STUDIO_REQUIRE_GATEWAY=1`, an absent identity header is a 500, not a fallback —
which is T1's control 3 doing double duty.

---

### T8 — `frame-ancestors` widened too far · **6.0** · Spoofing (clickjacking)

**How.** Framing the studio requires widening its `frame-ancestors`. Widened to
`*` — or to a wildcard subdomain — any site can frame a logged-in user's studio
and drive it by overlay.

**Existing control.** `check_openmaic_contract.py` already treats
`ALLOWED_FRAME_ANCESTORS` as part of the runtime contract it asserts, because a
rename there makes the iframe go blank. That machinery exists; it just is not
checking the *value*.

**Control.** Pin the exact host origin, never a wildcard, and extend the existing
contract check from "the variable still works" to "the value is exactly this
origin".

---

### T9 — No audit trail on the studio side · **4.6** · Repudiation

DeepTutor has `deeptutor/multi_user/audit.py`. The studio has nothing: no record
of who created, published or deleted a course. After the reconciliation script
of handoff §3.10 deletes an orphaned owner's rows, there is no record that it
happened either.

**Deferrable past phase 1**, but the reconciliation script should write its own
log from the first version — it is the one component whose whole job is deleting
other people's data.

---

## 3. What phase 1 must carry

| | mandatory | landed |
|---|---|---|
| T1 | studio publishes no host port · deploy-time assertion · `STUDIO_REQUIRE_GATEWAY` fail-closed | controls 1 and 2 yes — `deploy/docker-compose.openmaic.yml` publishes nothing for the studio, and `check_openmaic_contract.py` fails CI on a `ports:` key, on `network_mode: host`, and on the studio joining the shared network. Control 3 is set in compose and inert until the fork honours it |
| T2 | strip-before-set, tested in both directions | yes — `gatekeeper.mjs`, with the header stripped on both the HTTP and the websocket path |
| T3 | replace `server-auth.ts`; acceptance test covers an **asset**, not only a document | no — fork work. Compose meanwhile refuses to carry `PERSISTENCE_ALLOW_INSECURE_DEV_AUTH`, and the image's `NODE_ENV=production` makes upstream reject its own development authenticator |
| T4 | refuse `ALLOW_ANONYMOUS=1` in production | yes — non-zero exit at startup, and in compose the auth URL is a container name, so the guard fires there by construction |
| T5 | cache `{ ok, uid }` under the token key | yes |
| T6 | `SameSite=Lax` in production — the hostname claim is now measured, and confirmed | no — needs a running studio first, to confirm the same-origin embed does not need `None` |

Deferrable with a written owner: the rest of T6 (narrow `path=`, or a hostname of
its own — both coupled to the gatekeeper's token delivery), T8 (pin the origin
value), T9 (audit).

---

## 4. Things this model says are already right

Worth recording so they are not "improved" later by someone who has not read
this:

- **The auth cache is keyed by the token.** Any other key — IP, session id,
  path — leaks one user's verdict to another.
- **`dt_token` is stripped before forwarding**, with a test asserting the
  upstream receives none while unrelated cookies survive. The identity header
  needs the mirror of exactly this.
- **Four outcomes, not two.** Reading `authenticated` alone would have made the
  gate satisfiable with *any* cookie named `dt_token`, because DeepWitya answers
  `authenticated: true` to every caller when its own auth is off. The gate reads
  `enabled` as well. This was found by pointing it at a real DeepWitya rather
  than a stub, and it is the kind of thing a rewrite silently loses.
- **`openmaic-embed.ts` rejects dangerous studio URLs** (`javascript:` and
  friends) with a test. The studio URL is operator-supplied, so this is the
  right place for it.

---

## 5. Checks run, and what is still open

### Run

**Every `NEXT_PUBLIC_` variable in the studio was enumerated** — these are
compiled into the public browser bundle, so each one is readable by any visitor:

```
NEXT_PUBLIC_ENABLE_PPTX_IMPORT          NEXT_PUBLIC_PERSISTENCE
NEXT_PUBLIC_ENABLE_VIDEO_EXPORT         NEXT_PUBLIC_PERSISTENCE_TOKEN   ← the only secret-shaped one
NEXT_PUBLIC_MAIC_EDITOR_ENABLED         NEXT_PUBLIC_PI_CHAT_ENABLED
NEXT_PUBLIC_MAIC_EDITOR_RENDERER_ENABLED  NEXT_PUBLIC_PRO_WORKBENCH_ENABLED
NEXT_PUBLIC_MAIC_PLAYBACK_RENDERER_ENABLED NEXT_PUBLIC_SHOW_VOCATIONAL_TEST_UI
NEXT_PUBLIC_MAIN_SITE_ORIGIN            NEXT_PUBLIC_VIDEO_EXPORT_CTA_DESTINATION
```

Good news for the scope of T3: eleven of the twelve are feature flags or
origins. The public-bundle exposure is bounded to
`NEXT_PUBLIC_PERSISTENCE_TOKEN`, which T3 already covers, rather than being a
habit spread across the codebase.

**A secret scan over the studio checkout** returned only hits inside
`.pnpm-store/` — pnpm's content-addressed cache, where base64 integrity hashes
beginning `SK`/`sK` match the Twilio-key pattern. **All false positives**, and
that directory is already ignored by the local `.gitignore` edit. No secret was
found in tracked source.

### Still open

**The scan over this repository** returned 1,551 raw hits, 85 outside
`node_modules` / `.next` / `.venv`. Triaged, none is a repository leak:

| finding | verdict |
|---|---|
| `data/system/user-secrets/local-admin/private/mcp/google-maps.json` — a real Google Cloud API key | **not a leak.** Untracked, matched by `.gitignore:9 data/`, and `git log --all` shows nothing under `data/system/user-secrets/` was ever committed. It is a live key on the developer's disk, in the directory built to hold it |
| passwords in `tests/multi_user/test_login_username_contract.py` and two other test files | fixtures |
| a connection string in `web/tests/runtime-status.test.ts` | fixture |
| "Twilio API Key" throughout `pnpm-lock.yaml`, `web/package-lock.json` | false positives — base64 integrity hashes beginning `SK`/`sK` |

The one action worth taking is unrelated to this integration: that Google key is
real and lives unencrypted in a workspace directory, so it is worth confirming
it is scoped and still wanted.
- The PostgreSQL boundary (B5) has had only the ownership question asked of it —
  not connection secrets, not encryption at rest, not who can reach 5432. It
  will hold every user's course content, so it deserves its own pass.
- ~~**T6's hostname assumption is unverified.**~~ **Answered 2026-09-10.** One
  origin, no domain, seven paths, neighbours owned by another team, and
  `SameSite=None` on top. See T6.
- No dependency/CVE audit of the studio's tree. Upstream's most recent commit at
  the time of writing was `fix(ssrf): keep cloud metadata endpoints blocked
  under ALLOW_LOCAL_NETWORKS` — evidence that this class of issue is live in
  that codebase, and that following their releases has a security value beyond
  features.

---

## Round 2 — reviewed against the built image, 2026-09-10

The first pass modelled a design. This one read the running artefacts: the image
that `docker build` actually produced, the compose file as `docker compose
config` renders it, and the embed component as it ships. Four findings, and four
things that were assumed and are now measured.

### T10 — `dt_token` is `SameSite=None` in production (DREAD 7.6)

`deeptutor/api/routers/auth.py:31` — `_SAMESITE = "none" if _SECURE else "lax"`.
The comment above it justifies `None` by a **development** case: a frontend on
`127.0.0.1` and a backend on `localhost` are different origins. The code applies
`None` on the opposite branch — in production, behind nginx, where both are one
origin and the case does not arise. Production therefore ships the weaker value
for a reason that only holds where the stronger one is already used.

`SameSite=None` attaches the session cookie to every cross-site request to this
origin, which is the CSRF surface `Lax` exists to remove. The studio embed does
not need it: the built image bakes `frame-ancestors 'self'` and the deployment
is same-origin, so the frame carries the cookie under `Lax` unchanged.

**Control:** `Lax` in production. This is phase-1 item 6, and the evidence it
was waiting for now exists.

### T11 — the same-origin embed removes every browser boundary (DREAD 5.4)

Scored lower than it reads. Same origin means the studio can reach this app's
`localStorage`, `sessionStorage`, IndexedDB and DOM, and can navigate the top
window. What that is worth was measured rather than assumed: this app writes one
localStorage key (`deeptutor-theme`), keeps no PocketBase auth store in the
browser, and `dt_token` is HttpOnly — so the drawer the studio can open is
nearly empty, and the one thing worth taking is not in it.

**Control:** none needed today; the measurement is the control, and it has to be
re-taken whenever this app starts storing something in the browser. A `sandbox`
attribute would still block top-level navigation even alongside
`allow-same-origin`, and is worth testing once the stack runs — the component's
comment argues against `sandbox` without considering that flag.

### T12 — this app sets no Content-Security-Policy at all (DREAD 5.0)

Not specific to the studio, but it is the layer that would contain one. There is
no `Content-Security-Policy` header anywhere in `web/` or the API — no
`frame-src`, no `script-src`. The studio sets its own; the host sets none.

### T13 — the gate had no healthcheck (DREAD 4.2) — **closed**

The gatekeeper is the only service published to the host, so nginx forwarded to
it whether or not it was alive, and a crashed gate was a 502 with nothing
anywhere naming the container as the reason. It exposes
`/__gatekeeper/health`; compose now probes it. Memory limits, log rotation and
`no-new-privileges` were added to all three services in the same pass.

### Measured, not assumed

| claim | how it was checked |
|---|---|
| `frame-ancestors 'self'` is compiled at build, not read at runtime | `routes-manifest.json` inside the built image carries it |
| `basePath` reaches the image | same manifest: `basePath = "/deepwitya/studio"` |
| the studio does not run as root | `id` in the image: `uid=1001(nextjs)` |
| there is no `postMessage` between the two apps | searched; ADR-0005's rejection of two-way binding is honoured in the code |
| the embed URL cannot be turned into script execution | `normalizeEmbedUrl` rejects `//host`, and any protocol but http/https |

### T2 — closed by measurement, 2026-09-10

The client-supplied identity header (DREAD 8.8) was argued closed by reading
`stripHeader` and by a stub test. It is now closed by running it: the real
gatekeeper container in front of the real studio container, asked for one asset
six ways. Another account's cookie carrying `x-deeptutor-owner: user:alice`
answered **404**, and no cookie carrying the same header answered **401**. The
identity the studio acts on is the one the gate verified, or the request does
not arrive. Reproduction in `deploy/openmaic-gatekeeper/README.md`.
