import test from "node:test";
import assert from "node:assert/strict";

import {
  buildDashboardActivitySeries,
  capabilityLaunchHref,
  formatCapabilityLabel,
  normalizeUserPreset,
  sessionCapabilityId,
  visibleDashboardSessions,
} from "../lib/user-dashboard";
import type { SessionSummary } from "../lib/session-api";

function session(
  id: string,
  updatedAt: number,
  preferences: SessionSummary["preferences"] = {},
): SessionSummary {
  return {
    id,
    session_id: id,
    title: id,
    created_at: updatedAt,
    updated_at: updatedAt,
    message_count: 1,
    last_message: "",
    preferences,
  };
}

test("dashboard sessions exclude hidden threads and sort by recent activity", () => {
  const sessions = [
    session("old", 1),
    session("archived", 4, { archived: true }),
    session("child", 5, { parent_session_id: "old" }),
    session("selection", 6, { session_kind: "selection_tutor" }),
    session("recent", 3),
  ];
  assert.deepEqual(
    visibleDashboardSessions(sessions).map((item) => item.id),
    ["recent", "old"],
  );
  assert.deepEqual(sessions.map((item) => item.id), [
    "old",
    "archived",
    "child",
    "selection",
    "recent",
  ]);
});

test("workspace mode takes precedence over the last turn capability", () => {
  assert.equal(
    sessionCapabilityId(
      session("reading", 1, {
        workspace_mode: "immersive_reading",
        capability: "chat",
      }),
    ),
    "immersive_reading",
  );
  assert.equal(
    sessionCapabilityId(
      session("mastery", 1, {
        workspace_mode: "mastery_path",
        capability: "deep_solve",
      }),
    ),
    "mastery_path",
  );
});

test("preset and capability helpers provide stable safe fallbacks", () => {
  assert.equal(normalizeUserPreset("custom"), "custom");
  assert.equal(normalizeUserPreset("unknown"), "standard");
  assert.equal(capabilityLaunchHref("chat"), "/chat");
  assert.equal(capabilityLaunchHref("deep_solve"), "/chat?capability=deep_solve");
  assert.equal(formatCapabilityLabel("deep_research"), "Deep Research");
});

test("activity series groups visible session updates into a bounded week", () => {
  const now = new Date(2026, 8, 4, 12).getTime();
  const yesterday = new Date(2026, 8, 3, 9).getTime();
  const sessions = [
    session("today", now, {}),
    { ...session("yesterday", yesterday, {}), message_count: 4 },
    session("hidden", now, { archived: true }),
  ];
  const series = buildDashboardActivitySeries(sessions, 3, now);
  assert.equal(series.length, 3);
  assert.deepEqual(
    series.map((day) => [day.sessions, day.messages]),
    [
      [0, 0],
      [1, 4],
      [1, 1],
    ],
  );
});
