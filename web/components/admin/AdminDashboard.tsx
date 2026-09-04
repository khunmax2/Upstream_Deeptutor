"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  ArrowRight,
  BookMarked,
  BookOpen,
  Bot,
  Boxes,
  BrainCircuit,
  CircleCheck,
  Database,
  HeartHandshake,
  KeyRound,
  RefreshCw,
  Settings,
  ShieldCheck,
  Sparkles,
  UserCog,
  Users,
  Wrench,
} from "lucide-react";

import { fetchAuthStatus } from "@/lib/auth";
import { listUsers, type UserRecord } from "@/lib/admin-api";
import { formatDate as formatLocaleDate, type Language } from "@/lib/datetime";
import {
  listAdminGuardianRelationships,
  type GuardianRelationship,
} from "@/lib/guardian-api";
import {
  fetchAdminBooks,
  fetchAdminResources,
  fetchUserGrant,
} from "@/features/multi-user/api";
import type {
  GrantPayload,
  MultiUserResources,
  AdminBook,
} from "@/features/multi-user/types";
import {
  buildAdminDashboardSummary,
  buildAccountReadinessRows,
  buildAdminProvisioningSummary,
  countAdminAssignments,
  countAdminResources,
  newestAccounts,
  type AdminDashboardSummary,
  type AdminResourceCounts,
  type AccountReadinessRow,
  type AdminAssignmentCounts,
  type AdminProvisioningSummary,
} from "@/lib/admin-dashboard";

interface DashboardData {
  users: UserRecord[];
  summary: AdminDashboardSummary;
  resources: AdminResourceCounts;
  rawResources: MultiUserResources | null;
  grants: ReadonlyMap<string, GrantPayload>;
  relationships: GuardianRelationship[];
  grantErrors: number;
}

const EMPTY_SUMMARY: AdminDashboardSummary = {
  totalAccounts: 0,
  activeAccounts: 0,
  disabledAccounts: 0,
  admins: 0,
  standard: 0,
  custom: 0,
  learners: 0,
  guardianLinks: 0,
  customWithoutAssignments: 0,
  learnersWithoutMaterials: 0,
  needsReview: 0,
};

const EMPTY_RESOURCES: AdminResourceCounts = {
  models: 0,
  knowledgeBases: 0,
  books: 0,
  skills: 0,
  partners: 0,
  tools: 0,
  mcpTools: 0,
  readingMaterials: 0,
};

const EMPTY_PROVISIONING: AdminProvisioningSummary = {
  managedAccounts: 0,
  withModel: 0,
  configuredCustom: 0,
  learnersWithMaterials: 0,
  learnersWithGuardian: 0,
};

const EMPTY_ASSIGNMENTS: AdminAssignmentCounts = {
  models: 0,
  knowledgeBases: 0,
  skills: 0,
  partners: 0,
  tools: 0,
  mcpTools: 0,
  readingMaterials: 0,
};

function formatDate(iso: string, lang: Language): string {
  if (!iso) return "—";
  try {
    return formatLocaleDate(new Date(iso), lang);
  } catch {
    return "—";
  }
}

export default function AdminDashboard() {
  const router = useRouter();
  const { t, i18n } = useTranslation();
  const lang: Language = i18n.language?.startsWith("zh") ? "zh" : "en";
  const [data, setData] = useState<DashboardData>({
    users: [],
    summary: EMPTY_SUMMARY,
    resources: EMPTY_RESOURCES,
    rawResources: null,
    grants: new Map(),
    relationships: [],
    grantErrors: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const status = await fetchAuthStatus();
      if (!status?.authenticated) {
        router.replace("/login");
        return;
      }
      if (status.role !== "admin") {
        router.replace("/");
        return;
      }

      const [users, resources, books, relationships] = await Promise.all([
        listUsers(),
        fetchAdminResources(),
        fetchAdminBooks(),
        listAdminGuardianRelationships(),
      ]);
      const assignmentUsers = users.filter(
        (user) =>
          user.role === "user" &&
          (user.preset === "custom" || user.preset === "learner"),
      );
      const grantResults = await Promise.allSettled(
        assignmentUsers.map(async (user) => ({
          userId: user.id,
          grant: await fetchUserGrant(user.id),
        })),
      );
      const grants = new Map<string, GrantPayload>();
      let grantErrors = 0;
      for (const result of grantResults) {
        if (result.status === "fulfilled") {
          grants.set(result.value.userId, result.value.grant);
        } else {
          grantErrors += 1;
        }
      }
      setData({
        users,
        summary: buildAdminDashboardSummary(users, relationships, grants),
        resources: countAdminResources(
          resources as MultiUserResources,
          books as AdminBook[],
        ),
        rawResources: resources as MultiUserResources,
        grants,
        relationships,
        grantErrors,
      });
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t("Failed to load admin dashboard"),
      );
    } finally {
      setLoading(false);
    }
  }, [router, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const recentAccounts = useMemo(
    () => newestAccounts(data.users, 5),
    [data.users],
  );
  const provisioning = useMemo(
    () =>
      data.rawResources
        ? buildAdminProvisioningSummary(
            data.users,
            data.relationships,
            data.grants,
          )
        : EMPTY_PROVISIONING,
    [data.grants, data.rawResources, data.relationships, data.users],
  );
  const assignments = useMemo(
    () => (data.rawResources ? countAdminAssignments(data.grants) : EMPTY_ASSIGNMENTS),
    [data.grants, data.rawResources],
  );
  const readinessRows = useMemo(
    () => buildAccountReadinessRows(data.users, data.grants),
    [data.grants, data.users],
  );

  if (loading) return <AdminDashboardSkeleton />;

  return (
    <div className="h-full overflow-y-auto bg-[var(--background)] [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
        <header className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <div className="mb-1 flex items-center gap-2 text-xs font-medium uppercase tracking-[0.14em] text-[var(--primary)]">
              <ShieldCheck size={14} /> {t("Administration")}
            </div>
            <h1 className="text-2xl font-semibold tracking-tight text-[var(--foreground)] sm:text-3xl">
              {t("Admin overview")}
            </h1>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              {t("Monitor accounts, assignments, and shared learning resources.")}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void load()}
              className="inline-flex h-10 items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 text-sm text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
            >
              <RefreshCw size={15} /> {t("Refresh")}
            </button>
            <Link
              href="/admin/users"
              className="inline-flex h-10 items-center gap-2 rounded-lg bg-[var(--primary)] px-4 text-sm font-medium text-[var(--primary-foreground)] shadow-sm transition-opacity hover:opacity-90"
            >
              <UserCog size={16} /> {t("Manage accounts")}
            </Link>
          </div>
        </header>

        {error ? (
          <div className="mb-5 flex items-center justify-between gap-3 rounded-xl border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
            <span>{error}</span>
            <button type="button" onClick={() => void load()} className="font-medium underline">
              {t("Try again")}
            </button>
          </div>
        ) : null}

        {data.grantErrors > 0 ? (
          <div className="mb-5 rounded-xl border border-amber-500/25 bg-[var(--warning-surface)] px-4 py-3 text-xs text-[var(--warning)]">
            {t("{{count}} assignment record could not be checked.", {
              count: data.grantErrors,
            })}
          </div>
        ) : null}

        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label={t("Total accounts")}
            value={data.summary.totalAccounts}
            detail={t("{{count}} active", { count: data.summary.activeAccounts })}
            icon={Users}
            tone="primary"
          />
          <MetricCard
            label={t("Learners")}
            value={data.summary.learners}
            detail={t("Learner preset accounts")}
            icon={BrainCircuit}
            tone="teal"
          />
          <MetricCard
            label={t("Guardian links")}
            value={data.summary.guardianLinks}
            detail={t("Active relationships")}
            icon={HeartHandshake}
            tone="blue"
          />
          <MetricCard
            label={t("Needs review")}
            value={data.summary.needsReview}
            detail={t("Account setup checks")}
            icon={AlertTriangle}
            tone="amber"
          />
        </section>

        <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(340px,0.8fr)]">
          <ProvisioningOverview
            summary={data.summary}
            provisioning={provisioning}
          />
          <AdminQuickActions />
        </section>

        <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
          <AccountDistribution summary={data.summary} />
          <NeedsAttention summary={data.summary} />
        </section>

        <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(340px,0.75fr)]">
          <AccountReadiness rows={readinessRows} />
          <AssignmentUsage counts={assignments} />
        </section>

        <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
          <RecentAccounts users={recentAccounts} lang={lang} />
          <ResourceAccess counts={data.resources} />
        </section>
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
  tone,
}: {
  label: string;
  value: number;
  detail: string;
  icon: typeof Users;
  tone: "primary" | "teal" | "blue" | "amber";
}) {
  const toneClasses = {
    primary: "bg-[var(--primary)]/10 text-[var(--primary)]",
    teal: "bg-teal-500/10 text-teal-600 dark:text-teal-400",
    blue: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
    amber: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  };
  return (
    <article className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm text-[var(--muted-foreground)]">{label}</p>
          <p className="mt-1 text-3xl font-semibold tracking-tight text-[var(--foreground)]">
            {value.toLocaleString()}
          </p>
        </div>
        <div className={`rounded-xl p-2.5 ${toneClasses[tone]}`}>
          <Icon size={21} strokeWidth={1.7} />
        </div>
      </div>
      <p className="mt-3 text-xs text-[var(--muted-foreground)]">{detail}</p>
    </article>
  );
}

function CardHeader({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-[var(--border)]/70 px-5 py-4">
      <h2 className="text-sm font-semibold text-[var(--foreground)]">{title}</h2>
      {action}
    </div>
  );
}

function coveragePercent(value: number, total: number): number {
  if (total <= 0) return 100;
  return Math.round((value / total) * 100);
}

function ProvisioningOverview({
  summary,
  provisioning,
}: {
  summary: AdminDashboardSummary;
  provisioning: AdminProvisioningSummary;
}) {
  const { t } = useTranslation();
  const rows = [
    {
      label: t("Active accounts"),
      value: summary.activeAccounts,
      total: summary.totalAccounts,
      detail: t("Accounts able to sign in"),
    },
    {
      label: t("Model access"),
      value: provisioning.withModel,
      total: provisioning.managedAccounts,
      detail: t("Custom and Learner accounts with an assigned model"),
    },
    {
      label: t("Custom setup"),
      value: provisioning.configuredCustom,
      total: summary.custom,
      detail: t("Custom accounts with at least one explicit assignment"),
    },
    {
      label: t("Learner content"),
      value: provisioning.learnersWithMaterials,
      total: summary.learners,
      detail: t("Learners with assigned reading material"),
    },
  ];
  const score = Math.round(
    rows.reduce((sum, row) => sum + coveragePercent(row.value, row.total), 0) /
      rows.length,
  );
  return (
    <article className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <CardHeader
        title={t("Provisioning health")}
        action={
          <span className="rounded-full bg-[var(--success-surface)] px-2.5 py-1 text-xs font-semibold text-[var(--success)]">
            {score}%
          </span>
        }
      />
      <div className="grid gap-6 p-5 md:grid-cols-[150px_1fr] md:items-center">
        <div
          className="relative mx-auto grid h-32 w-32 place-items-center rounded-full"
          style={{
            background: `conic-gradient(var(--primary) 0 ${score}%, var(--muted) ${score}% 100%)`,
          }}
        >
          <div className="grid h-24 w-24 place-items-center rounded-full bg-[var(--card)] text-center">
            <div>
              <div className="text-2xl font-semibold text-[var(--foreground)]">{score}%</div>
              <div className="text-[11px] text-[var(--muted-foreground)]">{t("Ready")}</div>
            </div>
          </div>
        </div>
        <div className="space-y-4">
          {rows.map((row) => {
            const percent = coveragePercent(row.value, row.total);
            return (
              <div key={row.label}>
                <div className="mb-1.5 flex items-center justify-between gap-3 text-xs">
                  <span className="font-medium text-[var(--foreground)]">{row.label}</span>
                  <span className="text-[var(--muted-foreground)]">{row.value}/{row.total}</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-[var(--muted)]">
                  <div className="h-full rounded-full bg-[var(--primary)]" style={{ width: `${percent}%` }} />
                </div>
                <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">{row.detail}</p>
              </div>
            );
          })}
        </div>
      </div>
    </article>
  );
}

function AdminQuickActions() {
  const { t } = useTranslation();
  const actions = [
    {
      href: "/admin/users",
      label: t("Create or manage accounts"),
      detail: t("Presets, passwords, and account status"),
      icon: UserCog,
    },
    {
      href: "/admin/users",
      label: t("Assign access"),
      detail: t("Models, knowledge, tools, and learning content"),
      icon: KeyRound,
    },
    {
      href: "/admin/users",
      label: t("Manage guardians"),
      detail: t("Supervision links and learner restrictions"),
      icon: HeartHandshake,
    },
    {
      href: "/settings",
      label: t("Configure shared resources"),
      detail: t("Models, tools, and system services"),
      icon: Settings,
    },
  ];
  return (
    <article className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <CardHeader title={t("Quick actions")} />
      <div className="grid gap-2 p-4 sm:grid-cols-2 xl:grid-cols-1">
        {actions.map((action) => (
          <Link
            key={action.label}
            href={action.href}
            className="group flex items-center gap-3 rounded-xl border border-[var(--border)]/80 p-3 transition-colors hover:border-[var(--primary)]/35 hover:bg-[var(--primary)]/5"
          >
            <div className="rounded-xl bg-[var(--primary)]/10 p-2.5 text-[var(--primary)]">
              <action.icon size={17} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-[var(--foreground)]">{action.label}</p>
              <p className="truncate text-xs text-[var(--muted-foreground)]">{action.detail}</p>
            </div>
            <ArrowRight size={14} className="text-[var(--muted-foreground)] group-hover:text-[var(--primary)]" />
          </Link>
        ))}
      </div>
    </article>
  );
}

function AccountDistribution({ summary }: { summary: AdminDashboardSummary }) {
  const { t } = useTranslation();
  const total = Math.max(summary.standard + summary.custom + summary.learners, 1);
  const standardEnd = (summary.standard / total) * 100;
  const customEnd = standardEnd + (summary.custom / total) * 100;
  const rows = [
    { label: t("Standard"), value: summary.standard, color: "bg-[var(--primary)]" },
    { label: t("Custom"), value: summary.custom, color: "bg-teal-500" },
    { label: t("Learner"), value: summary.learners, color: "bg-blue-500" },
  ];
  return (
    <article className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <CardHeader title={t("Account distribution")} />
      <div className="grid items-center gap-8 p-5 sm:grid-cols-[220px_1fr]">
        <div
          className="relative mx-auto grid h-44 w-44 place-items-center rounded-full"
          style={{
            background: `conic-gradient(var(--primary) 0 ${standardEnd}%, #14b8a6 ${standardEnd}% ${customEnd}%, #3b82f6 ${customEnd}% 100%)`,
          }}
          role="img"
          aria-label={t("Distribution of Standard, Custom, and Learner accounts")}
        >
          <div className="grid h-28 w-28 place-items-center rounded-full bg-[var(--card)] text-center shadow-inner">
            <div>
              <div className="text-2xl font-semibold">{total === 1 && summary.totalAccounts === 0 ? 0 : total}</div>
              <div className="text-xs text-[var(--muted-foreground)]">{t("Users")}</div>
            </div>
          </div>
        </div>
        <div className="space-y-3">
          {rows.map((row) => (
            <div key={row.label} className="flex items-center gap-3 rounded-xl bg-[var(--background)]/60 px-3 py-2.5">
              <span className={`h-2.5 w-2.5 rounded-full ${row.color}`} />
              <span className="flex-1 text-sm text-[var(--foreground)]">{row.label}</span>
              <span className="text-sm font-semibold">{row.value}</span>
              <span className="w-12 text-right text-xs text-[var(--muted-foreground)]">
                {Math.round((row.value / total) * 100)}%
              </span>
            </div>
          ))}
          {summary.admins > 0 ? (
            <p className="px-3 text-xs text-[var(--muted-foreground)]">
              {t("{{count}} administrator account is excluded from the preset chart.", {
                count: summary.admins,
              })}
            </p>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function NeedsAttention({ summary }: { summary: AdminDashboardSummary }) {
  const { t } = useTranslation();
  const items = [
    {
      title: t("Learners without assigned material"),
      description: t("Assign reading material before guided study begins."),
      count: summary.learnersWithoutMaterials,
      icon: BookOpen,
    },
    {
      title: t("Custom accounts without assignments"),
      description: t("Complete their model, knowledge, or tool setup."),
      count: summary.customWithoutAssignments,
      icon: Sparkles,
    },
    {
      title: t("Disabled accounts"),
      description: t("Review accounts that cannot currently sign in."),
      count: summary.disabledAccounts,
      icon: AlertTriangle,
    },
  ];
  return (
    <article className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <CardHeader title={t("Needs attention")} />
      <div className="divide-y divide-[var(--border)]/70 px-5">
        {items.map((item) => (
          <div key={item.title} className="flex items-center gap-3 py-4">
            <div className={`rounded-xl p-2.5 ${item.count ? "bg-[var(--warning-surface)] text-[var(--warning)]" : "bg-[var(--success-surface)] text-[var(--success)]"}`}>
              {item.count ? <item.icon size={18} /> : <CircleCheck size={18} />}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <p className="truncate text-sm font-medium text-[var(--foreground)]">{item.title}</p>
                <span className="rounded-full bg-[var(--muted)] px-2 py-0.5 text-xs font-semibold">{item.count}</span>
              </div>
              <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">{item.description}</p>
            </div>
            {item.count ? (
              <Link href="/admin/users" className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-[var(--primary)] hover:underline">
                {t("View")} <ArrowRight size={13} />
              </Link>
            ) : null}
          </div>
        ))}
      </div>
    </article>
  );
}

function AccountReadiness({ rows }: { rows: AccountReadinessRow[] }) {
  const { t } = useTranslation();
  return (
    <article className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <CardHeader
        title={t("Account readiness")}
        action={
          <Link href="/admin/users" className="text-xs font-medium text-[var(--primary)] hover:underline">
            {t("Manage")}
          </Link>
        }
      />
      {rows.length === 0 ? (
        <div className="px-5 py-12 text-center text-sm text-[var(--muted-foreground)]">
          {t("No user accounts yet")}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--background)]/60 text-[11px] uppercase tracking-wider text-[var(--muted-foreground)]">
              <tr>
                <th className="px-5 py-3 font-medium">{t("Account")}</th>
                <th className="px-4 py-3 font-medium">{t("Preset")}</th>
                <th className="px-4 py-3 font-medium">{t("Model")}</th>
                <th className="px-4 py-3 font-medium">{t("Access")}</th>
                <th className="px-5 py-3 text-right font-medium">{t("Readiness")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]/70">
              {rows.slice(0, 7).map((row) => (
                <tr key={row.user.id || row.user.username} className="hover:bg-[var(--background)]/40">
                  <td className="px-5 py-3 font-medium text-[var(--foreground)]">{row.user.username}</td>
                  <td className="px-4 py-3 text-[var(--muted-foreground)]">
                    {t(row.user.preset === "learner" ? "Learner" : row.user.preset === "custom" ? "Custom" : "Standard")}
                  </td>
                  <td className="px-4 py-3">
                    <StatusDot ready={row.modelReady} unknown={!row.checked} />
                  </td>
                  <td className="px-4 py-3">
                    <StatusDot ready={row.contentReady} unknown={!row.checked} />
                  </td>
                  <td className="px-5 py-3 text-right">
                    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${
                      row.accessReady
                        ? "bg-[var(--success-surface)] text-[var(--success)]"
                        : "bg-[var(--warning-surface)] text-[var(--warning)]"
                    }`}>
                      {row.accessReady ? t("Ready") : t("Needs setup")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
}

function StatusDot({ ready, unknown }: { ready: boolean; unknown: boolean }) {
  const { t } = useTranslation();
  if (unknown) return <span className="text-xs text-[var(--muted-foreground)]">{t("Unknown")}</span>;
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs ${ready ? "text-[var(--success)]" : "text-[var(--warning)]"}`}>
      {ready ? <CircleCheck size={14} /> : <AlertTriangle size={14} />}
      {ready ? t("Ready") : t("Missing")}
    </span>
  );
}

function AssignmentUsage({ counts }: { counts: AdminAssignmentCounts }) {
  const { t } = useTranslation();
  const items = [
    { label: t("Model assignments"), value: counts.models, icon: Bot },
    { label: t("Knowledge assignments"), value: counts.knowledgeBases, icon: Database },
    { label: t("Skill assignments"), value: counts.skills, icon: Sparkles },
    { label: t("Partner assignments"), value: counts.partners, icon: HeartHandshake },
    { label: t("Tool assignments"), value: counts.tools + counts.mcpTools, icon: Wrench },
    { label: t("Reading assignments"), value: counts.readingMaterials, icon: BookMarked },
  ];
  const total = items.reduce((sum, item) => sum + item.value, 0);
  return (
    <article className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <CardHeader
        title={t("Assignments in use")}
        action={<span className="text-xs font-semibold text-[var(--foreground)]">{total}</span>}
      />
      <div className="grid grid-cols-2 gap-2 p-4">
        {items.map((item) => (
          <div key={item.label} className="rounded-xl border border-[var(--border)]/80 bg-[var(--background)]/35 p-3">
            <div className="flex items-center justify-between gap-2">
              <item.icon size={16} className="text-[var(--primary)]" />
              <span className="text-xl font-semibold text-[var(--foreground)]">{item.value}</span>
            </div>
            <p className="mt-2 truncate text-xs text-[var(--muted-foreground)]">{item.label}</p>
          </div>
        ))}
      </div>
      <p className="border-t border-[var(--border)]/70 px-5 py-3 text-xs text-[var(--muted-foreground)]">
        {t("Counts assignment references across Custom and Learner accounts.")}
      </p>
    </article>
  );
}

function RecentAccounts({ users, lang }: { users: UserRecord[]; lang: Language }) {
  const { t } = useTranslation();
  return (
    <article className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <CardHeader
        title={t("Recently joined accounts")}
        action={<Link href="/admin/users" className="text-xs font-medium text-[var(--primary)] hover:underline">{t("View all")}</Link>}
      />
      {users.length === 0 ? (
        <div className="px-5 py-12 text-center text-sm text-[var(--muted-foreground)]">{t("No accounts yet")}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--background)]/60 text-[11px] uppercase tracking-wider text-[var(--muted-foreground)]">
              <tr>
                <th className="px-5 py-3 font-medium">{t("Account")}</th>
                <th className="px-5 py-3 font-medium">{t("Type")}</th>
                <th className="px-5 py-3 font-medium">{t("Joined")}</th>
                <th className="px-5 py-3 font-medium">{t("Status")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]/70">
              {users.map((user) => (
                <tr key={user.id || user.username} className="hover:bg-[var(--background)]/40">
                  <td className="px-5 py-3 font-medium text-[var(--foreground)]">{user.username}</td>
                  <td className="px-5 py-3 text-[var(--muted-foreground)]">
                    {user.role === "admin" ? t("Admin") : t(user.preset === "learner" ? "Learner" : user.preset === "custom" ? "Custom" : "Standard")}
                  </td>
                  <td className="px-5 py-3 text-[var(--muted-foreground)]">{formatDate(user.created_at, lang)}</td>
                  <td className="px-5 py-3">
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${user.disabled ? "bg-red-500/10 text-red-600 dark:text-red-400" : "bg-[var(--success-surface)] text-[var(--success)]"}`}>
                      {user.disabled ? t("Disabled") : t("Active")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
}

function ResourceAccess({ counts }: { counts: AdminResourceCounts }) {
  const { t } = useTranslation();
  const resources = [
    { label: t("Models"), value: counts.models, icon: Bot },
    { label: t("Knowledge bases"), value: counts.knowledgeBases, icon: Database },
    { label: t("Books"), value: counts.books, icon: BookOpen },
    { label: t("Skills"), value: counts.skills, icon: Sparkles },
    { label: t("Partners"), value: counts.partners, icon: HeartHandshake },
    { label: t("Tools"), value: counts.tools, icon: Wrench },
    { label: t("MCP tools"), value: counts.mcpTools, icon: Boxes },
    { label: t("Reading materials"), value: counts.readingMaterials, icon: BrainCircuit },
  ];
  return (
    <article className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <CardHeader title={t("Resource access")} />
      <div className="grid grid-cols-2 gap-2 p-4">
        {resources.map((resource) => (
          <div key={resource.label} className="flex items-center gap-2.5 rounded-xl border border-[var(--border)]/80 bg-[var(--background)]/35 p-3">
            <div className="rounded-lg bg-[var(--primary)]/10 p-2 text-[var(--primary)]"><resource.icon size={16} /></div>
            <div className="min-w-0">
              <p className="truncate text-xs text-[var(--muted-foreground)]">{resource.label}</p>
              <p className="text-lg font-semibold text-[var(--foreground)]">{resource.value.toLocaleString()}</p>
            </div>
          </div>
        ))}
      </div>
      <div className="border-t border-[var(--border)]/70 px-5 py-3">
        <Link href="/settings" className="inline-flex items-center gap-1 text-xs font-medium text-[var(--primary)] hover:underline">
          {t("Manage shared resources")} <ArrowRight size={13} />
        </Link>
      </div>
    </article>
  );
}

function AdminDashboardSkeleton() {
  return (
    <div className="h-full overflow-hidden bg-[var(--background)] p-6" aria-hidden>
      <div className="mx-auto max-w-[1440px] animate-pulse">
        <div className="mb-6 h-16 w-full max-w-md rounded-xl bg-[var(--muted)]/60" />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((item) => <div key={item} className="h-32 rounded-2xl bg-[var(--muted)]/55" />)}
        </div>
        <div className="mt-5 grid gap-5 xl:grid-cols-2">
          <div className="h-80 rounded-2xl bg-[var(--muted)]/45" />
          <div className="h-80 rounded-2xl bg-[var(--muted)]/45" />
        </div>
      </div>
    </div>
  );
}
