'use client';

import { BASE_PATH, withBasePath } from '@/lib/base-path';

/**
 * Teach the browser-side URL APIs about `basePath`.
 *
 * Next's `basePath` prefixes <Link>, the router and /_next/ assets. It does not
 * prefix a URL the app writes itself, and this app writes a lot of them: 74
 * `fetch('/api/...')` calls across 44 files, plus three `new EventSource(...)`,
 * with no central helper to patch. Served under a prefix, every one of them
 * leaves for the domain root instead of this app.
 *
 * Rewriting 44 files would be 44 files to re-apply on every upstream sync.
 * Rewriting the two globals they all funnel through is one.
 *
 * Nothing about this is subtle when it goes wrong, but it is easy to
 * misdiagnose: the first symptom is not a network error, it is OpenMAIC showing
 * a login box that was never configured. `/api/access-code/status` fails,
 * `AccessCodeGuard` treats an error as "locked" — the right default — and the
 * app renders a modal for an access code nobody set.
 *
 * Not patched, deliberately:
 *
 * - `XMLHttpRequest`. The only browser-side use is inside the vendored
 *   `packages/pptxgenjs`, which fetches absolute URLs.
 * - `WebSocket` and `navigator.sendBeacon`. This app calls neither.
 * - Relative paths (`api/x`). They already resolve against a page that is
 *   itself under the prefix, so prefixing them again would be wrong.
 *
 * The whole module is inert when `NEXT_PUBLIC_BASE_PATH` is unset, which is
 * every deployment that owns its domain root.
 */

/** Root-absolute paths this app owns and Next will not prefix for it. */
const OWNED = /^\/api\//;

const INSTALLED = '__openmaicBasePathBridge';

function rewritePath(pathname: string): string {
  return OWNED.test(pathname) ? withBasePath(pathname) : pathname;
}

/** Rewrite a fetch/EventSource target, leaving anything cross-origin alone. */
function rewriteTarget<T extends string | URL>(target: T): T {
  try {
    if (typeof target === 'string') {
      // Only root-absolute. A relative path resolves against the current page,
      // which already carries the prefix.
      return (target.startsWith('/') ? rewritePath(target) : target) as T;
    }
    if (target instanceof URL && target.origin === window.location.origin) {
      const pathname = rewritePath(target.pathname);
      if (pathname !== target.pathname) {
        const next = new URL(target.href);
        next.pathname = pathname;
        return next as T;
      }
    }
  } catch {
    // A malformed target is the caller's problem, not ours — hand it back
    // untouched and let the original API report it.
  }
  return target;
}

function install(): void {
  const w = window as unknown as Record<string, unknown>;
  if (w[INSTALLED]) return; // HMR and StrictMode both re-evaluate this module
  w[INSTALLED] = true;

  const nativeFetch = window.fetch.bind(window);
  window.fetch = function patchedFetch(input: RequestInfo | URL, init?: RequestInit) {
    if (typeof input === 'string' || input instanceof URL) {
      return nativeFetch(rewriteTarget(input), init);
    }
    if (input instanceof Request) {
      const rewritten = rewriteTarget(new URL(input.url));
      if (rewritten.href !== input.url) {
        return nativeFetch(new Request(rewritten.href, input), init);
      }
    }
    return nativeFetch(input, init);
  };

  const NativeEventSource = window.EventSource;
  if (NativeEventSource) {
    class PatchedEventSource extends NativeEventSource {
      constructor(url: string | URL, init?: EventSourceInit) {
        super(rewriteTarget(url), init);
      }
    }
    window.EventSource = PatchedEventSource;
  }
}

if (typeof window !== 'undefined' && BASE_PATH) {
  // At module scope, not in an effect: every caller reaches these APIs from an
  // effect or an event handler, so patching while the module is evaluated puts
  // it comfortably ahead of the first request.
  install();
}

/**
 * Renders nothing. It exists so `app/layout.tsx` — a server component — has a
 * client boundary to mount, which is what pulls this module into the browser
 * bundle at all.
 */
export function BasePathBridge() {
  return null;
}
