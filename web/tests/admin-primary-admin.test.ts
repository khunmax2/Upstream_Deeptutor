import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

// Fork. The primary admin owns the deployment and is its superadmin: no other
// admin may demote or delete it. The server refuses both; the users page says
// so instead of offering them (report 2026-09-15).

const read = (file: string) =>
  readFileSync(path.resolve(process.cwd(), file), "utf8");
const usersPage = read("app/(admin)/admin/users/page.tsx");
const adminApi = read("lib/admin-api.ts");
const locale = (lang: string) =>
  JSON.parse(read(`locales/${lang}/app.json`)) as Record<string, string>;

test("the user list carries which account is the primary admin", () => {
  assert.match(adminApi, /is_primary\?: boolean;/);
});

test("the users page never offers to demote or delete the primary admin", () => {
  assert.match(usersPage, /const isPrimary = Boolean\(user\.is_primary\);/);
  // Both the role button and the delete button stay disabled for it.
  assert.equal(usersPage.match(/disabled=\{isSelf \|\| isPrimary\}/g)?.length, 2);
  assert.match(usersPage, /t\("The primary admin's role cannot be changed"\)/);
  assert.match(usersPage, /t\("The primary admin cannot be deleted"\)/);
  assert.match(usersPage, /t\("Primary admin"\)/);
});

test("the primary admin copy is present in every supported locale", () => {
  const keys = [
    "Primary admin",
    "The primary admin's role cannot be changed",
    "The primary admin cannot be deleted",
  ];
  for (const lang of ["en", "th", "zh"]) {
    const messages = locale(lang);
    for (const key of keys) {
      assert.ok(messages[key], `${lang} is missing "${key}"`);
    }
  }
});
