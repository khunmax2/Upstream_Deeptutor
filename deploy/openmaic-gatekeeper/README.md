# OpenMAIC gatekeeper

A small process that stands in front of the embedded OpenMAIC and refuses
anything that is not a signed-in DeepTutor session.

```
browser ──► nginx :10330 (TLS)  ──►  gatekeeper  ──►  OpenMAIC container
                                        │
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
| `ALLOW_ANONYMOUS` | — | `1` turns the gate off — local development, or a DeepTutor deliberately run without auth |

`AUTH_CACHE_TTL_MS` is a real trade. One page load is fifty to a hundred
requests; verifying each would make DeepTutor's auth endpoint this app's
bottleneck. The TTL is the window in which a just-logged-out session still
reaches OpenMAIC. Thirty seconds buys a hundredfold reduction in auth calls; set
it to `0` if that window matters more than the load.

## Running it

```bash
node deploy/openmaic-gatekeeper/gatekeeper.mjs
node deploy/openmaic-gatekeeper/gatekeeper.test.mjs   # 21 checks, no services needed
```

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

Serving HTTPS on a new port needs something holding the certificate key. nginx
already owns the Let's Encrypt certificate and its renewal timer, so it
terminates TLS on `:10330` and forwards to this process on loopback. That is one
server block someone has to add with `sudo` — see
`deploy/nginx-openmaic.locations.conf`.

There is no way around it: a second port cannot serve HTTPS without a key, and
the alternative — giving this process read access to `/etc/letsencrypt` — is
worse.

## What this does not solve

`dt_token` stays readable by anything else on the same host, because cookies are
scoped by host and path and ignore the port. This process keeps the token away
from OpenMAIC; it cannot keep it away from a third application deployed beside
them. A real domain, and a host-only cookie on a separate subdomain, is the
structural fix — see `deploy/OPENMAIC_EMBED.md`.
