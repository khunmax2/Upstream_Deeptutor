import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { BIN_RETENTION_DAYS, binDaysLeft } from "../lib/account-bin";

// Fork (admin design §4, Phase 2). Delete moves an account to the bin, where
// the primary admin restores it or purges it with its data on both sides;
// the purge is the typed step, the delete is not.

const read = (file: string) =>
  readFileSync(path.resolve(process.cwd(), file), "utf8");
const usersPage = read("app/(admin)/admin/users/AdminUsersClient.tsx");
const wrapper = read("app/(admin)/admin/users/page.tsx");
const adminApi = read("lib/admin-api.ts");
const studioApi = read("lib/studio-admin-api.ts");
const dialog = read("components/ui/ConfirmDialog.tsx");
const locale = (lang: string) =>
  JSON.parse(read(`locales/${lang}/app.json`)) as Record<string, string>;
const uses = (text: string) =>
  new RegExp(
    String.raw`t\(\s*"` +
      text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") +
      String.raw`",?\s*[,)]`,
  );

test("the page learns where the studio is from the server, not the bundle", () => {
  assert.match(wrapper, /export const dynamic = "force-dynamic";/);
  assert.match(wrapper, /resolveOpenMaicEmbed\(\)/);
  assert.match(wrapper, /studioBase=\{sameOrigin \? url : ""\}/);
  assert.match(usersPage, /studioBase: string;/);
});

test("the client carries the bin, restore, footprint, purge and orphan calls", () => {
  assert.match(adminApi, /deleted_at\?: string \| null;/);
  assert.match(adminApi, /export async function restoreUser/);
  assert.match(adminApi, /\/restore`\)/);
  assert.match(adminApi, /export async function getUserFootprint/);
  assert.match(adminApi, /export async function purgeUser/);
  assert.match(
    adminApi,
    /\/purge\?confirm=\$\{encodeURIComponent\(confirm\)\}/,
  );
  assert.match(adminApi, /export async function listOrphans/);
  assert.match(adminApi, /export async function purgeOrphan/);
  // The studio's half goes through the same-origin gatekeeper path with the
  // admin's own cookie: no secret, no server-to-server route.
  assert.match(studioApi, /\/api\/studio\/admin\/accounts/);
  assert.match(studioApi, /credentials: "include"/);
  assert.match(studioApi, /skipAuthRedirect: true/);
  assert.doesNotMatch(studioApi, /\bfetch\(/);
  assert.match(studioApi, /return `user:\$\{userId\}`;/);
  assert.match(studioApi, /if \(!studioBase\) return null;/);
});

test("delete is reversible and says so; the purge is typed", () => {
  assert.match(
    usersPage,
    /BIN_RETENTION_DAYS, binDaysLeft \} from "@\/lib\/account-bin"/,
  );
  assert.match(
    usersPage,
    uses(
      "The account goes to the bin: it can no longer sign in, everything it owns stays, and it can be restored for {{days}} days. Purging it from the bin is what removes its data.",
    ),
  );
  assert.match(
    usersPage,
    /const deletedAt = await deleteUser\(user\.username\);/,
  );
  assert.doesNotMatch(usersPage, /This permanently removes the account/);
  // The confirm button stays off until the typed name matches, and both
  // sides are measured before the admin can type.
  assert.match(dialog, /confirmDisabled\?: boolean;/);
  assert.match(usersPage, /purgeTyped !== \(purgeTarget\?\.name \?\? ""\)/);
  assert.match(
    usersPage,
    /if \(!purgeTarget \|\| purgeBusy \|\| purgeTyped !== purgeTarget\.name\) return;/,
  );
  assert.match(usersPage, uses("Type {{name}} to confirm"));
});

test("the studio is purged first, then DeepWitya", () => {
  const studioCall = usersPage.indexOf(
    "await purgeStudioAccount(studioBase, purgeTarget.userId);",
  );
  const ownCall = usersPage.indexOf(
    "await purgeUser(purgeTarget.name, purgeTyped);",
  );
  const orphanCall = usersPage.indexOf(
    "await purgeOrphan(purgeTarget.userId, purgeTyped);",
  );
  assert.ok(studioCall > 0 && ownCall > studioCall && orphanCall > studioCall);
});

test("the bin tab and the leftovers panel exist for the primary admin only", () => {
  assert.match(usersPage, /tab === "bin" && viewerIsPrimary \?/);
  assert.match(
    usersPage,
    /const binUsers = users\.filter\(\(u\) => Boolean\(u\.deleted_at\)\);/,
  );
  assert.match(
    usersPage,
    /const filteredUsers = filterUsersByQuery\(liveUsers, query\);/,
  );
  assert.match(usersPage, uses("Restore account"));
  assert.match(usersPage, uses("Leftovers"));
  assert.match(usersPage, /listOrphans\(\)/);
  assert.match(usersPage, /listStudioOwners\(studioBase\)/);
  assert.match(usersPage, uses("Published courses"));
  assert.match(usersPage, uses("{{count}} kept for learners"));
});

test("every new string is in en, th and zh", () => {
  const keys = [
    "Accounts",
    "Bin ({{count}})",
    "The bin is empty",
    "Restore account",
    "Restore",
    "Restoring…",
    "Purge account data",
    "Purge",
    "Purging…",
    "Type {{name}} to confirm",
    "Leftovers",
    "No leftovers",
    "Retention over",
    "{{count}} kept for learners",
    "The account goes to the bin: it can no longer sign in, everything it owns stays, and it can be restored for {{days}} days. Purging it from the bin is what removes its data.",
  ];
  for (const lang of ["en", "th", "zh"]) {
    const table = locale(lang);
    for (const key of keys) {
      assert.ok(table[key], `${lang} is missing "${key}"`);
    }
  }
});

test("the days left in the bin count down from the deletion stamp", () => {
  const day = 86_400_000;
  const stamp = "2026-09-19T00:00:00+00:00";
  const t0 = Date.parse(stamp);
  assert.equal(BIN_RETENTION_DAYS, 30);
  assert.equal(binDaysLeft(stamp, t0), 30);
  assert.equal(binDaysLeft(stamp, t0 + 29 * day + 1), 1);
  assert.equal(binDaysLeft(stamp, t0 + 30 * day), 0);
  assert.equal(binDaysLeft(stamp, t0 + 45 * day), 0);
  assert.equal(binDaysLeft("", t0), 30);
});
