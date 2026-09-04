import type { SessionSummary } from "@/lib/session-api";

export type UserPreset = "standard" | "custom" | "learner";

export interface DashboardActivityDay {
  dayStart: number;
  sessions: number;
  messages: number;
}

export function normalizeUserPreset(value: unknown): UserPreset {
  return value === "custom" || value === "learner" ? value : "standard";
}

export function visibleDashboardSessions(
  sessions: readonly SessionSummary[],
): SessionSummary[] {
  return sessions
    .filter(
      (session) =>
        !session.preferences?.archived &&
        !session.preferences?.parent_session_id &&
        session.preferences?.session_kind !== "selection_tutor",
    )
    .toSorted((left, right) => right.updated_at - left.updated_at);
}

export function sessionCapabilityId(session: SessionSummary): string {
  if (session.preferences?.workspace_mode === "immersive_reading") {
    return "immersive_reading";
  }
  if (session.preferences?.workspace_mode === "mastery_path") {
    return "mastery_path";
  }
  return String(session.preferences?.capability || "chat");
}

export function capabilityLaunchHref(capabilityId: string): string {
  if (capabilityId === "immersive_reading") return "/reading";
  if (capabilityId === "mastery_path") return "/mastery";
  if (!capabilityId || capabilityId === "chat") return "/chat";
  return `/chat?capability=${encodeURIComponent(capabilityId)}`;
}

export function formatCapabilityLabel(capabilityId: string): string {
  if (capabilityId === "immersive_reading") return "Immersive Reading";
  if (capabilityId === "mastery_path") return "Mastery Path";
  return capabilityId
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

export function buildDashboardActivitySeries(
  sessions: readonly SessionSummary[],
  days = 7,
  now = Date.now(),
): DashboardActivityDay[] {
  const safeDays = Math.max(1, Math.floor(days));
  const today = new Date(now);
  const todayStart = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate(),
  ).getTime();
  const series = Array.from({ length: safeDays }, (_, index) => ({
    dayStart: todayStart - (safeDays - index - 1) * 86_400_000,
    sessions: 0,
    messages: 0,
  }));
  const byDay = new Map(series.map((day) => [day.dayStart, day]));
  for (const session of visibleDashboardSessions(sessions)) {
    const timestamp =
      session.updated_at < 10_000_000_000
        ? session.updated_at * 1000
        : session.updated_at;
    const date = new Date(timestamp);
    const dayStart = new Date(
      date.getFullYear(),
      date.getMonth(),
      date.getDate(),
    ).getTime();
    const day = byDay.get(dayStart);
    if (!day) continue;
    day.sessions += 1;
    day.messages += Math.max(0, session.message_count || 0);
  }
  return series;
}
