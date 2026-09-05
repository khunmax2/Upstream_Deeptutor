/**
 * Exercises every branch of the gatekeeper against stubs, so each outcome is
 * checked rather than inferred: no cookie, bad token, good token, the auth
 * service being down, and — the one that matters most — whether `dt_token` is
 * actually stripped before OpenMAIC sees it.
 *
 * Stubs rather than the real services on purpose: this has to be able to fail.
 * Pointed at a live DeepTutor it could only ever confirm the happy path, and a
 * gate that has never been observed refusing anything is not a gate.
 *
 * Run: node deploy/openmaic-gatekeeper/gatekeeper.test.mjs
 */
import { spawn } from 'node:child_process';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const GATEKEEPER = process.argv[2] ?? path.join(HERE, 'gatekeeper.mjs');

const AUTH_PORT = 4801;
const UPSTREAM_PORT = 4802;
const GATE_PORT = 4803;
const GOOD = 'good-token';

let authUp = true;

const auth = http.createServer((req, res) => {
  if (!authUp) {
    req.socket.destroy();
    return;
  }
  const cookie = req.headers.cookie || '';
  const ok = cookie.includes(`dt_token=${GOOD}`);
  res.writeHead(200, { 'content-type': 'application/json' });
  res.end(JSON.stringify({ authenticated: ok, username: ok ? 'tester' : null }));
});

// Echoes back what it actually received, so the strip can be asserted.
const upstream = http.createServer((req, res) => {
  res.writeHead(200, { 'content-type': 'application/json' });
  res.end(JSON.stringify({ reachedUpstream: true, cookieSeen: req.headers.cookie ?? null }));
});

const listen = (server, port) => new Promise((r) => server.listen(port, r));

async function call(cookie) {
  const res = await fetch(`http://127.0.0.1:${GATE_PORT}/anything`, {
    headers: cookie ? { cookie } : {},
  });
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  return { status: res.status, body };
}

const results = [];
function check(name, actual, expected) {
  const pass = actual === expected;
  results.push(pass);
  console.log(`  ${pass ? 'PASS' : 'FAIL'}  ${name}${pass ? '' : ` — got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)}`}`);
}

await listen(auth, AUTH_PORT);
await listen(upstream, UPSTREAM_PORT);

const gate = spawn(process.execPath, [GATEKEEPER], {
  env: {
    ...process.env,
    PORT: String(GATE_PORT),
    OPENMAIC_UPSTREAM: `http://127.0.0.1:${UPSTREAM_PORT}`,
    DEEPTUTOR_AUTH_URL: `http://127.0.0.1:${AUTH_PORT}/api/auth/status`,
    LOGIN_URL: 'https://example.test/login',
    AUTH_CACHE_TTL_MS: '200',
  },
  stdio: 'ignore',
});
await new Promise((r) => setTimeout(r, 700));

console.log('[gatekeeper tests]');

const anon = await call(null);
check('no cookie -> 401', anon.status, 401);
check('no cookie -> not_signed_in', anon.body?.error?.code, 'not_signed_in');

const bad = await call('dt_token=nope');
check('bad token -> 401', bad.status, 401);
check('bad token -> session_invalid', bad.body?.error?.code, 'session_invalid');

const good = await call(`dt_token=${GOOD}`);
check('valid token -> 200', good.status, 200);
check('valid token reaches upstream', good.body?.reachedUpstream, true);
check('dt_token stripped before upstream', good.body?.cookieSeen, null);

const mixed = await call(`other=keep; dt_token=${GOOD}`);
check('other cookies survive the strip', mixed.body?.cookieSeen, 'other=keep');

// Let the cached verdict lapse, then take the auth service away.
await new Promise((r) => setTimeout(r, 400));
authUp = false;
const down = await call(`dt_token=${GOOD}`);
check('auth unreachable -> 503 not 401', down.status, 503);
check('auth unreachable -> auth_unavailable', down.body?.error?.code, 'auth_unavailable');

authUp = true;
await new Promise((r) => setTimeout(r, 100));
const recovered = await call(`dt_token=${GOOD}`);
check('recovers once auth returns', recovered.status, 200);

const health = await fetch(`http://127.0.0.1:${GATE_PORT}/__gatekeeper/health`);
check('health endpoint answers', health.status, 200);

gate.kill();
auth.close();
upstream.close();

const failed = results.filter((r) => !r).length;
console.log(failed ? `\n${failed} check(s) failed` : `\nall ${results.length} checks passed`);
process.exit(failed ? 1 : 0);
