import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { toAuthStatusState } from "../hooks/useAuthStatus";
import {
  filterHrefsForStudent,
  isStudentPreset,
  STUDENT_CLOSED_HREFS,
  STUDENT_CLOSED_SETTINGS,
} from "../lib/student-access";

// Fork (school roles design, Phase 1 step 2). The server closes three groups
// to a `student` account; the browser keeps them out of the menus so the
// restriction is an absence, not a 403 after a click.

const read = (file: string) =>
  readFileSync(path.resolve(process.cwd(), file), "utf8");
const locale = (lang: string) =>
  JSON.parse(read(`locales/${lang}/app.json`)) as Record<string, string>;

test("the closed set mirrors student_policy.CLOSED", () => {
  assert.deepEqual([...STUDENT_CLOSED_HREFS].sort(), [
    "/partners",
    "/space/cli-apps",
    "/space/mcp",
  ]);
  assert.deepEqual([...STUDENT_CLOSED_SETTINGS].sort(), [
    "agents",
    "models",
    "network",
  ]);
  // The server side names the same routes.
  const policy = read("../deeptutor/multi_user/student_policy.py");
  for (const route of [
    '"/api/partners"',
    '"/api/space/mcp"',
    '"/api/space/cli-apps"',
    '"/api/settings"',
    '"/api/agent-config"',
  ]) {
    assert.ok(policy.includes(route), `student_policy.py names ${route}`);
  }
});

test("only a student loses the closed entries; nothing else changes", () => {
  const entries = [
    { href: "/chat" },
    { href: "/partners" },
    { href: "/memory" },
    { href: "/space/mcp" },
    { href: "/space/cli-apps" },
    { href: "/space/questions" },
  ];
  assert.deepEqual(
    filterHrefsForStudent(entries, "student").map((e) => e.href),
    ["/chat", "/memory", "/space/questions"],
  );
  for (const preset of ["standard", "custom", "teacher", "learner", null]) {
    assert.deepEqual(filterHrefsForStudent(entries, preset), entries);
  }
  assert.equal(isStudentPreset("student"), true);
  assert.equal(isStudentPreset("teacher"), false);
});

test("the auth state carries the preset", () => {
  const state = toAuthStatusState({
    enabled: true,
    authenticated: true,
    user_id: "u_1",
    username: "s",
    role: "user",
    is_admin: false,
    preset: "student",
    learning_policy: null,
  } as never);
  assert.equal(state.preset, "student");
  assert.equal(state.allowedSurfaces, null);
});

test("the sidebar, the settings nav and Learning Space apply the filter", () => {
  assert.match(
    read("components/sidebar/SidebarNav.tsx"),
    /filterHrefsForStudent\(/,
  );
  assert.match(
    read("components/sidebar/SidebarShell.tsx"),
    /filterHrefsForStudent\(/,
  );
  assert.match(
    read("components/space/SpaceDashboard.tsx"),
    /filterHrefsForStudent\(group\.items, preset\)/,
  );
  assert.match(
    read("features/settings/navigation/settings-nav.ts"),
    /access\.hideStudentClosed && STUDENT_CLOSED_SETTINGS\.has\(category\.key\)/,
  );
  assert.match(
    read("features/settings/navigation/settings-access.ts"),
    /hideStudentClosed: isStudentPreset\(authStatus\.preset\)/,
  );
});

test("the one-time notice is mounted once, keyed by account, in en/th/zh", () => {
  const notice = read("components/StudentNotice.tsx");
  assert.match(notice, /student-notice-seen:\$\{userId\}/);
  assert.match(notice, /isStudentPreset\(preset\)/);
  assert.match(read("app/(workspace)/layout.tsx"), /<StudentNotice \/>/);
  const keys = [
    "Welcome to your tutor",
    "Your conversations with the tutor are private. Your teacher sees your learning progress, not what you say.",
    "Got it",
  ];
  for (const lang of ["en", "th", "zh"]) {
    const table = locale(lang);
    for (const key of keys)
      assert.ok(table[key], `${lang} is missing "${key}"`);
  }
});
