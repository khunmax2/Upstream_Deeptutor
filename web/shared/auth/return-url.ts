import { BASE_PATH, withBasePath } from "@/lib/basePath";

const RETURN_URL_BASE = "https://deeptutor.invalid";

/**
 * Drop the reverse-proxy subpath from a browser pathname.
 *
 * `window.location.pathname` carries BASE_PATH, but the `next` parameter must
 * NOT: the login page feeds it to `router.replace()`, and the Next router adds
 * BASE_PATH itself. The middleware already emits a stripped `next` (Next strips
 * BASE_PATH before proxy.ts sees the request), so stripping here keeps the
 * client-side and server-side redirects producing the same shape.
 */
function stripBasePath(pathname: string): string {
  if (!BASE_PATH) return pathname;
  if (pathname === BASE_PATH) return "/";
  if (pathname.startsWith(`${BASE_PATH}/`)) return pathname.slice(BASE_PATH.length);
  return pathname;
}

export interface BrowserLocationParts {
  pathname: string;
  search?: string;
  hash?: string;
}

/** Return a same-origin application path or the supplied safe fallback. */
export function normalizeInternalReturnPath(
  raw: string | null | undefined,
  fallback = "/",
): string {
  const candidate = String(raw ?? "").trim();
  if (
    !candidate.startsWith("/") ||
    candidate.startsWith("//") ||
    candidate.includes("\\") ||
    /[\u0000-\u001f\u007f]/.test(candidate)
  ) {
    return fallback;
  }

  try {
    const parsed = new URL(candidate, RETURN_URL_BASE);
    if (parsed.origin !== RETURN_URL_BASE) return fallback;
    const decodedPath = decodeURIComponent(parsed.pathname);
    if (
      decodedPath.startsWith("//") ||
      decodedPath.includes("\\") ||
      /[\u0000-\u001f\u007f]/.test(decodedPath)
    ) {
      return fallback;
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return fallback;
  }
}

export function browserReturnPath(location: BrowserLocationParts): string {
  return normalizeInternalReturnPath(
    `${stripBasePath(location.pathname)}${location.search ?? ""}${location.hash ?? ""}`,
  );
}

export function loginHref(returnPath: string): string {
  const query = new URLSearchParams({
    next: normalizeInternalReturnPath(returnPath),
  });
  // Assigned straight to window.location, which does NOT apply basePath the way
  // the Next router does — so the prefix has to be added here or the browser
  // leaves the app entirely and the reverse proxy answers 404.
  return `${withBasePath("/login")}?${query.toString()}`;
}

/**
 * Server redirects cannot read a fragment. Browsers retain it on the login
 * URL, so carry that fragment into a validated destination that lacks one.
 */
export function inheritLoginHash(returnPath: string, loginHash: string): string {
  const safe = normalizeInternalReturnPath(returnPath);
  if (!loginHash || safe.includes("#")) return safe;
  const hash = loginHash.startsWith("#") ? loginHash : `#${loginHash}`;
  return normalizeInternalReturnPath(`${safe}${hash}`);
}
