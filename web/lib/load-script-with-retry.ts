/**
 * Load a classic `<script>` and try again when the network drops it.
 *
 * Fork. GeoGebra's `deployggb.js` comes from geogebra.org's CDN, and from this
 * deployment's network the first connection is sometimes reset: measured
 * 2026-09-13 in a real Chrome, 2 of 12 fresh loads failed with
 * `net::ERR_CONNECTION_RESET`, and every one of them loaded on an immediate
 * second try. `components/Geogebra.tsx` used to give up on the first error, so
 * the applet stayed on "Failed to load GeoGebra" until the page was reloaded.
 *
 * Each try appends a fresh tag; a tag this helper saw fail is marked and taken
 * out before the next one, so a later lookup never mistakes it for a load in
 * flight. A try that neither loads nor errors within `timeoutMs` counts as a
 * failure instead of hanging the caller. A tag already in the document that
 * this helper did not create (another bundle, a hot reload) is waited on
 * rather than duplicated.
 *
 * It lives in its own file so the upstream component carries one call, and so
 * a test can drive it with a stand-in document.
 */

export interface LoadScriptOptions {
  /** Total tries, the first included. */
  attempts?: number;
  /** Pause before each retry, in ms; the last value repeats. */
  retryDelaysMs?: number[];
  /** Per-try limit, in ms, for a script that neither loads nor errors. */
  timeoutMs?: number;
  /** Resolve at once when this already holds (e.g. the global the script defines). */
  isReady?: () => boolean;
  /** The document to load into (a stand-in in tests). */
  doc?: Document;
  /** How to wait between tries (a no-op in tests). */
  sleep?: (ms: number) => Promise<void>;
}

const FAILED_MARK = "data-load-failed";

export async function loadScriptWithRetry(
  src: string,
  options: LoadScriptOptions = {},
): Promise<void> {
  const {
    attempts = 3,
    retryDelaysMs = [400, 1200],
    timeoutMs = 20_000,
    isReady = () => false,
    doc = document,
    sleep = (ms: number) =>
      new Promise<void>((resolve) => setTimeout(resolve, ms)),
  } = options;

  let lastError: Error | null = null;
  for (let attempt = 0; attempt < Math.max(1, attempts); attempt += 1) {
    if (isReady()) return;
    if (attempt > 0 && retryDelaysMs.length > 0) {
      const delay =
        retryDelaysMs[Math.min(attempt - 1, retryDelaysMs.length - 1)];
      if (delay > 0) await sleep(delay);
      if (isReady()) return;
    }
    try {
      await loadOnce(doc, src, timeoutMs);
      return;
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));
    }
  }
  throw lastError ?? new Error(`script failed to load: ${src}`);
}

function loadOnce(
  doc: Document,
  src: string,
  timeoutMs: number,
): Promise<void> {
  doc
    .querySelectorAll(`script[src="${src}"][${FAILED_MARK}]`)
    .forEach((node) => node.remove());
  const existing = doc.querySelector<HTMLScriptElement>(`script[src="${src}"]`);

  return new Promise<void>((resolve, reject) => {
    let settled = false;
    const settle = (node: HTMLScriptElement, error: Error | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) {
        node.setAttribute(FAILED_MARK, "");
        reject(error);
      } else {
        resolve();
      }
    };

    const script = existing ?? doc.createElement("script");
    const timer = setTimeout(
      () => settle(script, new Error(`script load timed out: ${src}`)),
      timeoutMs,
    );
    script.addEventListener("load", () => settle(script, null), { once: true });
    script.addEventListener(
      "error",
      () => settle(script, new Error(`script failed to load: ${src}`)),
      { once: true },
    );
    if (!existing) {
      script.src = src;
      script.async = true;
      doc.head.appendChild(script);
    }
  });
}
