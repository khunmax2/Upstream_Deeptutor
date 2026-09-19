import { apiFetch, apiUrl } from "@/lib/api";

import type { AccountPreset } from "@/lib/account-presets";

export type { AccountPreset };

export interface UserRecord {
  id: string;
  username: string;
  role: "admin" | "user";
  created_at: string;
  disabled?: boolean;
  /** Avatar marker: "", "icon:<name>:<color>", or "img:<version>". */
  avatar?: string;
  preset?: AccountPreset;
  /** Fork: the primary admin, whom no other admin may demote or delete. */
  is_primary?: boolean;
  /** Fork: set while the account is in the bin (deleted, restorable, name taken). */
  deleted_at?: string | null;
  book_permission?: {
    create: boolean;
    default: "none" | "read";
    books: Record<string, "none" | "read" | "edit">;
  };
}

export interface LearnerProfile {
  age?: number;
  grade_level?: string;
  curriculum?: string;
  language?: string;
  reading_level?: string;
  explanation_style?: string;
}

export async function getLearnerProfile(
  username: string,
): Promise<LearnerProfile | null> {
  const res = await apiFetch(
    apiUrl(`/api/auth/users/${encodeURIComponent(username)}/learner-profile`),
  );
  if (!res.ok) throw new Error("Failed to fetch learner profile");
  const data = (await res.json()) as {
    learner_profile?: LearnerProfile | null;
  };
  return data.learner_profile ?? null;
}

export async function setLearnerProfile(
  username: string,
  profile: LearnerProfile,
): Promise<LearnerProfile | null> {
  const res = await apiFetch(
    apiUrl(`/api/auth/users/${encodeURIComponent(username)}/learner-profile`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    },
  );
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? "Failed to save learner profile");
  }
  const data = (await res.json()) as {
    learner_profile?: LearnerProfile | null;
  };
  return data.learner_profile ?? null;
}

export async function listUsers(): Promise<UserRecord[]> {
  const res = await apiFetch(apiUrl("/api/auth/users"));
  if (!res.ok) throw new Error("Failed to fetch users");
  return res.json();
}

/** Fork: delete moves the account to the bin; it can be restored for 30 days. */
export async function deleteUser(username: string): Promise<string> {
  const res = await apiFetch(
    apiUrl(`/api/auth/users/${encodeURIComponent(username)}`),
    {
      method: "DELETE",
    },
  );
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? "Failed to delete user");
  }
  const data = (await res.json().catch(() => ({}))) as { deleted_at?: string };
  return data.deleted_at ?? new Date().toISOString();
}

/** Fork: take an account back out of the bin, exactly as it was. */
export async function restoreUser(username: string): Promise<void> {
  const res = await apiFetch(
    apiUrl(`/api/auth/users/${encodeURIComponent(username)}/restore`),
    { method: "POST" },
  );
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? "Failed to restore user");
  }
}

/** Fork: what a purge would remove on DeepWitya's side. */
export interface AccountFootprint {
  user_id: string;
  workspace_files: number;
  workspace_bytes: number;
  grant: boolean;
  secrets_files: number;
  mcp_config: boolean;
  device_credentials: number;
  guardian_links: number;
  avatar: boolean;
  locations: string[];
}

export async function getUserFootprint(
  username: string,
): Promise<AccountFootprint> {
  const res = await apiFetch(
    apiUrl(`/api/auth/users/${encodeURIComponent(username)}/footprint`),
  );
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? "Failed to measure the account");
  }
  return ((await res.json()) as { footprint: AccountFootprint }).footprint;
}

/**
 * Fork: remove an account in the bin and everything it owns here. The
 * typed name travels as `confirm`; the server refuses a mismatch and an
 * account that is not in the bin.
 */
export async function purgeUser(
  username: string,
  confirm: string,
): Promise<AccountFootprint> {
  const res = await apiFetch(
    apiUrl(
      `/api/auth/users/${encodeURIComponent(username)}/purge?confirm=${encodeURIComponent(confirm)}`,
    ),
    { method: "DELETE" },
  );
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? "Failed to purge the account");
  }
  return ((await res.json()) as { removed: AccountFootprint }).removed;
}

export interface OrphanRecord {
  user_id: string;
  footprint: AccountFootprint;
}

/** Fork: ids that still hold data here but have no account. */
export async function listOrphans(): Promise<OrphanRecord[]> {
  const res = await apiFetch(apiUrl("/api/auth/orphans"));
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? "Failed to list leftovers");
  }
  return ((await res.json()) as { orphans: OrphanRecord[] }).orphans;
}

export async function purgeOrphan(
  userId: string,
  confirm: string,
): Promise<AccountFootprint> {
  const res = await apiFetch(
    apiUrl(
      `/api/auth/orphans/${encodeURIComponent(userId)}?confirm=${encodeURIComponent(confirm)}`,
    ),
    { method: "DELETE" },
  );
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? "Failed to purge the leftovers");
  }
  return ((await res.json()) as { removed: AccountFootprint }).removed;
}

/** Fork: shut an account or reopen it; everything it owns stays. */
export async function setUserDisabled(
  username: string,
  disabled: boolean,
): Promise<void> {
  const res = await apiFetch(
    apiUrl(`/api/auth/users/${encodeURIComponent(username)}/disabled`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ disabled }),
    },
  );
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? "Failed to update account");
  }
}

export async function setUserRole(
  username: string,
  role: "admin" | "user",
): Promise<void> {
  const res = await apiFetch(
    apiUrl(`/api/auth/users/${encodeURIComponent(username)}/role`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    },
  );
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? "Failed to update role");
  }
}

export interface CreatedUser {
  user_id: string;
  username: string;
  role: "admin" | "user";
  is_admin: boolean;
  preset: AccountPreset;
}

export async function createUser(
  username: string,
  password: string,
  preset: AccountPreset = "standard",
): Promise<CreatedUser> {
  const res = await apiFetch(apiUrl("/api/auth/users"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, preset }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const detail = data?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail) && detail.length > 0 && detail[0]?.msg
          ? String(detail[0].msg)
          : "Failed to create user";
    throw new Error(message);
  }
  return (await res.json()) as CreatedUser;
}
