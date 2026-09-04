import test from "node:test";
import assert from "node:assert/strict";

import {
  buildAccountReadinessRows,
  buildAdminDashboardSummary,
  buildAdminProvisioningSummary,
  countAdminAssignments,
  countAdminResources,
  newestAccounts,
} from "../lib/admin-dashboard";
import type { UserRecord } from "../lib/admin-api";
import type { GuardianRelationship } from "../lib/guardian-api";
import type { GrantPayload, MultiUserResources } from "../features/multi-user/types";

const users: UserRecord[] = [
  { id: "a1", username: "admin", role: "admin", created_at: "2025-01-01T00:00:00Z" },
  { id: "s1", username: "standard", role: "user", preset: "standard", created_at: "2025-02-01T00:00:00Z" },
  { id: "c1", username: "custom", role: "user", preset: "custom", created_at: "2025-04-01T00:00:00Z" },
  { id: "l1", username: "learner", role: "user", preset: "learner", created_at: "2025-03-01T00:00:00Z", disabled: true },
];

function grant(userId: string): GrantPayload {
  return {
    version: 1,
    user_id: userId,
    models: { llm: [] },
    knowledge_bases: [],
    skills: [],
    partners: [],
    enabled_tools: [],
    mcp_tools: [],
    exec_enabled: false,
    learning_policy: null,
  };
}

test("admin summary keeps roles, presets, and review checks separate", () => {
  const learnerGrant = grant("l1");
  learnerGrant.learning_policy = {
    age_band: "9-12",
    locked_persona: "teacher",
    allowed_capabilities: ["chat", "immersive_reading"],
    default_capability: "immersive_reading",
    allowed_surfaces: ["chat", "reading"],
    reading: { allow_upload: false, material_ids: [], extensions: [] },
  };
  const relationships: GuardianRelationship[] = [
    { id: "g1", guardian_user_id: "s1", guardian_username: "standard", learner_user_id: "l1", learner_username: "learner", permissions: ["view_reports"] },
  ];
  const summary = buildAdminDashboardSummary(
    users,
    relationships,
    new Map([
      ["c1", grant("c1")],
      ["l1", learnerGrant],
    ]),
  );
  assert.deepEqual(summary, {
    totalAccounts: 4,
    activeAccounts: 3,
    disabledAccounts: 1,
    admins: 1,
    standard: 1,
    custom: 1,
    learners: 1,
    guardianLinks: 1,
    customWithoutAssignments: 1,
    learnersWithoutMaterials: 1,
    needsReview: 3,
  });
});

test("resource counts reflect the assignable admin catalogs", () => {
  const resources: MultiUserResources = {
    models: { llm: [{ profile_id: "p1", name: "Provider", models: [{ model_id: "m1", name: "One" }, { model_id: "m2", name: "Two" }] }] },
    knowledge_bases: [{ resource_id: "kb1", name: "KB", source: "admin" }],
    skills: [{ name: "skill" }],
    partners: [{ partner_id: "partner", name: "Partner" }],
    reading_materials: [{ material_id: "r1", title: "Reading", filename: "r.pdf", render_mode: "pdf" }],
    reading_extensions: [],
    tools: [{ name: "reason" }, { name: "search" }],
    mcp_tools: [{ name: "mcp-tool" }],
  };
  assert.deepEqual(countAdminResources(resources, [{ book_id: "b1", title: "Book", status: "ready", updated_at: 1 }]), {
    models: 2,
    knowledgeBases: 1,
    books: 1,
    skills: 1,
    partners: 1,
    tools: 2,
    mcpTools: 1,
    readingMaterials: 1,
  });
});

test("unavailable grant records are reported separately, not as missing setup", () => {
  const summary = buildAdminDashboardSummary(users, [], new Map());
  assert.equal(summary.customWithoutAssignments, 0);
  assert.equal(summary.learnersWithoutMaterials, 0);
  assert.equal(summary.needsReview, 1);
});

test("recent accounts are sorted newest first without mutating input", () => {
  const original = [...users];
  assert.deepEqual(newestAccounts(users, 2).map((user) => user.id), ["c1", "l1"]);
  assert.deepEqual(users, original);
});

test("provisioning metrics and assignment totals come from checked grants", () => {
  const customGrant = grant("c1");
  customGrant.models.llm.push({ profile_id: "p1", model_id: "m1" });
  customGrant.skills.push({ name: "guided" });
  const learnerGrant = grant("l1");
  learnerGrant.models.llm.push({ profile_id: "p1", model_id: "m1" });
  learnerGrant.learning_policy = {
    age_band: "9-12",
    locked_persona: "teacher",
    allowed_capabilities: ["chat", "immersive_reading"],
    default_capability: "immersive_reading",
    allowed_surfaces: ["chat", "reading"],
    reading: { allow_upload: false, material_ids: ["math-book"], extensions: [] },
  };
  const grants = new Map([
    ["c1", customGrant],
    ["l1", learnerGrant],
  ]);
  const relationships: GuardianRelationship[] = [
    { id: "g1", guardian_user_id: "s1", guardian_username: "standard", learner_user_id: "l1", learner_username: "learner", permissions: ["view_reports"] },
  ];
  assert.deepEqual(buildAdminProvisioningSummary(users, relationships, grants), {
    managedAccounts: 2,
    withModel: 2,
    configuredCustom: 1,
    learnersWithMaterials: 1,
    learnersWithGuardian: 1,
  });
  assert.deepEqual(countAdminAssignments(grants), {
    models: 2,
    knowledgeBases: 0,
    skills: 1,
    partners: 0,
    tools: 0,
    mcpTools: 0,
    readingMaterials: 1,
  });
  const readiness = buildAccountReadinessRows(users, grants);
  assert.equal(readiness.find((row) => row.user.id === "c1")?.accessReady, true);
  assert.equal(readiness.find((row) => row.user.id === "l1")?.accessReady, false);
});
