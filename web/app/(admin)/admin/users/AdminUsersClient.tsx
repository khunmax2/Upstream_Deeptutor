"use client";

import { Fragment, useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { fetchAuthStatus } from "@/lib/auth";
import {
  listUsers,
  deleteUser,
  restoreUser,
  purgeUser,
  purgeOrphan,
  getUserFootprint,
  listOrphans,
  setUserRole,
  setUserDisabled,
  createUser,
  type AccountFootprint,
  type OrphanRecord,
  type UserRecord,
  type AccountPreset,
} from "@/lib/admin-api";
import {
  ACCOUNT_PRESETS,
  isGuardablePreset,
  presetLabel,
} from "@/lib/account-presets";
import { BIN_RETENTION_DAYS, binDaysLeft } from "@/lib/account-bin";
import { listClassrooms } from "@/lib/school-api";
import {
  getStudioFootprint,
  listStudioOwners,
  purgeStudioAccount,
  type StudioFootprint,
} from "@/lib/studio-admin-api";
import { GrantEditor } from "@/features/multi-user/components/GrantEditor";
import { BookPermissionEditor } from "@/features/multi-user/components/BookPermissionEditor";
import { LearnerProfileEditor } from "@/features/multi-user/components/LearnerProfileEditor";
import { GuardianRelationshipsEditor } from "@/features/multi-user/components/GuardianRelationshipsEditor";
import { UserAvatar } from "@/components/UserAvatar";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { filterUsersByQuery } from "@/lib/admin-users";
import {
  Search,
  Shield,
  ShieldCheck,
  ShieldOff,
  Trash2,
  RefreshCw,
  ArrowLeft,
  Archive,
  RotateCcw,
  School,
  SlidersHorizontal,
  UserCheck,
  UserPlus,
  UserX,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { formatDate as formatLocaleDate, type Language } from "@/lib/datetime";
import { resolveUiLanguage } from "@/lib/ui-language";

// Delegates to the shared locale mapping so a new UI language only has to be
// taught to lib/datetime; the guard here is for the empty or unparseable
// created_at that Intl would throw on.
function formatDate(iso: string, lang: Language): string {
  if (!iso) return "—";
  try {
    return formatLocaleDate(new Date(iso), lang);
  } catch {
    return "—";
  }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

/**
 * What a purge will remove, and what it will keep, on both sides. The typed
 * name is the confirmation; the confirm button stays off until it matches.
 */
interface PurgeTarget {
  /** The DeepWitya account id (`u_…`); for a leftover, the stranded id. */
  userId: string;
  /** The account's name, or the id itself for a leftover with no account. */
  name: string;
  /** True for a leftover: no account record, purge by id. */
  orphan: boolean;
  /** Whether DeepWitya holds data for this id (a leftover may be studio-only). */
  onDeepWitya: boolean;
}

interface AdminUsersClientProps {
  /** Same-origin path of the Course Studio, or "" when none is configured. */
  studioBase: string;
}

export default function AdminUsersClient({
  studioBase,
}: AdminUsersClientProps) {
  const router = useRouter();
  const { t, i18n } = useTranslation();
  const lang: Language = resolveUiLanguage(i18n.language);
  const [currentUser, setCurrentUser] = useState<string | null>(null);
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [expandedUserId, setExpandedUserId] = useState<string | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [query, setQuery] = useState("");
  const [confirmTarget, setConfirmTarget] = useState<{
    kind: "delete" | "restore" | "promote" | "demote" | "disable" | "enable";
    user: UserRecord;
  } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [createUsername, setCreateUsername] = useState("");
  const [createPassword, setCreatePassword] = useState("");
  const [createPreset, setCreatePreset] = useState<AccountPreset>("standard");
  const [createSubmitting, setCreateSubmitting] = useState(false);
  const [createError, setCreateError] = useState("");
  // Fork (Phase 2): the bin tab, the typed purge dialog and the leftovers panel.
  const [tab, setTab] = useState<"users" | "bin">("users");
  const [purgeTarget, setPurgeTarget] = useState<PurgeTarget | null>(null);
  const [purgeTyped, setPurgeTyped] = useState("");
  const [purgeBusy, setPurgeBusy] = useState(false);
  const [purgeError, setPurgeError] = useState("");
  const [purgeFootprint, setPurgeFootprint] = useState<{
    deepwitya: AccountFootprint | null;
    studio: StudioFootprint | null;
    studioError: string;
    loading: boolean;
  }>({ deepwitya: null, studio: null, studioError: "", loading: false });
  const [orphans, setOrphans] = useState<OrphanRecord[]>([]);
  // Fork (school roles, Phase 3a): which classrooms each account is in,
  // shown under the preset. Read-only here; edited on /admin/classrooms.
  const [classNames, setClassNames] = useState<Map<string, string>>(
    () => new Map(),
  );
  const [studioOnlyIds, setStudioOnlyIds] = useState<string[]>([]);
  const [leftoversError, setLeftoversError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await listUsers();
      setUsers(data);
      listClassrooms()
        .then((rooms) => {
          const names = new Map<string, string[]>();
          for (const room of rooms) {
            for (const id of [...room.teacher_ids, ...room.student_ids]) {
              names.set(id, [...(names.get(id) ?? []), room.name]);
            }
          }
          setClassNames(
            new Map([...names].map(([id, list]) => [id, list.join(", ")])),
          );
        })
        .catch(() => setClassNames(new Map()));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("Failed to load users"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  // Fork: only the primary admin changes roles, deletes, restores or purges
  // (docs/planning/admin-roles/, §2 and §4); the server answers 403 to
  // anyone else, so the page does not offer.
  const viewerIsPrimary = users.some(
    (u) => u.username === currentUser && Boolean(u.is_primary),
  );
  const liveUsers = users.filter((u) => !u.deleted_at);
  const binUsers = users.filter((u) => Boolean(u.deleted_at));

  // Fork: ids with data but no account, on either side. DeepWitya lists its
  // own; the studio lists every owner it holds rows for, and the ones that
  // match no account (live or in the bin) and no DeepWitya leftover are
  // studio-only leftovers.
  const loadLeftovers = useCallback(async () => {
    if (!viewerIsPrimary) return;
    setLeftoversError("");
    try {
      const [own, studio] = await Promise.all([
        listOrphans(),
        listStudioOwners(studioBase).catch((e: unknown) => {
          setLeftoversError(
            e instanceof Error ? e.message : t("Failed to list leftovers"),
          );
          return null;
        }),
      ]);
      setOrphans(own);
      const known = new Set(users.map((u) => u.id));
      const ownIds = new Set(own.map((o) => o.user_id));
      setStudioOnlyIds(
        (studio ?? [])
          .filter((owner) => owner.startsWith("user:"))
          .map((owner) => owner.slice("user:".length))
          .filter((id) => !known.has(id) && !ownIds.has(id)),
      );
    } catch (e) {
      setLeftoversError(
        e instanceof Error ? e.message : t("Failed to list leftovers"),
      );
    }
  }, [viewerIsPrimary, studioBase, users, t]);

  useEffect(() => {
    if (tab === "bin") void loadLeftovers();
  }, [tab, loadLeftovers]);

  useEffect(() => {
    fetchAuthStatus().then((status) => {
      if (!status?.authenticated) {
        router.replace("/login");
        return;
      }
      if (status.role !== "admin") {
        router.replace("/");
        return;
      }
      setCurrentUser(status.username ?? null);
      void load();
    });
  }, [router, load]);

  function openCreateDialog() {
    setCreateUsername("");
    setCreatePassword("");
    setCreatePreset("standard");
    setCreateError("");
    setShowCreateDialog(true);
  }

  function closeCreateDialog() {
    if (createSubmitting) return;
    setShowCreateDialog(false);
  }

  async function handleCreateSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (createSubmitting) return;
    setCreateError("");
    const username = createUsername.trim();
    if (!username) {
      setCreateError(t("Username is required."));
      return;
    }
    if (createPassword.length < 8) {
      setCreateError(t("Password must be at least 8 characters."));
      return;
    }
    setCreateSubmitting(true);
    try {
      await createUser(username, createPassword, createPreset);
      setShowCreateDialog(false);
      await load();
    } catch (e) {
      setCreateError(
        e instanceof Error ? e.message : t("Failed to create user"),
      );
    } finally {
      setCreateSubmitting(false);
    }
  }

  async function handleConfirmAction() {
    if (!confirmTarget || confirmBusy) return;
    const { kind, user } = confirmTarget;
    setConfirmBusy(true);
    setActionError("");
    try {
      if (kind === "delete") {
        // Fork (Phase 2): the account goes to the bin, restorable for 30 days.
        const deletedAt = await deleteUser(user.username);
        setUsers((prev) =>
          prev.map((u) =>
            u.username === user.username ? { ...u, deleted_at: deletedAt } : u,
          ),
        );
      } else if (kind === "restore") {
        await restoreUser(user.username);
        setUsers((prev) =>
          prev.map((u) =>
            u.username === user.username ? { ...u, deleted_at: null } : u,
          ),
        );
      } else if (kind === "disable" || kind === "enable") {
        // Fork: shut or reopen the account; everything it owns stays.
        const disabled = kind === "disable";
        await setUserDisabled(user.username, disabled);
        setUsers((prev) =>
          prev.map((u) =>
            u.username === user.username ? { ...u, disabled } : u,
          ),
        );
      } else {
        const newRole = kind === "promote" ? "admin" : "user";
        await setUserRole(user.username, newRole);
        setUsers((prev) =>
          prev.map((u) =>
            u.username === user.username ? { ...u, role: newRole } : u,
          ),
        );
        if (newRole === "admin") {
          setExpandedUserId((current) =>
            current === user.id ? null : current,
          );
        }
      }
      setConfirmTarget(null);
    } catch (e) {
      setConfirmTarget(null);
      setActionError(
        e instanceof Error
          ? e.message
          : confirmTarget.kind === "delete"
            ? t("Failed to delete user")
            : confirmTarget.kind === "restore"
              ? t("Failed to restore user")
              : confirmTarget.kind === "disable" ||
                  confirmTarget.kind === "enable"
                ? t("Failed to update account")
                : t("Failed to update role"),
      );
    } finally {
      setConfirmBusy(false);
    }
  }

  // Fork (Phase 2): the purge dialog. It measures both sides first, so the
  // admin sees what goes and what stays before typing the name.
  function openPurge(target: PurgeTarget) {
    setPurgeTarget(target);
    setPurgeTyped("");
    setPurgeError("");
    setPurgeFootprint({
      deepwitya: null,
      studio: null,
      studioError: "",
      loading: true,
    });
    void (async () => {
      let deepwitya: AccountFootprint | null = null;
      let studio: StudioFootprint | null = null;
      let studioError = "";
      try {
        if (target.onDeepWitya) {
          deepwitya = target.orphan
            ? (orphans.find((o) => o.user_id === target.userId)?.footprint ??
              null)
            : await getUserFootprint(target.name);
        }
      } catch (e) {
        setPurgeError(
          e instanceof Error ? e.message : t("Failed to measure the account"),
        );
      }
      try {
        studio = await getStudioFootprint(studioBase, target.userId);
      } catch (e) {
        studioError =
          e instanceof Error ? e.message : t("Failed to measure studio data");
      }
      setPurgeFootprint({ deepwitya, studio, studioError, loading: false });
    })();
  }

  async function handlePurge() {
    if (!purgeTarget || purgeBusy || purgeTyped !== purgeTarget.name) return;
    setPurgeBusy(true);
    setPurgeError("");
    try {
      // The studio first: its rows are findable only while the id is known
      // here. If it fails, nothing is removed and the dialog says so; if
      // DeepWitya's half fails after it, the account is still in the bin and
      // the button can be pressed again -- the studio purge is idempotent.
      await purgeStudioAccount(studioBase, purgeTarget.userId);
      if (purgeTarget.onDeepWitya) {
        if (purgeTarget.orphan) {
          await purgeOrphan(purgeTarget.userId, purgeTyped);
        } else {
          await purgeUser(purgeTarget.name, purgeTyped);
        }
      }
      if (purgeTarget.orphan) {
        setOrphans((prev) =>
          prev.filter((o) => o.user_id !== purgeTarget.userId),
        );
        setStudioOnlyIds((prev) =>
          prev.filter((id) => id !== purgeTarget.userId),
        );
      } else {
        setUsers((prev) => prev.filter((u) => u.id !== purgeTarget.userId));
      }
      setPurgeTarget(null);
    } catch (e) {
      setPurgeError(
        e instanceof Error ? e.message : t("Failed to purge the account"),
      );
    } finally {
      setPurgeBusy(false);
    }
  }

  useEffect(() => {
    if (!expandedUserId) return;
    const expanded = users.find((user) => user.id === expandedUserId);
    if (!expanded || expanded.role === "admin") {
      setExpandedUserId(null);
    }
  }, [expandedUserId, users]);

  const normalizedQuery = query.trim().toLowerCase();
  const filteredUsers = filterUsersByQuery(liveUsers, query);

  // The confirmation dialog's copy, per action. Fork adds disable/enable
  // (docs/planning/admin-roles/, §3): the account is shut, not removed.
  const confirmCopy = (() => {
    switch (confirmTarget?.kind) {
      case "promote":
        return {
          title: t("Promote to admin"),
          confirm: t("Promote"),
          busy: t("Promoting…"),
          tone: "default" as const,
          body: t(
            "Admins can manage users and assignments, and work in the shared main workspace.",
          ),
        };
      case "demote":
        return {
          title: t("Demote to user"),
          confirm: t("Demote"),
          busy: t("Demoting…"),
          tone: "default" as const,
          body: t(
            "They will lose access to the admin area and switch to their own assigned workspace.",
          ),
        };
      case "disable":
        return {
          title: t("Disable account"),
          confirm: t("Disable"),
          busy: t("Disabling…"),
          tone: "danger" as const,
          body: t(
            "The account can no longer sign in. Everything it owns stays, and it can be enabled again.",
          ),
        };
      case "enable":
        return {
          title: t("Enable account"),
          confirm: t("Enable"),
          busy: t("Enabling…"),
          tone: "default" as const,
          body: t("The account can sign in again."),
        };
      case "restore":
        return {
          title: t("Restore account"),
          confirm: t("Restore"),
          busy: t("Restoring…"),
          tone: "default" as const,
          body: t(
            "The account comes back exactly as it was, and can sign in again.",
          ),
        };
      default:
        // Fork (Phase 2): delete is reversible, so it asks once and does not
        // make the admin type; the purge from the bin is the typed step.
        return {
          title: t("Delete user"),
          confirm: t("Delete user"),
          busy: t("Deleting…"),
          tone: "danger" as const,
          body: t(
            "The account goes to the bin: it can no longer sign in, everything it owns stays, and it can be restored for {{days}} days. Purging it from the bin is what removes its data.",
            { days: BIN_RETENTION_DAYS },
          ),
        };
    }
  })();

  return (
    <div className="h-screen overflow-y-auto bg-[var(--background)] px-4 py-10 [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-3xl">
        {/* Header */}
        <div className="mb-8">
          <Link
            href="/"
            className="mb-4 inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
          >
            <ArrowLeft size={16} />
            {t("Back")}
          </Link>
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="font-serif text-xl font-semibold text-[var(--foreground)]">
                {t("User Management")}
              </h1>
              <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
                {t("Manage registered accounts")}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {/* Fork (school roles, Phase 3a): classrooms live on their own page. */}
              <Link
                href="/admin/classrooms"
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm
                           border border-[var(--border)] text-[var(--foreground)]
                           hover:bg-[var(--card)] transition-colors"
              >
                <School size={14} />
                {t("Classrooms")}
              </Link>
              <button
                onClick={openCreateDialog}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm
                           border border-[var(--border)] text-[var(--foreground)]
                           hover:bg-[var(--card)] transition-colors"
              >
                <UserPlus size={14} />
                {t("Add user")}
              </button>
              <button
                onClick={load}
                disabled={loading}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm
                           border border-[var(--border)] text-[var(--muted-foreground)]
                           hover:text-[var(--foreground)] hover:bg-[var(--card)]
                           disabled:opacity-50 transition-colors"
              >
                <RefreshCw
                  size={14}
                  className={loading ? "animate-spin" : ""}
                />
                {t("Refresh")}
              </button>
            </div>
          </div>
        </div>

        {actionError && (
          <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
            {actionError}
          </div>
        )}

        {viewerIsPrimary && !loading && !error && (
          <div
            className="mb-4 inline-flex rounded-lg bg-[var(--muted)]/50 p-1"
            role="tablist"
          >
            {(["users", "bin"] as const).map((key) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  tab === key
                    ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
                    : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                {key === "users" ? <Users size={13} /> : <Archive size={13} />}
                {key === "users"
                  ? t("Accounts")
                  : t("Bin ({{count}})", { count: binUsers.length })}
              </button>
            ))}
          </div>
        )}

        {tab === "bin" && viewerIsPrimary ? (
          <BinPanel
            binUsers={binUsers}
            orphans={orphans}
            studioOnlyIds={studioOnlyIds}
            leftoversError={leftoversError}
            lang={lang}
            onRestore={(user) => setConfirmTarget({ kind: "restore", user })}
            onPurgeUser={(user) =>
              openPurge({
                userId: user.id,
                name: user.username,
                orphan: false,
                onDeepWitya: true,
              })
            }
            onPurgeLeftover={(userId, onDeepWitya) =>
              openPurge({ userId, name: userId, orphan: true, onDeepWitya })
            }
          />
        ) : null}

        {tab === "users" && !loading && !error && liveUsers.length > 0 && (
          <div className="mb-4 flex items-center gap-3">
            <div className="relative flex-1">
              <Search
                size={14}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
              />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("Search users…")}
                aria-label={t("Search users")}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--card)] py-2 pl-9 pr-3 text-sm
                           text-[var(--foreground)] placeholder:text-[var(--muted-foreground)]/70
                           outline-none focus:border-[var(--ring)] transition-colors"
              />
            </div>
            <span className="shrink-0 text-xs text-[var(--muted-foreground)]">
              {normalizedQuery
                ? t("{{filtered}} of {{total}}", {
                    filtered: filteredUsers.length,
                    total: liveUsers.length,
                  })
                : t(
                    liveUsers.length === 1
                      ? "{{count}} user"
                      : "{{count}} users",
                    {
                      count: liveUsers.length,
                    },
                  )}
            </span>
          </div>
        )}

        <div
          className="rounded-2xl border border-[var(--border)] bg-[var(--card)] overflow-hidden shadow-sm"
          hidden={tab === "bin" && viewerIsPrimary}
        >
          {loading ? (
            <div className="divide-y divide-[var(--border)]" aria-hidden>
              {[0, 1, 2].map((row) => (
                <div
                  key={row}
                  className="flex animate-pulse items-center gap-3 px-5 py-4"
                >
                  <div className="h-8 w-8 rounded-full bg-[var(--muted)]/60" />
                  <div className="flex-1 space-y-2">
                    <div className="h-3 w-36 rounded bg-[var(--muted)]/60" />
                    <div className="h-2.5 w-24 rounded bg-[var(--muted)]/40" />
                  </div>
                  <div className="h-5 w-16 rounded-full bg-[var(--muted)]/40" />
                </div>
              ))}
            </div>
          ) : error ? (
            <div className="flex items-center justify-center py-16 text-red-500 text-sm">
              {error}
            </div>
          ) : liveUsers.length === 0 ? (
            <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
              <Users
                size={28}
                strokeWidth={1.5}
                className="text-[var(--muted-foreground)]/50"
              />
              <p className="mt-3 text-sm font-medium text-[var(--foreground)]">
                {t("No users yet")}
              </p>
              <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                {t("Accounts you create will appear here.")}
              </p>
              <button
                onClick={openCreateDialog}
                className="mt-4 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm
                           border border-[var(--border)] text-[var(--foreground)]
                           hover:bg-[var(--background)]/60 transition-colors"
              >
                <UserPlus size={14} />
                {t("Add user")}
              </button>
            </div>
          ) : filteredUsers.length === 0 ? (
            <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
              <Search
                size={28}
                strokeWidth={1.5}
                className="text-[var(--muted-foreground)]/50"
              />
              <p className="mt-3 text-sm font-medium text-[var(--foreground)]">
                {t("No users match “{{query}}”", { query: query.trim() })}
              </p>
              <button
                onClick={() => setQuery("")}
                className="mt-4 rounded-lg px-3 py-1.5 text-sm border border-[var(--border)]
                           text-[var(--muted-foreground)] hover:text-[var(--foreground)]
                           hover:bg-[var(--background)]/60 transition-colors"
              >
                {t("Clear search")}
              </button>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--muted-foreground)] uppercase tracking-wider">
                  <th className="px-5 py-3 font-medium">{t("Username")}</th>
                  <th className="px-5 py-3 font-medium">{t("Role")}</th>
                  <th className="px-5 py-3 font-medium">{t("Joined")}</th>
                  <th className="px-5 py-3 font-medium text-right">
                    {t("Actions")}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {filteredUsers.map((user) => {
                  const isSelf = user.username === currentUser;
                  const isAdmin = user.role === "admin";
                  // Fork: the primary admin is the deployment's superadmin; the
                  // server refuses to demote or delete it, so the page never offers.
                  const isPrimary = Boolean(user.is_primary);
                  const canManageAssignments = !isAdmin && Boolean(user.id);
                  return (
                    <Fragment key={user.username}>
                      <tr className="group hover:bg-[var(--background)]/50 transition-colors">
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-3">
                            <UserAvatar
                              username={user.username}
                              userId={user.id}
                              avatar={user.avatar}
                              role={user.role}
                              size={32}
                            />
                            <span className="min-w-0 truncate font-medium text-[var(--foreground)]">
                              {user.username}
                              {isSelf && (
                                <span className="ml-2 text-xs font-normal text-[var(--muted-foreground)]">
                                  {t("(you)")}
                                </span>
                              )}
                            </span>
                          </div>
                        </td>
                        <td className="px-5 py-3">
                          <span
                            className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium
                            ${
                              isAdmin
                                ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                                : "bg-[var(--muted)]/50 text-[var(--muted-foreground)]"
                            }`}
                          >
                            {isAdmin && (
                              <ShieldCheck size={11} strokeWidth={2} />
                            )}
                            {isAdmin ? t("Admin") : t("User")}
                          </span>
                          {isPrimary && (
                            <span className="mt-1 block text-[11px] font-medium text-amber-600 dark:text-amber-400">
                              {t("Primary admin")}
                            </span>
                          )}
                          {user.disabled && (
                            <span className="mt-1 block text-[11px] font-medium text-red-600 dark:text-red-400">
                              {t("Disabled")}
                            </span>
                          )}
                          {!isAdmin && user.preset && (
                            <span className="mt-1 block text-[11px] text-[var(--muted-foreground)]">
                              {t("Preset: {{preset}}", {
                                preset: t(presetLabel(user.preset)),
                              })}
                            </span>
                          )}
                          {classNames.get(user.id) && (
                            <span className="mt-0.5 block text-[11px] text-[var(--muted-foreground)]">
                              {t("Class: {{names}}", {
                                names: classNames.get(user.id),
                              })}
                            </span>
                          )}
                        </td>
                        <td className="px-5 py-3.5 text-[var(--muted-foreground)]">
                          {formatDate(user.created_at, lang)}
                        </td>
                        <td className="px-5 py-3.5">
                          <div className="flex items-center justify-end gap-1.5">
                            {canManageAssignments && (
                              <button
                                onClick={() =>
                                  setExpandedUserId((current) =>
                                    current === user.id ? null : user.id,
                                  )
                                }
                                title={t("Manage assignments")}
                                className="rounded-lg p-1.5 text-[var(--muted-foreground)]
                                         hover:bg-[var(--background)] hover:text-[var(--foreground)]
                                         transition-colors"
                              >
                                <SlidersHorizontal size={15} />
                              </button>
                            )}
                            <button
                              onClick={() =>
                                setConfirmTarget({
                                  kind: isAdmin ? "demote" : "promote",
                                  user,
                                })
                              }
                              disabled={isSelf || isPrimary || !viewerIsPrimary}
                              title={
                                isSelf
                                  ? t("Cannot change your own role")
                                  : isPrimary
                                    ? t(
                                        "The primary admin's role cannot be changed",
                                      )
                                    : !viewerIsPrimary
                                      ? t(
                                          "Only the primary admin manages admins",
                                        )
                                      : user.role === "admin"
                                        ? t("Demote to user")
                                        : t("Promote to admin")
                              }
                              className="rounded-lg p-1.5 text-[var(--muted-foreground)]
                                       hover:bg-[var(--background)] hover:text-[var(--foreground)]
                                       disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                            >
                              {user.role === "admin" ? (
                                <ShieldOff size={15} />
                              ) : (
                                <Shield size={15} />
                              )}
                            </button>
                            {!isSelf && !isPrimary && (
                              <button
                                onClick={() =>
                                  setConfirmTarget({
                                    kind: user.disabled ? "enable" : "disable",
                                    user,
                                  })
                                }
                                disabled={isAdmin && !viewerIsPrimary}
                                title={
                                  isAdmin && !viewerIsPrimary
                                    ? t("Only the primary admin manages admins")
                                    : user.disabled
                                      ? t("Enable account")
                                      : t("Disable account")
                                }
                                className="rounded-lg p-1.5 text-[var(--muted-foreground)]
                                         hover:bg-[var(--background)] hover:text-[var(--foreground)]
                                         disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                              >
                                {user.disabled ? (
                                  <UserCheck size={15} />
                                ) : (
                                  <UserX size={15} />
                                )}
                              </button>
                            )}
                            {viewerIsPrimary && (
                              <button
                                onClick={() =>
                                  setConfirmTarget({ kind: "delete", user })
                                }
                                disabled={isSelf || isPrimary}
                                title={
                                  isSelf
                                    ? t("Cannot delete your own account")
                                    : isPrimary
                                      ? t("The primary admin cannot be deleted")
                                      : t("Delete {{username}}", {
                                          username: user.username,
                                        })
                                }
                                className="rounded-lg p-1.5 text-[var(--muted-foreground)]
                                         hover:bg-red-500/10 hover:text-red-500
                                         disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                              >
                                <Trash2 size={15} />
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                      {canManageAssignments && expandedUserId === user.id && (
                        <tr>
                          <td colSpan={4} className="p-0">
                            <GrantEditor
                              key={user.id}
                              userId={user.id}
                              lockLearningPolicy={user.preset === "learner"}
                            />
                            <BookPermissionEditor userId={user.id} />
                            {isGuardablePreset(user.preset) && (
                              <GuardianRelationshipsEditor
                                learnerId={user.id}
                                learnerUsername={user.username}
                                users={users}
                              />
                            )}
                            {user.preset === "learner" && (
                              <LearnerProfileEditor username={user.username} />
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <p className="mt-8 text-center text-xs text-[var(--muted-foreground)]">
          {t("DeepTutor Admin · User Management")}
        </p>
      </div>

      <ConfirmDialog
        open={confirmTarget !== null}
        title={confirmCopy.title}
        tone={confirmCopy.tone}
        confirmLabel={confirmCopy.confirm}
        busyLabel={confirmCopy.busy}
        busy={confirmBusy}
        onConfirm={handleConfirmAction}
        onCancel={() => setConfirmTarget(null)}
      >
        {confirmTarget && (
          <>
            <div className="flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--background)]/50 px-3 py-2.5">
              <UserAvatar
                username={confirmTarget.user.username}
                userId={confirmTarget.user.id}
                avatar={confirmTarget.user.avatar}
                role={confirmTarget.user.role}
                size={32}
              />
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-[var(--foreground)]">
                  {confirmTarget.user.username}
                </p>
                <p className="text-xs text-[var(--muted-foreground)]">
                  {t("{{role}} · joined {{date}}", {
                    role:
                      confirmTarget.user.role === "admin"
                        ? t("Admin")
                        : t("User"),
                    date: formatDate(confirmTarget.user.created_at, lang),
                  })}
                </p>
              </div>
            </div>
            <p className="mt-3">{confirmCopy.body}</p>
          </>
        )}
      </ConfirmDialog>

      <ConfirmDialog
        open={purgeTarget !== null}
        title={t("Purge account data")}
        tone="danger"
        confirmLabel={t("Purge")}
        busyLabel={t("Purging…")}
        busy={purgeBusy}
        confirmDisabled={
          purgeFootprint.loading || purgeTyped !== (purgeTarget?.name ?? "")
        }
        onConfirm={handlePurge}
        onCancel={() => {
          if (!purgeBusy) setPurgeTarget(null);
        }}
      >
        {purgeTarget && (
          <PurgeSummary
            target={purgeTarget}
            footprint={purgeFootprint}
            typed={purgeTyped}
            onTyped={setPurgeTyped}
            error={purgeError}
            studioConfigured={Boolean(studioBase)}
          />
        )}
      </ConfirmDialog>

      {showCreateDialog && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] px-4"
          role="dialog"
          aria-modal="true"
          onClick={closeCreateDialog}
        >
          <form
            onClick={(e) => e.stopPropagation()}
            onSubmit={handleCreateSubmit}
            className="w-full max-w-sm rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-xl"
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-base font-semibold text-[var(--foreground)]">
                {t("Add user")}
              </h2>
              <button
                type="button"
                onClick={closeCreateDialog}
                disabled={createSubmitting}
                className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)] disabled:opacity-40"
                aria-label={t("Close")}
              >
                <X size={16} />
              </button>
            </div>

            <label className="mb-3 block text-xs text-[var(--muted-foreground)]">
              {t("Username (or email)")}
              <input
                type="text"
                value={createUsername}
                onChange={(e) => setCreateUsername(e.target.value)}
                disabled={createSubmitting}
                autoComplete="off"
                autoFocus
                className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
              />
            </label>

            <label className="mb-4 block text-xs text-[var(--muted-foreground)]">
              {t("Password (≥ 8 chars)")}
              <input
                type="password"
                value={createPassword}
                onChange={(e) => setCreatePassword(e.target.value)}
                disabled={createSubmitting}
                autoComplete="new-password"
                className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
              />
            </label>

            <fieldset className="mb-4">
              <legend className="mb-1.5 block text-xs text-[var(--muted-foreground)]">
                {t("Account preset")}
              </legend>
              <div
                className="grid grid-cols-3 gap-1 sm:grid-cols-5 rounded-lg bg-[var(--muted)]/50 p-1"
                role="group"
                aria-label={t("Account preset")}
              >
                {ACCOUNT_PRESETS.map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    disabled={createSubmitting}
                    aria-pressed={createPreset === preset}
                    onClick={() => setCreatePreset(preset)}
                    className={`rounded-md px-2 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${
                      createPreset === preset
                        ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
                        : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    }`}
                  >
                    {t(presetLabel(preset))}
                  </button>
                ))}
              </div>
              <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
                {createPreset === "learner"
                  ? t(
                      "Chat and Immersive Reading only, with uploads and tools disabled until assigned.",
                    )
                  : createPreset === "custom"
                    ? t(
                        "Create an ordinary account, then customize its assignments.",
                      )
                    : createPreset === "student"
                      ? t(
                          "A secondary-school student: the full tutor with the school's models; no own keys, partners or code execution.",
                        )
                      : createPreset === "teacher"
                        ? t(
                            "A teacher: an ordinary account that is linked to students as their guardian.",
                          )
                        : t(
                            "Create an ordinary account with the default workspace behavior.",
                          )}
              </p>
            </fieldset>

            {createError && (
              <p className="mb-3 text-xs text-red-500">{createError}</p>
            )}

            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={closeCreateDialog}
                disabled={createSubmitting}
                className="rounded-lg px-3 py-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-40"
              >
                {t("Cancel")}
              </button>
              <button
                type="submit"
                disabled={createSubmitting}
                className="rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-sm font-medium text-[var(--background)] hover:opacity-90 disabled:opacity-40"
              >
                {createSubmitting ? t("Creating…") : t("Create")}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

/** Fork (Phase 2): the bin -- accounts that can be restored or purged -- and the leftovers. */
function BinPanel({
  binUsers,
  orphans,
  studioOnlyIds,
  leftoversError,
  lang,
  onRestore,
  onPurgeUser,
  onPurgeLeftover,
}: {
  binUsers: UserRecord[];
  orphans: OrphanRecord[];
  studioOnlyIds: string[];
  leftoversError: string;
  lang: Language;
  onRestore: (user: UserRecord) => void;
  onPurgeUser: (user: UserRecord) => void;
  onPurgeLeftover: (userId: string, onDeepWitya: boolean) => void;
}) {
  const { t } = useTranslation();
  const leftovers = [
    ...orphans.map((o) => ({ userId: o.user_id, onDeepWitya: true })),
    ...studioOnlyIds.map((id) => ({ userId: id, onDeepWitya: false })),
  ];
  const rowButton =
    "rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)] transition-colors";
  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] overflow-hidden shadow-sm">
        {binUsers.length === 0 ? (
          <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
            <Archive
              size={28}
              strokeWidth={1.5}
              className="text-[var(--muted-foreground)]/50"
            />
            <p className="mt-3 text-sm font-medium text-[var(--foreground)]">
              {t("The bin is empty")}
            </p>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              {t(
                "A deleted account waits here for {{days}} days. It can be restored, or purged with its data.",
                { days: BIN_RETENTION_DAYS },
              )}
            </p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--muted-foreground)] uppercase tracking-wider">
                <th className="px-5 py-3 font-medium">{t("Username")}</th>
                <th className="px-5 py-3 font-medium">{t("Deleted")}</th>
                <th className="px-5 py-3 font-medium">{t("Days left")}</th>
                <th className="px-5 py-3 font-medium text-right">
                  {t("Actions")}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {binUsers.map((user) => {
                const daysLeft = binDaysLeft(user.deleted_at ?? "");
                return (
                  <tr
                    key={user.username}
                    className="hover:bg-[var(--background)]/50"
                  >
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-3">
                        <UserAvatar
                          username={user.username}
                          userId={user.id}
                          avatar={user.avatar}
                          role={user.role}
                          size={32}
                        />
                        <div className="min-w-0">
                          <p className="truncate font-medium text-[var(--foreground)]">
                            {user.username}
                          </p>
                          <p className="text-[11px] text-[var(--muted-foreground)]">
                            {user.role === "admin" ? t("Admin") : t("User")}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-3.5 text-[var(--muted-foreground)]">
                      {formatDate(user.deleted_at ?? "", lang)}
                    </td>
                    <td className="px-5 py-3.5">
                      <span
                        className={
                          daysLeft === 0
                            ? "font-medium text-red-600 dark:text-red-400"
                            : "text-[var(--muted-foreground)]"
                        }
                      >
                        {daysLeft === 0
                          ? t("Retention over")
                          : t("{{count}} days", { count: daysLeft })}
                      </span>
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          type="button"
                          onClick={() => onRestore(user)}
                          title={t("Restore account")}
                          className={rowButton}
                        >
                          <RotateCcw size={15} />
                        </button>
                        <button
                          type="button"
                          onClick={() => onPurgeUser(user)}
                          title={t("Purge {{username}}", {
                            username: user.username,
                          })}
                          className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-red-500/10 hover:text-red-500 transition-colors"
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] overflow-hidden shadow-sm">
        <div className="border-b border-[var(--border)] px-5 py-3">
          <p className="text-sm font-medium text-[var(--foreground)]">
            {t("Leftovers")}
          </p>
          <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
            {t(
              "Data that belongs to no account: ids deleted before the bin existed. Purging removes it on both sides.",
            )}
          </p>
        </div>
        {leftoversError && (
          <p className="px-5 py-3 text-xs text-red-500">{leftoversError}</p>
        )}
        {leftovers.length === 0 ? (
          <p className="px-5 py-4 text-sm text-[var(--muted-foreground)]">
            {t("No leftovers")}
          </p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {leftovers.map((item) => (
              <li
                key={item.userId}
                className="flex items-center justify-between gap-3 px-5 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate font-mono text-xs text-[var(--foreground)]">
                    {item.userId}
                  </p>
                  <p className="text-[11px] text-[var(--muted-foreground)]">
                    {item.onDeepWitya
                      ? t("Data on DeepWitya, and possibly in the studio")
                      : t("Data in the Course Studio only")}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => onPurgeLeftover(item.userId, item.onDeepWitya)}
                  title={t("Purge leftovers")}
                  className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-red-500/10 hover:text-red-500 transition-colors"
                >
                  <Trash2 size={15} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** Fork (Phase 2): what a purge removes and keeps, and the typed confirmation. */
function PurgeSummary({
  target,
  footprint,
  typed,
  onTyped,
  error,
  studioConfigured,
}: {
  target: PurgeTarget;
  footprint: {
    deepwitya: AccountFootprint | null;
    studio: StudioFootprint | null;
    studioError: string;
    loading: boolean;
  };
  typed: string;
  onTyped: (value: string) => void;
  error: string;
  studioConfigured: boolean;
}) {
  const { t } = useTranslation();
  const { deepwitya, studio, studioError, loading } = footprint;
  const line = "flex items-center justify-between gap-3 text-xs";
  return (
    <div className="space-y-3">
      <p className="text-sm">
        {target.orphan
          ? t(
              "This removes every trace of {{name}} on both sides. It cannot be undone.",
              {
                name: target.name,
              },
            )
          : t(
              "This removes the account {{name}} and everything it owns on both sides. It cannot be undone.",
              { name: target.name },
            )}
      </p>
      {loading ? (
        <p className="text-xs text-[var(--muted-foreground)]">
          {t("Measuring…")}
        </p>
      ) : (
        <div className="space-y-3 rounded-xl border border-[var(--border)] bg-[var(--background)]/50 px-3 py-2.5">
          {target.onDeepWitya && (
            <div>
              <p className="mb-1 text-xs font-medium text-[var(--foreground)]">
                {t("DeepWitya")}
              </p>
              {deepwitya ? (
                <div className="space-y-0.5">
                  <p className={line}>
                    <span>
                      {t("Workspace (chats, notebooks, knowledge bases)")}
                    </span>
                    <span className="text-[var(--muted-foreground)]">
                      {t("{{count}} files", {
                        count: deepwitya.workspace_files,
                      })}{" "}
                      · {formatBytes(deepwitya.workspace_bytes)}
                    </span>
                  </p>
                  <p className={line}>
                    <span>{t("Grant, secrets, MCP, device credentials")}</span>
                    <span className="text-[var(--muted-foreground)]">
                      {[
                        deepwitya.grant ? t("grant") : null,
                        deepwitya.secrets_files
                          ? t("{{count}} secrets", {
                              count: deepwitya.secrets_files,
                            })
                          : null,
                        deepwitya.mcp_config ? t("MCP") : null,
                        deepwitya.device_credentials
                          ? t("{{count}} devices", {
                              count: deepwitya.device_credentials,
                            })
                          : null,
                      ]
                        .filter(Boolean)
                        .join(" · ") || t("none")}
                    </span>
                  </p>
                </div>
              ) : (
                <p className="text-xs text-[var(--muted-foreground)]">
                  {t("Could not be measured")}
                </p>
              )}
            </div>
          )}
          <div>
            <p className="mb-1 text-xs font-medium text-[var(--foreground)]">
              {t("Course Studio")}
            </p>
            {!studioConfigured ? (
              <p className="text-xs text-[var(--muted-foreground)]">
                {t("No studio is configured; nothing to remove there.")}
              </p>
            ) : studio ? (
              <div className="space-y-0.5">
                <p className={line}>
                  <span>{t("Draft courses and their media")}</span>
                  <span className="text-[var(--muted-foreground)]">
                    {t("{{count}} removed", {
                      count: studio.stagesRemoved.length,
                    })}
                  </span>
                </p>
                <p className={line}>
                  <span>{t("Published courses")}</span>
                  <span className="text-[var(--muted-foreground)]">
                    {t("{{count}} kept for learners", {
                      count: studio.stagesKept.length,
                    })}
                  </span>
                </p>
                <p className={line}>
                  <span>
                    {t("Sessions, skills, materials, settings, own keys")}
                  </span>
                  <span className="text-[var(--muted-foreground)]">
                    {studio.agentSessions +
                      studio.skills +
                      studio.materials +
                      studio.assets +
                      studio.accountKv +
                      studio.credentials}
                  </span>
                </p>
                {studio.sharedWrites > 0 && (
                  <p className="text-[11px] text-[var(--muted-foreground)]">
                    {t(
                      "Keys and lists this account shared with everyone stay; they will show as shared by a deleted account.",
                    )}
                  </p>
                )}
              </div>
            ) : (
              <p className="text-xs text-red-500">
                {studioError || t("Could not be measured")}
              </p>
            )}
          </div>
        </div>
      )}
      <label className="block text-xs text-[var(--muted-foreground)]">
        {t("Type {{name}} to confirm", { name: target.name })}
        <input
          type="text"
          value={typed}
          onChange={(e) => onTyped(e.target.value)}
          autoComplete="off"
          spellCheck={false}
          className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
        />
      </label>
      {error && <p className="text-xs text-red-500">{error}</p>}
    </div>
  );
}
