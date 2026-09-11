# OpenMAIC gatekeeper

A small process that stands in front of the embedded OpenMAIC and refuses
anything that is not a signed-in DeepTutor session.

```
browser ──► nginx :443 /deepwitya/studio ──► gatekeeper ──► OpenMAIC container
            (TLS, loopback hop)             │           (no published port)
                                            └─► DeepTutor /api/auth/status
```

## Why it exists

Framing OpenMAIC does not protect it. The frame's requests go to OpenMAIC's own
origin and never pass through `web/proxy.ts`, so anyone who learns that address
reaches the app directly — measured, not assumed: a plain `GET` with no cookie
answered `200`.

The usual answer, nginx `auth_request`, is not available on the target host.
There is no forward-auth anywhere in its config; DeepTutor does its own auth in
Next middleware. So the gate is a process we own instead.

## What makes it cheap

DeepTutor sets `dt_token` as a **host-only** cookie with `path=/` and
`SameSite=None; Secure`, and cookies ignore the port. A request to OpenMAIC on
any port of the same host therefore already carries it.

That is a leak — an application that should not hold a DeepTutor session token
receives one on every request. This process turns it into the mechanism *and*
closes it: it reads the cookie to decide, then **strips it before forwarding**,
so OpenMAIC never sees the token. Verified by a test that asserts the upstream
receives no `dt_token` while unrelated cookies survive.

## Four outcomes, not two

"Authorized" and "not authorized" are the easy pair. The third is that the
checker could not be reached, and answering `401` there tells a signed-in reader
they are signed out and sends them to a login page that will not help.

The fourth is that DeepTutor has no authentication to check against — see below.

| condition | status | code |
|---|---|---|
| no session cookie | 401 | `not_signed_in` |
| cookie present, session rejected | 401 | `session_invalid` |
| session valid, account is the `learner` preset | **403** | `account_restricted` |
| DeepTutor unreachable | **503** | `auth_unavailable` |
| **DeepTutor auth switched off** | **503** | `auth_disabled_upstream` |
| `DEEPTUTOR_AUTH_URL` unset | 500 | `gatekeeper_misconfigured` |
| OpenMAIC unreachable | 502 | `upstream_unreachable` |

Fail-closed throughout — including the misconfigured case, which refuses rather
than passing everything through.

## The case a stub could not have found

`/api/auth/status` returns `enabled` alongside `authenticated`, and with
DeepTutor's own auth switched off it answers `authenticated: true` to **every**
caller:

```
$ curl -H 'Cookie: dt_token=totally-made-up-garbage' .../api/auth/status
{"enabled":false,"authenticated":true,"user_id":"local-admin",...}
```

An earlier version of this gate read `authenticated` alone. Against a real
DeepTutor with `data/user/settings/auth.json` `{"enabled": false}` — which is the
shipped default — that made the gate mean "present any cookie called `dt_token`",
one line of JavaScript to satisfy. Measured, not reasoned about: the forged
cookie above returned `200` and reached OpenMAIC.

It failed in the honest direction too. With auth off DeepTutor never sets the
cookie, so real readers got `not_signed_in` and a link to a login page that does
not exist.

Both are the same missing check. The gate now reads `enabled` first and refuses
with `auth_disabled_upstream`, because serving OpenMAIC to everyone on the
strength of a setting nobody made *about OpenMAIC* is not a decision this process
should make silently. `ALLOW_ANONYMOUS=1` is how to say you want that on purpose.

The reason twelve green checks missed it is worth keeping: the stub returned
`{authenticated: <depends on the token>}`, which is what the code assumed. Stub
and code agreed about a case neither had seen. `gatekeeper.test.mjs` now serves
payloads copied from a live instance instead.

## Configuration

| variable | default | |
|---|---|---|
| `PORT` | `10330` | listen port |
| `OPENMAIC_UPSTREAM` | `http://127.0.0.1:3000` | where OpenMAIC is |
| `DEEPTUTOR_AUTH_URL` | — | **required**; DeepTutor's `/api/auth/status` |
| `COOKIE_NAME` | `dt_token` | session cookie to check |
| `AUTH_CACHE_TTL_MS` | `30000` | how long one verdict is reused |
| `LOGIN_URL` | — | included in the refusal message |
| `STUDIO_IDENTITY_HEADER` | `x-deeptutor-owner` | the header the uid is injected as; the studio must read the same name |
| `STUDIO_ROLE_HEADER` | `x-deeptutor-role` | the header the verified role is injected as, `admin` or `user`; stripped from the client like the identity header |
| `ALLOW_ANONYMOUS` | — | `1` turns the gate off — local development, or a DeepTutor deliberately run without auth |

`ALLOW_ANONYMOUS=1` is refused at startup, with a non-zero exit, when `NODE_ENV`
is `production` or `DEEPTUTOR_AUTH_URL` points anywhere but a local address. In
compose the auth URL is `http://deeptutor:…`, which is a container and not a
local address, so the gate cannot be switched off there by setting one variable —
which is the intended answer in a deployment.

`AUTH_CACHE_TTL_MS` is a real trade. One page load is fifty to a hundred
requests; verifying each would make DeepTutor's auth endpoint this app's
bottleneck. The TTL is the window in which a just-logged-out session still
reaches OpenMAIC. Thirty seconds buys a hundredfold reduction in auth calls; set
it to `0` if that window matters more than the load.

## Running it

```bash
node deploy/openmaic-gatekeeper/gatekeeper.mjs
node deploy/openmaic-gatekeeper/gatekeeper.test.mjs   # 31 checks, no services needed
```

In a deployment it is a compose service rather than a command — the source is
mounted read-only into `node:22-alpine`, because it imports only `node:`
builtins and so has nothing to install:

```bash
OPENMAIC_IMAGE=ghcr.io/khunmax2/openmaic@sha256:… \
OPENMAIC_POSTGRES_PASSWORD=… \
  docker compose -f docker-compose.yml -f deploy/docker-compose.openmaic.yml up -d
```

Both variables are required with no default. A floating `:latest` would let two
hosts run different code while both look correctly configured, and a development
password in a file that ships to the deploy host is how a weak password reaches
production without anyone choosing one.

The test runs against stubs so that every refusal path is exercised — a real
DeepTutor cannot be made unreachable, or made to reject a token, on demand, and a
gate never observed refusing anything is not a gate.

But stubs alone are how the `enabled` hole survived. **Both are needed**, and the
live check is the one that finds what the stub author did not know:

```bash
deeptutor serve --port 8099
PORT=4902 OPENMAIC_UPSTREAM=http://127.0.0.1:4901 \
  DEEPTUTOR_AUTH_URL=http://127.0.0.1:8099/api/auth/status \
  node deploy/openmaic-gatekeeper/gatekeeper.mjs
curl -i -H 'Cookie: dt_token=totally-made-up-garbage' http://127.0.0.1:4902/
```

Check the process actually bound its port before believing the result. A dead
gatekeeper and a permissive one are indistinguishable from `curl` alone, and an
`EADDRINUSE` against a still-running older copy reads exactly like "the fix did
nothing" — which is how this test was first misread.

## TLS, and the one thing that needs a hand

A path on `:443`, not a second port. The deploy host opens 443 and nothing else,
and opening one is a security decision that is not ours to take; the certificate
also has a single `IP Address:` SAN and no DNS name, so a second hostname is not
available either. nginx already owns the certificate and its renewal timer, so it
matches `location /deepwitya/studio/` and forwards to this process on loopback —
which is why the compose overlay publishes the gate as `127.0.0.1:10330` and
never on `0.0.0.0`.

That location block is the one step someone adds with `sudo`, alongside the
block that already serves DeepWitya (today `deploy/nginx-deepwitya2.locations.conf`,
written while the second stack was being validated under `/deepwitya2`).

The consequence is that the studio and DeepWitya share an origin, which is what
makes the embed work without any cross-origin cookie relaxation — and also what
puts `dt_token` within reach of the other applications on that host, measured and
scored as T6 in
`docs/planning/openmaic-integration/THREAT_MODEL_course_studio.md`.

## What this does not solve

`dt_token` stays readable by anything else on the same host, because cookies are
scoped by host and path and ignore the port. This process keeps the token away
from OpenMAIC; it cannot keep it away from a third application deployed beside
them — and it is not five neighbours but seven paths, owned by another team, with
`SameSite=none` in production, so *any* website can make a browser attach the
token to a request against that host. Measured, scored and decided as T6 in
`docs/planning/openmaic-integration/THREAT_MODEL_course_studio.md`: `SameSite=Lax`
in production is phase 1's control, and a real domain with a host-only cookie on
its own subdomain stays the structural fix.

## Proving the chain, without a DeepWitya

The 31 checks in `gatekeeper.test.mjs` exercise this file against stubs. What
they cannot show is the real gatekeeper container talking to the real studio
container, which is the seam that carries the whole design. That was run on
2026-09-10 and is reproducible in about a minute — a stub stands in for
DeepWitya's `/api/auth/status`, because what is under test is the hop after it.

```bash
# a stub that answers the way /api/auth/status answers, keyed by cookie
cat > /tmp/stub-auth.mjs <<'JS'
import { createServer } from 'node:http';
const USERS = { 'alice-token': 'alice', 'bob-token': 'bob' };
createServer((req, res) => {
  const m = /(?:^|;\s*)dt_token=([^;]+)/.exec(req.headers.cookie || '');
  const uid = m ? USERS[decodeURIComponent(m[1])] : undefined;
  res.writeHead(200, { 'content-type': 'application/json' });
  res.end(JSON.stringify(uid
    ? { enabled: true, authenticated: true, user_id: uid, username: uid }
    : { enabled: true, authenticated: false, user_id: null }));
}).listen(8001, '0.0.0.0');
JS

docker run -d --name stub-auth --network <net> --network-alias deeptutor   -v /tmp:/w:ro node:22-alpine node /w/stub-auth.mjs
```

Then start the gatekeeper against it and ask for one asset six ways. On Windows,
`MSYS_NO_PATHCONV=1` before every `docker` line — Git Bash rewrites `-v /w` and
any argument beginning with `/` into a Windows path.

| request | answer |
|---|---|
| no cookie | 401 `not_signed_in` |
| the owner's cookie | 200, the bytes |
| another account's cookie | 404 `ASSET_NOT_FOUND` |
| a cookie that verifies against nothing | 401 `session_invalid` |
| **another account's cookie plus `x-deeptutor-owner` claiming to be the owner** | **404** |
| **no cookie plus that header** | **401** |

The last two are T2. A client's own copy of the identity header changes nothing:
the gate strips it, and what the studio sees is the identity the gate verified,
or the request never arrives.
