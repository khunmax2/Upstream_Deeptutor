"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, PawPrint } from "lucide-react";
import { useTranslation } from "react-i18next";

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

  return (
    <nav
      aria-label={t("Dashboard")}
      className="flex border-b border-[var(--border)]"
    >
      {DASHBOARD_PAGES.map((page) => {
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
