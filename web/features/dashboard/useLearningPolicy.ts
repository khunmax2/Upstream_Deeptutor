"use client";

import { useEffect, useState } from "react";

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

  return {
    policyResolved: resolved,
    authStatus: status,
    ...learningPolicyAccessFor(status),
  };
}

/** Pure core of the hook, so the rules stay testable without React. */
export function learningPolicyAccessFor(status: AuthStatus | null): {
  learningPolicy: NonNullable<AuthStatus["learning_policy"]> | null;
  allowsLearningSurface: (surface: LearningSurface) => boolean;
} {
  // Admins manage the catalog directly and are never policy-bound, and an
  // account without a policy keeps every surface.
  const policy =
    status && !status.is_admin ? (status.learning_policy ?? null) : null;
  if (!policy) {
    return { learningPolicy: null, allowsLearningSurface: () => true };
  }
  const allowed = new Set(policy.allowed_surfaces ?? ["chat", "reading"]);
  return {
    learningPolicy: policy,
    allowsLearningSurface: (surface) => allowed.has(surface),
  };
}
