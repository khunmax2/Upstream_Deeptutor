"use client";

import { useEffect, useState } from "react";
import { Activity, BookOpen, FileQuestion, Target } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getMyEvidence, type LearningEvidence } from "@/lib/school-api";
import {
  SPOTLIGHT_HINTS,
  SPOTLIGHT_LABELS,
  formatMinutes,
  formatPercent,
  type SpotlightName,
} from "@/lib/school-dashboard";

import { Card, MetricCard, SpotlightChip, WeekBars } from "./school-parts";

/**
 * Fork: "My learning" on the student's own dashboard (school roles, step B).
 * The same evidence record a teacher reads, rendered for its owner -- one
 * source, two views -- with the teacher's part left out by the route: no
 * `teacher.md`, no alerts, no comparison with the class. Good news is
 * shown; a student's own page is not a watch list.
 */
export default function MyLearning() {
  const { t } = useTranslation();
  const [evidence, setEvidence] = useState<LearningEvidence | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getMyEvidence()
      .then((value) => {
        if (!cancelled) setEvidence(value);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // A dashboard that cannot get its evidence still stands: this section
  // simply is not there, rather than a card that says it is broken.
  if (failed) return null;

  const activity = evidence?.activity;
  const bank = evidence?.question_bank;
  const mastery = evidence?.mastery;
  const reading = evidence?.reading;
  const spotlights = (evidence?.spotlights ?? []) as SpotlightName[];
  const trend = activity?.trend ?? [];
  const nothingYet =
    evidence !== null &&
    !activity?.available &&
    !bank?.available &&
    !mastery?.available &&
    !reading?.available;

  return (
    <section className="mt-5" data-testid="my-learning">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-[var(--foreground)]">
          {t("My learning")}
        </h2>
        {spotlights.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {spotlights.map((name) => (
              <SpotlightChip
                key={name}
                label={t(SPOTLIGHT_LABELS[name] ?? name)}
                hint={t(SPOTLIGHT_HINTS[name] ?? "")}
              />
            ))}
          </div>
        )}
      </div>
      {evidence === null ? (
        <div
          className="grid animate-pulse gap-3 sm:grid-cols-2 lg:grid-cols-4"
          aria-hidden
        >
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-28 rounded-2xl bg-[var(--muted)]" />
          ))}
        </div>
      ) : nothingYet ? (
        <p className="rounded-2xl border border-[var(--border)] bg-[var(--card)] px-5 py-4 text-sm text-[var(--muted-foreground)]">
          {t(
            "Nothing to show yet. Talk to the tutor, answer a few questions or read something, and your progress appears here.",
          )}
        </p>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              label={t("Active days (30 d)")}
              value={activity?.active_days_30 ?? 0}
              detail={t("{{count}} turns · about {{minutes}}", {
                count: activity?.turns_30 ?? 0,
                minutes: formatMinutes(activity?.minutes_30 ?? 0, t),
              })}
              icon={Activity}
              tone="primary"
            />
            <MetricCard
              label={t("Accuracy (30 d)")}
              value={
                bank?.recent && bank.recent.total > 0
                  ? formatPercent(bank.recent.correct / bank.recent.total)
                  : "—"
              }
              detail={t("{{count}} questions answered", {
                count: bank?.recent?.total ?? 0,
              })}
              icon={FileQuestion}
              tone="teal"
            />
            <MetricCard
              label={t("Objectives mastered")}
              value={(mastery?.paths ?? []).reduce(
                (s, p) => s + p.counts.mastered,
                0,
              )}
              detail={t("of {{total}} across {{paths}} paths", {
                total: (mastery?.paths ?? []).reduce(
                  (s, p) => s + p.counts.total,
                  0,
                ),
                paths: mastery?.paths.length ?? 0,
              })}
              icon={Target}
              tone="blue"
            />
            <MetricCard
              label={t("Materials finished")}
              value={
                (reading?.materials ?? []).filter((m) => m.finished).length
              }
              detail={t("{{count}} started", {
                count: (reading?.materials ?? []).filter((m) => m.progress > 0)
                  .length,
              })}
              icon={BookOpen}
              tone="amber"
            />
          </div>
          {trend.length > 0 && (
            <div className="mt-3">
              <Card title={t("Last 8 weeks")}>
                <div className="grid gap-5 sm:grid-cols-2">
                  <div>
                    <p className="mb-2 text-xs text-[var(--muted-foreground)]">
                      {t("Time with the tutor, by week")}
                    </p>
                    <WeekBars
                      weeks={trend}
                      value={(w) => w.minutes}
                      labels={(w) =>
                        `${w.week_start}: ${formatMinutes(w.minutes, t)} · ${t("{{count}} active days", { count: w.active_days })}`
                      }
                    />
                  </div>
                  <div>
                    <p className="mb-2 text-xs text-[var(--muted-foreground)]">
                      {t("Questions answered, by week (filled = correct)")}
                    </p>
                    <WeekBars
                      weeks={trend}
                      value={(w) => w.questions}
                      share={(w) =>
                        w.questions > 0 ? w.correct / w.questions : null
                      }
                      labels={(w) =>
                        `${w.week_start}: ${w.correct}/${w.questions}`
                      }
                    />
                  </div>
                </div>
              </Card>
            </div>
          )}
        </>
      )}
    </section>
  );
}
