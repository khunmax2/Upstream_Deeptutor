import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

import type { Catalog } from "../features/settings/store/SettingsStore";
import {
  settingsErrorDetail,
  withTestedEmbeddingDimension,
} from "../lib/settings-draft-helpers";

// Fork. Settings' Run test used to replace the page's saved state and draft
// with the catalog it had saved (on the host, into the primary admin's file).
// Now only the tested model's detected dimension is merged into the draft.

function draft(): Catalog {
  const empty = {
    active_profile_id: null,
    active_model_id: null,
    profiles: [],
  };
  return {
    version: 1,
    services: {
      llm: empty,
      task: empty,
      embedding: {
        active_profile_id: "p1",
        active_model_id: "m1",
        profiles: [
          {
            id: "p1",
            name: "OpenRouter",
            base_url: "https://openrouter.ai/api/v1/embeddings",
            api_key: "sk-typed-not-saved",
            api_version: "",
            models: [
              { id: "m1", name: "bge-m3", model: "baai/bge-m3", dimension: "" },
              { id: "m2", name: "other", model: "x/other", dimension: "768" },
            ],
          },
          {
            id: "p2",
            name: "Ollama",
            base_url: "http://localhost:11434/api/embed",
            api_key: "",
            api_version: "",
            models: [
              { id: "m1", name: "bge-m3", model: "bge-m3", dimension: "" },
            ],
          },
        ],
      },
      search: empty,
      tts: empty,
      stt: empty,
      imagegen: empty,
      videogen: empty,
    },
  } as unknown as Catalog;
}

test("only the tested model receives the detected dimension", () => {
  const before = draft();
  const after = withTestedEmbeddingDimension(
    before,
    "p1",
    "m1",
    1024,
    "256,1024",
  );
  const [p1, p2] = after.services.embedding.profiles;
  assert.equal(p1.models[0].dimension, "1024");
  assert.equal(p1.models[0].supported_dimensions, "256,1024");
  assert.equal(p1.models[1].dimension, "768");
  assert.equal(p2.models[0].dimension, "");
  // What was typed but not saved stays exactly as typed.
  assert.equal(p1.api_key, "sk-typed-not-saved");
  // The input is not mutated.
  assert.equal(before.services.embedding.profiles[0].models[0].dimension, "");
});

test("nothing to change returns the same draft", () => {
  const before = draft();
  assert.equal(withTestedEmbeddingDimension(before, "p9", "m1", 1024), before);
  assert.equal(withTestedEmbeddingDimension(before, "p1", "m1", 0), before);
  assert.equal(withTestedEmbeddingDimension(before, null, "m1", 1024), before);
  const once = withTestedEmbeddingDimension(before, "p1", "m1", 1024);
  assert.equal(withTestedEmbeddingDimension(once, "p1", "m1", 1024), once);
});

test("a refused save shows the server's reason, not just its status", async () => {
  const refused = new Response(
    JSON.stringify({ detail: "Enter it again, then save." }),
    { status: 400, headers: { "Content-Type": "application/json" } },
  );
  assert.equal(
    await settingsErrorDetail(refused),
    "Enter it again, then save.",
  );
  assert.equal(
    await settingsErrorDetail(new Response("oops", { status: 502 })),
    "HTTP 502",
  );
});

test("the settings page merges the dimension instead of replacing its draft", () => {
  const store = readFileSync(
    path.resolve(process.cwd(), "features/settings/store/SettingsStore.tsx"),
    "utf8",
  );
  assert.doesNotMatch(store, /setDraft\(cloneCatalog\(entry\.catalog\)\)/);
  assert.match(store, /withTestedEmbeddingDimension\(/);
  assert.match(store, /settingsErrorDetail\(response\)/);
});
