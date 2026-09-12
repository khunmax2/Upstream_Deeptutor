import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { UPSTREAM_LINKS_ENABLED, upstreamOnly } from "../lib/upstream-links";

// Fork: Settings ▸ About no longer offers upstream's releases as this
// installation's (decided 2026-09-12). The page keeps what is true of a
// DeepWitya build — running version, current version, installation — and
// guards the rest behind NEXT_PUBLIC_UPSTREAM_LINKS, the switch that already
// hides the sidebar's GitHub link. An upstream sync that re-applies upstream's
// markup unguarded turns these red.
const about = readFileSync(
  "features/settings/sections/AboutSettingsSection.tsx",
  "utf8",
);

function Probe(): string {
  return "rendered";
}

test("upstream surfaces are off unless the switch is set", () => {
  if (!process.env.NEXT_PUBLIC_UPSTREAM_LINKS) {
    assert.equal(UPSTREAM_LINKS_ENABLED, false);
  }
  const guarded = upstreamOnly(Probe);
  assert.equal(guarded === Probe, UPSTREAM_LINKS_ENABLED);
  if (!UPSTREAM_LINKS_ENABLED) {
    assert.equal((guarded as unknown as () => unknown)(), null);
  }
});

test("the Updates section and the Release channel row are guarded, not deleted", () => {
  assert.match(about, /<UpdatesSection\s+title=\{t\("Updates"\)\}/);
  assert.doesNotMatch(about, /<SettingSection\s+title=\{t\("Updates"\)\}/);
  assert.match(about, /<UpstreamSettingRow\s+title=\{t\("Release channel"\)\}/);
  // The markup is still there for the switch to bring back.
  assert.match(about, /t\("Latest stable release"\)/);
  assert.match(about, /status\.installation\.command/);
});

test("the header's release-notes link, Check now and Update are guarded", () => {
  assert.match(about, /UPSTREAM_LINKS_ENABLED && status\?\.release\?\.url &&/);
  assert.match(about, /UPSTREAM_LINKS_ENABLED && status\?\.is_admin &&/);
  assert.match(about, /UPSTREAM_LINKS_ENABLED && canUpdate &&/);
  // A failed check of the hidden feed must not surface as a banner either.
  assert.match(about, /UPSTREAM_LINKS_ENABLED\s*\?\s*next\.check_error/);
});

test("what is true of this installation stays unguarded", () => {
  assert.match(about, /<SettingRow\s+title=\{t\("Current version"\)\}/);
  assert.match(about, /<SettingRow\s+title=\{t\("Installation"\)\}/);
  assert.match(about, /\{t\("Running version"\)\}/);
});
