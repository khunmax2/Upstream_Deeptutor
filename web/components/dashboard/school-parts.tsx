"use client";

import type { LucideIcon } from "lucide-react";

/**
 * Fork: the small visual parts the teacher's pages share (school roles,
 * Phase 3b). The same shapes as the user dashboard's own cards -- those are
 * module-private there, and the teacher's pages must not import that
 * page's data flow -- so they are repeated here in the same style.
 */

const TONES = {
  primary: "bg-[var(--primary)]/10 text-[var(--primary)]",
  teal: "bg-teal-500/10 text-teal-600 dark:text-teal-400",
  blue: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
  amber: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
} as const;

export function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
  tone,
}: {
  label: string;
  value: number | string;
  detail: string;
  icon: LucideIcon;
  tone: keyof typeof TONES;
}) {
  return (
    <article className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-[var(--muted-foreground)]">{label}</p>
          <p className="mt-1 text-3xl font-semibold tracking-tight text-[var(--foreground)]">
            {typeof value === "number" ? value.toLocaleString() : value}
          </p>
        </div>
        <div className={`rounded-xl p-2.5 ${TONES[tone]}`}>
          <Icon size={21} strokeWidth={1.7} />
        </div>
      </div>
      <p className="mt-3 truncate text-xs text-[var(--muted-foreground)]">
        {detail}
      </p>
    </article>
  );
}

export function Card({
  title,
  action,
  children,
  testId,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <section
      className="rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm"
      data-testid={testId}
    >
      <div className="flex items-center justify-between gap-3 border-b border-[var(--border)]/70 px-5 py-4">
        <h2 className="text-sm font-semibold text-[var(--foreground)]">
          {title}
        </h2>
        {action}
      </div>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}

export function ProgressBar({
  value,
  className = "",
}: {
  value: number;
  className?: string;
}) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div
      className={`h-1.5 w-full overflow-hidden rounded-full bg-[var(--muted)] ${className}`}
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className="h-full rounded-full bg-[var(--primary)]"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function AlertChip({ label, hint }: { label: string; hint?: string }) {
  return (
    <span
      title={hint}
      className="inline-flex items-center rounded-full bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-300"
    >
      {label}
    </span>
  );
}

export function StatusChip({
  status,
  label,
}: {
  status: string;
  label: string;
}) {
  const tone =
    status === "mastered"
      ? "bg-teal-500/10 text-teal-700 dark:text-teal-300"
      : status === "learning"
        ? "bg-blue-500/10 text-blue-700 dark:text-blue-300"
        : "bg-[var(--muted)] text-[var(--muted-foreground)]";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${tone}`}
    >
      {label}
    </span>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-[var(--muted-foreground)]">{children}</p>;
}

export function PageError({ message }: { message: string }) {
  return (
    <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
      {message}
    </div>
  );
}

export function PageSkeleton() {
  return (
    <div
      className="mx-auto max-w-[1440px] animate-pulse px-4 py-6 sm:px-6 lg:px-8"
      aria-hidden
    >
      <div className="mb-5 h-6 w-48 rounded bg-[var(--muted)]" />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-28 rounded-2xl bg-[var(--muted)]/60" />
        ))}
      </div>
      <div className="mt-5 h-64 rounded-2xl bg-[var(--muted)]/60" />
    </div>
  );
}
