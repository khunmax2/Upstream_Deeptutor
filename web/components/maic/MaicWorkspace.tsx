"use client";

import { useState } from "react";
import { ExternalLink, GraduationCap, Loader2, PlugZap } from "lucide-react";
import { useTranslation } from "react-i18next";

import { withBasePath } from "@/lib/basePath";
import { useAppShell } from "@/context/AppShellContext";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import type { Theme } from "@/lib/theme";
import type { AppLanguage } from "@/context/app-shell-storage";

interface MaicWorkspaceProps {
  /** Resolved by the server page; "" when OpenMAIC is not configured. */
  url: string;
  /** True when `url` is a path on this origin rather than an absolute URL. */
  sameOrigin: boolean;
}

/**
 * DeepTutor has four themes; OpenMAIC has light and dark. Map by what the theme
 * actually renders as rather than by name: `glass` sets the `dark` class too, and
 * `snow` is the pure-white default. Getting this backwards would put a white
 * panel inside a dark page, which is the exact seam this work exists to remove.
 *
 * Collapsing four onto two also means `dark` -> `glass` produces no change here,
 * so the frame is not reloaded for a switch it cannot represent.
 */
function toEmbedTheme(theme: Theme): "dark" | "light" {
  return theme === "dark" || theme === "glass" ? "dark" : "light";
}

/**
 * Hand the host's language and theme to OpenMAIC as query parameters.
 *
 * This is the sending half of the arrangement OpenMAIC's `?lang=`/`?theme=`/
 * `?embed=1` support was added for. Query parameters rather than shared storage,
 * and **not** because the two apps cannot reach each other's storage — in the
 * production shape they are one origin, so the studio can read every key this
 * app writes and vice versa. The reason is narrower and survives either shape:
 * a storage key is a second contract between two applications that must then
 * stay in version step forever, while a query parameter is read once on mount
 * and cannot drift.
 *
 * What that shared origin actually exposes was measured rather than assumed:
 * this app writes exactly one localStorage key, `deeptutor-theme`, keeps no
 * PocketBase auth store in the browser, and `dt_token` is HttpOnly, so no script
 * on either side can read it.
 *
 * `embed=1` additionally tells OpenMAIC to hide its own language and theme
 * controls, since this app already renders those and two sets of them in one
 * window is how an embed announces itself as a second application.
 *
 * OpenMAIC reads all three once on mount, so changing either value changes this
 * URL and reloads the frame. That is a real cost — a course generation running
 * at that moment is lost — accepted because changing language or theme is a
 * deliberate, infrequent act, and the alternative is a panel that stays in the
 * wrong language until something else happens to reload it.
 */
function withHostPreferences(
  src: string,
  language: AppLanguage,
  theme: Theme,
  { embedded }: { embedded: boolean },
): string {
  const separator = src.includes("?") ? "&" : "?";
  const params = new URLSearchParams({
    lang: language,
    theme: toEmbedTheme(theme),
  });
  // Only the framed copy is embedded. Opening OpenMAIC in its own tab should
  // give back the controls this app is standing in for, while still landing in
  // the language and theme the reader was just using.
  if (embedded) params.set("embed", "1");
  return `${src}${separator}${params.toString()}`;
}

/**
 * The OpenMAIC course studio, framed.
 *
 * There is deliberately no `sandbox` attribute. OpenMAIC needs scripts, forms,
 * downloads, popups and its own IndexedDB to function at all, so a sandbox that
 * left it working would grant nearly everything anyway — and it is a service we
 * deploy ourselves, not third-party content. The real boundary is the reverse
 * proxy and this app's auth gate in front of it.
 */
export default function MaicWorkspace({ url, sameOrigin }: MaicWorkspaceProps) {
  const { t } = useTranslation();
  const { theme, language, languageReady } = useAppShell();
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const auth = useAuthStatus();

  // A restricted learning account: the sidebar already hides this entry
  // (nav-entries.ts leaves its surface undeclared) and the gatekeeper in
  // front of the studio refuses the account with 403 account_restricted.
  // This page can still be reached by URL, and without this branch it frames
  // that refusal as raw JSON. Same test the sidebar uses: a non-null
  // allowedSurfaces is a policy, and this surface is not on any policy.
  if (!auth.loading && auth.allowedSurfaces !== null) {
    return (
      <div className="flex h-full items-center justify-center overflow-y-auto p-6">
        <div className="max-w-lg space-y-3 text-center">
          <GraduationCap
            size={32}
            strokeWidth={1.5}
            className="mx-auto text-[var(--muted-foreground)]"
          />
          <h1 className="text-lg font-medium text-[var(--foreground)]">
            {t("The course studio is not part of this account")}
          </h1>
          <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "This is a learning account. Ask an administrator if you need to build courses.",
            )}
          </p>
        </div>
      </div>
    );
  }

  if (!url) {
    return (
      <div className="flex h-full items-center justify-center overflow-y-auto p-6">
        <div className="max-w-lg space-y-4 text-center">
          <PlugZap
            size={32}
            strokeWidth={1.5}
            className="mx-auto text-[var(--muted-foreground)]"
          />
          <h1 className="text-lg font-medium text-[var(--foreground)]">
            {t("The course studio is not connected")}
          </h1>
          <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "The course studio runs as its own service beside this app. Point this page at it, then reload — the setting is read on every request.",
            )}
          </p>
          <div className="space-y-2 rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 p-4 text-left text-xs">
            <p className="text-[var(--muted-foreground)]">
              {t("Set the environment variable")}
            </p>
            <code className="block break-all text-[var(--foreground)]">
              {"DEEPTUTOR_OPENMAIC_URL=http://localhost:3100"}
            </code>
            <p className="pt-2 text-[var(--muted-foreground)]">
              {t("or add this to data/user/settings/openmaic.json")}
            </p>
            <code className="block break-all text-[var(--foreground)]">
              {'{ "embed_url": "http://localhost:3100" }'}
            </code>
          </div>
        </div>
      </div>
    );
  }

  // Only a same-origin path needs the reverse-proxy prefix; an absolute URL is
  // already complete, and withBasePath leaves it alone anyway.
  const base = sameOrigin ? withBasePath(url) : url;
  const frameSrc = withHostPreferences(base, language, theme, {
    embedded: true,
  });
  const tabSrc = withHostPreferences(base, language, theme, {
    embedded: false,
  });

  return (
    <div className="flex h-full w-full flex-col">
      {/* A strip of our own chrome rather than a button floating over the frame.
          OpenMAIC puts its own controls in the top-right (language / display /
          settings) and along the right edge in the classroom view, so any
          absolutely-positioned overlay collides with something at some width —
          on a phone it covered their settings gear outright. This also gives
          the page one honest line saying whose app you are looking at. */}
      <div className="flex h-9 shrink-0 items-center justify-between gap-2 border-b border-[var(--border)] bg-[var(--background)] px-3">
        <span className="truncate text-xs text-[var(--muted-foreground)]">
          {t("Course studio")}
        </span>
        <a
          href={tabSrc}
          target="_blank"
          rel="noopener noreferrer"
          title={t("Open the course studio in a new tab")}
          aria-label={t("Open the course studio in a new tab")}
          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
        >
          <ExternalLink size={15} strokeWidth={1.8} />
        </a>
      </div>

      <div className="relative min-h-0 flex-1">
        {loadedSrc !== frameSrc ? (
          <div className="absolute inset-0 flex items-center justify-center bg-[var(--background)]">
            <Loader2
              size={22}
              className="animate-spin text-[var(--muted-foreground)]"
            />
          </div>
        ) : null}

        {/* Nothing is framed until the stored language has been read. Rendering
            first and correcting after would load OpenMAIC twice, and the first
            load would be the wrong language — visibly, for as long as it takes
            to start. Tracking which src finished loading, rather than a bare
            boolean, keeps the spinner honest when a preference change reloads
            the frame. */}
        {languageReady ? (
          <iframe
            src={frameSrc}
            title={t("Course studio")}
            onLoad={() => setLoadedSrc(frameSrc)}
            allow="clipboard-write; fullscreen; microphone"
            /* The address of the page doing the framing is not the studio's
               business, and in the cross-origin dev shape it would leave this
               origin entirely. `origin` keeps enough for a server log without
               the path. */
            referrerPolicy="origin"
            className="h-full w-full border-0"
          />
        ) : null}
      </div>
    </div>
  );
}
