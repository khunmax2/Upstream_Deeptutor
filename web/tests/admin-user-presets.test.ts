import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const adminApi = readFileSync(
  path.resolve(process.cwd(), "lib/admin-api.ts"),
  "utf8",
);
const usersPage = readFileSync(
  path.resolve(process.cwd(), "app/(admin)/admin/users/AdminUsersClient.tsx"),
  "utf8",
);
const grantEditor = readFileSync(
  path.resolve(process.cwd(), "features/multi-user/components/GrantEditor.tsx"),
  "utf8",
);
const en = JSON.parse(
  readFileSync(path.resolve(process.cwd(), "locales/en/app.json"), "utf8"),
) as Record<string, string>;
const zh = JSON.parse(
  readFileSync(path.resolve(process.cwd(), "locales/zh/app.json"), "utf8"),
) as Record<string, string>;

test("admin user creation sends the selected preset", () => {
  assert.match(adminApi, /export type \{ AccountPreset \}/);
  assert.match(
    adminApi,
    /body: JSON\.stringify\(\{ username, password, preset \}\)/,
  );
  // Fork: the list comes from lib/account-presets.ts, which adds student and teacher.
  assert.match(usersPage, /ACCOUNT_PRESETS\.map\(\(preset\) =>/);
  const presets = readFileSync(
    path.resolve(process.cwd(), "lib/account-presets.ts"),
    "utf8",
  );
  assert.match(
    presets,
    /"standard",\s*"learner",\s*"custom",\s*"student",\s*"teacher",/,
  );
  assert.match(usersPage, /aria-pressed=\{createPreset === preset\}/);
});

test("grant editing exposes the server-enforced learning policy controls", () => {
  assert.match(grantEditor, /learning_policy: conservativeLearningPolicy\(\)/);
  assert.match(grantEditor, /allowed_surfaces: \["chat", "reading"\]/);
  assert.match(grantEditor, /toggleReadingMaterial/);
  assert.match(grantEditor, /toggleReadingExtension/);
  assert.match(
    grantEditor,
    /checked=\{grant\.learning_policy\.reading\.allow_upload\}/,
  );
});

test("account preset copy is present in both supported locales", () => {
  const keys = [
    "Account preset",
    "Learner",
    "Preset: {{preset}}",
    "Learning policy",
    "Enable learning policy",
    "Age band",
    "Assigned reading materials",
    "Allow learner uploads",
    "Reading extensions",
  ];
  for (const key of keys) {
    assert.ok(key in en, `missing English key: ${key}`);
    assert.ok(key in zh, `missing Chinese key: ${key}`);
    assert.notEqual(en[key], "");
    assert.notEqual(zh[key], "");
  }
});

// Fork (school roles design, Phase 2): a teacher's link to a `student` is the
// same guardian record as a parent's link to a `learner`, so the users page
// offers the guardian editor for both and neither can be a guardian.
test("a student account is guardable like a learner", () => {
  const presets = readFileSync(
    path.resolve(process.cwd(), "lib/account-presets.ts"),
    "utf8",
  );
  const guardianEditor = readFileSync(
    path.resolve(
      process.cwd(),
      "features/multi-user/components/GuardianRelationshipsEditor.tsx",
    ),
    "utf8",
  );
  assert.match(
    presets,
    /export function isGuardablePreset[\s\S]*preset === "learner" \|\| preset === "student"/,
  );
  assert.match(
    usersPage,
    /\{isGuardablePreset\(user\.preset\) && \(\s*<GuardianRelationshipsEditor/,
  );
  assert.match(
    usersPage,
    /\{user\.preset === "learner" && \(\s*<LearnerProfileEditor/,
  );
  assert.match(guardianEditor, /!isGuardablePreset\(user\.preset\) &&/);
  const guardians = readFileSync(
    path.resolve(process.cwd(), "../deeptutor/multi_user/guardians.py"),
    "utf8",
  );
  assert.match(
    guardians,
    /GUARDABLE_PRESETS = frozenset\(\{"learner", "student"\}\)/,
  );
});
