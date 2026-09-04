"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ArrowRight,
  CalendarDays,
  BookMarked,
  BookOpen,
  BookText,
  Bot,
  BrainCircuit,
  Clock3,
  Compass,
  Database,
  FileQuestion,
  Library,
  LayoutGrid,
  ListChecks,
  MessageSquare,
  NotebookTabs,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import { useLearningPolicy } from "@/features/dashboard/useLearningPolicy";
import { fetchCapabilityCatalog } from "@/features/capabilities/api";
import type { CapabilityDescriptor } from "@/features/capabilities/model";
import {
  mergeCapabilityPresentations,
  type ChatCapabilityDef,
} from "@/features/capabilities/presentation";
import { listKnowledgeBases } from "@/features/knowledge/api/catalog";
import type { KnowledgeBaseSummary } from "@/features/knowledge/model/types";
import {
  fetchAuthStatus,
  invalidateAuthStatusCache,
  type AuthStatus,
} from "@/lib/auth";
import { bookApi } from "@/lib/book-api";
import type { Book } from "@/lib/book-types";
import { listLLMOptions, type LLMOption } from "@/lib/llm-options";
import { sessionRoute } from "@/lib/mastery-session";
import {
  getQuestionBankStats,
  listNotebooks,
  type NotebookSummary,
  type QuestionBankStats,
} from "@/lib/notebook-api";
import { listPartners, type PartnerInfo } from "@/lib/partners-api";
import { listMaterials, type MaterialInfo } from "@/lib/reading-api";
import { listAllSessions, type SessionSummary } from "@/lib/session-api";
import { listSkills, type SkillInfo } from "@/lib/skills-api";
import { getEnabledOptionalTools } from "@/lib/tools-settings";
import {
  buildDashboardActivitySeries,
  capabilityLaunchHref,
  formatCapabilityLabel,
  normalizeUserPreset,
  sessionCapabilityId,
  visibleDashboardSessions,
  type DashboardActivityDay,
  type UserPreset,
} from "@/lib/user-dashboard";

interface DashboardData {
  sessions: SessionSummary[];
  notebooks: NotebookSummary[];
  questionStats: QuestionBankStats | null;
  books: Book[];
  materials: MaterialInfo[];
  capabilities: CapabilityDescriptor[];
  knowledgeBases: KnowledgeBaseSummary[];
  partners: PartnerInfo[];
  skills: SkillInfo[];
  tools: string[];
  models: LLMOption[];
  unavailable: string[];
}

const EMPTY_DATA: DashboardData = {
  sessions: [],
  notebooks: [],
  questionStats: null,
  books: [],
  materials: [],
  capabilities: [],
  knowledgeBases: [],
  partners: [],
  skills: [],
  tools: [],
  models: [],
  unavailable: [],
};

async function safeLoad<T>(
  name: string,
  request: Promise<T>,
  fallback: T,
): Promise<{ name: string; value: T; failed: boolean }> {
  try {
    return { name, value: await request, failed: false };
  } catch {
    return { name, value: fallback, failed: true };
  }
}

function epochMilliseconds(timestamp: number): number {
  return timestamp < 10_000_000_000 ? timestamp * 1000 : timestamp;
}

function relativeTime(timestamp: number, locale: string): string {
  if (!timestamp) return "—";
  const delta = epochMilliseconds(timestamp) - Date.now();
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

function presetLabel(preset: UserPreset): string {
  if (preset === "learner") return "Learner";
  if (preset === "custom") return "Custom";
  return "Standard";
}

export default function UserDashboard() {
  const router = useRouter();
  const { t, i18n } = useTranslation();
  const { allowsLearningSurface, policyResolved } = useLearningPolicy();
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [data, setData] = useState<DashboardData>(EMPTY_DATA);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!policyResolved) return;
    setLoading(true);
    setError("");
    try {
      // A reload is the user's way of asking for current numbers, so drop the
      // short-lived status cache first: a grant changed by an admin mid-session
      // should show up now rather than after the cache expires.
      invalidateAuthStatusCache();
      const auth = await fetchAuthStatus();
      if (!auth?.authenticated) {
        router.replace("/login");
        return;
      }
      if (auth.is_admin || auth.role === "admin") {
        router.replace("/admin");
        return;
      }
      setStatus(auth);
      const preset = normalizeUserPreset(auth.preset);
      const chatAllowed = allowsLearningSurface("chat");
      const readingAllowed = allowsLearningSurface("reading");

      const common = await Promise.all([
        safeLoad(
          "sessions",
          chatAllowed ? listAllSessions({ force: true }) : Promise.resolve([]),
          [] as SessionSummary[],
        ),
        safeLoad(
          "materials",
          readingAllowed ? listMaterials() : Promise.resolve([]),
          [] as MaterialInfo[],
        ),
        safeLoad(
          "capabilities",
          fetchCapabilityCatalog({ force: true }),
          [] as CapabilityDescriptor[],
        ),
      ]);

      const extended =
        preset === "learner"
          ? []
          : await Promise.all([
              safeLoad("notebooks", listNotebooks(), [] as NotebookSummary[]),
              safeLoad("questions", getQuestionBankStats(), null),
              safeLoad(
                "books",
                bookApi.list().then((response) => response.books),
                [] as Book[],
              ),
              safeLoad(
                "knowledge",
                listKnowledgeBases({ force: true }),
                [] as KnowledgeBaseSummary[],
              ),
              safeLoad("partners", listPartners(), [] as PartnerInfo[]),
              safeLoad("skills", listSkills({ force: true }), [] as SkillInfo[]),
              safeLoad(
                "tools",
                getEnabledOptionalTools({ force: true }),
                [] as string[],
              ),
              safeLoad(
                "models",
                listLLMOptions({ force: true }).then((response) => response.options),
                [] as LLMOption[],
              ),
            ]);

      const results = [...common, ...extended];
      const byName = new Map(results.map((result) => [result.name, result.value]));
      setData({
        sessions: (byName.get("sessions") as SessionSummary[]) ?? [],
        notebooks: (byName.get("notebooks") as NotebookSummary[]) ?? [],
        questionStats: (byName.get("questions") as QuestionBankStats | null) ?? null,
        books: (byName.get("books") as Book[]) ?? [],
        materials: (byName.get("materials") as MaterialInfo[]) ?? [],
        capabilities: (byName.get("capabilities") as CapabilityDescriptor[]) ?? [],
        knowledgeBases:
          (byName.get("knowledge") as KnowledgeBaseSummary[]) ?? [],
        partners: (byName.get("partners") as PartnerInfo[]) ?? [],
        skills: (byName.get("skills") as SkillInfo[]) ?? [],
        tools: (byName.get("tools") as string[]) ?? [],
        models: (byName.get("models") as LLMOption[]) ?? [],
        unavailable: results
          .filter((result) => result.failed)
          .map((result) => result.name),
      });
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : t("Failed to load dashboard"),
      );
    } finally {
      setLoading(false);
    }
  }, [allowsLearningSurface, policyResolved, router, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const preset = normalizeUserPreset(status?.preset);
  const sessions = useMemo(
    () => visibleDashboardSessions(data.sessions),
    [data.sessions],
  );
  const recent = sessions.slice(0, 5);
  const nextSession = sessions[0];
  const capabilities = useMemo(
    () => {
      const merged = mergeCapabilityPresentations(data.capabilities);
      if (
        allowsLearningSurface("reading") &&
        !merged.some((capability) => capability.value === "immersive_reading")
      ) {
        const reading: ChatCapabilityDef = {
          value: "immersive_reading",
          label: "Immersive Reading",
          description: "Read assigned or personal material with tutor support",
          icon: BookOpen,
          allowedTools: [],
          defaultTools: [],
        };
        const chatIndex = merged.findIndex(
          (capability) => (capability.value || "chat") === "chat",
        );
        merged.splice(chatIndex >= 0 ? chatIndex + 1 : 0, 0, reading);
      }
      return merged.slice(0, 6);
    },
    [allowsLearningSurface, data.capabilities],
  );
  const locale = i18n.language?.startsWith("zh") ? "zh-CN" : "en-US";
  const activitySeries = useMemo(
    () => buildDashboardActivitySeries(data.sessions, 7),
    [data.sessions],
  );
  const totalMessages = useMemo(
    () => sessions.reduce((sum, session) => sum + session.message_count, 0),
    [sessions],
  );

  if (loading || !status) return <DashboardSkeleton />;

  const metricCards =
    preset === "learner"
      ? [
          {
            label: t("Conversations"),
            value: sessions.length,
            detail: t("Learning conversations"),
            icon: MessageSquare,
            tone: "primary" as const,
          },
          {
            label: t("Assigned materials"),
            value: data.materials.length,
            detail: t("Ready for immersive reading"),
            icon: BookOpen,
            tone: "blue" as const,
          },
          {
            label: t("Available modes"),
            value: capabilities.length,
            detail: t("Set by your learning plan"),
            icon: BrainCircuit,
            tone: "teal" as const,
          },
          {
            label: t("Reading tools"),
            value: status.learning_policy?.reading?.extensions.length ?? 0,
            detail: t("Enabled by your administrator"),
            icon: Wrench,
            tone: "amber" as const,
          },
        ]
      : [
          {
            label: t("Conversations"),
            value: sessions.length,
            detail: t("Across your learning workspace"),
            icon: MessageSquare,
            tone: "primary" as const,
          },
          {
            label: t("Notebooks"),
            value: data.notebooks.length,
            detail: t("{{count}} saved records", {
              count: data.notebooks.reduce(
                (sum, notebook) => sum + (notebook.record_count ?? 0),
                0,
              ),
            }),
            icon: NotebookTabs,
            tone: "teal" as const,
          },
          {
            label: t("Saved questions"),
            value: data.questionStats?.total ?? 0,
            detail: t("{{count}} need another look", {
              count: data.questionStats?.wrong ?? 0,
            }),
            icon: FileQuestion,
            tone: "amber" as const,
          },
          {
            label: t("Books"),
            value: data.books.length,
            detail: t("{{count}} currently in progress", {
              count: data.books.filter(
                (book) => (book.reading?.percent ?? 0) > 0 && (book.reading?.percent ?? 0) < 100,
              ).length,
            }),
            icon: Library,
            tone: "blue" as const,
          },
        ];

  return (
    <div className="h-full overflow-y-auto bg-[var(--background)] [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
        <header className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <div className="mb-1 flex items-center gap-2 text-xs font-medium uppercase tracking-[0.14em] text-[var(--primary)]">
              <Sparkles size={14} /> {t("Your learning space")}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight text-[var(--foreground)] sm:text-3xl">
                {t("Welcome back, {{name}}", {
                  name: status.username || t("Learner"),
                })}
              </h1>
              <span className="rounded-full border border-[var(--primary)]/25 bg-[var(--primary)]/10 px-2.5 py-1 text-xs font-medium text-[var(--primary)]">
                {t(presetLabel(preset))}
              </span>
            </div>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              {preset === "learner"
                ? t("Continue your assigned learning and reading activities.")
                : t("Pick up where you left off or start something new.")}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex h-10 w-fit items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 text-sm text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            <RefreshCw size={15} /> {t("Refresh")}
          </button>
        </header>

        {error ? (
          <div className="mb-5 flex items-center justify-between gap-3 rounded-xl border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
            <span>{error}</span>
            <button type="button" onClick={() => void load()} className="font-medium underline">
              {t("Try again")}
            </button>
          </div>
        ) : null}

        {data.unavailable.length > 0 ? (
          <div className="mb-5 rounded-xl border border-amber-500/25 bg-[var(--warning-surface)] px-4 py-3 text-xs text-[var(--warning)]">
            {t("Some dashboard data is temporarily unavailable. Your available activities still work normally.")}
          </div>
        ) : null}

        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {metricCards.map((metric) => (
            <MetricCard key={metric.label} {...metric} />
          ))}
        </section>

        <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(340px,0.8fr)]">
          <LearningMomentum
            series={activitySeries}
            totalMessages={totalMessages}
            locale={locale}
          />
          <NextSteps
            preset={preset}
            sessions={sessions}
            materials={data.materials}
            books={data.books}
            questionStats={data.questionStats}
            chatAllowed={allowsLearningSurface("chat")}
            readingAllowed={allowsLearningSurface("reading")}
          />
        </section>

        <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
          <ContinueCard
            session={nextSession}
            firstMaterial={data.materials[0]}
            preset={preset}
            locale={locale}
          />
          <CapabilityCard capabilities={capabilities} />
        </section>

        <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
          <RecentActivity sessions={recent} locale={locale} />
          {preset === "learner" ? (
            <AssignedLearning status={status} materials={data.materials} />
          ) : (
            <WorkspaceAccess preset={preset} data={data} />
          )}
        </section>

        {preset === "learner" ? (
          <LearningPlan status={status} />
        ) : (
          <LearningLibrary data={data} />
        )}
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
  tone,
}: {
  label: string;
  value: number;
  detail: string;
  icon: LucideIcon;
  tone: "primary" | "teal" | "blue" | "amber";
}) {
  const tones = {
    primary: "bg-[var(--primary)]/10 text-[var(--primary)]",
    teal: "bg-teal-500/10 text-teal-600 dark:text-teal-400",
    blue: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
    amber: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  };
  return (
    <article className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm text-[var(--muted-foreground)]">{label}</p>
          <p className="mt-1 text-3xl font-semibold tracking-tight text-[var(--foreground)]">
            {value.toLocaleString()}
          </p>
        </div>
        <div className={`rounded-xl p-2.5 ${tones[tone]}`}>
          <Icon size={21} strokeWidth={1.7} />
        </div>
      </div>
      <p className="mt-3 text-xs text-[var(--muted-foreground)]">{detail}</p>
    </article>
  );
}

function CardHeader({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-[var(--border)]/70 px-5 py-4">
      <h2 className="text-sm font-semibold text-[var(--foreground)]">{title}</h2>
      {action}
    </div>
  );
}

function LearningMomentum({
  series,
  totalMessages,
  locale,
}: {
  series: DashboardActivityDay[];
  totalMessages: number;
  locale: string;
}) {
  const { t } = useTranslation();
  const max = Math.max(...series.map((day) => day.sessions), 1);
  const activeDays = series.filter((day) => day.sessions > 0).length;
  const touchedSessions = series.reduce((sum, day) => sum + day.sessions, 0);
  const weekday = new Intl.DateTimeFormat(locale, { weekday: "short" });
  return (
    <article className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <CardHeader
        title={t("Learning momentum")}
        action={<span className="text-xs text-[var(--muted-foreground)]">{t("Last 7 days")}</span>}
      />
      <div className="grid gap-6 p-5 sm:grid-cols-[1fr_210px]">
        <div className="flex h-44 items-end gap-2 rounded-xl bg-[var(--background)]/45 px-3 pb-3 pt-5">
          {series.map((day) => {
            const height = day.sessions ? Math.max(12, (day.sessions / max) * 112) : 4;
            return (
              <div key={day.dayStart} className="flex min-w-0 flex-1 flex-col items-center justify-end gap-2">
                <span className="text-[10px] font-medium text-[var(--muted-foreground)]">
                  {day.sessions || ""}
                </span>
                <div
                  className={`w-full max-w-10 rounded-t-md ${day.sessions ? "bg-[var(--primary)]" : "bg-[var(--muted)]"}`}
                  style={{ height }}
                  title={t("{{count}} active conversations", { count: day.sessions })}
                />
                <span className="truncate text-[10px] text-[var(--muted-foreground)]">
                  {weekday.format(new Date(day.dayStart))}
                </span>
              </div>
            );
          })}
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-1">
          <MomentumStat label={t("Active days")} value={`${activeDays}/7`} icon={CalendarDays} />
          <MomentumStat label={t("Conversations touched")} value={String(touchedSessions)} icon={MessageSquare} />
          <MomentumStat label={t("Messages in your history")} value={String(totalMessages)} icon={ListChecks} />
        </div>
      </div>
      <p className="border-t border-[var(--border)]/70 px-5 py-3 text-xs text-[var(--muted-foreground)]">
        {t("Activity is based on conversations updated each day.")}
      </p>
    </article>
  );
}

function MomentumStat({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: LucideIcon;
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-[var(--border)]/80 px-3 py-2.5">
      <div className="rounded-lg bg-[var(--primary)]/10 p-2 text-[var(--primary)]">
        <Icon size={15} />
      </div>
      <div className="min-w-0">
        <p className="text-lg font-semibold leading-none text-[var(--foreground)]">{value}</p>
        <p className="mt-1 truncate text-[11px] text-[var(--muted-foreground)]">{label}</p>
      </div>
    </div>
  );
}

function NextSteps({
  preset,
  sessions,
  materials,
  books,
  questionStats,
  chatAllowed,
  readingAllowed,
}: {
  preset: UserPreset;
  sessions: SessionSummary[];
  materials: MaterialInfo[];
  books: Book[];
  questionStats: QuestionBankStats | null;
  chatAllowed: boolean;
  readingAllowed: boolean;
}) {
  const { t } = useTranslation();
  const inProgressBook = books.find(
    (book) => (book.reading?.percent ?? 0) > 0 && (book.reading?.percent ?? 0) < 100,
  );
  const actions: Array<{
    href: string;
    label: string;
    detail: string;
    icon: LucideIcon;
  }> = [];
  if (sessions[0]) {
    actions.push({
      href: sessionRoute(sessions[0]),
      label: t("Continue your latest activity"),
      detail: sessions[0].title || t("Untitled conversation"),
      icon: Clock3,
    });
  }
  if (readingAllowed && materials[0]) {
    actions.push({
      href: "/reading/materials",
      label: preset === "learner" ? t("Open assigned reading") : t("Read a saved material"),
      detail: materials[0].title,
      icon: BookOpen,
    });
  }
  if (preset !== "learner" && (questionStats?.wrong ?? 0) > 0) {
    actions.push({
      href: "/space/questions",
      label: t("Review questions"),
      detail: t("{{count}} answers need another look", { count: questionStats?.wrong ?? 0 }),
      icon: FileQuestion,
    });
  }
  if (preset !== "learner" && inProgressBook) {
    actions.push({
      href: `/books/${encodeURIComponent(inProgressBook.id)}`,
      label: t("Continue your book"),
      detail: `${inProgressBook.title} · ${Math.round(inProgressBook.reading?.percent ?? 0)}%`,
      icon: Library,
    });
  }
  if (chatAllowed) {
    actions.push({
      href: "/chat",
      label: t("Start a fresh conversation"),
      detail: t("Ask, solve, research, or visualize"),
      icon: Compass,
    });
  }
  return (
    <article className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <CardHeader title={t("Recommended next steps")} />
      <div className="space-y-2 p-4">
        {actions.slice(0, 4).map((action, index) => (
          <Link
            key={`${action.href}-${index}`}
            href={action.href}
            className="group flex items-center gap-3 rounded-xl border border-[var(--border)]/80 p-3 transition-colors hover:border-[var(--primary)]/35 hover:bg-[var(--primary)]/5"
          >
            <div className="rounded-xl bg-[var(--primary)]/10 p-2.5 text-[var(--primary)]">
              <action.icon size={17} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-[var(--foreground)]">{action.label}</p>
              <p className="truncate text-xs text-[var(--muted-foreground)]">{action.detail}</p>
            </div>
            <ArrowRight size={14} className="text-[var(--muted-foreground)] group-hover:text-[var(--primary)]" />
          </Link>
        ))}
        {actions.length === 0 ? (
          <p className="px-2 py-8 text-center text-sm text-[var(--muted-foreground)]">
            {t("Your administrator has not enabled a learning activity yet.")}
          </p>
        ) : null}
      </div>
    </article>
  );
}

function ContinueCard({
  session,
  firstMaterial,
  preset,
  locale,
}: {
  session?: SessionSummary;
  firstMaterial?: MaterialInfo;
  preset: UserPreset;
  locale: string;
}) {
  const { t } = useTranslation();
  const fallbackToReading = preset === "learner" && firstMaterial;
  const href = session
    ? sessionRoute(session)
    : fallbackToReading
      ? "/reading/materials"
      : "/chat";
  const title = session
    ? session.title || t("Untitled conversation")
    : fallbackToReading
      ? firstMaterial.title
      : t("Start a new conversation");
  const description = session
    ? session.last_message || t("Continue this learning activity")
    : fallbackToReading
      ? t("Open your assigned material and continue reading.")
      : t("Ask a question, solve a problem, or explore a new topic.");
  const Icon = fallbackToReading && !session ? BookOpen : MessageSquare;
  return (
    <article className="relative overflow-hidden rounded-2xl border border-[var(--primary)]/20 bg-[var(--card)] shadow-sm">
      <div className="absolute inset-y-0 right-0 w-1/2 bg-gradient-to-l from-[var(--primary)]/8 to-transparent" />
      <div className="relative p-5 sm:p-6">
        <div className="mb-5 flex items-center gap-2 text-xs font-medium uppercase tracking-[0.12em] text-[var(--primary)]">
          <Clock3 size={14} /> {t("Continue where you left off")}
        </div>
        <div className="flex items-start gap-4">
          <div className="rounded-2xl bg-[var(--primary)] p-3 text-[var(--primary-foreground)] shadow-sm">
            <Icon size={24} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-xl font-semibold text-[var(--foreground)]">{title}</h2>
            <p className="mt-1 line-clamp-2 text-sm leading-6 text-[var(--muted-foreground)]">
              {description}
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Link
                href={href}
                className="inline-flex h-10 items-center gap-2 rounded-lg bg-[var(--primary)] px-4 text-sm font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
              >
                {session ? t("Continue learning") : t("Get started")}
                <ArrowRight size={15} />
              </Link>
              {session ? (
                <span className="text-xs text-[var(--muted-foreground)]">
                  {formatCapabilityLabel(sessionCapabilityId(session))} · {relativeTime(session.updated_at, locale)}
                </span>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </article>
  );
}

function CapabilityCard({
  capabilities,
}: {
  capabilities: ReturnType<typeof mergeCapabilityPresentations>;
}) {
  const { t } = useTranslation();
  return (
    <article className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <CardHeader title={t("Available learning modes")} />
      {capabilities.length === 0 ? (
        <div className="px-5 py-10 text-center text-sm text-[var(--muted-foreground)]">
          {t("No learning mode is currently available.")}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2 p-4">
          {capabilities.map((capability) => {
            const id = capability.value || "chat";
            const Icon = capability.icon;
            return (
              <Link
                key={id}
                href={capabilityLaunchHref(id)}
                className="group flex min-w-0 items-center gap-2.5 rounded-xl border border-[var(--border)]/80 bg-[var(--background)]/35 p-3 transition-colors hover:border-[var(--primary)]/35 hover:bg-[var(--primary)]/5"
              >
                <div className="rounded-lg bg-[var(--primary)]/10 p-2 text-[var(--primary)]">
                  <Icon size={17} />
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-[var(--foreground)]">
                    {t(capability.label)}
                  </p>
                  <p className="truncate text-[11px] text-[var(--muted-foreground)]">
                    {t("Open mode")}
                  </p>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </article>
  );
}

function RecentActivity({
  sessions,
  locale,
}: {
  sessions: SessionSummary[];
  locale: string;
}) {
  const { t } = useTranslation();
  return (
    <article className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <CardHeader title={t("Recent activity")} />
      {sessions.length === 0 ? (
        <div className="px-5 py-12 text-center">
          <MessageSquare className="mx-auto text-[var(--muted-foreground)]/50" size={28} />
          <p className="mt-2 text-sm text-[var(--muted-foreground)]">
            {t("Your recent learning activities will appear here.")}
          </p>
        </div>
      ) : (
        <div className="divide-y divide-[var(--border)]/70 px-5">
          {sessions.map((session) => (
            <Link
              key={session.session_id}
              href={sessionRoute(session)}
              className="group flex items-center gap-3 py-3.5"
            >
              <div className="rounded-xl bg-[var(--muted)] p-2.5 text-[var(--muted-foreground)] group-hover:text-[var(--primary)]">
                <MessageSquare size={17} />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-[var(--foreground)]">
                  {session.title || t("Untitled conversation")}
                </p>
                <p className="mt-0.5 truncate text-xs text-[var(--muted-foreground)]">
                  {formatCapabilityLabel(sessionCapabilityId(session))} · {t("{{count}} messages", { count: session.message_count })}
                </p>
              </div>
              <span className="shrink-0 text-xs text-[var(--muted-foreground)]">
                {relativeTime(session.updated_at, locale)}
              </span>
              <ArrowRight size={14} className="shrink-0 text-[var(--muted-foreground)] group-hover:text-[var(--primary)]" />
            </Link>
          ))}
        </div>
      )}
    </article>
  );
}

function WorkspaceAccess({ preset, data }: { preset: UserPreset; data: DashboardData }) {
  const { t } = useTranslation();
  const assignedKnowledge = data.knowledgeBases.filter(
    (item) => item.assigned || item.source === "admin" || item.read_only,
  ).length;
  const assignedSkills = data.skills.filter((item) => item.source === "admin").length;
  const assignedPartners = data.partners.filter((item) => item.can_manage === false).length;
  const sharedBooks = data.books.filter((item) => item.source === "shared").length;
  const assignedTotal = assignedKnowledge + assignedSkills + assignedPartners + sharedBooks;
  const custom = preset === "custom";
  const rows = custom
    ? [
        { label: t("Models"), value: data.models.length, icon: Bot },
        { label: t("Assigned knowledge"), value: assignedKnowledge, icon: Database },
        { label: t("Assigned skills"), value: assignedSkills, icon: Sparkles },
        { label: t("Assigned partners"), value: assignedPartners, icon: ShieldCheck },
        { label: t("Enabled tools"), value: data.tools.length, icon: Wrench },
        { label: t("Shared books"), value: sharedBooks, icon: BookMarked },
      ]
    : [
        { label: t("Models"), value: data.models.length, icon: Bot },
        { label: t("Knowledge bases"), value: data.knowledgeBases.length, icon: Database },
        { label: t("Skills"), value: data.skills.length, icon: Sparkles },
        { label: t("Partners"), value: data.partners.length, icon: ShieldCheck },
        { label: t("Enabled tools"), value: data.tools.length, icon: Wrench },
        { label: t("Reading materials"), value: data.materials.length, icon: BookText },
      ];
  return (
    <article className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <CardHeader
        title={custom ? t("Your assigned access") : t("Your workspace access")}
        action={
          <Link href="/settings" className="text-xs font-medium text-[var(--primary)] hover:underline">
            {t("View settings")}
          </Link>
        }
      />
      <div className="grid grid-cols-2 gap-2 p-4">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center gap-2.5 rounded-xl border border-[var(--border)]/80 bg-[var(--background)]/35 p-3">
            <div className="rounded-lg bg-[var(--primary)]/10 p-2 text-[var(--primary)]">
              <row.icon size={16} />
            </div>
            <div className="min-w-0">
              <p className="truncate text-xs text-[var(--muted-foreground)]">{row.label}</p>
              <p className="text-lg font-semibold text-[var(--foreground)]">{row.value}</p>
            </div>
          </div>
        ))}
      </div>
      {custom && assignedTotal === 0 ? (
        <p className="border-t border-[var(--border)]/70 px-5 py-3 text-xs text-[var(--muted-foreground)]">
          {t("No shared resources have been assigned yet. Contact your administrator if you need additional access.")}
        </p>
      ) : null}
    </article>
  );
}

function AssignedLearning({
  status,
  materials,
}: {
  status: AuthStatus;
  materials: MaterialInfo[];
}) {
  const { t } = useTranslation();
  const policy = status.learning_policy;
  return (
    <article className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <CardHeader
        title={t("Assigned learning")}
        action={
          <Link href="/reading" className="text-xs font-medium text-[var(--primary)] hover:underline">
            {t("Open reading")}
          </Link>
        }
      />
      <div className="p-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {policy?.age_band ? (
            <span className="rounded-full bg-[var(--muted)] px-2.5 py-1 text-xs text-[var(--muted-foreground)]">
              {t("Age {{band}}", { band: policy.age_band })}
            </span>
          ) : null}
          <span className="rounded-full bg-[var(--primary)]/10 px-2.5 py-1 text-xs text-[var(--primary)]">
            {t("Guided by teacher mode")}
          </span>
        </div>
        {materials.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[var(--border)] px-4 py-8 text-center">
            <BookOpen className="mx-auto text-[var(--muted-foreground)]/50" size={28} />
            <p className="mt-2 text-sm font-medium text-[var(--foreground)]">
              {t("No reading material assigned yet")}
            </p>
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">
              {t("Your administrator can add material to your learning plan.")}
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {materials.slice(0, 4).map((material) => (
              <Link
                key={material.material_id}
                href="/reading/materials"
                className="group flex items-center gap-3 rounded-xl border border-[var(--border)]/80 px-3 py-3 hover:border-[var(--primary)]/35"
              >
                <div className="rounded-lg bg-blue-500/10 p-2 text-blue-600 dark:text-blue-400">
                  <BookOpen size={16} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-[var(--foreground)]">{material.title}</p>
                  <p className="text-xs text-[var(--muted-foreground)]">
                    {t("{{count}} {{unit}}", { count: material.unit_count, unit: material.unit })}
                  </p>
                </div>
                <ArrowRight size={14} className="text-[var(--muted-foreground)] group-hover:text-[var(--primary)]" />
              </Link>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}

function LearningLibrary({ data }: { data: DashboardData }) {
  const { t } = useTranslation();
  const collections = [
    { href: "/books", label: t("Books"), value: data.books.length, icon: Library },
    { href: "/reading/materials", label: t("Reading materials"), value: data.materials.length, icon: BookOpen },
    { href: "/notebooks", label: t("Notebooks"), value: data.notebooks.length, icon: NotebookTabs },
    { href: "/space/questions", label: t("Question bank"), value: data.questionStats?.total ?? 0, icon: FileQuestion },
  ];
  return (
    <section className="mt-5 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <CardHeader
        title={t("Your learning library")}
        action={
          <Link href="/space" className="inline-flex items-center gap-1 text-xs font-medium text-[var(--primary)] hover:underline">
            {t("Open learning space")} <ArrowRight size={13} />
          </Link>
        }
      />
      <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
        {collections.map((collection) => (
          <Link
            key={collection.href}
            href={collection.href}
            className="group flex items-center gap-3 rounded-xl border border-[var(--border)]/80 bg-[var(--background)]/35 p-3 transition-colors hover:border-[var(--primary)]/35"
          >
            <div className="rounded-xl bg-[var(--primary)]/10 p-2.5 text-[var(--primary)]">
              <collection.icon size={17} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xl font-semibold leading-none text-[var(--foreground)]">{collection.value}</p>
              <p className="mt-1 truncate text-xs text-[var(--muted-foreground)]">{collection.label}</p>
            </div>
            <ArrowRight size={14} className="text-[var(--muted-foreground)] group-hover:text-[var(--primary)]" />
          </Link>
        ))}
      </div>
      <div className="border-t border-[var(--border)]/70 px-4 py-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">{t("Books to continue")}</h3>
          <Link href="/books" className="text-xs font-medium text-[var(--primary)] hover:underline">{t("View all")}</Link>
        </div>
        {data.books.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[var(--border)] px-4 py-7 text-center text-sm text-[var(--muted-foreground)]">
            {t("Books you create or receive will appear here.")}
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {data.books.slice(0, 3).map((book) => {
              const progress = Math.round(book.reading?.percent ?? 0);
              return (
                <Link
                  key={book.id}
                  href={`/books/${encodeURIComponent(book.id)}`}
                  className="rounded-xl border border-[var(--border)]/80 p-4 transition-colors hover:border-[var(--primary)]/35"
                >
                  <div className="flex items-start gap-3">
                    <div className="rounded-xl bg-teal-500/10 p-2.5 text-teal-600 dark:text-teal-400">
                      <Library size={18} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-[var(--foreground)]">{book.title}</p>
                      <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                        {t("{{count}} chapters", { count: book.chapter_count })}
                      </p>
                    </div>
                    {book.source === "shared" ? (
                      <span className="rounded-full bg-[var(--primary)]/10 px-2 py-0.5 text-[10px] text-[var(--primary)]">{t("Shared")}</span>
                    ) : null}
                  </div>
                  <div className="mt-4 flex items-center gap-3">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--muted)]">
                      <div className="h-full rounded-full bg-[var(--primary)]" style={{ width: `${Math.min(100, progress)}%` }} />
                    </div>
                    <span className="text-xs font-medium text-[var(--foreground)]">{progress}%</span>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

function LearningPlan({ status }: { status: AuthStatus }) {
  const { t } = useTranslation();
  const policy = status.learning_policy;
  const surfaces = policy?.allowed_surfaces ?? [];
  const capabilities = policy?.allowed_capabilities ?? [];
  const extensions = policy?.reading?.extensions ?? [];
  const facts = [
    {
      label: t("Default activity"),
      value: formatCapabilityLabel(policy?.default_capability ?? "chat"),
      icon: Compass,
    },
    {
      label: t("Available surfaces"),
      value: String(surfaces.length),
      icon: LayoutGrid,
    },
    {
      label: t("Learning modes"),
      value: String(capabilities.length),
      icon: BrainCircuit,
    },
    {
      label: t("Upload permission"),
      value: policy?.reading?.allow_upload ? t("Allowed") : t("Managed by administrator"),
      icon: ShieldCheck,
    },
  ];
  return (
    <section className="mt-5 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <CardHeader title={t("Your learning plan")} />
      <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
        {facts.map((fact) => (
          <div key={fact.label} className="flex items-center gap-3 rounded-xl border border-[var(--border)]/80 bg-[var(--background)]/35 p-3">
            <div className="rounded-xl bg-[var(--primary)]/10 p-2.5 text-[var(--primary)]">
              <fact.icon size={17} />
            </div>
            <div className="min-w-0">
              <p className="text-xs text-[var(--muted-foreground)]">{fact.label}</p>
              <p className="mt-0.5 truncate text-sm font-semibold text-[var(--foreground)]">{fact.value}</p>
            </div>
          </div>
        ))}
      </div>
      <div className="grid gap-5 border-t border-[var(--border)]/70 px-5 py-4 md:grid-cols-2">
        <PlanChips title={t("Accessible areas")} values={surfaces.map(formatCapabilityLabel)} empty={t("No area enabled")} />
        <PlanChips title={t("Reading extensions")} values={extensions.map(formatCapabilityLabel)} empty={t("No reading extension enabled")} />
      </div>
    </section>
  );
}

function PlanChips({ title, values, empty }: { title: string; values: string[]; empty: string }) {
  return (
    <div>
      <h3 className="text-xs font-semibold text-[var(--foreground)]">{title}</h3>
      <div className="mt-2 flex flex-wrap gap-2">
        {values.length ? values.map((value) => (
          <span key={value} className="rounded-full bg-[var(--muted)] px-2.5 py-1 text-xs text-[var(--muted-foreground)]">{value}</span>
        )) : <span className="text-xs text-[var(--muted-foreground)]">{empty}</span>}
      </div>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="h-full overflow-hidden bg-[var(--background)] p-6" aria-hidden>
      <div className="mx-auto max-w-[1440px] animate-pulse">
        <div className="mb-6 h-16 w-full max-w-md rounded-xl bg-[var(--muted)]/60" />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((item) => (
            <div key={item} className="h-32 rounded-2xl bg-[var(--muted)]/55" />
          ))}
        </div>
        <div className="mt-5 grid gap-5 xl:grid-cols-2">
          <div className="h-64 rounded-2xl bg-[var(--muted)]/45" />
          <div className="h-64 rounded-2xl bg-[var(--muted)]/45" />
        </div>
      </div>
    </div>
  );
}
