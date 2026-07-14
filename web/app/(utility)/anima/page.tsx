"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { PawPrint, MessageSquare } from "lucide-react";

import PetHabitat from "@/components/pet/PetHabitat";
import { fetchAllProgress } from "@/lib/learning-api";

/**
 * Learner Anima — the companion's own top-level page.
 *
 * One pet per user, fed by ALL their mastery paths (the aggregate lives in the
 * backend). This page is just the frame: it renders the same `<PetHabitat>`
 * component and, when the user has no paths yet, a call-to-action — a hungry pet
 * with nothing to eat is its own nudge to start learning.
 */
export default function AnimaPage() {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((cn: string, en: string) => (zh ? cn : en), [zh]);
  const router = useRouter();

  // `null` = still checking; empty state only shows once we know there are none.
  const [hasPaths, setHasPaths] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchAllProgress()
      .then((r) => {
        if (!cancelled) setHasPaths(r.summaries.some((s) => s.kp_count > 0));
      })
      .catch(() => {
        if (!cancelled) setHasPaths(true); // on error, don't nag with the CTA
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="h-full overflow-y-auto [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-2xl px-6 py-8">
        <header className="mb-5 flex items-center gap-2 text-[var(--foreground)]">
          <PawPrint className="h-5 w-5" />
          <h1 className="text-base font-semibold">
            {tr("学习伙伴", "Learner Anima")}
          </h1>
        </header>

        <PetHabitat tr={tr} />

        {hasPaths === false && (
          <div className="mt-5 rounded-lg border border-[var(--border)] p-4">
            <p className="text-sm text-[var(--foreground)]">
              {tr(
                "它还没有东西可吃。开始一条精通之路，真正掌握知识点来喂养它。",
                "It has nothing to eat yet. Start a Mastery Path and truly master an objective to feed it.",
              )}
            </p>
            <button
              onClick={() => router.push("/home")}
              className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
            >
              <MessageSquare className="h-3.5 w-3.5" />
              {tr("在对话中开始", "Start in Chat")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
