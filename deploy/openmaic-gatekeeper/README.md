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

## Three outcomes, not two

"Authorized" and "not authorized" are the easy pair. The third is that the
checker could not be reached, and answering `401` there tells a signed-in reader
they are signed out and sends them to a login page that will not help.

| condition | status | code |
|---|---|---|
| no session cookie | 401 | `not_signed_in` |
| cookie present, session rejected | 401 | `session_invalid` |
| DeepTutor unreachable | **503** | `auth_unavailable` |
| `DEEPTUTOR_AUTH_URL` unset | 500 | `gatekeeper_misconfigured` |
| OpenMAIC unreachable | 502 | `upstream_unreachable` |

Fail-closed throughout — including the misconfigured case, which refuses rather
than passing everything through.

## Configuration

| variable | default | |
|---|---|---|
| `PORT` | `10330` | listen port |
| `OPENMAIC_UPSTREAM` | `http://127.0.0.1:3000` | where OpenMAIC is |
| `DEEPTUTOR_AUTH_URL` | — | **required**; DeepTutor's `/api/auth/status` |
| `COOKIE_NAME` | `dt_token` | session cookie to check |
| `AUTH_CACHE_TTL_MS` | `30000` | how long one verdict is reused |
| `LOGIN_URL` | — | included in the refusal message |
| `ALLOW_ANONYMOUS` | — | `1` turns the gate off, for local development only |

`AUTH_CACHE_TTL_MS` is a real trade. One page load is fifty to a hundred
requests; verifying each would make DeepTutor's auth endpoint this app's
bottleneck. The TTL is the window in which a just-logged-out session still
reaches OpenMAIC. Thirty seconds buys a hundredfold reduction in auth calls; set
it to `0` if that window matters more than the load.

## Running it

```bash
node deploy/openmaic-gatekeeper/gatekeeper.mjs
node deploy/openmaic-gatekeeper/gatekeeper.test.mjs   # 12 checks, no services needed
```

The test runs against stubs rather than live services on purpose: pointed at a
real DeepTutor it could only ever confirm the happy path, and a gate that has
never been observed refusing anything is not a gate.

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
