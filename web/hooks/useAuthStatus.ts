"use client";

import { useEffect, useState } from "react";
import { fetchAuthStatus } from "@/lib/auth";

export interface AuthStatusState {
  /** Whether auth is enabled on the backend. */
  enabled: boolean;
  /** Whether the current session is authenticated. */
  authenticated: boolean;
  /** Whether the authenticated user is an admin. */
  isAdmin: boolean;
  /** Stable account id for account-scoped browser state. */
  userId: string | null;
  /** False when the runtime status endpoint could not be reached. */
  statusAvailable: boolean;
  /** True until the first status fetch resolves. */
  loading: boolean;
  /**
   * Server surfaces this account may use, or null when it is unrestricted.
   *
   * `/api/auth/status` has always carried the learning policy and nothing read
   * it, so a restricted learner was still offered Co-Writer, Books, Mastery
   * Path and the rest — every one of them behind `require_learning_surface`,
   * which answers 403. The restriction only became visible as an error after
   * the learner clicked. Surfacing it here lets the navigation reflect it.
   */
  allowedSurfaces: string[] | null;
}

const INITIAL: AuthStatusState = {
  enabled: false,
  authenticated: false,
  isAdmin: false,
  userId: null,
  statusAvailable: false,
  loading: true,
  allowedSurfaces: null,
};

/**
 * Map a raw `/api/auth/status` payload to the state the UI consumes.
 *
 * Exported for tests: the `learning_policy` branch below decides whether the
 * navigation hides surfaces the account cannot reach, and that decision is
 * worth pinning down without standing up a browser and a restricted account.
 */
export function toAuthStatusState(
  status: Awaited<ReturnType<typeof fetchAuthStatus>>,
): AuthStatusState {
  return {
    enabled: Boolean(status?.enabled),
    authenticated: Boolean(status?.authenticated),
    isAdmin: status?.role === "admin",
    userId:
      typeof status?.user_id === "string" && status.user_id.trim()
        ? status.user_id
        : null,
    statusAvailable: status !== null,
    loading: false,
    // Absent policy means an ordinary account: no surface restriction at all.
    // An empty list is still a restriction, so distinguish it from null.
    allowedSurfaces: status?.learning_policy
      ? (status.learning_policy.allowed_surfaces ?? ["chat", "reading"])
      : null,
  };
}

function loadAuthStatus(): Promise<AuthStatusState> {
  return fetchAuthStatus().then(toAuthStatusState);
}

/**
 * Resolve auth state at runtime from the backend (`/api/auth/status`).
 *
 * The frontend bundle is URL- and auth-agnostic (see web/lib/api.ts): the auth
 * toggle is a runtime setting read from `data/user/settings/auth.json`, never
 * baked into the build. Components that need to know whether auth is on — to
 * show the Sign-out / Admin affordances — use this hook instead of a build-time
 * constant, so it works identically on Docker (read-only rootfs), the PyPI
 * `deeptutor start` launcher, and source dev.
 */
export function useAuthStatus(): AuthStatusState {
  const [state, setState] = useState<AuthStatusState>(INITIAL);

  useEffect(() => {
    let alive = true;
    loadAuthStatus().then((next) => {
      if (alive) setState(next);
    });
    return () => {
      alive = false;
    };
  }, []);

  return state;
}
