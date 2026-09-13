import test from "node:test";
import assert from "node:assert/strict";

import { loadScriptWithRetry } from "../lib/load-script-with-retry";

// Fork. The GeoGebra loader gave up on the first network error; from this
// deployment's network geogebra.org's CDN resets a first connection about one
// load in six (measured 2026-09-13), and a second try always loaded. These
// tests drive the retry helper with a stand-in document: each script tag is
// told whether to load, fail, or stay silent.

type Outcome = "load" | "error" | "silent";

class FakeScript {
  src = "";
  async = false;
  attrs = new Map<string, string>();
  removed = false;
  listeners: Record<string, Array<() => void>> = {};
  constructor(private readonly doc: FakeDocument) {}
  setAttribute(name: string, value: string) {
    this.attrs.set(name, value);
  }
  hasAttribute(name: string) {
    return this.attrs.has(name);
  }
  addEventListener(type: string, fn: () => void) {
    (this.listeners[type] ||= []).push(fn);
  }
  fire(type: string) {
    for (const fn of this.listeners[type] || []) fn();
  }
  remove() {
    this.removed = true;
    this.doc.nodes = this.doc.nodes.filter((node) => node !== this);
  }
}

class FakeDocument {
  nodes: FakeScript[] = [];
  created: FakeScript[] = [];
  constructor(private readonly outcomes: Outcome[]) {}
  createElement() {
    const script = new FakeScript(this);
    this.created.push(script);
    return script;
  }
  head = {
    appendChild: (script: FakeScript) => {
      this.nodes.push(script);
      const outcome = this.outcomes[this.created.length - 1] ?? "error";
      if (outcome !== "silent") setTimeout(() => script.fire(outcome), 0);
    },
  };
  private match(selector: string) {
    const src = selector.split('"')[1];
    const failedOnly = selector.includes("[data-load-failed]");
    return this.nodes.filter(
      (node) =>
        node.src === src &&
        (!failedOnly || node.hasAttribute("data-load-failed")),
    );
  }
  querySelectorAll(selector: string) {
    return this.match(selector);
  }
  querySelector(selector: string) {
    return this.match(selector)[0] ?? null;
  }
}

const SRC = "https://www.geogebra.org/apps/deployggb.js";

function run(doc: FakeDocument, extra: Record<string, unknown> = {}) {
  const waits: number[] = [];
  const promise = loadScriptWithRetry(SRC, {
    doc: doc as unknown as Document,
    sleep: async (ms: number) => {
      waits.push(ms);
    },
    ...extra,
  });
  return { promise, waits };
}

test("a reset first connection is retried and the script loads", async () => {
  const doc = new FakeDocument(["error", "load"]);
  const { promise, waits } = run(doc);
  await promise;
  assert.equal(doc.created.length, 2);
  assert.equal(doc.created[0].removed, true, "the failed tag is taken out");
  assert.deepEqual(
    doc.nodes.map((node) => node.src),
    [SRC],
    "one live tag remains",
  );
  assert.deepEqual(waits, [400]);
});

test("it gives up after the configured tries, pausing between them", async () => {
  const doc = new FakeDocument(["error", "error", "error"]);
  const { promise, waits } = run(doc);
  await assert.rejects(promise, /script failed to load/);
  assert.equal(doc.created.length, 3);
  assert.deepEqual(waits, [400, 1200]);
});

test("a script that never answers times out instead of hanging", async () => {
  const doc = new FakeDocument(["silent", "load"]);
  const { promise } = run(doc, { timeoutMs: 5 });
  await promise;
  assert.equal(doc.created.length, 2);
});

test("nothing is fetched when the global is already there", async () => {
  const doc = new FakeDocument(["load"]);
  const { promise } = run(doc, { isReady: () => true });
  await promise;
  assert.equal(doc.created.length, 0);
});

test("a tag someone else added is waited on, not duplicated", async () => {
  const doc = new FakeDocument([]);
  const foreign = new FakeScript(doc);
  foreign.src = SRC;
  doc.nodes.push(foreign);
  const { promise } = run(doc);
  setTimeout(() => foreign.fire("load"), 0);
  await promise;
  assert.equal(doc.created.length, 0);
});
