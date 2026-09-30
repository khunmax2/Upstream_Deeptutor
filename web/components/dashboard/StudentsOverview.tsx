"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  RefreshCw,
  Target,
  Users,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { useLearningPolicy } from "@/features/dashboard/useLearningPolicy";
import {
  getClassroomRoster,
  listClassrooms,
  type Classroom,
  type Roster,
  type RosterRow,
} from "@/lib/school-api";
import {
  ALERT_HINTS,
  ALERT_LABELS,
  SPOTLIGHT_HINTS,
  SPOTLIGHT_LABELS,
  canSeeStudents,
  formatMinutes,
  formatPercent,
  relativeTime,
  type AlertName,
  type SpotlightName,
} from "@/lib/school-dashboard";
import { resolveUiLanguage } from "@/lib/ui-language";

import {
  AlertChip,
  MetricCard,
  PageError,
  PageSkeleton,
  SpotlightChip,
} from "./school-parts";

/**
 * Fork: every student the teacher is responsible for, by classroom
 * (school roles design, Phase 3b, §2.2 and §3). One call per classroom
 * (`/school/classrooms/{id}/roster`, audited once) gives the rows and the
 * class in numbers; a row links to the student's own page.
 *
 * Nothing on this page comes from a first-person route: the data is what
 * the guardian link allows and nothing else.
 */
export default function StudentsOverview() {
  const router = useRouter();
  const { t, i18n } = useTranslation();
  const locale = resolveUiLanguage(i18n.language);
  const { policyResolved, authStatus } = useLearningPolicy();
  const [classrooms, setClassrooms] = useState<Classroom[] | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [roster, setRoster] = useState<Roster | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const allowed = policyResolved && canSeeStudents(authStatus ?? {});

  useEffect(() => {
    if (!policyResolved) return;
    if (!allowed) {
      router.replace("/dashboard");
      return;
    }
    listClassrooms()
      .then((rooms) => {
        setClassrooms(rooms);
        setSelected((current) => current || rooms[0]?.id || "");
      })
      .catch((e: unknown) => {
        setClassrooms([]);
        setError(
          e instanceof Error ? e.message : t("Failed to load classrooms"),
        );
      });
  }, [policyResolved, allowed, router, t]);

  const loadRoster = useCallback(async () => {
    if (!selected) return;
    setLoading(true);
    setError("");
    try {
      setRoster(await getClassroomRoster(selected));
    } catch (e) {
      setRoster(null);
      setError(e instanceof Error ? e.message : t("Failed to load the roster"));
    } finally {
      setLoading(false);
    }
  }, [selected, t]);

  useEffect(() => {
    void loadRoster();
  }, [loadRoster]);

  const rows = useMemo(() => roster?.rows ?? [], [roster]);

  if (!policyResolved || classrooms === null) return <PageSkeleton />;

  return (
    <div className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-serif text-xl font-semibold text-[var(--foreground)]">
            {t("My students")}
          </h1>
          <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
            {t(
              "Learning evidence only: progress, questions, reading, activity. Never a conversation.",
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {classrooms.length > 1 && (
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              aria-label={t("Classroom")}
              className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
            >
              {classrooms.map((room) => (
                <option key={room.id} value={room.id}>
                  {room.name}
                  {room.term ? ` · ${room.term}` : ""}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            onClick={loadRoster}
            disabled={loading || !selected}
            className="flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--muted-foreground)] transition-colors hover:bg-[var(--card)] hover:text-[var(--foreground)] disabled:opacity-50"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            {t("Refresh")}
          </button>
        </div>
      </div>

      {error && <PageError message={error} />}

      {classrooms.length === 0 ? (
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] px-5 py-10 text-center text-sm text-[var(--muted-foreground)]">
          <Users size={28} className="mx-auto mb-2 opacity-50" />
          {t(
            "You are not in a classroom yet. Ask an administrator to add you to one.",
          )}
        </div>
      ) : roster === null ? (
        loading ? (
          <PageSkeleton />
        ) : null
      ) : (
        <>
          <ClassNumbers roster={roster} />
          <RosterTable
            rows={rows}
            locale={locale}
            classroomId={roster.classroom.id}
          />
        </>
      )}
    </div>
  );
}

function ClassNumbers({ roster }: { roster: Roster }) {
  const { t } = useTranslation();
  const totals = roster.totals;
  const alertTotal = Object.values(totals.alerts).reduce((a, b) => a + b, 0);
  return (
    <section className="mb-5" data-testid="class-numbers">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold text-[var(--foreground)]">
          {roster.classroom.name}
          {roster.classroom.term && (
            <span className="ml-2 text-xs font-normal text-[var(--muted-foreground)]">
              {roster.classroom.term}
            </span>
          )}
        </h2>
        {totals.top_wrong_categories.length > 0 && (
          <p className="text-xs text-[var(--muted-foreground)]">
            {t("Most missed: {{names}}", {
              names: totals.top_wrong_categories
                .map((c) => `${c.name} (${c.wrong})`)
                .join(", "),
            })}
          </p>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          label={t("Active this week")}
          value={totals.active_7}
          detail={t("{{count}} of {{total}} students this month", {
            count: totals.active_30,
            total: totals.students,
          })}
          icon={Users}
          tone="primary"
        />
        <MetricCard
          label={t("Median accuracy (30 d)")}
          value={formatPercent(totals.median_accuracy_30)}
          detail={t("{{count}} under 50%", { count: totals.below_half })}
          icon={CheckCircle2}
          tone="teal"
        />
        <MetricCard
          label={t("Time with the tutor (30 d)")}
          value={formatMinutes(totals.minutes_30, t)}
          detail={t("{{count}} reviews due · {{finished}} materials finished", {
            count: totals.reviews_due,
            finished: totals.reading_finished,
          })}
          icon={Target}
          tone="blue"
        />
        <MetricCard
          label={t("Alerts")}
          value={alertTotal}
          detail={
            alertTotal === 0
              ? t("Nothing to look at right now")
              : Object.entries(totals.alerts)
                  .filter(([, n]) => n > 0)
                  .map(
                    ([name, n]) => `${t(ALERT_LABELS[name as AlertName])} ${n}`,
                  )
                  .join(" · ")
          }
          icon={AlertTriangle}
          tone="amber"
        />
      </div>
    </section>
  );
}

function RosterTable({
  rows,
  locale,
  classroomId,
}: {
  rows: RosterRow[];
  locale: string;
  classroomId: string;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] px-5 py-10 text-center text-sm text-[var(--muted-foreground)]">
        {t("No students in this classroom yet.")}
      </div>
    );
  }
  return (
    <div className="overflow-x-auto rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <table className="w-full text-sm" data-testid="roster">
        <thead>
          <tr className="border-b border-[var(--border)] text-left text-xs uppercase tracking-wide text-[var(--muted-foreground)]">
            <th className="px-4 py-3 font-medium">{t("Student")}</th>
            <th className="px-4 py-3 font-medium">{t("Last active")}</th>
            <th className="px-4 py-3 text-right font-medium">
              {t("Active days (30 d)")}
            </th>
            <th className="px-4 py-3 text-right font-medium">
              {t("Time (30 d)")}
            </th>
            <th className="px-4 py-3 text-right font-medium">
              {t("Questions (30 d)")}
            </th>
            <th className="px-4 py-3 text-right font-medium">{t("Mastery")}</th>
            <th className="px-4 py-3 text-right font-medium">{t("Reading")}</th>
            <th className="px-4 py-3 font-medium">{t("Alerts")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--border)]">
          {rows.map((row) => (
            <tr
              key={row.student.id}
              className="hover:bg-[var(--background)]/60"
            >
              <td className="px-4 py-3">
                <Link
                  href={`/dashboard/students/${encodeURIComponent(row.student.id)}?classroom=${encodeURIComponent(classroomId)}`}
                  className="font-medium text-[var(--foreground)] underline-offset-4 hover:underline"
                >
                  {row.student.username}
                </Link>
                {row.summary_at && (
                  <span className="ml-2 inline-flex items-center gap-1 text-[11px] text-[var(--muted-foreground)]">
                    <BookOpen size={11} />
                    {t("summary")}
                  </span>
                )}
              </td>
              <td className="px-4 py-3 text-[var(--muted-foreground)]">
                {relativeTime(row.last_active_at, locale)}
              </td>
              <td className="px-4 py-3 text-right tabular-nums">
                {row.active_days_30}
              </td>
              <td className="px-4 py-3 text-right tabular-nums">
                {row.minutes_30 > 0 ? formatMinutes(row.minutes_30, t) : "—"}
              </td>
              <td className="px-4 py-3 text-right tabular-nums">
                {row.questions_30 > 0
                  ? `${formatPercent(row.accuracy_30)} · ${row.questions_30}`
                  : "—"}
              </td>
              <td className="px-4 py-3 text-right tabular-nums">
                {row.objectives > 0 ? `${row.mastered}/${row.objectives}` : "—"}
              </td>
              <td className="px-4 py-3 text-right tabular-nums">
                {row.reading_started > 0 || row.reading_finished > 0
                  ? `${row.reading_finished}/${row.reading_started}`
                  : "—"}
              </td>
              <td className="px-4 py-3">
                <div className="flex flex-wrap gap-1">
                  {row.alerts.map((name) => (
                    <AlertChip
                      key={name}
                      label={t(ALERT_LABELS[name as AlertName] ?? name)}
                      hint={t(ALERT_HINTS[name as AlertName] ?? "")}
                    />
                  ))}
                  {(row.spotlights ?? []).map((name) => (
                    <SpotlightChip
                      key={name}
                      label={t(SPOTLIGHT_LABELS[name as SpotlightName] ?? name)}
                      hint={t(SPOTLIGHT_HINTS[name as SpotlightName] ?? "")}
                    />
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
