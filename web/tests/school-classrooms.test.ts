import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

// Fork (school roles design, Phase 3a): the classrooms page and its API
// client speak to the fork's school routes, and every string on the page
// has an entry in en / th / zh.

const read = (file: string) =>
  readFileSync(path.resolve(process.cwd(), file), "utf8");
const locale = (lang: string) =>
  JSON.parse(read(`locales/${lang}/app.json`)) as Record<string, string>;

const api = read("lib/school-api.ts");
const page = read("app/(admin)/admin/classrooms/AdminClassroomsClient.tsx");

test("the API client names the school routes the server mounts", () => {
  for (const route of [
    "/api/multi-user/school/classrooms",
    "/api/multi-user/school/import",
    "/api/multi-user/school/settings",
    "/api/multi-user/school/summaries/run",
    "/evidence",
    "/summary",
  ]) {
    assert.ok(api.includes(route), `school-api.ts names ${route}`);
  }
  const router = read("../deeptutor/api/routers/school.py");
  for (const route of [
    '"/school/classrooms"',
    '"/school/classrooms/{classroom_id}/teachers"',
    '"/school/classrooms/{classroom_id}/students"',
    '"/school/import"',
    '"/learners/{learner_user_id}/evidence"',
  ]) {
    assert.ok(router.includes(route), `school.py mounts ${route}`);
  }
});

test("the page is admin-only, edits members and defaults, and imports", () => {
  assert.match(page, /status\.role !== "admin"/);
  for (const call of [
    "listClassrooms(",
    "createClassroom(",
    "updateClassroom(",
    "archiveClassroom(",
    "setClassroomTeachers(",
    "setClassroomStudents(",
    "importStudents(",
  ]) {
    assert.ok(page.includes(call), `page calls ${call}`);
  }
  // Phase 3c: IT's switch for the nightly summary lives on the same page.
  for (const call of [
    "getSchoolSettings(",
    "saveSchoolSettings(",
    "runSummariesNow(",
  ]) {
    assert.ok(page.includes(call), `page calls ${call}`);
  }
  assert.match(page, /data-testid="nightly-summary"/);
  // The generated passwords are offered as a download, never rendered as text.
  assert.match(page, /student-credentials\.csv/);
  assert.doesNotMatch(page, /credentials_csv\}\s*</);
  // The users page links here.
  assert.match(
    read("app/(admin)/admin/users/AdminUsersClient.tsx"),
    /href="\/admin\/classrooms"/,
  );
});

test("every t() literal on the page has an entry in en, th and zh", () => {
  const keys = new Set<string>();
  for (const match of page.matchAll(/\bt\(\s*"((?:[^"\\]|\\.)*)"/g)) {
    keys.add(match[1]);
  }
  assert.ok(keys.size > 30, `found ${keys.size} keys`);
  for (const lang of ["en", "th", "zh"]) {
    const table = locale(lang);
    for (const key of keys) {
      assert.ok(table[key], `${lang} is missing "${key}"`);
    }
  }
});
