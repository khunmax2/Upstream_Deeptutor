import type { UserRecord } from "@/lib/admin-api";
import type { GuardianRelationship } from "@/lib/guardian-api";
import type {
  AdminBook,
  GrantPayload,
  MultiUserResources,
} from "@/features/multi-user/types";

export interface AdminDashboardSummary {
  totalAccounts: number;
  activeAccounts: number;
  disabledAccounts: number;
  admins: number;
  standard: number;
  custom: number;
  learners: number;
  guardianLinks: number;
  customWithoutAssignments: number;
  learnersWithoutMaterials: number;
  needsReview: number;
}

export interface AdminResourceCounts {
  models: number;
  knowledgeBases: number;
  books: number;
  skills: number;
  partners: number;
  tools: number;
  mcpTools: number;
  readingMaterials: number;
}

export interface AdminProvisioningSummary {
  managedAccounts: number;
  withModel: number;
  configuredCustom: number;
  learnersWithMaterials: number;
  learnersWithGuardian: number;
}

export interface AdminAssignmentCounts {
  models: number;
  knowledgeBases: number;
  skills: number;
  partners: number;
  tools: number;
  mcpTools: number;
  readingMaterials: number;
}

export interface AccountReadinessRow {
  user: UserRecord;
  checked: boolean;
  modelReady: boolean;
  contentReady: boolean;
  accessReady: boolean;
}

export function hasExplicitAssignment(grant: GrantPayload | undefined): boolean {
  if (!grant) return false;
  return Boolean(
    grant.models.llm.length ||
      grant.knowledge_bases.length ||
      grant.skills.length ||
      grant.partners.length ||
      (grant.enabled_tools?.length ?? 0) ||
      (grant.mcp_tools?.length ?? 0) ||
      grant.exec_enabled,
  );
}

export function assignedMaterialCount(grant: GrantPayload | undefined): number {
  return grant?.learning_policy?.reading.material_ids.filter(
    (materialId) => materialId !== "*",
  ).length ?? 0;
}

export function buildAdminProvisioningSummary(
  users: UserRecord[],
  relationships: GuardianRelationship[],
  grants: ReadonlyMap<string, GrantPayload>,
): AdminProvisioningSummary {
  const custom = users.filter(
    (user) => user.role === "user" && user.preset === "custom",
  );
  const learners = users.filter(
    (user) => user.role === "user" && user.preset === "learner",
  );
  const managed = [...custom, ...learners];
  const guardianLearnerIds = new Set(
    relationships
      .filter((relationship) => !relationship.revoked_at)
      .map((relationship) => relationship.learner_user_id),
  );
  return {
    managedAccounts: managed.length,
    withModel: managed.filter(
      (user) => (grants.get(user.id)?.models.llm.length ?? 0) > 0,
    ).length,
    configuredCustom: custom.filter((user) =>
      hasExplicitAssignment(grants.get(user.id)),
    ).length,
    learnersWithMaterials: learners.filter(
      (user) => assignedMaterialCount(grants.get(user.id)) > 0,
    ).length,
    learnersWithGuardian: learners.filter((user) =>
      guardianLearnerIds.has(user.id),
    ).length,
  };
}

export function countAdminAssignments(
  grants: ReadonlyMap<string, GrantPayload>,
): AdminAssignmentCounts {
  const totals: AdminAssignmentCounts = {
    models: 0,
    knowledgeBases: 0,
    skills: 0,
    partners: 0,
    tools: 0,
    mcpTools: 0,
    readingMaterials: 0,
  };
  for (const grant of grants.values()) {
    totals.models += grant.models.llm.length;
    totals.knowledgeBases += grant.knowledge_bases.length;
    totals.skills += grant.skills.length;
    totals.partners += grant.partners.length;
    totals.tools += grant.enabled_tools?.length ?? 0;
    totals.mcpTools += grant.mcp_tools?.length ?? 0;
    totals.readingMaterials += assignedMaterialCount(grant);
  }
  return totals;
}

export function buildAccountReadinessRows(
  users: UserRecord[],
  grants: ReadonlyMap<string, GrantPayload>,
): AccountReadinessRow[] {
  return users
    .filter((user) => user.role === "user")
    .map((user) => {
      const managed = user.preset === "custom" || user.preset === "learner";
      const checked = !managed || grants.has(user.id);
      const grant = grants.get(user.id);
      const modelReady = !managed || (grant?.models.llm.length ?? 0) > 0;
      const contentReady =
        user.preset === "learner"
          ? assignedMaterialCount(grant) > 0
          : user.preset === "custom"
            ? hasExplicitAssignment(grant)
            : true;
      return {
        user,
        checked,
        modelReady,
        contentReady,
        accessReady: checked && !user.disabled && modelReady && contentReady,
      };
    })
    .sort((left, right) => {
      if (left.accessReady !== right.accessReady) return left.accessReady ? 1 : -1;
      return (Date.parse(right.user.created_at) || 0) -
        (Date.parse(left.user.created_at) || 0);
    });
}

export function buildAdminDashboardSummary(
  users: UserRecord[],
  relationships: GuardianRelationship[],
  grants: ReadonlyMap<string, GrantPayload>,
): AdminDashboardSummary {
  const ordinaryUsers = users.filter((user) => user.role === "user");
  const customUsers = ordinaryUsers.filter((user) => user.preset === "custom");
  const learnerUsers = ordinaryUsers.filter(
    (user) => user.preset === "learner",
  );
  const disabledAccounts = users.filter((user) => user.disabled).length;
  const customWithoutAssignments = customUsers.filter(
    (user) => grants.has(user.id) && !hasExplicitAssignment(grants.get(user.id)),
  ).length;
  const learnersWithoutMaterials = learnerUsers.filter(
    (user) =>
      grants.has(user.id) && assignedMaterialCount(grants.get(user.id)) === 0,
  ).length;

  return {
    totalAccounts: users.length,
    activeAccounts: users.length - disabledAccounts,
    disabledAccounts,
    admins: users.filter((user) => user.role === "admin").length,
    standard: ordinaryUsers.filter(
      (user) => !user.preset || user.preset === "standard",
    ).length,
    custom: customUsers.length,
    learners: learnerUsers.length,
    guardianLinks: relationships.filter((relationship) => !relationship.revoked_at)
      .length,
    customWithoutAssignments,
    learnersWithoutMaterials,
    needsReview:
      disabledAccounts + customWithoutAssignments + learnersWithoutMaterials,
  };
}

export function countAdminResources(
  resources: MultiUserResources,
  books: AdminBook[],
): AdminResourceCounts {
  const profiles = resources.models.llm;
  const modelCount = profiles.reduce(
    (count, profile) => count + Math.max(profile.models?.length ?? 0, 1),
    0,
  );
  return {
    models: modelCount,
    knowledgeBases: resources.knowledge_bases.length,
    books: books.length,
    skills: resources.skills.length,
    partners: resources.partners.length,
    tools: resources.tools.length,
    mcpTools: resources.mcp_tools.length,
    readingMaterials: resources.reading_materials.length,
  };
}

export function newestAccounts(users: UserRecord[], limit = 5): UserRecord[] {
  return [...users]
    .sort((left, right) => {
      const leftTime = Date.parse(left.created_at) || 0;
      const rightTime = Date.parse(right.created_at) || 0;
      return rightTime - leftTime;
    })
    .slice(0, Math.max(0, limit));
}
