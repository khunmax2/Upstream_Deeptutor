/**
 * Fork: the Course Studio's half of an account purge (admin design §4,
 * Phase 2), called from the users page.
 *
 * The studio is reached on the same origin, through the gatekeeper, with the
 * admin's own session cookie: `/deepwitya/studio/api/studio/admin/accounts`.
 * The gatekeeper verifies the cookie against `/api/auth/status` and sets the
 * `x-deeptutor-primary` header only for the primary admin, so no new secret
 * and no server-to-server route is needed, and a promoted admin gets the
 * studio's own 403. `studioBase` is the same-origin embed path the server
 * resolved (`DEEPTUTOR_OPENMAIC_URL`); an empty base means no studio is
 * configured, and every call here answers `null`.
 *
 * Requests go through the shared client as a `URL` object: the studio path
 * is already absolute on this origin, so the client's base-path rewrite must
 * not touch it, and a 401 from the gatekeeper is an answer to show, not a
 * reason to leave the page.
 */

import { apiFetch } from "@/lib/api";

export interface StudioFootprint {
  ownerId: string;
  stagesRemoved: string[];
  stagesKept: string[];
  agentSessions: number;
  ownerSessionEvents: number;
  skills: number;
  folders: number;
  materials: number;
  assets: number;
  accountKv: number;
  credentials: number;
  sharedWrites: number;
}

export interface StudioPurgeSummary extends StudioFootprint {
  mediaDirectoriesRemoved: number;
  materialFilesRemoved: number;
}

/** The studio's owner id for a DeepWitya account id. */
export function studioOwnerId(userId: string): string {
  return `user:${userId}`;
}

function accountsUrl(studioBase: string, tail = ""): URL {
  const base = studioBase.replace(/\/+$/, "");
  return new URL(
    `${base}/api/studio/admin/accounts${tail}`,
    window.location.origin,
  );
}

function studioRequest(url: URL, init?: RequestInit): Promise<Response> {
  return apiFetch(url, {
    ...init,
    credentials: "include",
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
    skipAuthRedirect: true,
  });
}

async function studioError(res: Response, fallback: string): Promise<Error> {
  const data = (await res.json().catch(() => ({}))) as {
    error?: { message?: string };
  };
  return new Error(data.error?.message ?? `${fallback} (${res.status})`);
}

/** Every `user:` id the studio holds rows for. */
export async function listStudioOwners(
  studioBase: string,
): Promise<string[] | null> {
  if (!studioBase) return null;
  const res = await studioRequest(accountsUrl(studioBase));
  if (!res.ok) throw await studioError(res, "Failed to list studio accounts");
  return ((await res.json()) as { owners: string[] }).owners;
}

export async function getStudioFootprint(
  studioBase: string,
  userId: string,
): Promise<StudioFootprint | null> {
  if (!studioBase) return null;
  const res = await studioRequest(
    accountsUrl(
      studioBase,
      `/${encodeURIComponent(studioOwnerId(userId))}/footprint`,
    ),
  );
  if (!res.ok) throw await studioError(res, "Failed to measure studio data");
  return ((await res.json()) as { footprint: StudioFootprint }).footprint;
}

/** Idempotent: an id with nothing left answers zeros. */
export async function purgeStudioAccount(
  studioBase: string,
  userId: string,
): Promise<StudioPurgeSummary | null> {
  if (!studioBase) return null;
  const res = await studioRequest(
    accountsUrl(studioBase, `/${encodeURIComponent(studioOwnerId(userId))}`),
    { method: "DELETE" },
  );
  if (!res.ok) throw await studioError(res, "Failed to purge studio data");
  return ((await res.json()) as { purged: StudioPurgeSummary }).purged;
}
