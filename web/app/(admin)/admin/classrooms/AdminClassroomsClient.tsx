"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Archive,
  ArrowLeft,
  Download,
  FileUp,
  Plus,
  RefreshCw,
  Star,
  Users,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { fetchAdminResources } from "@/features/multi-user/api";
import type { MultiUserResources } from "@/features/multi-user/types";
import { fetchAuthStatus } from "@/lib/auth";
import { listUsers, type UserRecord } from "@/lib/admin-api";
import {
  archiveClassroom,
  createClassroom,
  importStudents,
  listClassrooms,
  setClassroomStudents,
  setClassroomTeachers,
  updateClassroom,
  type Classroom,
  type ClassroomDefaults,
  type ImportReport,
  type MemberChanges,
} from "@/lib/school-api";

/**
 * Fork: classrooms (school roles design, Phase 3a). One page for IT: the
 * classes, each with its teachers (one starred as home-room), its students,
 * and the class defaults a student receives on joining. Membership derives
 * the teacher↔student guardian links on the server; the page only edits
 * the lists and shows what the server did ("2 links created").
 *
 * The CSV import lives here too: a file at term start, a report back, and
 * the generated passwords offered once as a download — they are in that
 * response and nowhere else.
 */

const inputClass =
  "rounded-lg border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]";
const buttonClass =
  "flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--foreground)] transition-colors hover:bg-[var(--card)] disabled:opacity-50";
const primaryButtonClass =
  "rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-sm font-medium text-[var(--background)] hover:opacity-90 disabled:opacity-50";

function errorText(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

export default function AdminClassroomsClient() {
  const router = useRouter();
  const { t } = useTranslation();
  const [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [resources, setResources] = useState<MultiUserResources | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [archiveTarget, setArchiveTarget] = useState<Classroom | null>(null);
  const [archiveBusy, setArchiveBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [rooms, accounts] = await Promise.all([
        listClassrooms(),
        listUsers(),
      ]);
      setClassrooms(rooms);
      setUsers(accounts.filter((u) => !u.deleted_at));
    } catch (e) {
      setError(errorText(e, t("Failed to load classrooms")));
    } finally {
      setLoading(false);
    }
  }, [t]);

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
      void load();
      fetchAdminResources()
        .then(setResources)
        .catch(() => setResources(null));
    });
  }, [router, load]);

  const teachers = useMemo(
    () => users.filter((u) => u.role === "user" && u.preset === "teacher"),
    [users],
  );
  const students = useMemo(
    () => users.filter((u) => u.role === "user" && u.preset === "student"),
    [users],
  );

  const replaceRoom = (room: Classroom) =>
    setClassrooms((current) =>
      current.map((item) => (item.id === room.id ? room : item)),
    );

  const describeChanges = (changes: MemberChanges) =>
    t("{{created}} links created, {{revoked}} revoked", {
      created: changes.links_created,
      revoked: changes.links_revoked,
    });

  const confirmArchive = async () => {
    if (!archiveTarget) return;
    setArchiveBusy(true);
    setError("");
    try {
      await archiveClassroom(archiveTarget.id);
      setClassrooms((current) =>
        current.filter((item) => item.id !== archiveTarget.id),
      );
      setNotice(
        t("Classroom archived: {{name}}", { name: archiveTarget.name }),
      );
      setArchiveTarget(null);
    } catch (e) {
      setError(errorText(e, t("Failed to archive classroom")));
    } finally {
      setArchiveBusy(false);
    }
  };

  return (
    <div className="h-screen overflow-y-auto bg-[var(--background)] px-4 py-10 [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-3xl">
        <div className="mb-8">
          <Link
            href="/admin/users"
            className="mb-4 inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            <ArrowLeft size={16} />
            {t("User Management")}
          </Link>
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="font-serif text-xl font-semibold text-[var(--foreground)]">
                {t("Classrooms")}
              </h1>
              <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
                {t(
                  "Teachers see the students in their classrooms. Students receive the classroom defaults when they join.",
                )}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={() => setShowCreate(true)}
                className={buttonClass}
              >
                <Plus size={14} />
                {t("New classroom")}
              </button>
              <button
                type="button"
                onClick={() => setShowImport(true)}
                className={buttonClass}
              >
                <FileUp size={14} />
                {t("Import CSV")}
              </button>
              <button
                type="button"
                onClick={load}
                disabled={loading}
                className={buttonClass}
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

        {error && (
          <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        )}
        {notice && (
          <div className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-sm text-[var(--foreground)]">
            {notice}
          </div>
        )}

        <div className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
          {loading ? (
            <div className="px-4 py-8 text-center text-sm text-[var(--muted-foreground)]">
              {t("Loading...")}
            </div>
          ) : classrooms.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-[var(--muted-foreground)]">
              {t("No classrooms yet. Create one, or import a CSV.")}
            </div>
          ) : (
            <ul className="divide-y divide-[var(--border)]">
              {classrooms.map((room) => (
                <li key={room.id} data-testid="classroom-row">
                  <button
                    type="button"
                    onClick={() =>
                      setExpandedId(expandedId === room.id ? null : room.id)
                    }
                    className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-[var(--background)]/60"
                    aria-expanded={expandedId === room.id}
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-[var(--foreground)]">
                        {room.name}
                        {room.term && (
                          <span className="ml-2 text-xs text-[var(--muted-foreground)]">
                            {room.term}
                          </span>
                        )}
                      </div>
                      <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                        {t("{{teachers}} teachers · {{students}} students", {
                          teachers: room.teachers.length,
                          students: room.students.length,
                        })}
                        {room.home_room_teacher_id && (
                          <>
                            {" · "}
                            {t("Home-room: {{name}}", {
                              name:
                                room.teachers.find(
                                  (x) => x.id === room.home_room_teacher_id,
                                )?.username ?? "",
                            })}
                          </>
                        )}
                      </div>
                    </div>
                    <Users
                      size={16}
                      className="shrink-0 text-[var(--muted-foreground)]"
                    />
                  </button>
                  {expandedId === room.id && (
                    <ClassroomEditor
                      room={room}
                      teachers={teachers}
                      students={students}
                      resources={resources}
                      onSaved={(next, message) => {
                        replaceRoom(next);
                        if (message) setNotice(message);
                      }}
                      onError={(message) => setError(message)}
                      onArchive={() => setArchiveTarget(room)}
                      describeChanges={describeChanges}
                    />
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {showCreate && (
        <CreateDialog
          teachers={teachers}
          onClose={() => setShowCreate(false)}
          onCreated={(room) => {
            setClassrooms((current) => [...current, room]);
            setShowCreate(false);
            setExpandedId(room.id);
          }}
        />
      )}
      {showImport && (
        <ImportDialog
          onClose={() => {
            setShowImport(false);
            void load();
          }}
        />
      )}
      <ConfirmDialog
        open={archiveTarget !== null}
        title={t("Archive classroom?")}
        confirmLabel={t("Archive")}
        cancelLabel={t("Cancel")}
        tone="danger"
        busy={archiveBusy}
        onConfirm={confirmArchive}
        onCancel={() => setArchiveTarget(null)}
      >
        {t(
          "Its teachers lose access to these students' learning evidence. Accounts and grants are not changed.",
        )}
      </ConfirmDialog>
    </div>
  );
}

// ── the editor ─────────────────────────────────────────────────────────────

function ClassroomEditor({
  room,
  teachers,
  students,
  resources,
  onSaved,
  onError,
  onArchive,
  describeChanges,
}: {
  room: Classroom;
  teachers: UserRecord[];
  students: UserRecord[];
  resources: MultiUserResources | null;
  onSaved: (room: Classroom, message?: string) => void;
  onError: (message: string) => void;
  onArchive: () => void;
  describeChanges: (changes: MemberChanges) => string;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(room.name);
  const [term, setTerm] = useState(room.term);
  const [teacherIds, setTeacherIds] = useState<string[]>(room.teacher_ids);
  const [homeRoom, setHomeRoom] = useState(room.home_room_teacher_id);
  const [studentIds, setStudentIds] = useState<string[]>(room.student_ids);
  const [studentQuery, setStudentQuery] = useState("");
  const [defaults, setDefaults] = useState<ClassroomDefaults>(room.defaults);
  const [busy, setBusy] = useState("");

  const run = async (label: string, work: () => Promise<void>) => {
    setBusy(label);
    try {
      await work();
    } catch (e) {
      onError(errorText(e, t("Failed to save classroom")));
    } finally {
      setBusy("");
    }
  };

  const saveDetails = () =>
    run("details", async () => {
      const next = await updateClassroom(room.id, { name, term });
      onSaved(next, t("Classroom saved"));
    });

  const saveTeachers = () =>
    run("teachers", async () => {
      const { classroom, changes } = await setClassroomTeachers(
        room.id,
        teacherIds,
      );
      const next =
        homeRoom && teacherIds.includes(homeRoom)
          ? await updateClassroom(room.id, { home_room_teacher_id: homeRoom })
          : classroom;
      if (!teacherIds.includes(homeRoom)) setHomeRoom("");
      onSaved(next, describeChanges(changes));
    });

  const saveStudents = () =>
    run("students", async () => {
      const { classroom, changes } = await setClassroomStudents(
        room.id,
        studentIds,
      );
      onSaved(classroom, describeChanges(changes));
    });

  const saveDefaults = () =>
    run("defaults", async () => {
      const next = await updateClassroom(room.id, { defaults });
      onSaved(next, t("Classroom defaults saved"));
    });

  const toggle = (list: string[], id: string) =>
    list.includes(id) ? list.filter((x) => x !== id) : [...list, id];

  const visibleStudents = students.filter(
    (u) =>
      !studentQuery.trim() ||
      u.username.toLowerCase().includes(studentQuery.trim().toLowerCase()),
  );

  const llmDefaults = defaults.grant?.models?.llm ?? [];
  const kbDefaults = defaults.grant?.knowledge_bases ?? [];
  const hasModel = (profileId: string, modelId: string) =>
    llmDefaults.some(
      (item) =>
        item.profile_id === profileId &&
        (item.model_ids ?? []).includes(modelId),
    );
  const toggleModel = (profileId: string, modelId: string) =>
    setDefaults((current) => {
      const llm = (current.grant?.models?.llm ?? []).map((item) => ({
        ...item,
        model_ids: [...(item.model_ids ?? [])],
      }));
      const existing = llm.find((item) => item.profile_id === profileId);
      if (!existing) llm.push({ profile_id: profileId, model_ids: [modelId] });
      else if (existing.model_ids?.includes(modelId))
        existing.model_ids = existing.model_ids.filter((m) => m !== modelId);
      else existing.model_ids = [...(existing.model_ids ?? []), modelId];
      return {
        grant: {
          ...current.grant,
          models: { llm: llm.filter((item) => (item.model_ids ?? []).length) },
        },
      };
    });
  const toggleKb = (resourceId: string, kbName: string) =>
    setDefaults((current) => {
      const kbs = current.grant?.knowledge_bases ?? [];
      const exists = kbs.some((item) => item.resource_id === resourceId);
      return {
        grant: {
          ...current.grant,
          knowledge_bases: exists
            ? kbs.filter((item) => item.resource_id !== resourceId)
            : [
                ...kbs,
                {
                  resource_id: resourceId,
                  name: kbName,
                  access: "read",
                  source: "admin",
                },
              ],
        },
      };
    });

  return (
    <div className="space-y-5 border-t border-[var(--border)] bg-[var(--background)]/40 px-4 py-4 text-sm">
      <section className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-[var(--muted-foreground)]">
          {t("Name")}
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={`mt-1 block ${inputClass}`}
          />
        </label>
        <label className="text-xs text-[var(--muted-foreground)]">
          {t("Term")}
          <input
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="2569/1"
            className={`mt-1 block ${inputClass}`}
          />
        </label>
        <button
          type="button"
          onClick={saveDetails}
          disabled={busy !== "" || !name.trim()}
          className={primaryButtonClass}
        >
          {busy === "details" ? t("Saving...") : t("Save")}
        </button>
        <button
          type="button"
          onClick={onArchive}
          className={`${buttonClass} ml-auto text-red-600 dark:text-red-400`}
        >
          <Archive size={14} />
          {t("Archive")}
        </button>
      </section>

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("Teachers")}
        </h3>
        {teachers.length === 0 ? (
          <p className="text-xs text-[var(--muted-foreground)]">
            {t(
              "No teacher accounts yet. Create one on the users page with the Teacher account preset.",
            )}
          </p>
        ) : (
          <ul className="grid gap-1 sm:grid-cols-2">
            {teachers.map((u) => (
              <li key={u.id} className="flex items-center gap-2 py-0.5">
                <label className="flex flex-1 cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    checked={teacherIds.includes(u.id)}
                    onChange={() => setTeacherIds(toggle(teacherIds, u.id))}
                  />
                  <span className="truncate">{u.username}</span>
                </label>
                <button
                  type="button"
                  title={t("Home-room teacher")}
                  aria-label={t("Home-room teacher")}
                  aria-pressed={homeRoom === u.id}
                  disabled={!teacherIds.includes(u.id)}
                  onClick={() => setHomeRoom(homeRoom === u.id ? "" : u.id)}
                  className="rounded p-1 text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-30"
                >
                  <Star
                    size={14}
                    fill={homeRoom === u.id ? "currentColor" : "none"}
                  />
                </button>
              </li>
            ))}
          </ul>
        )}
        <button
          type="button"
          onClick={saveTeachers}
          disabled={busy !== ""}
          className={`${primaryButtonClass} mt-2`}
        >
          {busy === "teachers" ? t("Saving...") : t("Save teachers")}
        </button>
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("Students")} ({studentIds.length})
          </h3>
          <input
            type="search"
            value={studentQuery}
            onChange={(e) => setStudentQuery(e.target.value)}
            placeholder={t("Search students…")}
            aria-label={t("Search students")}
            className={`${inputClass} w-44`}
          />
        </div>
        {students.length === 0 ? (
          <p className="text-xs text-[var(--muted-foreground)]">
            {t(
              "No student accounts yet. Import a CSV, or create them on the users page.",
            )}
          </p>
        ) : (
          <ul className="grid max-h-64 gap-1 overflow-y-auto sm:grid-cols-3">
            {visibleStudents.map((u) => (
              <li key={u.id}>
                <label className="flex cursor-pointer items-center gap-2 py-0.5">
                  <input
                    type="checkbox"
                    checked={studentIds.includes(u.id)}
                    onChange={() => setStudentIds(toggle(studentIds, u.id))}
                  />
                  <span className="truncate">{u.username}</span>
                </label>
              </li>
            ))}
          </ul>
        )}
        <button
          type="button"
          onClick={saveStudents}
          disabled={busy !== ""}
          className={`${primaryButtonClass} mt-2`}
        >
          {busy === "students" ? t("Saving...") : t("Save students")}
        </button>
      </section>

      <section>
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("Classroom defaults")}
        </h3>
        <p className="mb-2 text-xs text-[var(--muted-foreground)]">
          {t(
            "Given to a student when they join this classroom. Each student's grant can still be edited on the users page; leaving the classroom takes nothing away.",
          )}
        </p>
        {resources === null ? (
          <p className="text-xs text-[var(--muted-foreground)]">
            {t("Loading...")}
          </p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <div className="mb-1 text-xs text-[var(--muted-foreground)]">
                {t("Models")}
              </div>
              {(resources.models.llm || []).map((profile) => (
                <div key={profile.profile_id} className="mb-1.5">
                  <div className="truncate text-xs text-[var(--muted-foreground)]">
                    {profile.name}
                  </div>
                  {(profile.models || []).map((model) => (
                    <label
                      key={model.model_id}
                      className="flex cursor-pointer items-center gap-2 py-0.5 text-xs"
                    >
                      <input
                        type="checkbox"
                        checked={hasModel(profile.profile_id, model.model_id)}
                        onChange={() =>
                          toggleModel(profile.profile_id, model.model_id)
                        }
                      />
                      <span className="truncate">{model.name}</span>
                    </label>
                  ))}
                </div>
              ))}
            </div>
            <div>
              <div className="mb-1 text-xs text-[var(--muted-foreground)]">
                {t("Knowledge")}
              </div>
              {(resources.knowledge_bases || []).map((kb) => (
                <label
                  key={kb.resource_id}
                  className="flex cursor-pointer items-center gap-2 py-0.5 text-xs"
                >
                  <input
                    type="checkbox"
                    checked={kbDefaults.some(
                      (item) => item.resource_id === kb.resource_id,
                    )}
                    onChange={() => toggleKb(kb.resource_id, kb.name)}
                  />
                  <span className="truncate">{kb.name}</span>
                </label>
              ))}
            </div>
          </div>
        )}
        <button
          type="button"
          onClick={saveDefaults}
          disabled={busy !== "" || resources === null}
          className={`${primaryButtonClass} mt-2`}
        >
          {busy === "defaults" ? t("Saving...") : t("Save defaults")}
        </button>
      </section>
    </div>
  );
}

// ── create ─────────────────────────────────────────────────────────────────

function CreateDialog({
  teachers,
  onClose,
  onCreated,
}: {
  teachers: UserRecord[];
  onClose: () => void;
  onCreated: (room: Classroom) => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [term, setTerm] = useState("");
  const [homeRoom, setHomeRoom] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const room = await createClassroom({
        name: name.trim(),
        term: term.trim(),
        teacher_ids: homeRoom ? [homeRoom] : [],
        home_room_teacher_id: homeRoom,
      });
      onCreated(room);
    } catch (err) {
      setError(errorText(err, t("Failed to create classroom")));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] px-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        className="w-full max-w-sm rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-xl"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-[var(--foreground)]">
            {t("New classroom")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            aria-label={t("Close")}
          >
            <X size={16} />
          </button>
        </div>
        <label className="mb-3 block text-xs text-[var(--muted-foreground)]">
          {t("Name")}
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
            placeholder="ม.4/1"
            className={`mt-1 w-full ${inputClass}`}
          />
        </label>
        <label className="mb-3 block text-xs text-[var(--muted-foreground)]">
          {t("Term")}
          <input
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="2569/1"
            className={`mt-1 w-full ${inputClass}`}
          />
        </label>
        <label className="mb-4 block text-xs text-[var(--muted-foreground)]">
          {t("Home-room teacher")}
          <select
            value={homeRoom}
            onChange={(e) => setHomeRoom(e.target.value)}
            className={`mt-1 w-full ${inputClass}`}
          >
            <option value="">{t("None yet")}</option>
            {teachers.map((u) => (
              <option key={u.id} value={u.id}>
                {u.username}
              </option>
            ))}
          </select>
        </label>
        {error && (
          <p className="mb-3 text-xs text-red-600 dark:text-red-400">{error}</p>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className={buttonClass}>
            {t("Cancel")}
          </button>
          <button
            type="submit"
            disabled={busy || !name.trim()}
            className={primaryButtonClass}
          >
            {busy ? t("Creating...") : t("Create")}
          </button>
        </div>
      </form>
    </div>
  );
}

// ── import ─────────────────────────────────────────────────────────────────

function ImportDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const [csv, setCsv] = useState("");
  const [createRooms, setCreateRooms] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<ImportReport | null>(null);

  const readFile = (file: File | undefined) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setCsv(String(reader.result ?? ""));
    reader.readAsText(file, "utf-8");
  };

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      setReport(await importStudents(csv, createRooms));
    } catch (err) {
      setError(errorText(err, t("Import failed")));
    } finally {
      setBusy(false);
    }
  };

  const download = () => {
    if (!report?.credentials_csv) return;
    const blob = new Blob(["﻿", report.credentials_csv], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "student-credentials.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] px-4"
      role="dialog"
      aria-modal="true"
      onClick={busy ? undefined : onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-xl"
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold text-[var(--foreground)]">
            {t("Import students from CSV")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-md p-1 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            aria-label={t("Close")}
          >
            <X size={16} />
          </button>
        </div>
        {report === null ? (
          <>
            <p className="mb-3 text-xs text-[var(--muted-foreground)]">
              {t(
                "Columns: username, password, classroom. Leave the password empty to have one generated; the generated passwords are shown once, after the import.",
              )}
            </p>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => readFile(e.target.files?.[0])}
              className="mb-2 block text-xs text-[var(--muted-foreground)]"
            />
            <textarea
              value={csv}
              onChange={(e) => setCsv(e.target.value)}
              rows={8}
              spellCheck={false}
              placeholder={"username,password,classroom\nsomchai.k,,ม.4/1"}
              className={`w-full font-mono ${inputClass}`}
            />
            <label className="mt-2 flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
              <input
                type="checkbox"
                checked={createRooms}
                onChange={(e) => setCreateRooms(e.target.checked)}
              />
              {t("Create classrooms named in the file that do not exist yet")}
            </label>
            {error && (
              <p className="mt-3 text-xs text-red-600 dark:text-red-400">
                {error}
              </p>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                disabled={busy}
                className={buttonClass}
              >
                {t("Cancel")}
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={busy || !csv.trim()}
                className={primaryButtonClass}
              >
                {busy ? t("Importing...") : t("Import")}
              </button>
            </div>
          </>
        ) : (
          <div
            className="text-sm text-[var(--foreground)]"
            data-testid="import-report"
          >
            <p>
              {t(
                "{{created}} created, {{skipped}} skipped, {{errors}} errors",
                {
                  created: report.created.length,
                  skipped: report.skipped.length,
                  errors: report.errors.length,
                },
              )}
              {report.classrooms_created.length > 0 && (
                <>
                  {" · "}
                  {t("Classrooms created: {{names}}", {
                    names: report.classrooms_created.join(", "),
                  })}
                </>
              )}
            </p>
            {report.errors.length > 0 && (
              <ul className="mt-2 max-h-32 overflow-y-auto text-xs text-red-600 dark:text-red-400">
                {report.errors.map((item, index) => (
                  <li key={index}>
                    {item.line > 0
                      ? t("Line {{line}}: {{reason}}", {
                          line: item.line,
                          reason: t(item.reason),
                        })
                      : t(item.reason)}
                  </li>
                ))}
              </ul>
            )}
            {report.skipped.length > 0 && (
              <ul className="mt-2 max-h-32 overflow-y-auto text-xs text-[var(--muted-foreground)]">
                {report.skipped.map((item) => (
                  <li key={item.line}>
                    {t("Line {{line}}: {{username}} {{reason}}", {
                      line: item.line,
                      username: item.username,
                      reason: t(item.reason),
                    })}
                  </li>
                ))}
              </ul>
            )}
            {report.credentials_csv && (
              <div className="mt-4 rounded-lg border border-[var(--border)] bg-[var(--background)]/60 p-3">
                <p className="mb-2 text-xs text-[var(--muted-foreground)]">
                  {t(
                    "The generated passwords are in this file and nowhere else. Download it now; closing this dialog discards it.",
                  )}
                </p>
                <button
                  type="button"
                  onClick={download}
                  className={primaryButtonClass}
                >
                  <span className="flex items-center gap-1.5">
                    <Download size={14} />
                    {t("Download credentials CSV")}
                  </span>
                </button>
              </div>
            )}
            <div className="mt-4 flex justify-end">
              <button type="button" onClick={onClose} className={buttonClass}>
                {t("Done")}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
