/**
 * Fork: the school routes (school roles design, Phases 2–3), under
 * `/api/multi-user`. Classrooms are a bulk editor of guardian links: an
 * admin edits membership here, the server derives the links, and a teacher
 * reads a student's evidence through them. Every call goes through the
 * shared client, so a session that lapses is handled the way it is
 * everywhere else.
 */

import { apiFetch, apiUrl } from "@/lib/api";

async function readError(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    return String(data?.detail || fallback);
  } catch {
    return fallback;
  }
}

async function json<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) throw new Error(await readError(res, fallback));
  return (await res.json()) as T;
}

const jsonInit = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

// ── classrooms ─────────────────────────────────────────────────────────────

export interface ClassroomMember {
  id: string;
  username: string;
}

export interface ClassroomDefaults {
  grant?: {
    models?: { llm?: Array<{ profile_id: string; model_ids?: string[] }> };
    knowledge_bases?: Array<{
      resource_id: string;
      name?: string;
      access?: string;
      source?: string;
    }>;
    skills?: Array<{ skill_id: string; access?: string; source?: string }>;
  };
}

export interface Classroom {
  id: string;
  name: string;
  term: string;
  home_room_teacher_id: string;
  teacher_ids: string[];
  student_ids: string[];
  teachers: ClassroomMember[];
  students: ClassroomMember[];
  defaults: ClassroomDefaults;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface MemberChanges {
  added: number;
  removed: number;
  links_created: number;
  links_revoked: number;
}

export async function listClassrooms(
  includeArchived = false,
): Promise<Classroom[]> {
  const res = await apiFetch(
    apiUrl(
      `/api/multi-user/school/classrooms${includeArchived ? "?include_archived=true" : ""}`,
    ),
  );
  const data = await json<{ classrooms: Classroom[] }>(
    res,
    "Failed to load classrooms",
  );
  return data.classrooms;
}

export async function createClassroom(payload: {
  name: string;
  term?: string;
  home_room_teacher_id?: string;
  teacher_ids?: string[];
  student_ids?: string[];
  defaults?: ClassroomDefaults | null;
}): Promise<Classroom> {
  const res = await apiFetch(
    apiUrl("/api/multi-user/school/classrooms"),
    jsonInit("POST", payload),
  );
  const data = await json<{ classroom: Classroom }>(
    res,
    "Failed to create classroom",
  );
  return data.classroom;
}

export async function updateClassroom(
  id: string,
  payload: {
    name?: string;
    term?: string;
    home_room_teacher_id?: string;
    defaults?: ClassroomDefaults | null;
  },
): Promise<Classroom> {
  const res = await apiFetch(
    apiUrl(`/api/multi-user/school/classrooms/${encodeURIComponent(id)}`),
    jsonInit("PUT", payload),
  );
  const data = await json<{ classroom: Classroom }>(
    res,
    "Failed to update classroom",
  );
  return data.classroom;
}

export async function archiveClassroom(id: string): Promise<Classroom> {
  const res = await apiFetch(
    apiUrl(`/api/multi-user/school/classrooms/${encodeURIComponent(id)}`),
    { method: "DELETE" },
  );
  const data = await json<{ classroom: Classroom }>(
    res,
    "Failed to archive classroom",
  );
  return data.classroom;
}

export async function setClassroomTeachers(
  id: string,
  ids: string[],
): Promise<{ classroom: Classroom; changes: MemberChanges }> {
  const res = await apiFetch(
    apiUrl(
      `/api/multi-user/school/classrooms/${encodeURIComponent(id)}/teachers`,
    ),
    jsonInit("PUT", { ids }),
  );
  return json(res, "Failed to update teachers");
}

export async function setClassroomStudents(
  id: string,
  ids: string[],
): Promise<{ classroom: Classroom; changes: MemberChanges }> {
  const res = await apiFetch(
    apiUrl(
      `/api/multi-user/school/classrooms/${encodeURIComponent(id)}/students`,
    ),
    jsonInit("PUT", { ids }),
  );
  return json(res, "Failed to update students");
}

// ── CSV import ─────────────────────────────────────────────────────────────

export interface ImportReport {
  created: Array<{ username: string; classroom: string }>;
  skipped: Array<{ line: number; username: string; reason: string }>;
  errors: Array<{ line: number; reason: string }>;
  classrooms_created: string[];
  /** The generated passwords, in this response and nowhere else. */
  credentials_csv: string;
}

export async function importStudents(
  csv: string,
  createClassrooms: boolean,
): Promise<ImportReport> {
  const res = await apiFetch(
    apiUrl("/api/multi-user/school/import"),
    jsonInit("POST", { csv, create_classrooms: createClassrooms }),
  );
  return json(res, "Import failed");
}

// ── the nightly summary switch ─────────────────────────────────────────────

export interface SchoolSettings {
  summaries_enabled: boolean;
  summaries_hour: number;
  last_run: {
    started_at?: string;
    finished_at?: string;
    students?: number;
    written?: string[];
    unchanged?: number;
    no_input?: number;
    failed?: string[];
  } | null;
}

export async function getSchoolSettings(): Promise<SchoolSettings> {
  const res = await apiFetch(apiUrl("/api/multi-user/school/settings"));
  return json(res, "Failed to load school settings");
}

export async function saveSchoolSettings(payload: {
  summaries_enabled?: boolean;
  summaries_hour?: number;
}): Promise<SchoolSettings> {
  const res = await apiFetch(
    apiUrl("/api/multi-user/school/settings"),
    jsonInit("PUT", payload),
  );
  return json(res, "Failed to save school settings");
}

export async function runSummariesNow(): Promise<
  NonNullable<SchoolSettings["last_run"]>
> {
  const res = await apiFetch(apiUrl("/api/multi-user/school/summaries/run"), {
    method: "POST",
  });
  return json(res, "The run failed");
}

// ── evidence (Phase 2 routes, read by the teacher's page) ──────────────────

export interface EvidenceSummarySection {
  title: string;
  items: string[];
}

export interface LearningEvidence {
  student: { id: string; username: string; preset: string };
  generated_at: string;
  mastery: {
    available: boolean;
    paths: Array<{
      id: string;
      name: string;
      stage: string;
      counts: {
        mastered: number;
        learning: number;
        new: number;
        total: number;
      };
      due_reviews: number;
      complete: boolean;
      quiz_attempts: number;
      quiz_correct: number;
      errors_active: number;
      modules: Array<{
        name: string;
        objective: string;
        mastered: number;
        total: number;
        knowledge_points: Array<{
          name: string;
          type: string;
          status: string;
          mastery: number;
        }>;
      }>;
      updated_at: string | null;
    }>;
  };
  question_bank: {
    available: boolean;
    total: number;
    correct?: number;
    wrong?: number;
    unresolved?: number;
    last_answered_at?: string | null;
    recent?: { days: number; total: number; correct: number };
    by_source?: Record<string, { total: number; correct: number }>;
    materials?: Array<{
      material_id: string;
      title: string;
      total: number;
      correct: number;
    }>;
    categories?: Array<{ name: string; total: number; wrong: number }>;
  };
  reading: {
    available: boolean;
    materials: Array<{
      material_id: string;
      title: string;
      unit_count: number;
      progress: number;
      finished: boolean;
      last_read_at: string | null;
      annotations: number;
      bookmarks: number;
      added_at: string | null;
    }>;
  };
  activity: {
    available: boolean;
    sessions_total: number;
    first_active_at?: string | null;
    last_active_at?: string | null;
    active_days_7?: number;
    active_days_30?: number;
    turns_30?: number;
    by_capability_30?: Record<string, number>;
  };
  profile: {
    account: Record<string, string> | null;
    goals: Array<Record<string, string>>;
  };
  summary: {
    available: boolean;
    generated_at: string | null;
    language?: string | null;
    sections: EvidenceSummarySection[];
  };
}

export async function getLearningEvidence(
  studentId: string,
): Promise<LearningEvidence> {
  const res = await apiFetch(
    apiUrl(
      `/api/multi-user/learners/${encodeURIComponent(studentId)}/evidence`,
    ),
  );
  return json(res, "Failed to load learning evidence");
}

export async function refreshTeacherSummary(
  studentId: string,
): Promise<{ status: string; summary: LearningEvidence["summary"] }> {
  const res = await apiFetch(
    apiUrl(`/api/multi-user/learners/${encodeURIComponent(studentId)}/summary`),
    { method: "POST" },
  );
  return json(res, "Failed to refresh the summary");
}

// ── the roster (Phase 3b) ──────────────────────────────────────────────────

export interface RosterRow {
  student: { id: string; username: string; preset: string };
  last_active_at: string | null;
  active_days_30: number;
  turns_30: number;
  questions_30: number;
  correct_30: number;
  accuracy_30: number | null;
  unresolved: number;
  mastered: number;
  objectives: number;
  paths: number;
  reviews_due: number;
  reading_started: number;
  reading_finished: number;
  summary_at: string | null;
  alerts: string[];
}

export interface ClassTotals {
  students: number;
  active_7: number;
  active_30: number;
  median_accuracy_30: number | null;
  below_half: number;
  reviews_due: number;
  reading_finished: number;
  alerts: Record<string, number>;
  top_wrong_categories: Array<{ name: string; wrong: number }>;
}

export interface Roster {
  classroom: Classroom;
  rows: RosterRow[];
  totals: ClassTotals;
}

export async function getClassroomRoster(id: string): Promise<Roster> {
  const res = await apiFetch(
    apiUrl(
      `/api/multi-user/school/classrooms/${encodeURIComponent(id)}/roster`,
    ),
  );
  return json(res, "Failed to load the roster");
}
