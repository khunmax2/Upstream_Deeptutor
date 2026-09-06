# Pre-push audit of the OpenMAIC embed branch

**Branch** `feat/openmaic-thai-locale` · 22 commits, none pushed · 2026-09-06

The question this answers is "has all of this actually been tested, or only
asserted?" Everything below was re-run in this session. Nothing is quoted from
memory or from an earlier round's summary, because every defect found here was
hiding behind exactly that kind of quotation.

---

## Three defects found, all fixed

### 1. The gate admitted a forged cookie

`gatekeeper.mjs` decided access from `/api/auth/status`'s `authenticated` field.
That endpoint also returns `enabled`, and with DeepTutor's auth switched off it
answers `authenticated: true` to every caller regardless of cookie:

```
$ curl -H 'Cookie: dt_token=totally-made-up-garbage' .../api/auth/status
{"enabled":false,"authenticated":true,"user_id":"local-admin",...}
```

`data/user/settings/auth.json` ships with `"enabled": false`. Against such an
instance the gate meant "present any cookie named `dt_token`". Measured, not
inferred — the forged request returned `200` and reached the upstream.

It failed in the honest direction too: with auth off DeepTutor never sets the
cookie, so a real reader got `not_signed_in` and a link to a login page that does
not exist.

Fixed by reading `enabled` first and refusing with `auth_disabled_upstream`
(503). `ALLOW_ANONYMOUS=1` remains the deliberate way to serve OpenMAIC openly.

**Why twelve green checks missed it.** The stub returned
`{authenticated: <depends on the token>}` — the shape the code assumed. Stub and
code agreed about a case neither had ever seen. The suite now serves payloads
copied verbatim from a live instance: 12 checks → 21.

### 2. The nginx block would not have loaded

`nginx-openmaic.locations.conf` used `http2 on;`, the standalone directive added
in nginx 1.25. The target host runs 1.24, where it is an unknown directive and
`nginx -t` rejects the **entire** configuration — so the one step that needs
someone's `sudo` would have failed at the moment they ran it, on a live web
server.

The file had never been run through nginx. It was written to be correct rather
than checked. Now `listen 10330 ssl http2;`, passing on 1.24 and 1.27.

### 3. 0004 and 0005 did nothing at all

Both patches read query parameters — `?lang=`, `?theme=`, `?embed=1`. Nothing in
DeepTutor ever sent one. `MaicWorkspace` framed the bare URL, and
`normalizeEmbedUrl` rebuilds its result as `origin + pathname`, discarding a
query string an operator might have added. The receiving half was built and
verified; the sending half was never written.

The patches' own notes say "verified on a dev server with
`?lang=th&theme=dark&embed=1`" — true, and the reason this survived. Typing the
parameters by hand tests OpenMAIC. It does not test whether anything produces
them.

Fixed by making `MaicWorkspace` send all three from `useAppShell()`, mapping
DeepTutor's four themes onto OpenMAIC's two by what they render as, and holding
the frame back until the stored language is known so it does not load twice.

**Verified across two genuinely separate origins** — DeepTutor on
`127.0.0.1:3200`, OpenMAIC on `localhost:3100`, with `iframe.contentDocument`
blocked by the browser as proof they are separate:

| | |
|---|---|
| `lang=th` | OpenMAIC renders Thai inside the frame |
| `theme=dark`, and `snow` -> `light` | the frame follows the host both ways |
| `embed=1` | framed shows only the settings gear; the same build opened directly shows the full language/theme/settings pill |

A fourth thing this run settled: without `ALLOWED_FRAME_ANCESTORS` the frame is
blocked outright by `frame-ancestors 'self'` plus `X-Frame-Options: SAMEORIGIN`.
`deploy/docker-compose.openmaic.yml` already sets it; now the failure mode has
been seen rather than predicted.

The two known upstream i18n gaps were confirmed visually in a Thai session — the
hardcoded English persistence toast and the hardcoded Chinese dev chip.

### 4. (Process) A verification that silently measured nothing

Re-testing the gate fix against the live server appeared to show *no change* —
the forged cookie still returned `200`. The cause was `pkill` silently failing on
Windows, so the old process kept the port and the new one died on `EADDRINUSE`.
I was curling the unfixed binary.

This is the same shape as the port-publish error from the previous round: a check
that did not run, reported as a result. The habit that catches it is reading the
process's own startup output before believing its responses, and it is now
written into the gatekeeper README.

---

## Verified in this session

| what | how | result |
|---|---|---|
| nothing pushed | no upstream tracking ref | 22 commits, local only |
| working tree | `git status --porcelain` | clean |
| OpenMAIC checkout | `git rev-parse` | `d4ef5faa`, at the pin |
| all 5 patches | `git apply --check` | apply clean |
| tree guard | `check_openmaic_tree.py` | works; flags the 6 Docker files as foreign, which is correct |
| contract, offline | `check_openmaic_contract.py` | pass — pin and 1,800 keys unchanged |
| Thai coverage | `build_th_locale.py --check` | 1,689/1,800 (93.8%) |
| web node suite | `npm run test:node` | **1105/1105 pass** |
| embed unit tests | `openmaic-embed.test.ts` | 8/8 |
| i18n parity | `npm run i18n:check` | exit 0, `th`/`zh` OK |
| eslint | `npm run lint` | 0 errors; none of the new files warn |
| ruff | `check` + `format --check` | pass, 1,813 files |
| **production build** | `npm run build` | exit 0, `/maic` is `ƒ (Dynamic)` |
| published ports | `docker compose config --format json` | `openmaic` none; `gatekeeper` `127.0.0.1:10331` |
| gate vs stubs | `gatekeeper.test.mjs` | 21/21 |
| **gate vs live DeepTutor, auth off** | real backend on :8099 | refuses forged cookie, 503 |
| **gate vs live DeepTutor, auth on** | isolated `DEEPTUTOR_HOME`, real login, real JWT | no cookie 401 · forged 401 · **real token 200 with `dt_token` stripped** · unrelated cookies survive |
| **nginx config** | `nginx:1.24-alpine -t`, `1.27-alpine -t` | both pass |
| **cross-origin embed** | DeepTutor `127.0.0.1:3200` framing OpenMAIC `localhost:3100`, in a browser | `contentDocument` blocked · Thai renders in-frame · theme follows both ways · `embed=1` hides OpenMAIC's own controls |

The auth-on run used `DEEPTUTOR_HOME` pointed at a scratch directory with its own
`auth.json`, so the user's real settings were never modified — confirmed
unchanged afterwards.

`pytest` was not run. The branch touches **zero** Python application code
(`git diff --stat main..HEAD -- deeptutor/ deeptutor_cli/ deeptutor_web/ tests/
pyproject.toml` is empty); the only Python added is under
`deploy/openmaic-patches/`, which is outside `testpaths`. Ruff does cover it and
passes.

---

## Not verified, and why

1. **The stack has never run on the target host.** Everything above is local. The
   images build and the containers talk to each other, but no part of this has
   met the real nginx, the real certificate, or real users.
2. **The nginx block has not been applied.** It now passes `nginx -t` offline,
   which is what defect 2 was about; applying it still needs `sudo` on the host.
3. **Live theme/language change while `/maic` is the open page** was not
   separately exercised. Propagation was verified across a client-side
   navigation, which mounts the component with the new value; a change made
   while the panel is already open takes the same code path and reloads the
   frame, but that exact sequence was not clicked through.
4. **The workbench overlay's 247 keys are still English.** They fall back
   readably; they are not translated.
5. **No load or concurrency testing.** `AUTH_CACHE_TTL_MS` is reasoned about, not
   measured.
6. **Three questions the deploy side could not answer** remain open: who the
   users are, what compliance or data-residency rules apply, and who operates
   this after handover. Prompts already egress to OpenRouter and Google, so this
   is a real question rather than a formality.

---

## Still outstanding from earlier rounds

- **Rotate the OpenRouter and Gemini API keys** exposed in the deploy-side
  report. This is the oldest open item and the only one with a clock on it.
- Push, and the fork's own PR — held by the standing instruction to keep this
  local until testing is confirmed clean.
- Upstream PRs to THU-MAIC for the five patches, all of which are
  upstream-candidates.
- Two upstream i18n gaps to report: a hardcoded English toast
  (`app/page.tsx:291`, `lib/hooks/use-home-discovery.tsx:139`) and a hardcoded
  Chinese dev chip (`app/page.tsx:988`).

---

## What this round changes about the method

Every defect found here came from running something against a real dependency,
and every one had passed a test written against a stub. The gate's stub encoded
the author's assumption; the nginx file had no test at all; the port check used a
matcher that ended its range early.

The pattern is that a test written by the same person who wrote the code, against
a fixture that person invented, verifies agreement rather than correctness. The
stubs are still worth keeping — they exercise refusal paths a live service cannot
be made to produce on demand — but each now carries payloads copied from a live
instance, and the live check is documented alongside as the one that finds what
the stub author did not know.
