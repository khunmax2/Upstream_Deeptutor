/**
 * Normalize a dynamic route segment read from Next.js `useParams()`.
 *
 * `useParams()` hands back the raw pathname segment, which is still
 * percent-encoded whenever the id contains non-ASCII characters. Passing that
 * straight to an API client that encodes its arguments — as every function in
 * `lib/*-api.ts` does with `encodeURIComponent` — encodes it a second time, and
 * the backend then resolves a different id than the one in the URL:
 *
 *     partner id            เพ-อนฉ-น
 *     useParams()           %E0%B9%80%E0%B8%9E-...     (already encoded)
 *     + encodeURIComponent  %25E0%25B9%2580%25E0%25B8%259E-...
 *     backend decodes once  %E0%B9%80%E0%B8%9E-...     → 404
 *
 * Observed as a 404 on the partners endpoint with `%25E0%25B9%2580…` for a partner whose
 * id was minted before ids were forced to ASCII: its detail page could not be
 * opened, so it could not be edited or deleted from the UI either. Pure-ASCII
 * ids are unaffected — they encode to themselves, so the second pass is a
 * no-op, which is why this only ever showed up on non-Latin names.
 *
 * Decoding here is safe and idempotent for id-shaped values: a decoded id
 * contains no `%`, so a second call cannot change it. A malformed sequence (a
 * lone `%`) makes `decodeURIComponent` throw, so the raw value is returned
 * rather than crashing the page.
 */
export function decodeRouteParam(value: string | undefined | null): string {
  if (!value) return "";
  try {
    return decodeURIComponent(value);
  } catch {
    // Not a valid percent-encoded sequence — use it as-is.
    return value;
  }
}
