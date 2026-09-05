// Subpath the app is served under when behind a reverse proxy (e.g. "/deepwitya"),
// or "" when served at the domain root. Inlined at build time from the
// NEXT_PUBLIC_BASE_PATH build arg (exposed via next.config.js `env`).
//
// Next.js basePath auto-prefixes <Link>, the router and /_next/ assets, but NOT
// raw <img src> / next/image src / metadata icon URLs that point at /public.
// Wrap those root-absolute paths with `asset()` so they resolve under basePath.
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || "";

/** Prefix a root-absolute public asset path (e.g. "/logo.png") with BASE_PATH. */
export function asset(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${BASE_PATH}${p}`;
}

/**
 * Prefix a root-absolute app path with BASE_PATH, **idempotently**.
 *
 * Idempotency is the whole point: `apiUrl()` already applies this, and it is
 * also applied centrally inside `apiFetch`, so a path that went through
 * `apiUrl` must not get a second prefix. Anything already under BASE_PATH, or
 * any absolute URL, is returned untouched.
 */
export function withBasePath(path: string): string {
  if (!BASE_PATH) return path;
  if (!path.startsWith("/")) return path; // relative or absolute URL — leave it
  if (path === BASE_PATH || path.startsWith(`${BASE_PATH}/`)) return path;
  return `${BASE_PATH}${path}`;
}
