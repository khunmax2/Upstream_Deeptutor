"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { resolveUiLanguage } from "@/lib/ui-language";

import { apiFetch, apiUrl } from "@/lib/api";
import SettingsReadinessPanel from "@/components/settings/SettingsReadinessPanel";
import SettingsStatusPanel from "@/components/settings/SettingsStatusPanel";
import { SettingRow, SettingSection } from "@/components/settings/shared";
import { useSettingsAccess } from "@/features/settings/navigation/SettingsAccessProvider";
import { setPendingPrompt } from "@/lib/pending-prompt";
import {
  settingsAnchorHref,
  type Lang,
} from "@/features/settings/navigation/settings-nav";
import { useSettings } from "@/features/settings/store/SettingsStore";
import { useUiSettings } from "@/features/settings/store";

/** The en/zh segmented control both language rows use. */
function LanguageToggle({
  value,
  onChange,
}: {
  value: string;
  // Fork: `th` is a third interface language. v1.6.6 moved this control here
  // from AppearanceSettingsSection, and the version that moved offers `en`
  // and `zh` only — a Thai reader arriving on the settings page would have
  // had no way left to choose Thai, and no error to explain why.
  onChange: (next: "en" | "zh" | "th") => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex gap-0.5 rounded-lg bg-[var(--muted)] p-0.5">
      {(["en", "zh", "th"] as const).map((option) => (
        <button
          key={option}
          onClick={() => onChange(option)}
          className={`rounded-md px-2.5 py-1 text-[12px] transition-all ${
            value === option
              ? "bg-[var(--card)] font-medium text-[var(--foreground)] shadow-sm"
              : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          }`}
        >
          {
            {
              en: t("language.english"),
              zh: t("language.chinese"),
              th: t("language.thai"),
            }[option]
          }
        </button>
      ))}
    </div>
  );
}

/**
 * The settings landing page.
 *
 * It used to be a grid of seven cards whose only job was to link to the seven
 * categories — a directory, now that the navigator lists every page anyway.
 * What it could not answer, and what a landing page is for, is "what state am
 * I actually in".
 *
 * That question now has exactly one answer on the page: `Readiness`. Two
 * earlier lists — "needs attention" and "model services" — reported slices of
 * it from the client's own view of the catalog, which meant the same service
 * could be counted twice with two different totals. They were folded into the
 * readiness rows, which carry the model name, the last test result, and what
 * depends on the service on one line.
 *
 * Above it sits only what needs no diagnosis: the runtime strip, and the two
 * language toggles that decide what the rest of the page reads like.
 */
export default function SettingsOverview() {
  const { t, i18n } = useTranslation();
  // Fork: a `zh ? .zh : .en` reader answers English for Thai, silently.
  // resolveUiLanguage keeps the third language addressable by key.
  const uiLang = resolveUiLanguage(i18n.language);
  const tr = useCallback((value: Lang) => value[uiLang], [uiLang]);
  const { language, responseLanguage, updateLanguage, updateResponseLanguage } =
    useUiSettings();
  const {
    catalog,
    catalogEditable,
    diagnosticsResults,
    draftState,
    storedDraft,
    startTour,
  } = useSettings();
  const access = useSettingsAccess();

  // The effective browser API base. The old hub previewed it on its Network
  // card, and it is the first thing to check on a Docker or LAN install, so it
  // did not deserve to disappear with that card.
  const [apiBase, setApiBase] = useState("");
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(apiUrl("/api/settings/network"));
        if (!res.ok) return;
        const data = (await res.json()) as {
          effective?: { browser_api_base?: string };
        };
        if (!cancelled) setApiBase(data.effective?.browser_api_base || "");
      } catch {
        /* non-admins get 403; the row simply does not render */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <header className="mb-6 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="font-serif text-[22px] font-semibold tracking-tight text-[var(--foreground)]">
            {t("Settings")}
          </h1>
          <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--muted-foreground)]">
            {t("Appearance, models, knowledge, chat, and memory.")}
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setPendingPrompt(
              tr({
                zh: "帮我配置一下 DeepWitya，先看看现在缺什么。",
                en: "Help me configure DeepWitya — start by checking what's missing.",
                th: "Help me configure DeepWitya — start by checking what's missing.",
              }),
            );
          }}
          className="hidden shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] sm:inline-flex"
        >
          {t("Set up with DeepTutor")}
        </button>
      </header>

      {/* The strip reads /api/system/status, which the learning guard denies, so
          a restricted account saw "Checking" forever. Server health is not a
          learner's concern; drop the strip rather than paint a dead one. */}
      {!access.restricted && <SettingsStatusPanel />}

      <div className="mt-8">
        <SettingSection
          title={t("Language")}
          description={t("Choose the interface language.")}
        >
          <SettingRow
            title={t("Interface language")}
            description={t(
              "Controls navigation, settings, and status text only.",
            )}
            control={
              <LanguageToggle value={language} onChange={updateLanguage} />
            }
          />
          <SettingRow
            title={t("Model output language")}
            description={t(
              "Sets the default language for chat and capability responses.",
            )}
            control={
              <LanguageToggle
                value={responseLanguage}
                onChange={updateResponseLanguage}
              />
            }
          />
        </SettingSection>
      </div>

      <SettingsReadinessPanel enabled={catalogEditable === true} />

      {apiBase && (
        <p className="mt-5 text-[11.5px] text-[var(--muted-foreground)]">
          {t("Browser API base")}{" "}
          <Link
            href={settingsAnchorHref("network")}
            className="font-mono text-[var(--foreground)]/70 underline-offset-2 hover:underline"
          >
            {apiBase}
          </Link>
        </p>
      )}

      <button
        type="button"
        onClick={startTour}
        className="mt-6 text-[11.5px] text-[var(--muted-foreground)] underline-offset-2 transition-colors hover:text-[var(--foreground)] hover:underline"
      >
        {t("Take the tour")}
      </button>
      {storedDraft?.updated_at && (
        <p className="mt-2 text-[11px] text-[var(--muted-foreground)]/70">
          {t("Draft saved {{when}}", { when: storedDraft.updated_at })}
        </p>
      )}
    </div>
  );
}
