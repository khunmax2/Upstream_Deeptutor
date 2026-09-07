/**
 * Exercises every branch of the gatekeeper against a stub DeepTutor, so each
 * outcome is checked rather than inferred.
 *
 * The stub answers with payloads **copied from a real `/api/auth/status`**
 * rather than invented ones. That distinction is the whole reason this file was
 * rewritten: the first version returned `{authenticated: <depends on token>}`,
 * which is what I assumed the endpoint did. The real one carries `enabled` too,
 * and when DeepTutor's auth is switched off it answers `authenticated: true` to
 * every caller — so the original stub agreed with the original code about a
 * case neither of them had ever seen, and twelve green checks hid an open door.
 *
 *   node gatekeeper.test.mjs            # against ../gatekeeper.mjs
 *   node gatekeeper.test.mjs <path>     # against a specific copy
 */
import http from 'node:http';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const AUTH_PORT = 4801;
const UPSTREAM_PORT = 4802;
const GATE_PORT = 4803;
const OPEN_GATE_PORT = 4804;
const GOOD = 'good-token';
const TTL_MS = 200;

const here = path.dirname(fileURLToPath(import.meta.url));
const GATEKEEPER = process.argv[2] ?? path.join(here, 'gatekeeper.mjs');

// 'up' | 'down' | 'auth-off' — 'auth-off' is DeepTutor running with
// data/user/settings/auth.json { "enabled": false }, which is its default.
let mode = 'up';

/** Verbatim from a live DeepTutor with auth disabled. */
const AUTH_OFF = {
  enabled: false,
  authenticated: true,
  user_id: 'local-admin',
  username: 'local',
  role: 'admin',
  is_admin: true,
  avatar: '',
  preset: 'standard',
  learning_policy: null,
};

/** Same endpoint with auth enabled; `authenticated` then tracks the cookie. */
const authOn = (ok) => ({
  enabled: true,
  authenticated: ok,
  user_id: ok ? 'u-1' : null,
  username: ok ? 'tester' : null,
  role: ok ? 'user' : null,
  is_admin: false,
  avatar: '',
  preset: ok ? 'standard' : null,
  learning_policy: null,
});

const auth = http.createServer((req, res) => {
  if (mode === 'down') {
    req.socket.destroy();
    return;
  }
  const body =
    mode === 'auth-off' ? AUTH_OFF : authOn((req.headers.cookie || '').includes(`dt_token=${GOOD}`));
  res.writeHead(200, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
});

// Echoes what it actually received, so the cookie strip can be asserted and so
// "did this reach OpenMAIC" is answered by OpenMAIC rather than by the status.
const upstream = http.createServer((req, res) => {
  res.writeHead(200, { 'content-type': 'application/json' });
  res.end(JSON.stringify({ reachedUpstream: true, cookieSeen: req.headers.cookie ?? null }));
});

const listen = (server, port) => new Promise((r) => server.listen(port, r));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function call(cookie, port = GATE_PORT) {
  const res = await fetch(`http://127.0.0.1:${port}/anything`, {
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
  console.log(
    `  ${pass ? 'PASS' : 'FAIL'}  ${name}` +
      (pass ? '' : ` — got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)}`),
  );
}

function startGate(port, extraEnv = {}) {
  return spawn(process.execPath, [GATEKEEPER], {
    env: {
      ...process.env,
      PORT: String(port),
      OPENMAIC_UPSTREAM: `http://127.0.0.1:${UPSTREAM_PORT}`,
      DEEPTUTOR_AUTH_URL: `http://127.0.0.1:${AUTH_PORT}/api/auth/status`,
      LOGIN_URL: 'https://example.test/login',
      AUTH_CACHE_TTL_MS: String(TTL_MS),
      ...extraEnv,
    },
    stdio: 'ignore',
  });
}

await listen(auth, AUTH_PORT);
await listen(upstream, UPSTREAM_PORT);

const gate = startGate(GATE_PORT);
const openGate = startGate(OPEN_GATE_PORT, { ALLOW_ANONYMOUS: '1' });
await sleep(700);

console.log('[gatekeeper tests]');

console.log('\n  -- DeepTutor auth enabled --');

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

console.log('\n  -- DeepTutor unreachable --');

await sleep(TTL_MS * 2);
mode = 'down';
const down = await call(`dt_token=${GOOD}`);
check('auth unreachable -> 503 not 401', down.status, 503);
check('auth unreachable -> auth_unavailable', down.body?.error?.code, 'auth_unavailable');

const downAnon = await call(null);
check('auth unreachable, no cookie -> 503 not 401', downAnon.status, 503);

mode = 'up';
await sleep(TTL_MS * 2);
const recovered = await call(`dt_token=${GOOD}`);
check('recovers once auth returns', recovered.status, 200);

// The case that was open. With auth off, DeepTutor answers `authenticated:true`
// to anything, so a gate reading only that field admits a fabricated cookie.
console.log('\n  -- DeepTutor auth DISABLED (the regression) --');

mode = 'auth-off';
await sleep(TTL_MS * 2);

const forged = await call('dt_token=totally-made-up-garbage');
check('forged cookie is refused, not admitted', forged.status, 503);
check('forged cookie -> auth_disabled_upstream', forged.body?.error?.code, 'auth_disabled_upstream');
check('forged cookie never reaches OpenMAIC', forged.body?.reachedUpstream, undefined);

const offAnon = await call(null);
check('no cookie -> 503, not a login link that cannot help', offAnon.status, 503);
check('no cookie -> auth_disabled_upstream', offAnon.body?.error?.code, 'auth_disabled_upstream');

const offReal = await call(`dt_token=${GOOD}`);
check('even a real-looking token is refused', offReal.status, 503);

// ...unless someone says out loud that they want it open.
const opened = await call('dt_token=anything', OPEN_GATE_PORT);
check('ALLOW_ANONYMOUS=1 still serves it deliberately', opened.status, 200);
check('ALLOW_ANONYMOUS=1 reaches upstream', opened.body?.reachedUpstream, true);

console.log('\n  -- health --');
const health = await fetch(`http://127.0.0.1:${GATE_PORT}/__gatekeeper/health`);
check('health endpoint answers', health.status, 200);

gate.kill();
openGate.kill();
auth.close();
upstream.close();

const failed = results.filter((r) => !r).length;
console.log(failed ? `\n${failed} check(s) failed` : `\nall ${results.length} checks passed`);
process.exit(failed ? 1 : 0);
