"use client";

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import { isStudentPreset } from "@/lib/student-access";
import { browserStorage } from "@/shared/storage";
import { dynamicStorageKey } from "@/shared/storage/keys";

/**
 * Fork: the one-time notice a `student` account sees on its first sign-in
 * (school roles design, decision 8). Two sentences: conversations with the
 * tutor are private; the teacher sees learning progress. Shown once per
 * account per browser and never again -- a per-file "your teacher sees this"
 * marker was decided against, because a standing reminder that someone is
 * watching is what stops a student talking to the tutor. The statement
 * itself also lives in the consent the school collects from parents; this
 * is the reminder, not the record.
 */
const seenKey = (userId: string) =>
  dynamicStorageKey<boolean>(
    {
      scope: "local",
      version: 1,
      fallback: false,
      validate: (value): value is boolean => typeof value === "boolean",
    },
    `student-notice-seen:${userId}`,
  );

export function StudentNotice() {
  const { t } = useTranslation();
  const { authenticated, preset, userId, loading } = useAuthStatus();
  const [dismissed, setDismissed] = useState(false);
  const eligible =
    !loading && authenticated && Boolean(userId) && isStudentPreset(preset);
  // Read once per account, during render, not in an effect: the status
  // arrives asynchronously, and the answer is a pure function of it.
  const seen = useMemo(() => {
    if (!eligible || !userId) return true;
    try {
      return browserStorage.read(seenKey(userId));
    } catch {
      // Storage unavailable (private window, blocked): show it; it is a notice.
      return false;
    }
  }, [eligible, userId]);
  const open = eligible && !seen && !dismissed;

  if (!open) return null;

  const close = () => {
    setDismissed(true);
    if (userId) {
      try {
        browserStorage.write(seenKey(userId), true);
      } catch {
        // Nothing to do: it will simply show again next time.
      }
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] px-4"
      role="dialog"
      aria-modal="true"
      aria-label={t("Welcome to your tutor")}
      data-testid="student-notice"
    >
      <div className="w-full max-w-sm rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-xl">
        <h2 className="text-base font-semibold text-[var(--foreground)]">
          {t("Welcome to your tutor")}
        </h2>
        <p className="mt-3 text-sm text-[var(--foreground)]">
          {t(
            "Your conversations with the tutor are private. Your teacher sees your learning progress, not what you say.",
          )}
        </p>
        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={close}
            autoFocus
            className="rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-sm font-medium text-[var(--background)] hover:opacity-90"
          >
            {t("Got it")}
          </button>
        </div>
      </div>
    </div>
  );
}
