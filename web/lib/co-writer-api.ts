import { apiFetch, apiUrl } from "@/lib/api";

const BASE = "/api";

export interface CoWriterDocumentSummary {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  preview: string;
}

export interface CoWriterDocument {
  id: string;
  title: string;
  content: string;
  created_at: number;
  updated_at: number;
}

/**
 * Pull the human sentence out of a FastAPI error body.
 *
 * These errors reach the page verbatim, so dumping the raw body printed
 * `Request failed (403): {"detail":"This learning account cannot use the
 * requested server surface."}` — the envelope and the status code drowning the
 * one part a reader needs. A restricted learner should no longer reach
 * Co-Writer at all now that the navigation honours the policy, but a 403 can
 * still arrive from a policy changed mid-session, and it should read like a
 * sentence when it does.
 */
async function errorMessage(res: Response): Promise<string> {
  const text = await res.text().catch(() => "");
  if (text) {
    try {
      const detail = (JSON.parse(text) as { detail?: unknown }).detail;
      if (typeof detail === "string" && detail.trim()) return detail;
    } catch {
      // not JSON — fall through to the raw body
    }
  }
  return text || res.statusText || `Request failed (${res.status})`;
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json() as Promise<T>;
}

export async function listCoWriterDocuments(): Promise<
  CoWriterDocumentSummary[]
> {
  const res = await apiFetch(apiUrl(`${BASE}/documents`), {
    cache: "no-store",
  });
  const data = await jsonOrThrow<{ documents: CoWriterDocumentSummary[] }>(res);
  return Array.isArray(data?.documents) ? data.documents : [];
}

export async function createCoWriterDocument(payload?: {
  title?: string | null;
  content?: string;
}): Promise<CoWriterDocument> {
  const res = await apiFetch(apiUrl(`${BASE}/documents`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: payload?.title ?? null,
      content: payload?.content ?? "",
    }),
  });
  return jsonOrThrow<CoWriterDocument>(res);
}

export async function getCoWriterDocument(
  docId: string,
): Promise<CoWriterDocument> {
  const res = await apiFetch(
    apiUrl(`${BASE}/documents/${encodeURIComponent(docId)}`),
    {
      cache: "no-store",
    },
  );
  return jsonOrThrow<CoWriterDocument>(res);
}

export async function updateCoWriterDocument(
  docId: string,
  payload: { title?: string | null; content?: string | null },
): Promise<CoWriterDocument> {
  const res = await apiFetch(
    apiUrl(`${BASE}/documents/${encodeURIComponent(docId)}`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: payload.title ?? null,
        content: payload.content ?? null,
      }),
    },
  );
  return jsonOrThrow<CoWriterDocument>(res);
}

export async function deleteCoWriterDocument(docId: string): Promise<boolean> {
  const res = await apiFetch(
    apiUrl(`${BASE}/documents/${encodeURIComponent(docId)}`),
    {
      method: "DELETE",
    },
  );
  const data = await jsonOrThrow<{ deleted: boolean }>(res);
  return Boolean(data?.deleted);
}

export async function importCoWriterDocx(
  file: File,
): Promise<CoWriterDocument> {
  const body = new FormData();
  body.append("file", file);
  const res = await apiFetch(apiUrl(`${BASE}/documents/import/docx`), {
    method: "POST",
    body,
  });
  return jsonOrThrow<CoWriterDocument>(res);
}

export async function exportCoWriterDocx(payload: {
  title: string;
  content: string;
}): Promise<Blob> {
  const res = await apiFetch(apiUrl(`${BASE}/documents/export/docx`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: payload.title ?? "",
      content: payload.content ?? "",
    }),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.blob();
}
