"use client";

import { useEffect, useMemo, useState } from "react";

import { fetchAuthStatus, type AuthStatus } from "@/lib/auth";

export type LearningSurface = "chat" | "reading";

export interface LearningPolicyAccess {
  /** False until `/api/auth/status` has resolved; panels stay unrendered. */
  policyResolved: boolean;
  /** The resolved account, or null when the probe failed. */
  authStatus: AuthStatus | null;
  /** Active only for a non-admin account the server restricts. */
  learningPolicy: NonNullable<AuthStatus["learning_policy"]> | null;
  /** Whether a learner-facing surface is present in the active policy. */
  allowsLearningSurface: (surface: LearningSurface) => boolean;
  /** Whether Learner Anima is reachable; see `learningPolicyAccessFor`. */
  allowsAnima: boolean;
}

/**
 * Read-only view of the server's learning policy, for the dashboards.
 *
 * The shared `CapabilityAccessContext` is an upstream file, so rather than
 * widening it this hook derives the same answer from the auth status the
 * dashboards already fetch. It is advisory only — the backend's
 * `require_learning_surface` guard remains the enforcement boundary; this just
 * stops the page mounting panels whose APIs would be denied.
 */
export function useLearningPolicy(): LearningPolicyAccess {
  const [resolved, setResolved] = useState(false);
  const [status, setStatus] = useState<AuthStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchAuthStatus().then((value) => {
      if (cancelled) return;
      setStatus(value);
      setResolved(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Memoised on the status object, not recomputed per render: consumers put
  // `allowsLearningSurface` in useCallback/useEffect dependency arrays, and a
  // fresh closure every render makes the effect that loads the dashboard
  // re-fire on its own result — a fetch loop that never leaves the skeleton.
  const access = useMemo(() => learningPolicyAccessFor(status), [status]);

  return {
    policyResolved: resolved,
    authStatus: status,
    ...access,
  };
}

/**
 * Pure core of the hook, so the rules stay testable without React.
 *
 * `allowsAnima` is the coarsest of the three and deliberately so. The pet
 * router sits behind `require_learning_surface` (`api/main.py`), and
 * `_learning_surface_for_path()` has **no mapping for `/api/v1/pet`** — so the
 * guard default-denies it for every policy-bound account, whatever that
 * policy's `allowed_surfaces` happen to say. There is no combination of
 * surfaces that opens the companion today; holding a policy at all closes it.
 * Hence `!policy`, not a lookup.
 *
 * When Anima becomes grantable the fix is here and in one line of the backend
 * map — see the round-2 report: mastery has to become assignable first, since
 * the companion is fed exclusively by mastery gates.
 */
export function learningPolicyAccessFor(status: AuthStatus | null): {
  learningPolicy: NonNullable<AuthStatus["learning_policy"]> | null;
  allowsLearningSurface: (surface: LearningSurface) => boolean;
  allowsAnima: boolean;
} {
  // Admins manage the catalog directly and are never policy-bound, and an
  // account without a policy keeps every surface.
  const policy =
    status && !status.is_admin ? (status.learning_policy ?? null) : null;
  if (!policy) {
    return {
      learningPolicy: null,
      allowsLearningSurface: () => true,
      allowsAnima: true,
    };
  }
  const allowed = new Set(policy.allowed_surfaces ?? ["chat", "reading"]);
  return {
    learningPolicy: policy,
    allowsLearningSurface: (surface) => allowed.has(surface),
    allowsAnima: false,
  };
}
