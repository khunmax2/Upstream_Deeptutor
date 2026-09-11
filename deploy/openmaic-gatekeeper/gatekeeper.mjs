/**
 * Auth gate in front of the embedded OpenMAIC.
 *
 * The `/maic` page frames OpenMAIC, but framing it does not protect it: the
 * frame's requests go straight to OpenMAIC's own origin and never pass through
 * `web/proxy.ts`, so anyone who learns that address reaches the app directly.
 * Measured, not assumed — a plain GET with no cookie answered 200.
 *
 * The obvious fix, nginx `auth_request`, is not available on the target host:
 * there is no forward-auth anywhere in its config and DeepTutor does its own
 * auth in Next middleware instead. So the gate lives here, as a small process
 * we own, in front of OpenMAIC's port.
 *
 * What makes it cheap is an accident of how DeepTutor sets its cookie. `dt_token`
 * is host-only with `path=/` and `SameSite=None; Secure`, and cookies ignore the
 * port — so a request to OpenMAIC on any port of the same host already carries
 * it. That is a real leak (an app that should not hold that token receives it on
 * every request) and this process closes it: it reads the cookie to decide, then
 * strips it before forwarding, so OpenMAIC never sees a DeepTutor session token.
 *
 * Deployment shape it assumes:
 *
 *   nginx :10330 (TLS, existing IP certificate)
 *     -> this process, plain HTTP on loopback
 *       -> OpenMAIC container
 *
 * nginx terminates TLS because it already owns the certificate and its renewal.
 * That does mean one server block has to be added by hand — there is no way to
 * serve HTTPS on a new port without something holding the key.
 *
 * Configuration, all via environment:
 *
 *   PORT                  listen port                      (default 10330)
 *   OPENMAIC_UPSTREAM     where OpenMAIC is                (default http://127.0.0.1:3000)
 *   DEEPTUTOR_AUTH_URL    DeepTutor's /api/auth/status     (required)
 *   COOKIE_NAME           session cookie to check          (default dt_token)
 *   AUTH_CACHE_TTL_MS     how long a verdict is reused     (default 30000)
 *   LOGIN_URL             where to send an unauthenticated reader
 *   ALLOW_ANONYMOUS       "1" disables the gate entirely   (local development)
 */

import http from 'node:http';
import net from 'node:net';

const PORT = Number(process.env.PORT || 10330);
const UPSTREAM = new URL(process.env.OPENMAIC_UPSTREAM || 'http://127.0.0.1:3000');
const AUTH_URL = process.env.DEEPTUTOR_AUTH_URL || '';
const COOKIE_NAME = process.env.COOKIE_NAME || 'dt_token';
const CACHE_TTL_MS = Number(process.env.AUTH_CACHE_TTL_MS || 30_000);

/**
 * The header that tells the studio who is asking. Server-controlled: this
 * process is the only thing allowed to set it, and any copy arriving from a
 * client is deleted before the request is forwarded.
 *
 * The value is `user:<uid>`, not a bare uid. OpenMAIC's own tests establish that
 * convention — `user:mine` and `user:foreign` for authenticated owners against
 * `anon:` for cookie-minted ones — so an authenticated owner is distinguishable
 * from an anonymous one by looking at it.
 *
 * Both sides must agree on this name. If either renames it silently nothing
 * turns red: the studio falls back to minting an anonymous owner per browser and
 * every user quietly stops seeing their own work. That is why the name is
 * asserted in check_openmaic_contract.py rather than left as a convention.
 */
const IDENTITY_HEADER = (process.env.STUDIO_IDENTITY_HEADER || 'x-deeptutor-owner').toLowerCase();
const IDENTITY_PREFIX = 'user:';
/**
 * The second half of the identity contract. The studio has one admin-only
 * surface -- the shared default credentials every account falls back to --
 * and DeepWitya is the only thing that knows who is an admin. Carried the
 * same way as the owner: stripped from the client, set from the verified
 * status, never from anything the caller sent. Values are exactly `admin` or
 * `user`; the studio treats anything else, including absence, as `user`.
 */
const ROLE_HEADER = (process.env.STUDIO_ROLE_HEADER || 'x-deeptutor-role').toLowerCase();
const LOGIN_URL = process.env.LOGIN_URL || '';
const ALLOW_ANONYMOUS = process.env.ALLOW_ANONYMOUS === '1';
const AUTH_TIMEOUT_MS = 5_000;

/**
 * Hostnames that mean "this is somebody's laptop", which is the only place the
 * gate is meant to be switched off.
 */
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]', 'host.docker.internal']);

/**
 * Whether the DeepTutor this gate verifies against looks like a local trial.
 *
 * Unparseable or unset counts as local: an unset AUTH_URL already refuses every
 * request with `gatekeeper_misconfigured`, so there is nothing to protect and
 * refusing to start would only replace a clear error with a confusing one.
 */
function authTargetIsLocal() {
  if (!AUTH_URL) return true;
  try {
    const host = new URL(AUTH_URL).hostname;
    return LOCAL_HOSTS.has(host) || host.endsWith('.local') || host.endsWith('.localhost');
  } catch {
    return true;
  }
}

/**
 * `ALLOW_ANONYMOUS=1` turns the gate off completely. It exists for a local
 * trial, and the threat model (T4) is about the copied `.env`: one inherited
 * compose override and a public deployment is serving the studio to anyone,
 * with the identity header now set by nobody and stripped from nobody.
 *
 * The control the threat model proposed was `NODE_ENV=production`. Checked
 * before implementing: **nothing sets it.** The compose file passes seven
 * variables to this service and `NODE_ENV` is not among them, and `node:22-alpine`
 * does not set it either — so that guard alone would never once have fired.
 *
 * The signal that does exist is the one the compose file already documents as
 * the difference between the two worlds:
 *
 *   local     DEEPTUTOR_AUTH_URL=http://host.docker.internal:3782/api/auth/status
 *   deployed  DEEPTUTOR_AUTH_URL=https://203.185.144.41/deepwitya/api/auth/status
 *
 * So both are honoured: `NODE_ENV=production` because it is the conventional
 * signal and costs nothing to support, and a non-local auth target because it is
 * the one that actually fires here. Either refuses to start.
 *
 * Refusing to start rather than warning is deliberate. A warning in a container
 * log is a thing nobody reads; a container that will not come up is a thing
 * somebody has to look at, and the message says exactly which of the two
 * conditions tripped it.
 */
function refuseUnsafeAnonymous() {
  if (!ALLOW_ANONYMOUS) return;
  const reasons = [];
  if (process.env.NODE_ENV === 'production') reasons.push('NODE_ENV=production');
  if (!authTargetIsLocal()) reasons.push(`DEEPTUTOR_AUTH_URL is not local (${AUTH_URL})`);
  if (!reasons.length) return;

  console.error('[gatekeeper] REFUSING TO START');
  console.error('[gatekeeper] ALLOW_ANONYMOUS=1 turns the gate off entirely, and this does not');
  console.error('[gatekeeper] look like a local trial: ' + reasons.join('; '));
  console.error('[gatekeeper] Unset ALLOW_ANONYMOUS to run gated, which is what a deployment wants.');
  process.exit(1);
}

/**
 * One page load is fifty to a hundred requests. Asking DeepTutor to verify each
 * one would turn its auth endpoint into this app's bottleneck, so a verdict is
 * reused briefly. The TTL is the window in which a logged-out session still
 * reaches OpenMAIC; thirty seconds trades that for not amplifying every asset
 * request into an auth call.
 */
const verdicts = new Map();

/**
 * Sentinel key for "is DeepTutor's auth even switched on". Cached in the same
 * map and under the same TTL as a session verdict, so an anonymous flood costs
 * one auth call per TTL rather than one per request.
 */
const MODE_KEY = '\0auth-mode';

/**
 * Returns the whole entry, not just the boolean, because phase 1 needs the uid
 * on every request and the three cheap ways to get it are all wrong: calling
 * /api/auth/status per request turns DeepTutor's auth endpoint into the studio's
 * bottleneck, which is what this cache exists to prevent; keying the uid by
 * anything but the token invites one reader's identity being served to another;
 * and resolving it from something the client sends is the spoof this gate is
 * here to stop.
 *
 * So: same key, same TTL, one more field.
 */
function cachedEntry(token) {
  const hit = verdicts.get(token);
  if (!hit) return null;
  if (Date.now() > hit.expires) {
    verdicts.delete(token);
    return null;
  }
  return hit;
}

/** The boolean alone, for the callers that only ask yes or no. */
function cachedVerdict(token) {
  const hit = cachedEntry(token);
  return hit ? hit.ok : null;
}

function remember(token, ok, uid, role, restricted = false) {
  verdicts.set(token, { ok, uid, role, restricted, expires: Date.now() + CACHE_TTL_MS });
  // The map only ever holds live sessions; sweep on write so it cannot grow
  // without bound on a host that sees many short-lived tokens.
  if (verdicts.size > 1000) {
    const now = Date.now();
    for (const [key, value] of verdicts) if (now > value.expires) verdicts.delete(key);
  }
}

function readCookie(header, name) {
  for (const part of (header || '').split(';')) {
    const eq = part.indexOf('=');
    if (eq === -1) continue;
    if (part.slice(0, eq).trim() === name) return part.slice(eq + 1).trim();
  }
  return null;
}

/** Remove one cookie from a Cookie header, preserving the rest. */
/**
 * Delete every copy of a header a client may have sent, before this process sets
 * its own. The mirror of stripCookie, and needed for the same reason.
 *
 * Written over the keys rather than as `delete headers[name]` because the object
 * is a spread of req.headers: Node lowercases what it parses, but missing a
 * differently-cased key would forward two values, most headers join with ', ',
 * and whichever end the studio's parser takes decides who you are.
 */
function stripHeader(headers, name) {
  for (const key of Object.keys(headers)) {
    if (key.toLowerCase() === name) delete headers[key];
  }
}

function stripCookie(header, name) {
  const kept = (header || '')
    .split(';')
    .filter((part) => part.slice(0, part.indexOf('=')).trim() !== name)
    .map((part) => part.trim())
    .filter(Boolean);
  return kept.length ? kept.join('; ') : undefined;
}

/**
 * Four outcomes, not two. "Authorized" and "not authorized" are the easy pair.
 * The third is that the checker itself could not be reached, and answering 401
 * there would tell a signed-in reader they are signed out and send them to a
 * login page that will not help.
 *
 * The fourth was found by pointing this at a real DeepTutor instead of a stub.
 * `/api/auth/status` carries `enabled` as well as `authenticated`, and when
 * DeepTutor's own auth is switched off it answers `authenticated: true` to
 * every caller — no cookie, junk cookie, any cookie:
 *
 *   $ curl -H 'Cookie: dt_token=totally-made-up-garbage' .../api/auth/status
 *   {"enabled":false,"authenticated":true,"user_id":"local-admin",...}
 *
 * Reading `authenticated` alone therefore turns this gate into "present any
 * cookie named dt_token", which is one line of JavaScript to satisfy. It also
 * misdiagnoses the honest case: with auth off DeepTutor never sets the cookie
 * at all, so real readers get `not_signed_in` and a login link that cannot help.
 * Both go away by reading the field that says whether there is anything to
 * verify against.
 */
async function verify(token) {
  const cached = cachedEntry(token);
  if (cached) {
    const verdict = cached.ok ? 'allow' : cached.restricted ? 'restricted' : 'deny';
    return { verdict, uid: cached.uid, role: cached.role };
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), AUTH_TIMEOUT_MS);
  try {
    const response = await fetch(AUTH_URL, {
      // A token of null is the anonymous probe: it asks only whether auth is on.
      headers: token === null ? {} : { cookie: `${COOKIE_NAME}=${token}` },
      redirect: 'manual',
      signal: controller.signal,
    });
    if (!response.ok) {
      if (token !== null) remember(token, false, undefined);
      return { verdict: 'deny' };
    }
    const body = await response.json();
    // Unwrap either shape: the payload directly, or wrapped in `data`.
    const status = body?.data ?? body;

    if (status?.enabled === false) {
      remember(MODE_KEY, false, undefined);
      return { verdict: 'auth_disabled' };
    }
    remember(MODE_KEY, true, undefined);
    if (token === null) return { verdict: 'deny' };

    const authenticated = status?.authenticated === true;
    // A restricted learning account: default-deny on every surface nobody has
    // explicitly opened to it, and nobody has opened this one. DeepWitya
    // decides that by POLICY, not by preset -- `learning_policy` is non-null
    // for the `learner` preset by default and for any account an admin
    // attached a policy to (a `custom` account can carry one), and its own
    // surface guard and sidebar read exactly that field. The first cut here
    // read the preset instead, which admitted a policied `custom` account the
    // sidebar was hiding the entry from. The sidebar hides; refusing here
    // closes the door the hidden entry led to, since a URL is not a menu.
    // Decided 2026-09-11.
    const restricted =
      authenticated && (status?.learning_policy != null || status?.preset === 'learner');
    const ok = authenticated && !restricted;
    // Read the uid and role from the same answer that granted the verdict.
    // Anything else — a second call, a different cache key, a value the
    // client sends — either costs a round trip per request or hands identity
    // to the caller.
    const uid = ok ? String(status?.user_id ?? '').trim() : '';
    const role = ok && (status?.is_admin === true || status?.role === 'admin') ? 'admin' : 'user';
    remember(token, ok, uid || undefined, role, restricted);
    return { verdict: ok ? 'allow' : restricted ? 'restricted' : 'deny', uid: uid || undefined, role };
  } catch {
    // Deliberately not cached: a transient outage must not lock a reader out
    // for the whole TTL after the checker comes back.
    return { verdict: 'unavailable' };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Whether DeepTutor's auth is on, for the no-cookie path. Answers from cache
 * when it can, so an anonymous flood does not become an auth call per request.
 */
async function authIsEnabled() {
  const cached = cachedVerdict(MODE_KEY);
  if (cached !== null) return cached;
  const { verdict } = await verify(null);
  if (verdict === 'auth_disabled') return false;
  if (verdict === 'unavailable') return null;
  return true;
}

function refuse(res, status, code, message) {
  const body = JSON.stringify({ error: { code, message } });
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  });
  res.end(body);
}

function refuseRestricted(res) {
  return refuse(
    res,
    403,
    'account_restricted',
    'This account is a learning account and the Course Studio is not part of what it can use. ' +
      'Ask an administrator if you need it.',
  );
}

function refuseUnavailable(res) {
  return refuse(
    res,
    503,
    'auth_unavailable',
    'Could not reach DeepTutor to verify the session. This is not a permission problem — retry shortly.',
  );
}

/**
 * Refusing here is the deliberate choice. DeepTutor with auth off has no
 * sessions to check, so serving OpenMAIC anyway would mean serving it to the
 * whole internet on the strength of a setting nobody made about OpenMAIC. If
 * that is genuinely what is wanted, `ALLOW_ANONYMOUS=1` says so out loud.
 */
function refuseAuthDisabled(res) {
  return refuse(
    res,
    503,
    'auth_disabled_upstream',
    "DeepTutor has authentication switched off, so this gate cannot identify anyone and will " +
      'not serve OpenMAIC openly by accident. Enable auth in DeepTutor, or set ALLOW_ANONYMOUS=1 ' +
      'here to serve OpenMAIC without a gate on purpose.',
  );
}

/**
 * `ownerId` is the verified uid, or undefined when nothing verified one — which
 * is the ALLOW_ANONYMOUS path. Undefined sends **no** identity header at all
 * rather than an empty one, so the studio falls back to its own anonymous owner
 * instead of being handed a blank identity it might treat as a name.
 *
 * Strip before set, always, including on the anonymous path: a client-supplied
 * copy is exactly the hole this header exists to close, and leaving it in place
 * when the gate is off would make ALLOW_ANONYMOUS a spoofing tool rather than a
 * development convenience.
 */
function forward(req, res, ownerId, role) {
  const cookie = stripCookie(req.headers.cookie, COOKIE_NAME);
  const headers = { ...req.headers, host: UPSTREAM.host };
  if (cookie) headers.cookie = cookie;
  else delete headers.cookie;
  stripHeader(headers, IDENTITY_HEADER);
  stripHeader(headers, ROLE_HEADER);
  if (ownerId) headers[IDENTITY_HEADER] = `${IDENTITY_PREFIX}${ownerId}`;
  if (ownerId && role) headers[ROLE_HEADER] = role;

  const proxied = http.request(
    {
      protocol: UPSTREAM.protocol,
      hostname: UPSTREAM.hostname,
      port: UPSTREAM.port || 80,
      method: req.method,
      path: req.url,
      headers,
    },
    (upstream) => {
      res.writeHead(upstream.statusCode ?? 502, upstream.headers);
      upstream.pipe(res);
    },
  );
  proxied.on('error', (error) => {
    refuse(res, 502, 'upstream_unreachable', `OpenMAIC did not answer: ${error.message}`);
  });
  req.pipe(proxied);
}

const server = http.createServer(async (req, res) => {
  // Liveness for the container healthcheck. Answers before the gate so a
  // misconfigured DEEPTUTOR_AUTH_URL shows up as an unhealthy service rather
  // than as a container that looks fine and refuses every real request.
  if (req.url === '/__gatekeeper/health') {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ ok: true, upstream: UPSTREAM.origin, gated: !ALLOW_ANONYMOUS }));
    return;
  }

  if (ALLOW_ANONYMOUS) return forward(req, res, undefined);

  if (!AUTH_URL) {
    return refuse(
      res,
      500,
      'gatekeeper_misconfigured',
      'DEEPTUTOR_AUTH_URL is not set, so no request can be verified. Refusing rather than ' +
        'passing everything through.',
    );
  }

  const token = readCookie(req.headers.cookie, COOKIE_NAME);
  if (!token) {
    // Ask *why* there is no cookie before blaming the reader: with DeepTutor's
    // auth off there is no login to send them to, and "sign in first" would be
    // a wrong answer dressed as a helpful one.
    const enabled = await authIsEnabled();
    if (enabled === false) return refuseAuthDisabled(res);
    if (enabled === null) return refuseUnavailable(res);
    return refuse(
      res,
      401,
      'not_signed_in',
      LOGIN_URL
        ? `Open this through DeepWitya's Course Studio. Sign in at ${LOGIN_URL} first.`
        : "Open this through DeepWitya's Course Studio rather than directly.",
    );
  }

  const { verdict, uid, role } = await verify(token);
  if (verdict === 'allow') return forward(req, res, uid, role);
  if (verdict === 'restricted') return refuseRestricted(res);
  if (verdict === 'auth_disabled') return refuseAuthDisabled(res);
  if (verdict === 'unavailable') return refuseUnavailable(res);
  return refuse(
    res,
    401,
    'session_invalid',
    LOGIN_URL ? `Session expired or invalid. Sign in again at ${LOGIN_URL}.` : 'Session expired or invalid.',
  );
});

/**
 * Websockets carry the same cookie, so the same verdict applies. There is no
 * response object to write an error into once an upgrade is in flight, so a
 * refusal is a socket destroy — the client sees the connection fail, which for
 * a hot-reload or live channel is the correct outcome.
 */
server.on('upgrade', async (req, socket, head) => {
  const token = readCookie(req.headers.cookie, COOKIE_NAME);
  let ownerId;
  let role;
  if (!ALLOW_ANONYMOUS) {
    if (!token) return socket.destroy();
    const result = await verify(token);
    if (result.verdict !== 'allow') return socket.destroy();
    ownerId = result.uid;
    role = result.role;
  }

  const cookie = stripCookie(req.headers.cookie, COOKIE_NAME);
  const headers = { ...req.headers, host: UPSTREAM.host };
  if (cookie) headers.cookie = cookie;
  else delete headers.cookie;
  // The same strip-then-set as forward(). An upgrade that skipped this would be
  // a way around the header entirely, and a socket is exactly where nobody
  // thinks to look.
  stripHeader(headers, IDENTITY_HEADER);
  stripHeader(headers, ROLE_HEADER);
  if (ownerId) headers[IDENTITY_HEADER] = `${IDENTITY_PREFIX}${ownerId}`;
  if (ownerId && role) headers[ROLE_HEADER] = role;

  const upstream = net.connect(Number(UPSTREAM.port || 80), UPSTREAM.hostname, () => {
    upstream.write(
      `${req.method} ${req.url} HTTP/1.1\r\n` +
        Object.entries(headers)
          .map(([key, value]) => `${key}: ${value}\r\n`)
          .join('') +
        '\r\n',
    );
    upstream.write(head);
    upstream.pipe(socket);
    socket.pipe(upstream);
  });
  upstream.on('error', () => socket.destroy());
  socket.on('error', () => upstream.destroy());
});

refuseUnsafeAnonymous();

server.listen(PORT, () => {
  console.log(`[gatekeeper] listening on :${PORT} -> ${UPSTREAM.origin}`);
  console.log(`[gatekeeper] cookie=${COOKIE_NAME} ttl=${CACHE_TTL_MS}ms identity=${IDENTITY_HEADER}`);
  if (ALLOW_ANONYMOUS) console.warn('[gatekeeper] ALLOW_ANONYMOUS=1 — the gate is OFF');
  else if (!AUTH_URL) console.error('[gatekeeper] DEEPTUTOR_AUTH_URL unset — every request is refused');
  else console.log(`[gatekeeper] verifying against ${AUTH_URL}`);
});
