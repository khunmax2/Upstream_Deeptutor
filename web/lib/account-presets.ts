/**
 * Fork: the account presets, in one place. Upstream had three
 * (`standard`, `learner`, `custom`); the school roles design adds `student`
 * and `teacher` (docs/planning/school-roles/DESIGN_teacher_student_it.md).
 * Both are labels on an ordinary user, never a role: a `teacher` behaves as
 * `custom` plus guardian links, a `student` is the full product with a few
 * groups closed by the server.
 */

export type AccountPreset =
  "standard" | "learner" | "custom" | "student" | "teacher";

export const ACCOUNT_PRESETS: readonly AccountPreset[] = [
  "standard",
  "learner",
  "custom",
  "student",
  "teacher",
];

/** The i18n key of a preset's display name. */
export function presetLabel(preset: string | null | undefined): string {
  switch (preset) {
    case "learner":
      return "Learner";
    case "custom":
      return "Custom";
    case "student":
      return "Student";
    case "teacher":
      return "Teacher";
    default:
      return "Standard";
  }
}

/**
 * Presets whose grants an administrator curates and the admin dashboard
 * tracks for readiness. `standard` accounts configure themselves.
 */
export function isCuratedPreset(preset: string | null | undefined): boolean {
  return (
    preset === "custom" ||
    preset === "learner" ||
    preset === "student" ||
    preset === "teacher"
  );
}
