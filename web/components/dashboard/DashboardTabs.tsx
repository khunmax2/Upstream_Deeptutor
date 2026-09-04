"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, PawPrint } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useLearningPolicy } from "@/features/dashboard/useLearningPolicy";

/**
 * The Dashboard's two inner pages.
 *
 * Learner Anima used to own a top-level sidebar entry. Folding it in here keeps
 * the sidebar to one "Dashboard" entry while leaving each page on its own
 * route, so a link into the companion still deep-links. These are real
 * navigations rather than local tab state, hence links with `aria-current`
 * instead of an ARIA tablist.
 */
const DASHBOARD_PAGES = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { href: "/dashboard/anima", label: "Learner Anima", icon: PawPrint },
] as const;

export default function DashboardTabs() {
  const { t } = useTranslation();
  const pathname = usePathname() || "/dashboard";
  const { allowsAnima, policyResolved } = useLearningPolicy();

  // An account the companion is closed to gets no tab for it at all. It used to
  // get the tab plus a locked notice, which is honest but invites the question
  // "why is this here if I can't use it?" — so the door is simply not shown.
  //
  // Gated on `policyResolved` in the *hiding* direction: the tab appears once
  // the account is known to be allowed, rather than showing first and being
  // pulled away, which is the flicker that would prompt the same question. The
  // auth status is cached and deduped, so this costs a fetch only on a cold
  // load and nothing when switching between the two pages.
  //
  // The panel keeps its locked notice regardless — this hides the entrance, not
  // the explanation, and someone arriving on /dashboard/anima from a bookmark
  // or an old link still gets told why rather than meeting a broken page.
  const pages = DASHBOARD_PAGES.filter(
    (page) =>
      page.href !== "/dashboard/anima" || (policyResolved && allowsAnima),
  );

  return (
    <nav
      aria-label={t("Dashboard")}
      className="flex border-b border-[var(--border)]"
    >
      {pages.map((page) => {
        const active = pathname === page.href;
        const Icon = page.icon;
        return (
          <Link
            key={page.href}
            href={page.href}
            aria-current={active ? "page" : undefined}
            className={`relative min-w-0 px-4 py-2.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--ring)] ${
              active
                ? "text-[var(--primary)]"
                : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
          >
            <span className="flex items-center gap-2 text-[13px] font-medium">
              <Icon className="h-4 w-4 shrink-0" strokeWidth={1.7} />
              <span className="truncate">{t(page.label)}</span>
            </span>
            {active && (
              <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-[var(--primary)]" />
            )}
          </Link>
        );
      })}
    </nav>
  );
}
