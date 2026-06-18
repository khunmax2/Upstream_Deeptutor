import test from "node:test";
import assert from "node:assert/strict";

import { normalizeLanguage } from "../context/app-shell-storage";

// app-shell-storage.normalizeLanguage is the canonical normalizer used by
// AppShellContext, I18nProvider and UnifiedChatContext. The second normalizer
// in i18n/init.ts transitively imports ESM-only i18next/react-i18next, which
// the CommonJS node-test runner cannot load, so its "th" handling is covered by
// `tsc --noEmit` (AppLanguage union) rather than a runtime test here.

test("normalizeLanguage: th passes through", () => {
  assert.equal(normalizeLanguage("th"), "th");
});

test("normalizeLanguage: zh passes through", () => {
  assert.equal(normalizeLanguage("zh"), "zh");
});

test("normalizeLanguage: en passes through", () => {
  assert.equal(normalizeLanguage("en"), "en");
});

test("normalizeLanguage: unknown / junk falls back to en", () => {
  assert.equal(normalizeLanguage("xx"), "en");
  assert.equal(normalizeLanguage("thai"), "en"); // storage normalizer is exact-match only
  assert.equal(normalizeLanguage(""), "en");
});

test("normalizeLanguage: null / undefined falls back to en", () => {
  assert.equal(normalizeLanguage(null), "en");
  assert.equal(normalizeLanguage(undefined), "en");
});
