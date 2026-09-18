import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

// Fork. The primary admin owns the deployment and is its superadmin: no other
// admin may demote or delete it. The server refuses both; the users page says
// so instead of offering them (report 2026-09-15).

const read = (file: string) =>
  readFileSync(path.resolve(process.cwd(), file), "utf8");
const usersPage = read("app/(admin)/admin/users/AdminUsersClient.tsx");
const adminApi = read("lib/admin-api.ts");
const locale = (lang: string) =>
  JSON.parse(read(`locales/${lang}/app.json`)) as Record<string, string>;
// `t("…")` as prettier may print it: split over lines, with a trailing comma.
const uses = (text: string) =>
  new RegExp(
    String.raw`t\(\s*"` +
      text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") +
      String.raw`",?\s*\)`,
  );

test("the user list carries which account is the primary admin", () => {
  assert.match(adminApi, /is_primary\?: boolean;/);
});

test("the users page never offers to demote or delete the primary admin", () => {
  assert.match(usersPage, /const isPrimary = Boolean\(user\.is_primary\);/);
  // The delete button stays disabled for it; the role button adds the
  // viewer check (see the next test).
  assert.equal(
    usersPage.match(/disabled=\{isSelf \|\| isPrimary\}/g)?.length,
    1,
  );
  assert.match(usersPage, uses("The primary admin's role cannot be changed"));
  assert.match(usersPage, uses("The primary admin cannot be deleted"));
  assert.match(usersPage, uses("Primary admin"));
});

test("only the primary admin is offered role changes and deletion", () => {
  // Phase 1 step 2 (docs/planning/admin-roles/, §2): the server answers 403
  // to any other admin, so the page disables the role button and hides delete.
  assert.match(usersPage, /const viewerIsPrimary = users\.some\(/);
  assert.match(
    usersPage,
    /disabled=\{isSelf \|\| isPrimary \|\| !viewerIsPrimary\}/,
  );
  assert.match(usersPage, uses("Only the primary admin manages admins"));
  assert.match(usersPage, /\{viewerIsPrimary && \(\s*<button/);
});

test("an account is disabled instead of deleted", () => {
  // Phase 1 step 3 (docs/planning/admin-roles/, §3 and §6): every admin gets
  // a disable/enable toggle; for an admin row it needs the primary admin.
  assert.match(adminApi, /export async function setUserDisabled\(/);
  assert.match(adminApi, /\/disabled`\)/);
  assert.match(usersPage, /kind: user\.disabled \? "enable" : "disable"/);
  assert.match(usersPage, /disabled=\{isAdmin && !viewerIsPrimary\}/);
  assert.match(usersPage, uses("Disable account"));
  assert.match(usersPage, uses("Enable account"));
  assert.match(usersPage, uses("Disabled"));
  assert.match(usersPage, /case "disable":/);
  assert.match(usersPage, /case "enable":/);
});

test("the primary admin copy is present in every supported locale", () => {
  const keys = [
    "Primary admin",
    "The primary admin's role cannot be changed",
    "The primary admin cannot be deleted",
    "Only the primary admin manages admins",
    "Disable account",
    "Enable account",
    "Disabling…",
    "Enabling…",
    "Disabled",
    "The account can no longer sign in. Everything it owns stays, and it can be enabled again.",
    "The account can sign in again.",
    "Failed to update account",
  ];
  for (const lang of ["en", "th", "zh"]) {
    const messages = locale(lang);
    for (const key of keys) {
      assert.ok(messages[key], `${lang} is missing "${key}"`);
    }
  }
});
