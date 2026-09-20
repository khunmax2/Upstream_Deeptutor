/**
 * Fork: pure helpers for the teacher's pages (school roles design, Phase
 * 3b). Kept out of the components so the node suite can pin them: who gets
 * the Students tab, how an alert is named, how a percentage and a date
 * read.
 */

export type AlertName =
  "inactive" | "struggling" | "backlog" | "reviews_due" | "reading_stalled";

export const ALERT_ORDER: readonly AlertName[] = [
  "inactive",
  "struggling",
  "backlog",
  "reviews_due",
  "reading_stalled",
];

/** Translation keys, one per alert; the page passes them through t(). */
export const ALERT_LABELS: Record<AlertName, string> = {
  inactive: "Inactive",
  struggling: "Struggling",
  backlog: "Backlog",
  reviews_due: "Reviews due",
  reading_stalled: "Reading stalled",
};

export const ALERT_HINTS: Record<AlertName, string> = {
  inactive: "No activity for 7 days",
  struggling: "Under 50% on at least 10 questions in 30 days",
  backlog: "At least 10 wrong answers not yet resolved",
  reviews_due: "At least 5 Mastery Path reviews due",
  reading_stalled: "A material started but not opened for 14 days",
};

export type SpotlightName =
  "mastered_recently" | "reading_finished" | "accuracy_up" | "steady" | "back";

export const SPOTLIGHT_ORDER: readonly SpotlightName[] = [
  "mastered_recently",
  "reading_finished",
  "accuracy_up",
  "steady",
  "back",
];

export const SPOTLIGHT_LABELS: Record<SpotlightName, string> = {
  mastered_recently: "Mastered this week",
  reading_finished: "Finished a material",
  accuracy_up: "Accuracy up",
  steady: "Steady",
  back: "Back",
};

export const SPOTLIGHT_HINTS: Record<SpotlightName, string> = {
  mastered_recently: "An objective reached mastered in the last 7 days",
  reading_finished: "A reading material finished in the last 7 days",
  accuracy_up: "This week's accuracy is 10 points over the four weeks before",
  steady: "Active on at least 4 of the last 7 days",
  back: "Active again after two quiet weeks",
};

/** "about 25 min" / "about 1 h 40 min"; minutes are an estimate. */
export function formatMinutes(
  value: number | null | undefined,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  if (value === null || value === undefined) return "—";
  const minutes = Math.round(value);
  if (minutes < 60) return t("{{count}} min", { count: minutes });
  return t("{{hours}} h {{minutes}} min", {
    hours: Math.floor(minutes / 60),
    minutes: minutes % 60,
  });
}

/**
 * The Students tab is for teachers and admins. A teacher is an ordinary
 * account with the `teacher` preset (parent design, decision 3); admins see
 * every classroom.
 */
export function canSeeStudents(status: {
  role?: string | null;
  preset?: string | null;
}): boolean {
  return status.role === "admin" || status.preset === "teacher";
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

export function formatDateTime(
  iso: string | null | undefined,
  locale: string,
): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function relativeTime(
  iso: string | null | undefined,
  locale: string,
  now: number = Date.now(),
): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const delta = date.getTime() - now;
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const minutes = Math.round(delta / 60_000);
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
  const hours = Math.round(delta / 3_600_000);
  if (Math.abs(hours) < 24) return formatter.format(hours, "hour");
  const days = Math.round(delta / 86_400_000);
  if (Math.abs(days) < 30) return formatter.format(days, "day");
  const months = Math.round(delta / 2_592_000_000);
  return formatter.format(months, "month");
}

/** Status chips of a Mastery Path objective, in display order. */
export const OBJECTIVE_STATUS_LABELS: Record<string, string> = {
  mastered: "Mastered",
  learning: "Learning",
  new: "New",
};

/** Question sources as the evidence record names them. */
export const SOURCE_LABELS: Record<string, string> = {
  deep_question: "Deep Question",
  mastery_path: "Mastery Path",
  immersive_reading: "Reading quiz",
  book: "Book quiz",
};
