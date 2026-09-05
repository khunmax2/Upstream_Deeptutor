"use client";

import { useState } from "react";
import { ExternalLink, Loader2, PlugZap } from "lucide-react";
import { useTranslation } from "react-i18next";

import { withBasePath } from "@/lib/basePath";

interface MaicWorkspaceProps {
  /** Resolved by the server page; "" when OpenMAIC is not configured. */
  url: string;
  /** True when `url` is a path on this origin rather than an absolute URL. */
  sameOrigin: boolean;
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
  const [loaded, setLoaded] = useState(false);

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
            {t("OpenMAIC is not connected")}
          </h1>
          <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "OpenMAIC runs as its own service beside DeepTutor. Point this page at it, then reload — the setting is read on every request.",
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
  const src = sameOrigin ? withBasePath(url) : url;

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
          {t("OpenMAIC course studio")}
        </span>
        <a
          href={src}
          target="_blank"
          rel="noopener noreferrer"
          title={t("Open OpenMAIC in a new tab")}
          aria-label={t("Open OpenMAIC in a new tab")}
          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
        >
          <ExternalLink size={15} strokeWidth={1.8} />
        </a>
      </div>

      <div className="relative min-h-0 flex-1">
        {!loaded ? (
          <div className="absolute inset-0 flex items-center justify-center bg-[var(--background)]">
            <Loader2
              size={22}
              className="animate-spin text-[var(--muted-foreground)]"
            />
          </div>
        ) : null}

        <iframe
          src={src}
          title={t("OpenMAIC course studio")}
          onLoad={() => setLoaded(true)}
          allow="clipboard-write; fullscreen; microphone"
          className="h-full w-full border-0"
        />
      </div>
    </div>
  );
}
