import type { AuthStatus } from "@/lib/auth";

export interface SettingsAccess {
  /** False until the backend has resolved the runtime auth mode and account. */
  resolved: boolean;
  /** Admin-owned settings stay hidden on auth failures and for ordinary users. */
  hideAdminOnly: boolean;
  /** The self-service learner profile belongs only to learner accounts. */
  showLearnerOnly: boolean;
  /** Ordinary standard/custom accounts may act as authorized guardians. */
  showGuardianOnly: boolean;
  /**
   * The account carries a learning policy. Every settings router except the
   * UI-preferences read is behind `require_learning_surface`, so a category not
   * marked `learningSafe` would render, fetch, and 403. Visibility had three
   * dimensions (admin / learner / guardian) and no way to say "this account is
   * restricted" — which is how Network, Models, Knowledge Base, Chat and Memory
   * were all offered to a learner and all failed.
   */
  restricted: boolean;
}

export const PENDING_SETTINGS_ACCESS: SettingsAccess = {
  resolved: false,
  hideAdminOnly: true,
  showLearnerOnly: false,
  showGuardianOnly: false,
  restricted: false,
};

/** Convert the backend's account identity into the settings visibility model. */
export function settingsAccessFromAuthStatus(
  authStatus: AuthStatus | null,
): SettingsAccess {
  if (!authStatus) {
    return { ...PENDING_SETTINGS_ACCESS, resolved: true };
  }

  const ordinaryAuthenticatedUser = Boolean(
    authStatus.enabled && authStatus.authenticated && !authStatus.is_admin,
  );
  return {
    resolved: true,
    hideAdminOnly: Boolean(authStatus.enabled) && !authStatus.is_admin,
    showLearnerOnly:
      ordinaryAuthenticatedUser && authStatus.preset === "learner",
    // The preset alone is not enough. A standard or custom account can also
    // carry a learning policy, and `/api/multi-user/*` — everything the
    // guardian panel reads — sits behind require_learning_surface and answers
    // 403 for it. Showing the section then produced a settings page that could
    // not load at all. A restricted account is the supervised side of a
    // guardian relationship, never the supervising one.
    showGuardianOnly:
      ordinaryAuthenticatedUser &&
      !authStatus.learning_policy &&
      (authStatus.preset === "standard" || authStatus.preset === "custom"),
    restricted: Boolean(authStatus.learning_policy),
  };
}
