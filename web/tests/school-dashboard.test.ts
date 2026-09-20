import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  ALERT_HINTS,
  ALERT_LABELS,
  ALERT_ORDER,
  canSeeStudents,
  formatPercent,
  relativeTime,
} from "../lib/school-dashboard";

// Fork (school roles design, Phase 3b): the teacher's pages. The tab is for
// teachers and admins; the pages read only the school routes; every alert
// the server can raise has a label and a hint in en / th / zh.

const read = (file: string) =>
  readFileSync(path.resolve(process.cwd(), file), "utf8");
const locale = (lang: string) =>
  JSON.parse(read(`locales/${lang}/app.json`)) as Record<string, string>;

test("the Students tab is for the teacher preset and admins only", () => {
  assert.equal(canSeeStudents({ role: "admin", preset: "standard" }), true);
  assert.equal(canSeeStudents({ role: "user", preset: "teacher" }), true);
  for (const preset of ["standard", "custom", "student", "learner", null]) {
    assert.equal(canSeeStudents({ role: "user", preset }), false);
  }
  const tabs = read("components/dashboard/DashboardTabs.tsx");
  assert.match(tabs, /href: "\/dashboard\/students"/);
  assert.match(tabs, /page\.href !== "\/dashboard\/students" \|\| teacher/);
});

test("the alerts the server raises all have a label and a hint", () => {
  const server = read("../deeptutor/multi_user/school_alerts.py");
  const match = server.match(/ALERTS: tuple\[str, \.\.\.\] = \(([^)]*)\)/);
  assert.ok(match, "school_alerts.py names ALERTS");
  const serverAlerts = [...match![1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
  assert.deepEqual([...ALERT_ORDER], serverAlerts);
  for (const lang of ["en", "th", "zh"]) {
    const table = locale(lang);
    for (const name of ALERT_ORDER) {
      assert.ok(table[ALERT_LABELS[name]], `${lang} label for ${name}`);
      assert.ok(table[ALERT_HINTS[name]], `${lang} hint for ${name}`);
    }
  }
});

test("the pages read only the school routes and never a first-person one", () => {
  for (const file of [
    "components/dashboard/StudentsOverview.tsx",
    "components/dashboard/StudentDetail.tsx",
  ]) {
    const source = read(file);
    assert.match(source, /from "@\/lib\/school-api"/);
    assert.doesNotMatch(
      source,
      /lib\/session-api|lib\/reading-api|lib\/notebook-api|features\/knowledge/,
    );
    assert.match(source, /router\.replace\("\/dashboard"\)/);
  }
  assert.match(
    read("components/dashboard/StudentsOverview.tsx"),
    /\/dashboard\/students\/\$\{encodeURIComponent\(row\.student\.id\)\}/,
  );
  assert.match(read("lib/school-api.ts"), /\/roster/);
});

test("formatting helpers", () => {
  assert.equal(formatPercent(null), "—");
  assert.equal(formatPercent(0.754), "75%");
  const now = Date.parse("2026-09-21T12:00:00Z");
  assert.equal(relativeTime(null, "en", now), "—");
  assert.equal(relativeTime("2026-09-20T12:00:00Z", "en", now), "yesterday");
  assert.equal(
    relativeTime("2026-09-21T11:30:00Z", "en", now),
    "30 minutes ago",
  );
});

test("every t() literal on the pages has an entry in en, th and zh", () => {
  const keys = new Set<string>();
  for (const file of [
    "components/dashboard/StudentsOverview.tsx",
    "components/dashboard/StudentDetail.tsx",
  ]) {
    for (const match of read(file).matchAll(/\bt\(\s*"((?:[^"\\]|\\.)*)"/g)) {
      keys.add(match[1]);
    }
  }
  assert.ok(keys.size > 40, `found ${keys.size} keys`);
  for (const lang of ["en", "th", "zh"]) {
    const table = locale(lang);
    for (const key of keys)
      assert.ok(table[key], `${lang} is missing "${key}"`);
  }
});
