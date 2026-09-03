import type { Language } from "@/lib/datetime";

/**
 * Resolve i18next's language tag to one this app actually renders.
 *
 * Exists because the same two-language shape kept reappearing by hand —
 * `i18n.language.startsWith("zh") ? "zh" : "en"`, or a `zh` boolean feeding
 * `zh ? value.zh : value.en`. Both compile fine and both silently render Thai
 * as English, which is how the entire settings navigation shipped in English
 * for Thai accounts while every label object already carried a `th` string.
 *
 * Anything that needs to choose between per-language values should call this
 * (or `pickLang` below) rather than testing for one language and assuming the
 * other.
 */
export function resolveUiLanguage(language: string | undefined): Language {
  const code = language?.toLowerCase() ?? "";
  if (code.startsWith("zh")) return "zh";
  if (code.startsWith("th")) return "th";
  return "en";
}

/** Pick the field matching the active language from a `{ en, zh, th }` object. */
export function pickLang<T>(
  value: { en: T; zh: T; th: T },
  language: string | undefined,
): T {
  return value[resolveUiLanguage(language)];
}
