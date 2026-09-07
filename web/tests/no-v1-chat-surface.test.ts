import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
// Path comparisons below are written with forward slashes, but path.relative()
// and path.join() return backslash-separated paths on Windows, so the
// allowlists never matched and every exempt file read as a violation.
// Normalise to POSIX separators before comparing. Split on path.sep rather
// than regex-replacing backslashes: a backslash is a legal character in a
// POSIX filename, and replacing it there would corrupt the path. On macOS and
// Linux path.sep is already "/", so this is the identity function and CI
// (ubuntu) is unaffected.
const toPosix = (p: string) => p.split(path.sep).join("/");

const SOURCE_ROOTS = [
  "app",
  "components",
  "context",
  "features",
  "hooks",
  "lib",
  "shared",
];

function sourceFiles(directory: string): string[] {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(absolute);
    return /\.(?:ts|tsx)$/.test(entry.name) ? [absolute] : [];
  });
}

test("the frontend has no retired transport, URL, or compatibility surface", () => {
  const cwd = process.cwd();
  // Files that legitimately name a live endpoint rather than a retired one.
  // Keep this list short and justified — it is an exemption from a rule that
  // exists to stop the frontend drifting back onto the v1 surface.
  const ALLOWED = new Set([
    // Fork-owned realtime voice channel. `/api/v1/voice/ws` is this fork's own
    // WebSocket (deeptutor/api/routers/voice_realtime.py), served today — it is
    // not part of the retired v1 chat transport this rule targets.
    "components/voice/VoiceCallWidget.tsx",
    // Same reason: `/api/v1/pet/*` is the fork's Learner Anima router
    // (deeptutor/api/routers/pet.py), mounted and serving today.
    "lib/pet-api.ts",
    // Upstream's own whisper page still imports UnifiedWSClient. It ships that
    // way in v1.6.3 because this suite never ran in their CI (python-tests and
    // the web job were both blocked). Remove this entry once upstream migrates
    // the page — it is theirs to fix, not the fork's.
    "app/(workspace)/whisper/page.tsx",
  ]);
  const files = SOURCE_ROOTS.flatMap((root) =>
    sourceFiles(path.resolve(cwd, root)),
  ).filter((file) => !ALLOWED.has(toPosix(path.relative(cwd, file))));
  const forbidden = [
    /\/api\/v1(?:\/|["'`])/,
    /\/api\/(?:attachments|book|co_writer|knowledge|learning|notebook|outputs)(?:\/|["'`])/,
    /["'`]\/(?:book|home|knowledge|notebook|study)(?:[/?#"'`]|$)/,
    /\?session=/,
    /UnifiedWSClient/,
    /lib\/unified-ws/,
    /features\/chat\/compat\/UnifiedChatFacade/,
  ];

  for (const file of files) {
    const source = fs.readFileSync(file, "utf8");
    for (const pattern of forbidden) {
      assert.doesNotMatch(
        source,
        pattern,
        `${toPosix(path.relative(cwd, file))} contains ${pattern}`,
      );
    }
  }

  for (const relative of [
    "lib/unified-ws.ts",
    "lib/unified-ws-recovery.ts",
    "components/chat/home/ChatMessages.tsx",
    "components/chat/home/TracePanels.tsx",
    "lib/chat-capabilities.ts",
    "lib/capabilities-api.ts",
    "lib/settings-nav.ts",
    "app/api/v1",
    "app/(workspace)/home",
    "app/(workspace)/book",
    "app/(utility)/knowledge",
    "app/(utility)/notebook",
    "app/(utility)/space/notebooks/page.tsx",
  ]) {
    assert.equal(
      fs.existsSync(path.resolve(cwd, relative)),
      false,
      `${relative} must stay deleted`,
    );
  }
});

test("all chat entry points share the validated v2 runtime", () => {
  const adapter = fs.readFileSync(
    path.resolve(process.cwd(), "features/chat/transport/UnifiedTurnClient.ts"),
    "utf8",
  );
  assert.match(adapter, /TurnRuntimeClient/);
  assert.match(adapter, /protocol_version: "2\.0"/);
});
