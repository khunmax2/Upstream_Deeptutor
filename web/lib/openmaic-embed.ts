import fs from "node:fs";
import path from "node:path";

/**
 * Where the embedded OpenMAIC app lives.
 *
 * OpenMAIC (https://github.com/THU-MAIC/OpenMAIC, MIT) is a whole second
 * application, not a library: its own Next server, its own 69 `/api/*` routes,
 * its own Postgres and render service. It deliberately is *not* merged into
 * this bundle, for two reasons that no amount of effort removes:
 *
 *   - it ships Tailwind v4 (CSS-first `@theme`) against this app's v3 JS
 *     config, and one Next app has exactly one PostCSS pipeline;
 *   - `proxy.ts` forwards every `/api/*` path to FastAPI, which would swallow
 *     all 69 of its routes.
 *
 * So it runs beside us and we frame it. Two supported shapes, and the
 * difference is a security boundary, not just plumbing:
 *
 *   "/maic-app"              a same-origin path owned by the reverse proxy.
 *                            The request never reaches Next (no route exists
 *                            here). This is the production shape: one origin,
 *                            so `dt_token` is sent normally and OpenMAIC's own
 *                            `frame-ancestors 'self'` is already satisfied with
 *                            no configuration on its side. The cost is that
 *                            `localStorage` is then shared — see the security
 *                            note in docs/reports.
 *   "http://localhost:3100"  a cross-origin dev server. Needs
 *                            ALLOWED_FRAME_ANCESTORS set on the OpenMAIC side,
 *                            and its access-code cookie (SameSite=Lax) will not
 *                            survive the frame — leave ACCESS_CODE unset there
 *                            so this app's auth gate is the only gate.
 *
 * Resolution order mirrors `backend-runtime-config.ts`: the environment wins
 * (that is how Docker supplies it), `data/user/settings/openmaic.json` is the
 * dev convenience, and absent both the feature is simply off — the page
 * explains how to turn it on rather than framing a broken URL.
 *
 * That settings file is a *fork-owned* one, and deliberately not a key inside
 * upstream's `integrations.json`. `_normalize_integrations` in
 * `deeptutor/services/config/runtime_settings.py` rebuilds that payload from a
 * hardcoded dict literal on every load *and* save, so an added key does not
 * merely fail to round-trip — it is silently deleted the next time the backend
 * touches the file. Found the hard way: a configured embed URL vanished between
 * writing it and loading the page.
 *
 * Server-only: reads the filesystem. Never import this from a client component.
 */

export interface OpenMaicEmbed {
  /** iframe src, or "" when OpenMAIC is not configured. */
  url: string;
  /** True when `url` is a path on this origin rather than an absolute URL. */
  sameOrigin: boolean;
}

const NOT_CONFIGURED: OpenMaicEmbed = { url: "", sameOrigin: false };

/** `data/` is gitignored, so a fresh clone legitimately has no settings file. */
function readSettings(): Record<string, unknown> {
  try {
    const file = path.resolve(
      process.cwd(),
      "..",
      "data",
      "user",
      "settings",
      "openmaic.json",
    );
    const parsed: unknown = JSON.parse(fs.readFileSync(file, "utf8"));
    return parsed && typeof parsed === "object"
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

/**
 * Accept only what is safe to hand to an `<iframe src>`.
 *
 * Exported for the unit tests, which is also why it takes the raw value rather
 * than reading the environment itself.
 */
export function normalizeEmbedUrl(raw: unknown): OpenMaicEmbed {
  const value = typeof raw === "string" ? raw.trim() : "";
  if (!value) return NOT_CONFIGURED;

  // "//host" is an absolute URL wearing a path's clothes: it would silently
  // leave this origin while reading like a local route. Reject, don't guess.
  if (value.startsWith("//")) return NOT_CONFIGURED;

  // Same-origin path. Trailing slashes are stripped so the caller can append
  // "/workspace" without producing a double slash.
  if (value.startsWith("/")) {
    return { url: value.replace(/\/+$/, ""), sameOrigin: true };
  }

  try {
    const parsed = new URL(value);
    // javascript: and data: in an iframe src are script execution in this
    // origin. Only ever frame http(s).
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return NOT_CONFIGURED;
    }
    return {
      url: `${parsed.origin}${parsed.pathname.replace(/\/+$/, "")}`,
      sameOrigin: false,
    };
  } catch {
    return NOT_CONFIGURED;
  }
}

/** Resolve the configured OpenMAIC embed target, or `{ url: "" }` when unset. */
export function resolveOpenMaicEmbed(
  env: Record<string, string | undefined> = process.env,
): OpenMaicEmbed {
  const fromEnv = normalizeEmbedUrl(env.DEEPTUTOR_OPENMAIC_URL);
  if (fromEnv.url) return fromEnv;

  return normalizeEmbedUrl(readSettings().embed_url);
}
