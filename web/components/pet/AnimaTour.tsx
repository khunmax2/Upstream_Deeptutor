"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Sparkles, X } from "lucide-react";
import { useTranslation } from "react-i18next";

/**
 * A single-page guided tour for /anima. Mirrors the settings tour overlay
 * (soft scrim + highlight ring + tooltip, keyboard nav) but self-contained:
 * no routing, no context. The parent mounts it only while open and remounts it
 * (via `key`) to restart, so step state resets naturally. Steps anchor to
 * `data-tour` attributes on the dashboard cards.
 */

export type TourStep = { target: string; titleKey: string; descKey: string };

export const ANIMA_TOUR_STEPS: TourStep[] = [
  {
    target: "anima-habitat",
    titleKey: "Meet Pixel",
    descKey:
      "Pixel is your learning companion. Its hunger, happiness, and health all come from your real mastery progress — the only way to feed it is to truly learn.",
  },
  {
    target: "anima-status",
    titleKey: "Companion status",
    descKey:
      "These are read straight from the server: hunger, happiness, and knowledge toward the next level. There is no shortcut feed button.",
  },
  {
    target: "anima-profile",
    titleKey: "Knowledge Mastery Profile",
    descKey:
      "Your mastery across the four knowledge types, pooled across every path and counted with the tutor's own gate. N/A means there are no objectives of that type yet.",
  },
  {
    target: "anima-growth",
    titleKey: "Your growth",
    descKey:
      "What you're close to mastering, the misconceptions you've cleared, and the tutor's own suggested next step.",
  },
  {
    target: "anima-activity",
    titleKey: "Activity & reviews",
    descKey:
      "Your latest quiz answers and the spaced-repetition reviews that are due.",
  },
  {
    target: "anima-paths",
    titleKey: "Paths & shortcuts",
    descKey:
      "A summary of every Mastery Path, plus quick links to keep learning.",
  },
];

const TOOLTIP_W = 340;
const TOOLTIP_H_EST = 200;
const SCROLL_PADDING = 80;
const HIGHLIGHT_PAD = 10;

export default function AnimaTour({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);

  const step =
    index >= 0 && index < ANIMA_TOUR_STEPS.length
      ? ANIMA_TOUR_STEPS[index]
      : null;
  const total = ANIMA_TOUR_STEPS.length;
  const isFirst = index <= 0;
  const isLast = index === total - 1;

  // Drop the stale rect the moment the wanted target changes (React's
  // adjust-state-during-render pattern), so we never spotlight the old card.
  const wantKey = step ? `${step.target}#${index}` : null;
  const [resolvedFor, setResolvedFor] = useState<string | null>(null);
  if (resolvedFor !== wantKey) {
    setResolvedFor(wantKey);
    if (rect !== null) setRect(null);
  }

  // Resolve the target: scroll it into view, then measure. Retry briefly in
  // case the card is still mounting.
  useEffect(() => {
    if (!step) return;
    let cancelled = false;
    let attempt = 0;
    const tryResolve = () => {
      if (cancelled) return;
      const el = document.querySelector(`[data-tour="${step.target}"]`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        window.requestAnimationFrame(() => {
          if (!cancelled) setRect(el.getBoundingClientRect());
        });
        return;
      }
      attempt += 1;
      if (attempt < 8) window.setTimeout(tryResolve, 80);
    };
    const raf = window.requestAnimationFrame(tryResolve);
    return () => {
      cancelled = true;
      window.cancelAnimationFrame(raf);
    };
  }, [step]);

  // Keep the highlight aligned while the user resizes or scrolls.
  useEffect(() => {
    if (!step) return;
    const sync = () => {
      const el = document.querySelector(`[data-tour="${step.target}"]`);
      if (el) setRect(el.getBoundingClientRect());
    };
    window.addEventListener("resize", sync);
    window.addEventListener("scroll", sync, true);
    return () => {
      window.removeEventListener("resize", sync);
      window.removeEventListener("scroll", sync, true);
    };
  }, [step]);

  // Keyboard: Esc closes, ←/→ (and Enter) navigate.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (e.key === "ArrowRight" || e.key === "Enter") {
        e.preventDefault();
        if (isLast) onClose();
        else setIndex((v) => v + 1);
      } else if (e.key === "ArrowLeft" && !isFirst) {
        e.preventDefault();
        setIndex((v) => Math.max(0, v - 1));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isFirst, isLast, onClose]);

  if (!step || !rect) return null;

  const holeLeft = rect.left - HIGHLIGHT_PAD;
  const holeTop = rect.top - HIGHLIGHT_PAD;
  const holeW = rect.width + HIGHLIGHT_PAD * 2;
  const holeH = rect.height + HIGHLIGHT_PAD * 2;

  const wouldOverflowBelow =
    holeTop + holeH + 16 + TOOLTIP_H_EST > window.innerHeight - SCROLL_PADDING;
  const tooltipTop = wouldOverflowBelow
    ? Math.max(16, holeTop - TOOLTIP_H_EST - 16)
    : Math.min(holeTop + holeH + 16, window.innerHeight - TOOLTIP_H_EST - 16);
  const tooltipLeft = Math.max(
    16,
    Math.min(holeLeft, window.innerWidth - TOOLTIP_W - 16),
  );

  return (
    <div className="pointer-events-none fixed inset-0 z-[9999]">
      {/* No full-screen scrim: the highlight's huge box-shadow spread dims
          everything OUTSIDE the target rect, so the highlighted card stays crisp
          and unblurred while the rest of the page darkens around it. */}
      <div
        className="absolute rounded-2xl ring-2 ring-[var(--primary)] ring-offset-2 ring-offset-transparent transition-all duration-300"
        style={{
          left: holeLeft,
          top: holeTop,
          width: holeW,
          height: holeH,
          boxShadow:
            "0 0 0 9999px rgba(0,0,0,0.55), 0 0 32px rgba(212,115,75,0.45)",
        }}
      />

      <div
        className="animate-fade-in pointer-events-auto absolute z-10 w-[340px] overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-[0_24px_60px_-12px_rgba(0,0,0,0.3)]"
        style={{ top: tooltipTop, left: tooltipLeft }}
        role="dialog"
        aria-labelledby="anima-tour-title"
      >
        <div className="h-1 w-full bg-[var(--muted)]">
          <div
            className="h-full bg-[var(--primary)] transition-all duration-500"
            style={{ width: `${((index + 1) / total) * 100}%` }}
          />
        </div>

        <div className="px-5 pb-3 pt-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="inline-flex items-center gap-1.5 rounded-full bg-[var(--muted)] px-2.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)]">
              <Sparkles className="h-3 w-3" />
              <span>
                {t("Step {{current}} of {{total}}", {
                  current: index + 1,
                  total,
                })}
              </span>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label={t("Skip tour")}
              className="rounded-md p-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          <h2
            id="anima-tour-title"
            className="mb-1.5 text-[14px] font-semibold text-[var(--foreground)]"
          >
            {t(step.titleKey)}
          </h2>
          <p className="text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
            {t(step.descKey)}
          </p>
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-[var(--border)] bg-[var(--background)] px-5 py-3">
          <button
            type="button"
            onClick={() => setIndex((v) => Math.max(0, v - 1))}
            disabled={isFirst}
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronLeft className="h-3 w-3" />
            {t("Back")}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="text-[12px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            {t("Skip tour")}
          </button>
          <button
            type="button"
            onClick={() => (isLast ? onClose() : setIndex((v) => v + 1))}
            className="inline-flex items-center gap-1 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-80"
          >
            {isLast ? t("Got it") : t("Next")}
            <ChevronRight className="h-3 w-3" />
          </button>
        </div>
      </div>
    </div>
  );
}
