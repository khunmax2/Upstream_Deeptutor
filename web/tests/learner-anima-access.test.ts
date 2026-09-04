import test from "node:test";
import assert from "node:assert/strict";

import { learningPolicyAccessFor } from "../features/dashboard/useLearningPolicy";
import type { AuthStatus } from "../lib/auth";

/**
 * Who may see Learner Anima, and therefore who gets its tab in the Dashboard.
 *
 * The rule is coarse on purpose. The pet router sits behind
 * `require_learning_surface` in `api/main.py`, and `_learning_surface_for_path`
 * has no mapping for `/api/v1/pet` — so the guard default-denies it for every
 * policy-bound account, whatever surfaces that policy names. Holding a policy
 * at all closes the companion; no combination of `allowed_surfaces` opens it.
 *
 * This is pinned because it is exactly the kind of rule that rots quietly: the
 * day someone maps `/api/v1/pet` to a surface, these expectations should fail
 * and be rewritten deliberately rather than drift.
 */
function statusFor(
  overrides: Partial<AuthStatus> = {},
): AuthStatus {
  return {
    enabled: true,
    authenticated: true,
    user_id: "u_1",
    role: "user",
    ...overrides,
  } as AuthStatus;
}

const POLICY = {
  age_band: "13-15",
  locked_persona: "teacher",
  allowed_capabilities: ["chat", "immersive_reading"],
  default_capability: "immersive_reading",
  allowed_surfaces: ["chat", "reading"],
  reading: { allow_upload: true, material_ids: [], extensions: [] },
} as NonNullable<AuthStatus["learning_policy"]>;

test("an account with no policy keeps Anima", () => {
  const access = learningPolicyAccessFor(statusFor({ learning_policy: null }));
  assert.equal(access.allowsAnima, true);
});

test("an admin keeps Anima even while carrying a policy", () => {
  // learningPolicyAccessFor drops the policy for admins entirely — they manage
  // the catalog and are never policy-bound — and the /admin quick-action card
  // that links to /dashboard/anima depends on this staying true.
  const access = learningPolicyAccessFor(
    statusFor({ is_admin: true, role: "admin", learning_policy: POLICY }),
  );
  assert.equal(access.allowsAnima, true);
  assert.equal(access.learningPolicy, null);
});

test("any policy-bound account loses Anima, whatever its surfaces say", () => {
  for (const allowed_surfaces of [
    ["chat", "reading"],
    ["chat"],
    ["reading"],
    [],
  ]) {
    const access = learningPolicyAccessFor(
      statusFor({ learning_policy: { ...POLICY, allowed_surfaces } }),
    );
    assert.equal(
      access.allowsAnima,
      false,
      `surfaces [${allowed_surfaces.join(", ")}] must not open the companion`,
    );
  }
});

test("a policy with no explicit surface list still loses Anima", () => {
  const { allowed_surfaces: _dropped, ...withoutSurfaces } = POLICY;
  const access = learningPolicyAccessFor(
    statusFor({
      learning_policy:
        withoutSurfaces as NonNullable<AuthStatus["learning_policy"]>,
    }),
  );
  assert.equal(access.allowsAnima, false);
  // The surface fallback still applies to the other two rules.
  assert.equal(access.allowsLearningSurface("chat"), true);
  assert.equal(access.allowsLearningSurface("reading"), true);
});

test("no status at all is not a restriction", () => {
  assert.equal(learningPolicyAccessFor(null).allowsAnima, true);
});
