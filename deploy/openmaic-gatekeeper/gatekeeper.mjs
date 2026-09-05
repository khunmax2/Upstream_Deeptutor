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
const LOGIN_URL = process.env.LOGIN_URL || '';
const ALLOW_ANONYMOUS = process.env.ALLOW_ANONYMOUS === '1';
const AUTH_TIMEOUT_MS = 5_000;

/**
 * One page load is fifty to a hundred requests. Asking DeepTutor to verify each
 * one would turn its auth endpoint into this app's bottleneck, so a verdict is
 * reused briefly. The TTL is the window in which a logged-out session still
 * reaches OpenMAIC; thirty seconds trades that for not amplifying every asset
 * request into an auth call.
 */
const verdicts = new Map();

function cachedVerdict(token) {
  const hit = verdicts.get(token);
  if (!hit) return null;
  if (Date.now() > hit.expires) {
    verdicts.delete(token);
    return null;
  }
  return hit.ok;
}

function remember(token, ok) {
  verdicts.set(token, { ok, expires: Date.now() + CACHE_TTL_MS });
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
function stripCookie(header, name) {
  const kept = (header || '')
    .split(';')
    .filter((part) => part.slice(0, part.indexOf('=')).trim() !== name)
    .map((part) => part.trim())
    .filter(Boolean);
  return kept.length ? kept.join('; ') : undefined;
}

/**
 * Three outcomes, not two. "Authorized" and "not authorized" are the easy pair;
 * the third is that the checker itself could not be reached, and answering 401
 * there would tell a signed-in reader they are signed out and send them to a
 * login page that will not help. That distinction is the difference between a
 * gate that fails closed and one that fails closed *and* says why.
 */
async function verify(token) {
  const cached = cachedVerdict(token);
  if (cached !== null) return cached ? 'allow' : 'deny';

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), AUTH_TIMEOUT_MS);
  try {
    const response = await fetch(AUTH_URL, {
      headers: { cookie: `${COOKIE_NAME}=${token}` },
      redirect: 'manual',
      signal: controller.signal,
    });
    if (!response.ok) {
      remember(token, false);
      return 'deny';
    }
    const body = await response.json();
    // Unwrap either shape: the payload directly, or wrapped in `data`.
    const status = body?.data ?? body;
    const ok = status?.authenticated === true;
    remember(token, ok);
    return ok ? 'allow' : 'deny';
  } catch {
    // Deliberately not cached: a transient outage must not lock a reader out
    // for the whole TTL after the checker comes back.
    return 'unavailable';
  } finally {
    clearTimeout(timer);
  }
}

function refuse(res, status, code, message) {
  const body = JSON.stringify({ error: { code, message } });
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  });
  res.end(body);
}

function forward(req, res) {
  const cookie = stripCookie(req.headers.cookie, COOKIE_NAME);
  const headers = { ...req.headers, host: UPSTREAM.host };
  if (cookie) headers.cookie = cookie;
  else delete headers.cookie;

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

  if (ALLOW_ANONYMOUS) return forward(req, res);

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
    return refuse(
      res,
      401,
      'not_signed_in',
      LOGIN_URL
        ? `Open this through DeepTutor's Course Studio. Sign in at ${LOGIN_URL} first.`
        : "Open this through DeepTutor's Course Studio rather than directly.",
    );
  }

  const verdict = await verify(token);
  if (verdict === 'allow') return forward(req, res);
  if (verdict === 'unavailable') {
    return refuse(
      res,
      503,
      'auth_unavailable',
      'Could not reach DeepTutor to verify the session. This is not a permission problem — ' +
        'retry shortly.',
    );
  }
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
  if (!ALLOW_ANONYMOUS) {
    if (!token) return socket.destroy();
    if ((await verify(token)) !== 'allow') return socket.destroy();
  }

  const cookie = stripCookie(req.headers.cookie, COOKIE_NAME);
  const headers = { ...req.headers, host: UPSTREAM.host };
  if (cookie) headers.cookie = cookie;
  else delete headers.cookie;

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

server.listen(PORT, () => {
  console.log(`[gatekeeper] listening on :${PORT} -> ${UPSTREAM.origin}`);
  console.log(`[gatekeeper] cookie=${COOKIE_NAME} ttl=${CACHE_TTL_MS}ms`);
  if (ALLOW_ANONYMOUS) console.warn('[gatekeeper] ALLOW_ANONYMOUS=1 — the gate is OFF');
  else if (!AUTH_URL) console.error('[gatekeeper] DEEPTUTOR_AUTH_URL unset — every request is refused');
  else console.log(`[gatekeeper] verifying against ${AUTH_URL}`);
});
