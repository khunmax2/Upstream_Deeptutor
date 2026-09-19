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
      return "Student account";
    case "teacher":
      // Not the shared "Teacher" key: that is the locked-persona option in
      // the grant editor, and a school names the person, not the persona.
      return "Teacher account";
    default:
      return "Standard";
  }
}

/**
 * Presets an account can be guarded under: a parent's link to a `learner`
 * and a teacher's link to a `student` are the same guardian record
 * (`multi_user/guardians.py`, `GUARDABLE_PRESETS`).
 */
export function isGuardablePreset(preset: string | null | undefined): boolean {
  return preset === "learner" || preset === "student";
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
