/**
 * Fork: what the browser hides from a `student` account (school roles design,
 * Phase 1). The rule itself lives on the server
 * (`deeptutor/multi_user/student_policy.py`) and answers 403; this is the
 * mirror that keeps a closed entry out of the menus, so the restriction is an
 * absence rather than an error after a click — the same lesson as the
 * learner surfaces filter beside it.
 *
 * Closed for a student: partners, MCP connections, CLI apps (code execution),
 * and the Settings categories that write personal providers, keys, tools,
 * capabilities, network and agent configuration. Everything else — every
 * learning surface, Memory, Co-Writer, own knowledge bases — stays.
 */

export function isStudentPreset(preset: string | null | undefined): boolean {
  return preset === "student";
}

/** Sidebar and Learning Space destinations a student does not get. */
export const STUDENT_CLOSED_HREFS: ReadonlySet<string> = new Set([
  "/partners",
  "/space/mcp",
  "/space/cli-apps",
]);

/** Settings categories (by key) a student does not get. */
export const STUDENT_CLOSED_SETTINGS: ReadonlySet<string> = new Set([
  "models",
  "network",
  "agents",
]);

export function filterHrefsForStudent<T extends { href: string }>(
  entries: readonly T[],
  preset: string | null | undefined,
): T[] {
  if (!isStudentPreset(preset)) return [...entries];
  return entries.filter((entry) => !STUDENT_CLOSED_HREFS.has(entry.href));
}
