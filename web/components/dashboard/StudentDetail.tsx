"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Activity,
  ArrowLeft,
  BookOpen,
  FileQuestion,
  RefreshCw,
  Sparkles,
  Target,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { useLearningPolicy } from "@/features/dashboard/useLearningPolicy";
import {
  getLearningEvidence,
  refreshTeacherSummary,
  type LearningEvidence,
} from "@/lib/school-api";
import {
  ALERT_HINTS,
  ALERT_LABELS,
  OBJECTIVE_STATUS_LABELS,
  SOURCE_LABELS,
  canSeeStudents,
  formatDateTime,
  formatPercent,
  relativeTime,
  type AlertName,
} from "@/lib/school-dashboard";
import { resolveUiLanguage } from "@/lib/ui-language";

import {
  AlertChip,
  Card,
  Empty,
  MetricCard,
  PageError,
  PageSkeleton,
  ProgressBar,
  StatusChip,
} from "./school-parts";

/**
 * Fork: one student's learning evidence for their teacher (school roles
 * design, Phase 3b, §2.3). Everything on this page is the evidence record
 * from `/learners/{id}/evidence` -- one audited read -- and the summary
 * `teacher.md` written from the allowed memory sections. There is no link
 * from here into the student's chat, Memory, knowledge bases or Co-Writer,
 * and the page fetches from no route outside `/api/multi-user/`.
 */
export default function StudentDetail({ studentId }: { studentId: string }) {
  const router = useRouter();
  const { t, i18n } = useTranslation();
  const locale = resolveUiLanguage(i18n.language);
  const { policyResolved, authStatus } = useLearningPolicy();
  const [evidence, setEvidence] = useState<LearningEvidence | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshNote, setRefreshNote] = useState("");

  const allowed = policyResolved && canSeeStudents(authStatus ?? {});

  const load = useCallback(async () => {
    setError("");
    try {
      setEvidence(await getLearningEvidence(studentId));
    } catch (e) {
      setError(
        e instanceof Error ? e.message : t("Failed to load learning evidence"),
      );
    }
  }, [studentId, t]);

  useEffect(() => {
    if (!policyResolved) return;
    if (!allowed) {
      router.replace("/dashboard");
      return;
    }
    void load();
  }, [policyResolved, allowed, router, load]);

  const refresh = async () => {
    setRefreshing(true);
    setRefreshNote("");
    try {
      const result = await refreshTeacherSummary(studentId);
      setEvidence((current) =>
        current ? { ...current, summary: result.summary } : current,
      );
      setRefreshNote(
        result.status === "written"
          ? t("Summary updated")
          : result.status === "no_input"
            ? t("The student has no consolidated memory yet.")
            : result.status === "failed"
              ? t("The model returned nothing; the previous summary is kept.")
              : t("Nothing new since the last summary"),
      );
    } catch (e) {
      setRefreshNote(
        e instanceof Error ? e.message : t("Failed to refresh the summary"),
      );
    } finally {
      setRefreshing(false);
    }
  };

  if (!policyResolved) return <PageSkeleton />;
  if (error) {
    return (
      <div className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
        <BackLink />
        <PageError message={error} />
      </div>
    );
  }
  if (!evidence) return <PageSkeleton />;

  const {
    mastery,
    question_bank: bank,
    reading,
    activity,
    profile,
    summary,
  } = evidence;
  const alerts = collectAlerts(evidence);

  return (
    <div className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
      <BackLink />
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1
            className="font-serif text-xl font-semibold text-[var(--foreground)]"
            data-testid="student-name"
          >
            {evidence.student.username}
          </h1>
          <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
            {t("Last active {{when}}", {
              when: relativeTime(activity.last_active_at, locale),
            })}
          </p>
        </div>
        {alerts.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {alerts.map((name) => (
              <AlertChip
                key={name}
                label={t(ALERT_LABELS[name])}
                hint={t(ALERT_HINTS[name])}
              />
            ))}
          </div>
        )}
      </div>

      <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          label={t("Active days (30 d)")}
          value={activity.active_days_30 ?? 0}
          detail={t("{{count}} turns with the tutor", {
            count: activity.turns_30 ?? 0,
          })}
          icon={Activity}
          tone="primary"
        />
        <MetricCard
          label={t("Accuracy (30 d)")}
          value={
            bank.recent && bank.recent.total > 0
              ? formatPercent(bank.recent.correct / bank.recent.total)
              : "—"
          }
          detail={t("{{count}} questions answered", {
            count: bank.recent?.total ?? 0,
          })}
          icon={FileQuestion}
          tone="teal"
        />
        <MetricCard
          label={t("Objectives mastered")}
          value={mastery.paths.reduce((s, p) => s + p.counts.mastered, 0)}
          detail={t("of {{total}} across {{paths}} paths", {
            total: mastery.paths.reduce((s, p) => s + p.counts.total, 0),
            paths: mastery.paths.length,
          })}
          icon={Target}
          tone="blue"
        />
        <MetricCard
          label={t("Materials finished")}
          value={reading.materials.filter((m) => m.finished).length}
          detail={t("{{count}} started", {
            count: reading.materials.filter((m) => m.progress > 0).length,
          })}
          icon={BookOpen}
          tone="amber"
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="space-y-5">
          <Card
            title={t("Summary for the teacher")}
            testId="teacher-summary"
            action={
              <button
                type="button"
                onClick={refresh}
                disabled={refreshing}
                className="flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:opacity-50"
              >
                <RefreshCw
                  size={12}
                  className={refreshing ? "animate-spin" : ""}
                />
                {t("Refresh")}
              </button>
            }
          >
            {summary.available ? (
              <>
                <div className="grid gap-4 sm:grid-cols-2">
                  {summary.sections.map((section) => (
                    <div key={section.title}>
                      <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                        <Sparkles size={12} />
                        {t(section.title)}
                      </h3>
                      <ul className="space-y-1 text-sm text-[var(--foreground)]">
                        {section.items.map((item, index) => (
                          <li key={index} className="flex gap-2">
                            <span className="text-[var(--muted-foreground)]">
                              •
                            </span>
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-[11px] text-[var(--muted-foreground)]">
                  {t("Written {{when}} from the student's learning memory.", {
                    when: formatDateTime(summary.generated_at, locale),
                  })}
                </p>
              </>
            ) : (
              <Empty>
                {t(
                  "No summary yet: the student has no consolidated learning memory. It is written nightly once there is one, or on Refresh.",
                )}
              </Empty>
            )}
            {refreshNote && (
              <p className="mt-2 text-xs text-[var(--muted-foreground)]">
                {refreshNote}
              </p>
            )}
          </Card>

          <Card title={t("Mastery paths")} testId="mastery">
            {mastery.paths.length === 0 ? (
              <Empty>{t("No Mastery Path started yet.")}</Empty>
            ) : (
              <div className="space-y-4">
                {mastery.paths.map((path) => (
                  <div key={path.id}>
                    <div className="flex items-baseline justify-between gap-3">
                      <h3 className="text-sm font-medium text-[var(--foreground)]">
                        {path.name}
                      </h3>
                      <span className="text-xs text-[var(--muted-foreground)]">
                        {path.counts.mastered}/{path.counts.total}
                        {path.due_reviews > 0 &&
                          ` · ${t("{{count}} reviews due", { count: path.due_reviews })}`}
                      </span>
                    </div>
                    <ProgressBar
                      value={
                        path.counts.total
                          ? path.counts.mastered / path.counts.total
                          : 0
                      }
                      className="my-2"
                    />
                    {path.modules.map((module) => (
                      <div key={module.name} className="mt-2">
                        <p className="text-xs font-medium text-[var(--muted-foreground)]">
                          {module.name} · {module.mastered}/{module.total}
                        </p>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {module.knowledge_points.map((kp) => (
                            <span
                              key={kp.name}
                              className="inline-flex items-center gap-1 text-xs"
                              title={`${Math.round(kp.mastery * 100)}%`}
                            >
                              <StatusChip
                                status={kp.status}
                                label={t(
                                  OBJECTIVE_STATUS_LABELS[kp.status] ??
                                    kp.status,
                                )}
                              />
                              <span className="text-[var(--foreground)]">
                                {kp.name}
                              </span>
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card title={t("Questions")} testId="questions">
            {!bank.available || bank.total === 0 ? (
              <Empty>{t("No questions answered yet.")}</Empty>
            ) : (
              <div className="space-y-3 text-sm">
                <p className="text-[var(--foreground)]">
                  {t(
                    "{{correct}} of {{total}} correct overall · {{unresolved}} wrong answers not yet resolved",
                    {
                      correct: bank.correct ?? 0,
                      total: bank.total,
                      unresolved: bank.unresolved ?? 0,
                    },
                  )}
                </p>
                <SmallTable
                  head={[t("Source"), t("Answered"), t("Correct")]}
                  rows={Object.entries(bank.by_source ?? {}).map(
                    ([source, item]) => [
                      t(SOURCE_LABELS[source] ?? source),
                      String(item.total),
                      formatPercent(item.total ? item.correct / item.total : 0),
                    ],
                  )}
                />
                {(bank.materials ?? []).length > 0 && (
                  <SmallTable
                    head={[t("Material"), t("Answered"), t("Correct")]}
                    rows={(bank.materials ?? []).map((item) => [
                      item.title || item.material_id,
                      String(item.total),
                      formatPercent(item.total ? item.correct / item.total : 0),
                    ])}
                  />
                )}
                {(bank.categories ?? []).length > 0 && (
                  <SmallTable
                    head={[t("Category"), t("Answered"), t("Wrong")]}
                    rows={(bank.categories ?? []).map((item) => [
                      item.name,
                      String(item.total),
                      String(item.wrong),
                    ])}
                  />
                )}
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-5">
          <Card title={t("Reading")} testId="reading">
            {reading.materials.length === 0 ? (
              <Empty>{t("No reading material yet.")}</Empty>
            ) : (
              <ul className="space-y-3">
                {reading.materials.map((m) => (
                  <li key={m.material_id}>
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="truncate text-sm font-medium text-[var(--foreground)]">
                        {m.title || m.material_id}
                      </span>
                      <span className="shrink-0 text-xs text-[var(--muted-foreground)]">
                        {m.finished ? t("Finished") : formatPercent(m.progress)}
                      </span>
                    </div>
                    <ProgressBar value={m.progress} className="my-1.5" />
                    <p className="text-[11px] text-[var(--muted-foreground)]">
                      {t(
                        "Last read {{when}} · {{annotations}} notes · {{bookmarks}} bookmarks",
                        {
                          when: relativeTime(m.last_read_at, locale),
                          annotations: m.annotations,
                          bookmarks: m.bookmarks,
                        },
                      )}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title={t("Activity")} testId="activity">
            {!activity.available ? (
              <Empty>{t("No activity yet.")}</Empty>
            ) : (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <dt className="text-[var(--muted-foreground)]">
                  {t("Sessions")}
                </dt>
                <dd className="text-right tabular-nums">
                  {activity.sessions_total}
                </dd>
                <dt className="text-[var(--muted-foreground)]">
                  {t("Active days (7 d)")}
                </dt>
                <dd className="text-right tabular-nums">
                  {activity.active_days_7 ?? 0}
                </dd>
                <dt className="text-[var(--muted-foreground)]">
                  {t("Active days (30 d)")}
                </dt>
                <dd className="text-right tabular-nums">
                  {activity.active_days_30 ?? 0}
                </dd>
                <dt className="text-[var(--muted-foreground)]">
                  {t("First active")}
                </dt>
                <dd className="text-right">
                  {formatDateTime(activity.first_active_at, locale)}
                </dd>
                {Object.entries(activity.by_capability_30 ?? {}).map(
                  ([cap, n]) => (
                    <FragmentRow key={cap} label={cap} value={n} />
                  ),
                )}
              </dl>
            )}
          </Card>

          <Card title={t("Learner profile")} testId="profile">
            {!profile.account && profile.goals.length === 0 ? (
              <Empty>{t("The student has not filled in a profile.")}</Empty>
            ) : (
              <div className="space-y-3 text-sm">
                {profile.account && (
                  <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                    {Object.entries(profile.account).map(([key, value]) => (
                      <FragmentRow
                        key={key}
                        label={t(PROFILE_LABELS[key] ?? key)}
                        value={value}
                      />
                    ))}
                  </dl>
                )}
                {profile.goals.map((goal, index) => (
                  <div
                    key={index}
                    className="rounded-lg border border-[var(--border)]/60 p-3"
                  >
                    <p className="mb-1 text-xs font-medium text-[var(--muted-foreground)]">
                      {goal.path}
                    </p>
                    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                      {Object.entries(goal)
                        .filter(([key]) => key !== "path")
                        .map(([key, value]) => (
                          <FragmentRow
                            key={key}
                            label={t(PROFILE_LABELS[key] ?? key)}
                            value={value}
                          />
                        ))}
                    </dl>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

const PROFILE_LABELS: Record<string, string> = {
  grade_level: "Grade level",
  curriculum: "Curriculum",
  language: "Language",
  reading_level: "Reading level",
  explanation_style: "Explanation style",
  prior_knowledge: "Prior knowledge",
  target_level: "Target level",
  time_budget: "Time budget",
};

function collectAlerts(evidence: LearningEvidence): AlertName[] {
  // The roster computes these on the server; the detail page repeats the
  // same five rules on the record it already has, so the chips match.
  const out: AlertName[] = [];
  const now = Date.now();
  const days = (iso: string | null | undefined) =>
    iso ? (now - new Date(iso).getTime()) / 86_400_000 : null;
  const sinceActive = days(evidence.activity.last_active_at);
  if (sinceActive === null || sinceActive >= 7) out.push("inactive");
  const recent = evidence.question_bank.recent;
  if (recent && recent.total >= 10 && recent.correct / recent.total < 0.5)
    out.push("struggling");
  if ((evidence.question_bank.unresolved ?? 0) >= 10) out.push("backlog");
  if (evidence.mastery.paths.reduce((s, p) => s + p.due_reviews, 0) >= 5)
    out.push("reviews_due");
  if (
    evidence.reading.materials.some((m) => {
      const since = days(m.last_read_at);
      return m.progress > 0 && !m.finished && since !== null && since >= 14;
    })
  )
    out.push("reading_stalled");
  return out;
}

function BackLink() {
  const { t } = useTranslation();
  return (
    <Link
      href="/dashboard/students"
      className="mb-4 inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
    >
      <ArrowLeft size={16} />
      {t("My students")}
    </Link>
  );
}

function FragmentRow({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <>
      <dt className="text-[var(--muted-foreground)]">{label}</dt>
      <dd className="text-right tabular-nums text-[var(--foreground)]">
        {value}
      </dd>
    </>
  );
}

function SmallTable({ head, rows }: { head: string[]; rows: string[][] }) {
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-[var(--muted-foreground)]">
          {head.map((h, i) => (
            <th
              key={h}
              className={`py-1 font-medium ${i > 0 ? "text-right" : ""}`}
            >
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-[var(--border)]/60">
        {rows.map((row, r) => (
          <tr key={r}>
            {row.map((cell, i) => (
              <td
                key={i}
                className={`py-1 ${i > 0 ? "text-right tabular-nums" : ""}`}
              >
                {cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
