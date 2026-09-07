import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeEmbedUrl,
  resolveOpenMaicEmbed,
} from "../lib/openmaic-embed";

test("openmaic embed accepts an absolute http origin", () => {
  assert.deepEqual(normalizeEmbedUrl("http://localhost:3100"), {
    url: "http://localhost:3100",
    sameOrigin: false,
  });
});

test("openmaic embed accepts https and strips a trailing slash", () => {
  assert.deepEqual(normalizeEmbedUrl("https://maic.example.com/"), {
    url: "https://maic.example.com",
    sameOrigin: false,
  });
});

test("openmaic embed marks a same-origin path", () => {
  assert.deepEqual(normalizeEmbedUrl("/maic-app/"), {
    url: "/maic-app",
    sameOrigin: true,
  });
});

// The three that matter: each of these would put content this app did not
// choose — or script in this app's own origin — inside the frame.
test("openmaic embed rejects a protocol-relative host", () => {
  assert.deepEqual(normalizeEmbedUrl("//evil.example"), {
    url: "",
    sameOrigin: false,
  });
});

test("openmaic embed rejects javascript: and data: sources", () => {
  for (const hostile of ["javascript:alert(1)", "data:text/html,<script>"]) {
    assert.deepEqual(
      normalizeEmbedUrl(hostile),
      { url: "", sameOrigin: false },
      hostile,
    );
  }
});

test("openmaic embed treats blank and non-string settings as unconfigured", () => {
  for (const blank of ["", "   ", undefined, null, 42, {}]) {
    assert.deepEqual(normalizeEmbedUrl(blank), {
      url: "",
      sameOrigin: false,
    });
  }
});

test("openmaic embed prefers the environment over the settings file", () => {
  assert.deepEqual(
    resolveOpenMaicEmbed({ DEEPTUTOR_OPENMAIC_URL: "http://openmaic:3000" }),
    { url: "http://openmaic:3000", sameOrigin: false },
  );
});

test("openmaic embed ignores a malformed environment value", () => {
  // Falls through to the settings file, which is absent in CI — the point is
  // that a bad env value never becomes the iframe src.
  assert.notEqual(
    resolveOpenMaicEmbed({ DEEPTUTOR_OPENMAIC_URL: "javascript:alert(1)" }).url,
    "javascript:alert(1)",
  );
});
