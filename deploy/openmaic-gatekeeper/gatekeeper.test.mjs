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
const ADMIN = 'admin-token-ok';
const LEARNER = 'learner-token-ok';
const CUSTOM_OPEN = 'custom-open-token-ok';
const CUSTOM_POLICIED = 'custom-policied-token-ok';
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

/**
 * Same endpoint with auth enabled; `authenticated` then tracks the cookie.
 * Three accounts, told apart by token: an ordinary user, an admin, and a
 * `learner` -- DeepWitya's restricted preset, which the gate must refuse.
 */
// `learning_policy` is what DeepWitya's own surface guard and sidebar read:
// non-null for the learner preset by default, and for any account an admin
// attached a policy to. A `custom` account can go either way.
const POLICY = { allowed_surfaces: ['chat', 'reading'] };
const ACCOUNTS = {
  [GOOD]: { user_id: 'u-1', username: 'tester', role: 'user', is_admin: false, preset: 'standard', learning_policy: null },
  [ADMIN]: { user_id: 'u-9', username: 'boss', role: 'admin', is_admin: true, preset: 'standard', learning_policy: null },
  [LEARNER]: { user_id: 'u-5', username: 'pupil', role: 'user', is_admin: false, preset: 'learner', learning_policy: POLICY },
  [CUSTOM_OPEN]: { user_id: 'u-6', username: 'tutor', role: 'user', is_admin: false, preset: 'custom', learning_policy: null },
  [CUSTOM_POLICIED]: { user_id: 'u-7', username: 'cadet', role: 'user', is_admin: false, preset: 'custom', learning_policy: POLICY },
};
const authOn = (cookieHeader) => {
  const token = Object.keys(ACCOUNTS).find((t) => cookieHeader.includes(`dt_token=${t}`));
  const account = token ? ACCOUNTS[token] : null;
  return {
    enabled: true,
    authenticated: account !== null,
    user_id: account?.user_id ?? null,
    username: account?.username ?? null,
    role: account?.role ?? null,
    is_admin: account?.is_admin ?? false,
    avatar: '',
    preset: account?.preset ?? null,
    learning_policy: account?.learning_policy ?? null,
  };
};

const auth = http.createServer((req, res) => {
  if (mode === 'down') {
    req.socket.destroy();
    return;
  }
  const body =
    mode === 'auth-off' ? AUTH_OFF : authOn(req.headers.cookie || '');
  res.writeHead(200, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
});

// Echoes what it actually received, so the cookie strip can be asserted and so
// "did this reach OpenMAIC" is answered by OpenMAIC rather than by the status.
const upstream = http.createServer((req, res) => {
  res.writeHead(200, { 'content-type': 'application/json' });
  // `identitySeen` is read straight off the request, because the thing under
  // test is what the upstream literally receives. Node joins repeated headers
  // with ', ', so a failed strip shows up here as two values in one string
  // rather than as a test that quietly checks the wrong copy.
  res.end(
    JSON.stringify({
      reachedUpstream: true,
      cookieSeen: req.headers.cookie ?? null,
      identitySeen: req.headers['x-deeptutor-owner'] ?? null,
      roleSeen: req.headers['x-deeptutor-role'] ?? null,
    }),
  );
});

const listen = (server, port) => new Promise((r) => server.listen(port, r));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function call(cookie, port = GATE_PORT, extraHeaders = {}) {
  const res = await fetch(`http://127.0.0.1:${port}/anything`, {
    headers: { ...(cookie ? { cookie } : {}), ...extraHeaders },
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

console.log('\n  -- identity header (T2, T5) --');

// The section above leaves the stub answering `enabled: false`, where every
// request is refused and none reaches the upstream to be inspected. Put auth
// back on and wait out the TTL, or these assertions would read a refusal body
// and report undefined — which is what they did before this line existed.
mode = 'up';
await sleep(TTL_MS * 2);

// The verdict and the uid come from the same answer, so an allowed request
// carries a name. `user:` is upstream's own convention for an authenticated
// owner, against `anon:` for a cookie-minted one.
const identified = await call(`dt_token=${GOOD}`);
check('verified request carries the identity', identified.body?.identitySeen, 'user:u-1');

// A client that sets the header itself does not get to choose who it is.
//
// Worth being exact about what this proves, because the obvious reading is
// wrong: it passes even with stripHeader removed. Node lowercases incoming
// header names, so the client's copy and the one set here are the same key on
// the spread object, and assignment overwrites it. What the strip actually
// defends is the case assignment cannot reach — the anonymous path below, where
// nothing is assigned because nothing was verified. Confirmed by removing the
// strip: only that assertion goes red.
const spoofed = await call(`dt_token=${GOOD}`, GATE_PORT, { 'x-deeptutor-owner': 'user:admin' });
check("a client's own value never survives", spoofed.body?.identitySeen, 'user:u-1');

// A header that is present but empty is still a header, and the studio would
// have to decide what an empty owner means. Nothing verified anyone here, so
// nothing is sent.
const openNoHeader = await call(null, OPEN_GATE_PORT);
check('ALLOW_ANONYMOUS sends no identity at all', openNoHeader.body?.identitySeen, null);

// ALLOW_ANONYMOUS turns the gate off; it must not turn the strip off with it,
// or a development convenience becomes a spoofing tool.
const openSpoof = await call(null, OPEN_GATE_PORT, { 'x-deeptutor-owner': 'user:admin' });
check('ALLOW_ANONYMOUS still strips a client header', openSpoof.body?.identitySeen, null);

// T5: the second call inside the TTL is answered from cache. Had the cache kept
// only the boolean, this one would arrive with no name.
const cachedId = await call(`dt_token=${GOOD}`);
check('a cached verdict still carries the uid', cachedId.body?.identitySeen, 'user:u-1');

console.log('\n  -- role header and the learner preset (decided 2026-09-11) --');

check('an ordinary account is forwarded as user', cachedId.body?.roleSeen, 'user');
const asAdmin = await call(`dt_token=${ADMIN}`);
check('an admin account is forwarded as admin', asAdmin.body?.roleSeen, 'admin');
check('admin identity is its own uid', asAdmin.body?.identitySeen, 'user:u-9');
const roleSpoof = await call(`dt_token=${GOOD}`, GATE_PORT, { 'x-deeptutor-role': 'admin' });
check("a client's own role never survives", roleSpoof.body?.roleSeen, 'user');
const openRole = await call(null, OPEN_GATE_PORT, { 'x-deeptutor-role': 'admin' });
check('ALLOW_ANONYMOUS strips a client role too', openRole.body?.roleSeen, null);

// The sidebar hides the studio from a learning account; the gate closes the
// door that hidden entry led to. A refusal, not a login link -- the reader is
// signed in, the account just does not include this.
const pupil = await call(`dt_token=${LEARNER}`);
check('learner preset -> 403', pupil.status, 403);
check('learner preset -> account_restricted', pupil.body?.error?.code, 'account_restricted');
check('learner never reaches OpenMAIC', pupil.body?.reachedUpstream, undefined);
const pupilAgain = await call(`dt_token=${LEARNER}`);
check('a cached learner verdict is still 403', pupilAgain.status, 403);

// The rule is the policy, not the preset: DeepWitya's own guard reads
// `learning_policy`, and an admin can attach one to a `custom` account.
const tutor = await call(`dt_token=${CUSTOM_OPEN}`);
check('a custom account without a policy is admitted', tutor.status, 200);
check('...and forwarded as user', tutor.body?.roleSeen, 'user');
const cadet = await call(`dt_token=${CUSTOM_POLICIED}`);
check('a custom account WITH a learning policy -> 403', cadet.status, 403);
check('...account_restricted, same as a learner', cadet.body?.error?.code, 'account_restricted');

console.log('\n  -- ALLOW_ANONYMOUS guard (T4) --');

/**
 * Spawns a gatekeeper and reports how it ended: 'exited' with its code, or
 * 'running' if it was still up after a moment. Reading the exit code is the
 * whole point — a warning that nobody reads is what this guard replaces.
 */
function startAndSettle(extraEnv, ms = 600) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [GATEKEEPER], {
      env: {
        ...process.env,
        PORT: '4899',
        OPENMAIC_UPSTREAM: `http://127.0.0.1:${UPSTREAM_PORT}`,
        DEEPTUTOR_AUTH_URL: `http://127.0.0.1:${AUTH_PORT}/api/auth/status`,
        ...extraEnv,
      },
      stdio: 'ignore',
    });
    const timer = setTimeout(() => {
      child.kill();
      resolve({ state: 'running' });
    }, ms);
    child.on('exit', (code) => {
      clearTimeout(timer);
      resolve({ state: 'exited', code });
    });
  });
}

// The escape hatch still works where it is meant to: a local trial.
const localAnon = await startAndSettle({ ALLOW_ANONYMOUS: '1' });
check('ALLOW_ANONYMOUS on a local target still starts', localAnon.state, 'running');

// The conventional signal. Supported even though nothing in this repository's
// compose sets it — checked before writing the guard, which is why it is not
// the only condition.
const prodAnon = await startAndSettle({ ALLOW_ANONYMOUS: '1', NODE_ENV: 'production' });
check('ALLOW_ANONYMOUS + NODE_ENV=production refuses to start', prodAnon.state, 'exited');
check('  and exits non-zero', prodAnon.code, 1);

// The signal that actually fires here: the compose file documents a remote
// https auth URL as the difference between a laptop and the server.
const remoteAnon = await startAndSettle({
  ALLOW_ANONYMOUS: '1',
  DEEPTUTOR_AUTH_URL: 'https://203.185.144.41/deepwitya/api/auth/status',
});
check('ALLOW_ANONYMOUS + a remote auth target refuses to start', remoteAnon.state, 'exited');

// The guard is about the gate being off. With the gate on, neither signal is a
// reason to refuse — a deployment is the normal case.
const prodGated = await startAndSettle({ NODE_ENV: 'production' });
check('the gate ON in production starts normally', prodGated.state, 'running');

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
