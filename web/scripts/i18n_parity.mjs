import fs from "node:fs";
import path from "node:path";

function listJsonFiles(dir) {
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...listJsonFiles(full));
    else if (ent.isFile() && ent.name.endsWith(".json")) out.push(full);
  }
  return out;
}

function loadJson(p) {
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function flattenKeys(obj, prefix = "") {
  const keys = [];
  if (!obj || typeof obj !== "object") return keys;
  for (const [k, v] of Object.entries(obj)) {
    const next = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) keys.push(...flattenKeys(v, next));
    else keys.push(next);
  }
  return keys;
}

function toRel(p, root) {
  return path.relative(root, p).replaceAll("\\", "/");
}

const webRoot = path.resolve(process.cwd());
const localesRoot = path.join(webRoot, "locales");
const enRoot = path.join(localesRoot, "en");

if (!fs.existsSync(enRoot)) {
  console.error(`[i18n:parity] Missing baseline locale root: ${enRoot}`);
  process.exit(2);
}

// Every locale directory under locales/ is checked against `en` as the
// baseline. Adding a new locale folder (e.g. th) is picked up automatically.
const locales = fs
  .readdirSync(localesRoot, { withFileTypes: true })
  .filter((ent) => ent.isDirectory() && ent.name !== "en")
  .map((ent) => ent.name)
  .sort();

if (!locales.length) {
  console.error(`[i18n:parity] No non-en locales found under ${localesRoot}`);
  process.exit(2);
}

const enFiles = listJsonFiles(enRoot).map((p) => toRel(p, enRoot)).sort();

let ok = true;

for (const locale of locales) {
  const localeRoot = path.join(localesRoot, locale);
  const localeFiles = listJsonFiles(localeRoot).map((p) => toRel(p, localeRoot)).sort();

  const missingFiles = enFiles.filter((f) => !localeFiles.includes(f));
  const extraFiles = localeFiles.filter((f) => !enFiles.includes(f));

  if (missingFiles.length) {
    ok = false;
    console.error(`[i18n:parity] Missing ${locale} files:`);
    for (const f of missingFiles) console.error(`- ${f}`);
  }
  if (extraFiles.length) {
    ok = false;
    console.error(`[i18n:parity] Extra ${locale} files:`);
    for (const f of extraFiles) console.error(`- ${f}`);
  }

  for (const rel of enFiles) {
    if (!localeFiles.includes(rel)) continue;
    const enJson = loadJson(path.join(enRoot, rel));
    const localeJson = loadJson(path.join(localeRoot, rel));
    const enKeys = new Set(flattenKeys(enJson));
    const localeKeys = new Set(flattenKeys(localeJson));

    const missingKeys = [...enKeys].filter((k) => !localeKeys.has(k)).sort();
    const extraKeys = [...localeKeys].filter((k) => !enKeys.has(k)).sort();

    if (missingKeys.length || extraKeys.length) {
      ok = false;
      console.error(`[i18n:parity] Key mismatch in ${locale}/${rel}`);
      if (missingKeys.length) {
        console.error(`  Missing ${locale} keys:`);
        for (const k of missingKeys) console.error(`  - ${k}`);
      }
      if (extraKeys.length) {
        console.error(`  Extra ${locale} keys:`);
        for (const k of extraKeys) console.error(`  - ${k}`);
      }
    }
  }
}

// ── sidebar labels and tooltips ────────────────────────────────────────────
//
// The audit pass only sees `t("a literal")` written in source. Every sidebar
// entry renders its tooltip as `t(entry.tooltipKey)` — a *variable* — so the
// audit is blind to the whole set, and three separate defects survived there
// unnoticed: a tooltip key absent from all three locales (so `t()` returned the
// key and Thai and Chinese readers were shown raw English), an `en` value that
// was the key echoed back as a placeholder, and a `th` value that translated
// the key's *name* instead of its content.
//
// The first two are machine-checkable, so they are checked here. The third is
// not — only a reader can tell "tooltip for immersive reading" from a tooltip.
const navEntriesPath = path.join(webRoot, "components", "sidebar", "nav-entries.ts");
if (fs.existsSync(navEntriesPath)) {
  const navSource = fs.readFileSync(navEntriesPath, "utf8");
  const referenced = new Set();
  for (const match of navSource.matchAll(/^\s*(?:label|tooltipKey):\s*"([^"]+)",/gm)) {
    referenced.add(match[1]);
  }

  const enJson = loadJson(path.join(enRoot, "app.json"));
  const missing = [...referenced].filter((key) => !(key in enJson)).sort();
  const placeholders = [...referenced]
    .filter((key) => enJson[key] === key && key.toLowerCase().includes("tooltip"))
    .sort();

  if (missing.length) {
    ok = false;
    console.error("[i18n:parity] Sidebar keys referenced by nav-entries.ts but absent from en/app.json:");
    for (const key of missing) console.error(`  - ${key}`);
    console.error("  (t() falls back to the key, so every non-en reader is shown English.)");
  }
  if (placeholders.length) {
    ok = false;
    console.error("[i18n:parity] Sidebar tooltips whose en value is just the key echoed back:");
    for (const key of placeholders) console.error(`  - ${key}`);
    console.error("  (Write the real sentence; the other locales may already have one.)");
  }
  if (!missing.length && !placeholders.length) {
    console.log(`[i18n:parity] sidebar: ${referenced.size} label/tooltip keys resolve`);
  }
}

if (!ok) process.exit(1);
console.log(`[i18n:parity] OK (locales checked vs en: ${locales.join(", ")})`);
