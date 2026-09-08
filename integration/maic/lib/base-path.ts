// Subpath this app is served under when a reverse proxy routes a prefix to it,
// or "" when it owns the domain root. Inlined at build time from the
// NEXT_PUBLIC_BASE_PATH build arg — the same variable `next.config.ts` feeds to
// Next's own `basePath`, so the two can never disagree.
//
// Next's basePath auto-prefixes <Link>, the router and /_next/ assets. It does
// NOT touch anything the app addresses by hand: `fetch('/api/...')`,
// `new EventSource('/api/...')`, or a root-absolute `src` pointing into
// /public. Those are what this module exists for.
//
// Deliberately mirrors `web/lib/basePath.ts` in the DeepTutor app, down to the
// function names, so the two halves of the product read the same way.
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || '';

/**
 * Prefix a root-absolute path with BASE_PATH, **idempotently**.
 *
 * Idempotency is load-bearing here rather than merely tidy: the fetch wrapper
 * applies this to every request, including ones whose caller already applied
 * it, and a second prefix would produce `/prefix/prefix/api/...`. Anything
 * already under BASE_PATH, and anything that is not a root-absolute path
 * (a relative path, an absolute URL, a data: URI), is returned untouched.
 */
export function withBasePath(path: string): string {
  if (!BASE_PATH) return path;
  if (!path.startsWith('/')) return path;
  if (path === BASE_PATH || path.startsWith(`${BASE_PATH}/`)) return path;
  return `${BASE_PATH}${path}`;
}

/**
 * Prefix a root-absolute /public asset path (`/avatars/x.png`, `/logos/y.svg`).
 *
 * Same operation as `withBasePath`; the separate name marks the call sites that
 * are about static files, because those are the ones a reader will otherwise
 * assume Next already handles.
 */
export const asset = withBasePath;
