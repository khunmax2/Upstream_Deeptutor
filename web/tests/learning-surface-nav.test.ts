import test from "node:test";
import assert from "node:assert/strict";

import { toAuthStatusState } from "../hooks/useAuthStatus";
import {
  PRIMARY_NAV,
  PRIMARY_NAV_HREFS,
  SECONDARY_NAV,
  filterNavBySurfaces,
} from "../components/sidebar/nav-entries";

/**
 * A learning account is default-deny on the server: every router outside its
 * `allowed_surfaces` answers 403 through `require_learning_surface`. The
 * navigation used to ignore that entirely — `/api/auth/status` has always
 * carried the policy and nothing read it — so a learner restricted to Chat and
 * Immersive Reading was still shown Co-Writer, Books, Mastery Path, Learning
 * Space and the rest, and met the restriction only as a raw 403 body after
 * clicking one.
 *
 * This mirrors the filter SidebarNav applies, so the two cannot drift apart
 * without a failing test.
 */
function permittedHrefs(allowedSurfaces: string[] | null): string[] {
  return filterNavBySurfaces(PRIMARY_NAV, allowedSurfaces).map((e) => e.href);
}

test("an unrestricted account keeps every entry", () => {
  assert.deepEqual(permittedHrefs(null), [...PRIMARY_NAV_HREFS]);
});

test("chat + reading learner sees only the surfaces it can reach", () => {
  assert.deepEqual(permittedHrefs(["chat", "reading"]), [
    "/chat",
    "/reading",
    "/dashboard",
  ]);
});

test("dropping a surface drops its entry", () => {
  assert.deepEqual(permittedHrefs(["chat"]), ["/chat", "/dashboard"]);
  assert.deepEqual(permittedHrefs(["reading"]), ["/reading", "/dashboard"]);
});

test("an empty allow-list is a restriction, not an absent policy", () => {
  // Dashboard survives even here: it is the one page that describes the
  // restriction itself, so an account allowed nothing else can still read what
  // its plan says and who to ask.
  assert.deepEqual(permittedHrefs([]), ["/dashboard"]);
});

test("Dashboard survives a restriction — it is the restricted account's own overview", () => {
  // Verified against the running server on a `custom` account holding a
  // chat+reading policy: /dashboard renders in full, because its one required
  // call (/api/auth/status) is never guarded and every optional one degrades to
  // a stated denial. Left undeclared it was hidden from exactly the accounts
  // whose layout it exists to serve — reachable only by typing the URL.
  for (const surfaces of [["chat", "reading"], ["chat"], ["reading"], []]) {
    assert.ok(
      permittedHrefs(surfaces).includes("/dashboard"),
      `/dashboard must stay reachable with surfaces [${surfaces.join(", ")}]`,
    );
  }
});

test("Settings survives a restriction because its API is not guarded", () => {
  // Verified against the running server: /api/settings/ui answers 200 for a
  // restricted learner. Hiding it would strand them with no way to change their
  // own language or theme, so it is marked "unrestricted" rather than left
  // undeclared (which means hidden).
  const secondary = filterNavBySurfaces(SECONDARY_NAV, ["chat", "reading"]);
  assert.deepEqual(
    secondary.map((e) => e.href),
    ["/settings"],
  );
});

test("Memory and Knowledge Center are hidden — both answer 403", () => {
  // /api/memory/overview and /api/knowledge-bases were both confirmed 403 for
  // a chat+reading learner against the running server.
  const hidden = SECONDARY_NAV.filter((e) => e.surface === undefined).map(
    (e) => e.href,
  );
  assert.deepEqual(hidden, ["/memory", "/knowledge-bases"]);
});

test("an undeclared entry is hidden from a restricted learner, not shown", () => {
  // The safe direction: a feature added without deciding its surface must not
  // leak into a restricted account, where its API would 403 anyway.
  const undeclared = PRIMARY_NAV.filter((entry) => entry.surface === undefined);
  assert.ok(
    undeclared.length > 0,
    "fixture assumes some entries are undeclared",
  );
  const permitted = new Set(permittedHrefs(["chat", "reading"]));
  for (const entry of undeclared) {
    assert.equal(
      permitted.has(entry.href),
      false,
      `${entry.href} has no surface and must stay hidden`,
    );
  }
});

test("every declared surface is one the backend actually enforces", () => {
  // _learning_surface_for_path in deeptutor/api/routers/auth.py maps paths to
  // exactly these two; a third value here would silently never match.
  for (const entry of [...PRIMARY_NAV, ...SECONDARY_NAV]) {
    if (entry.surface === undefined) continue;
    assert.ok(
      ["chat", "reading", "unrestricted"].includes(entry.surface),
      `${entry.href} declares an unknown surface ${entry.surface}`,
    );
  }
});

// ── the other half of the wiring: reading the policy off /api/auth/status ──

test("a status payload with a policy yields its allowed surfaces", () => {
  const state = toAuthStatusState({
    enabled: true,
    authenticated: true,
    user_id: "u_1",
    role: "user",
    learning_policy: {
      age_band: "13-15",
      locked_persona: "teacher",
      allowed_capabilities: ["chat"],
      default_capability: "chat",
      allowed_surfaces: ["chat", "reading"],
      reading: { allow_upload: false, material_ids: [], extensions: [] },
    },
  } as Parameters<typeof toAuthStatusState>[0]);
  assert.deepEqual(state.allowedSurfaces, ["chat", "reading"]);
});

test("an ordinary account reports no restriction at all", () => {
  const state = toAuthStatusState({
    enabled: true,
    authenticated: true,
    user_id: "u_2",
    role: "user",
    learning_policy: null,
  } as Parameters<typeof toAuthStatusState>[0]);
  assert.equal(state.allowedSurfaces, null);
});

test("a policy without an explicit list falls back to chat + reading", () => {
  // Mirrors the server default in assert_learning_surface, so the navigation
  // and the guard agree on what an unspecified policy means.
  const state = toAuthStatusState({
    enabled: true,
    authenticated: true,
    user_id: "u_3",
    role: "user",
    learning_policy: {
      age_band: "13-15",
      locked_persona: "teacher",
      allowed_capabilities: ["chat"],
      default_capability: "chat",
    },
  } as Parameters<typeof toAuthStatusState>[0]);
  assert.deepEqual(state.allowedSurfaces, ["chat", "reading"]);
});

test("no status at all is not a restriction", () => {
  assert.equal(toAuthStatusState(null).allowedSurfaces, null);
});
