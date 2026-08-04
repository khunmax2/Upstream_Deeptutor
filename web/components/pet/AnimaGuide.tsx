"use client";

import { useEffect } from "react";
import {
  X,
  ArrowUp,
  ArrowDown,
  HeartPulse,
  Sparkles,
  BarChart3,
} from "lucide-react";
import { useTranslation } from "react-i18next";

/**
 * "How it works" popup for the Learner Anima page — a modal card over a blurred
 * backdrop that explains every meter (Hunger / Happiness / Knowledge) in plain
 * terms: what raises it and what lowers it. All numbers mirror the real pet
 * tuning (`deeptutor/pet/tuning.py` + `derive.py`), so the guide can't drift from
 * the engine. Opaque (via `anima-tooltip`) so it stays readable in the glass theme.
 */

type Row = { dir: "up" | "down"; textKey: string };
type Stat = { icon: string; titleKey: string; noteKey?: string; rows: Row[] };

const STATS: Stat[] = [
  {
    icon: "🍴",
    titleKey: "Hunger",
    noteKey: "0% full, 100% starving",
    rows: [
      { dir: "down", textKey: "Master an objective — Pixel eats (−25)" },
      { dir: "up", textKey: "Time passing — slowly gets hungrier" },
      { dir: "up", textKey: "At 75% Pixel gets sick" },
    ],
  },
  {
    icon: "❤️",
    titleKey: "Happiness",
    rows: [
      { dir: "up", textKey: "Correct quiz answer (+20)" },
      { dir: "up", textKey: "Master an objective (+10)" },
      { dir: "down", textKey: "Wrong answer (−5)" },
      { dir: "down", textKey: "Staying very hungry" },
    ],
  },
  {
    icon: "📖",
    titleKey: "Knowledge",
    noteKey: "XP toward the next level",
    rows: [
      { dir: "up", textKey: "Master an objective — +50 XP" },
      {
        dir: "up",
        textKey: "A level every 2 objectives, and it only ever goes up",
      },
      { dir: "up", textKey: "Pixel evolves into a new form at Lv.3 and Lv.7" },
    ],
  },
];

export default function AnimaGuide({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="anima-guide-title"
    >
      <button
        type="button"
        aria-label={t("Close")}
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-black/50 backdrop-blur-sm"
      />
      <div className="anima-tooltip animate-fade-in relative z-10 max-h-[86vh] w-full max-w-[460px] overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-[0_28px_70px_-12px_rgba(0,0,0,0.45)]">
        <div className="flex items-center justify-between gap-2 border-b border-[var(--border)] px-5 py-4">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-[var(--primary)]" />
            <h2
              id="anima-guide-title"
              className="text-sm font-semibold text-[var(--foreground)]"
            >
              {t("How Pixel's meters work")}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("Close")}
            className="rounded-md p-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex flex-col gap-3 px-5 py-4">
          <p className="text-[12px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Everything comes from real learning — no button fills a meter.",
            )}
          </p>

          {STATS.map((stat) => (
            <div
              key={stat.titleKey}
              className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-3.5"
            >
              <div className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className="text-base leading-none">{stat.icon}</span>
                <strong className="text-[13px] text-[var(--foreground)]">
                  {t(stat.titleKey)}
                </strong>
                {stat.noteKey && (
                  <span className="text-[10px] text-[var(--muted-foreground)]">
                    · {t(stat.noteKey)}
                  </span>
                )}
              </div>
              <ul className="flex flex-col gap-1.5">
                {stat.rows.map((r, i) => (
                  <li key={i} className="flex items-start gap-2 text-[12px]">
                    {r.dir === "up" ? (
                      <ArrowUp className="mt-[1px] h-3.5 w-3.5 shrink-0 text-[#5fa892]" />
                    ) : (
                      <ArrowDown className="mt-[1px] h-3.5 w-3.5 shrink-0 text-[#d9a24a]" />
                    )}
                    <span className="text-[var(--foreground)]">
                      {t(r.textKey)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}

          <div className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-3.5">
            <div className="mb-2 flex items-center gap-2">
              <HeartPulse className="h-4 w-4 text-[var(--destructive)]" />
              <strong className="text-[13px] text-[var(--foreground)]">
                {t("Sick")}
              </strong>
            </div>
            <ul className="flex flex-col gap-1.5 text-[12px] text-[var(--foreground)]">
              <li>• {t("Starts when Hunger reaches 75%")}</li>
              <li>• {t("One correct answer cures it")}</li>
            </ul>
          </div>

          <div className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-3.5">
            <div className="mb-2 flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-[var(--primary)]" />
              <strong className="text-[13px] text-[var(--foreground)]">
                {t("Knowledge Mastery Profile")}
              </strong>
            </div>
            <ul className="flex flex-col gap-1.5 text-[12px] text-[var(--foreground)]">
              <li>
                •{" "}
                {t(
                  "The four knowledge types the tutor tracks: Memory, Concept, Procedure, Design.",
                )}
              </li>
              <li>
                •{" "}
                {t(
                  "Each bar is how many objectives of that type you've mastered out of its total, pooled across every path.",
                )}
              </li>
              <li>
                • {t("N/A means no objectives of that type yet — not 0%.")}
              </li>
            </ul>
          </div>

          <div className="rounded-xl border border-dashed border-[var(--border)] p-3.5">
            <strong className="mb-1 block text-[12px] text-[var(--foreground)]">
              {t("What counts as mastering?")}
            </strong>
            <p className="text-[11px] leading-relaxed text-[var(--muted-foreground)]">
              {t(
                "Clearing the tutor's real gate — 90% for Memory & Procedure (about 3 correct answers), or explaining the idea for Concept & Design. No shortcut.",
              )}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
