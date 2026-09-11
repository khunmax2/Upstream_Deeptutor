import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, sep } from "node:path";

/**
 * Next prefixes NEXT_PUBLIC_BASE_PATH on its own router, its own <Link>, and
 * /_next/ assets — and on nothing else. Everything the app writes itself has to
 * go through `withBasePath()` / `asset()` / `apiUrl()`, or it addresses the
 * origin root, which under /deepwitya is somebody else's page.
 *
 * This exists because of one raw <a href="/co-writer/…"> that a person found by
 * clicking it during UAT. The sweep that followed found exactly that one; this
 * keeps the count at zero.
 *
 * Matches the shapes that bypass Next. A `<Link>` is deliberately not matched —
 * that is the correct thing to write — and neither is a value in a data table,
 * because a value is only a URL when something renders it, and the renderers
 * are what this scans.
 */
const ROOTS = ["app", "components", "features", "lib", "hooks"];
const SAFE = ["withBasePath(", "asset(", "apiUrl(", "apiFetch(", "BASE_PATH"];

const SHAPES: Array<[string, RegExp]> = [
  [
    'raw <a href="/…">',
    /<a\b[^>]{0,300}?\bhref=(?:"\/(?!\/)|\{`\/(?!\/)|\{['"]\/(?!\/))/g,
  ],
  [
    'element src="/…"',
    /<(?:img|video|audio|iframe|source|embed)\b[^>]{0,200}?\bsrc=(?:"\/(?!\/)|\{`\/(?!\/)|\{['"]\/(?!\/))/g,
  ],
  [
    '<form action="/…">',
    /<form\b[^>]{0,200}?\baction=(?:"\/(?!\/)|\{`\/(?!\/))/g,
  ],
  ["raw fetch('/…')", /(?<![\w$.])fetch\(\s*[`'"]\/(?!\/)/g],
  [
    "EventSource/WebSocket('/…')",
    /new (?:EventSource|WebSocket)\(\s*[`'"]\/(?!\/)/g,
  ],
  ["location = '/…'", /(?:window\.)?location(?:\.href)?\s*=\s*[`'"]\/(?!\/)/g],
  [
    "location.assign/replace('/…')",
    /location\.(?:assign|replace)\(\s*[`'"]\/(?!\/)/g,
  ],
  ["window.open('/…')", /window\.open\(\s*[`'"]\/(?!\/)/g],
];

function sources(dir: string): string[] {
  let entries: string[];
  try {
    entries = readdirSync(dir, { recursive: true, encoding: "utf8" });
  } catch {
    return [];
  }
  return entries
    .filter(
      (e) =>
        /\.tsx?$/.test(e) &&
        !e.includes("node_modules") &&
        !e.includes(`${sep}tests${sep}`),
    )
    .map((e) => join(dir, e));
}

test("nothing the app writes itself addresses the origin root", () => {
  const offenders: string[] = [];
  let scanned = 0;
  for (const root of ROOTS) {
    for (const file of sources(root)) {
      scanned += 1;
      const text = readFileSync(file, "utf8");
      for (const [label, pattern] of SHAPES) {
        for (const match of text.matchAll(pattern)) {
          const around = text.slice(
            Math.max(0, (match.index ?? 0) - 120),
            (match.index ?? 0) + match[0].length + 40,
          );
          if (SAFE.some((k) => around.includes(k))) continue;
          const line = text.slice(0, match.index).split("\n").length;
          const src = text.split("\n")[line - 1]?.trim() ?? "";
          if (/^(\/\/|\*|\/\*)/.test(src)) continue;
          offenders.push(`${file.split(sep).join("/")}:${line}  [${label}]`);
        }
      }
    }
  }
  // A guard that scans nothing passes vacuously and looks identical to one
  // that scanned everything. The app has several hundred source files; if
  // this ever drops below that, the walk broke, not the code.
  assert.ok(
    scanned > 300,
    `scanned only ${scanned} files -- the walk is broken`,
  );
  assert.deepEqual(offenders, []);
});

test("the patterns match what they claim to", () => {
  const hits = (s: string) =>
    SHAPES.reduce((n, [, p]) => n + [...s.matchAll(p)].length, 0);
  assert.equal(hits("<a href={`/co-writer/${id}`}>"), 1);
  assert.equal(hits('<img src="/logo.png" />'), 1);
  assert.equal(hits("window.location.href = '/login'"), 1);
  assert.equal(hits("await fetch('/api/x')"), 1);
  // the correct forms
  assert.equal(hits("<Link href={`/co-writer/${id}`}>"), 0);
  assert.equal(hits("await apiFetch('/api/x')"), 0);
  assert.equal(hits('<a href="https://example.com">'), 0);
  assert.equal(hits('<a href="//cdn.example">'), 0);
});
