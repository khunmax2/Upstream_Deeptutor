# Settings sub-nav serializes as icon-only links (no text) → loop can't distinguish

Status: ready-for-agent

## What happened (live, 2026-07-13)

On `/settings` the sub-navigation links serialize as **empty, text-less lines**
— e.g. `[18]<a  />`, `[23]<a  />`, `[29]<a  />` — because each link's label lives
in a nested element the flattener doesn't surface as the anchor's text. The loop
therefore cannot tell "การค้นหา" (search) from "ความสามารถ" (capabilities) and
picks the wrong one; sub-pages whose target IS identifiable (models, appearance)
navigate fine.

Evidence: "เข้าหน้าตั้งค่าการค้นหา" → landed on `/settings/capabilities`;
"ตั้งค่าเสียงพูดออก" → could not find the entry at all. (See sibling issue 01 for
the false-success half of the same run.)

## Why it matters

Deep, icon-only navs are common (settings, toolbars). If the serializer hands
the model blank `[N]<a />` lines, no amount of reasoning can pick the right one —
this caps the loop on exactly the "several pages deep" flows it should own.

## Fix direction

In `web/lib/page-actuator/serialize.ts`, when an interactive element (anchor /
button) has no direct text, fall back to its **accessible name** so each line
carries an identity: `aria-label` → `title` → nested text of the element →
last path segment of `href`. e.g. `[18]<a >Model settings />` instead of
`[18]<a />`. Keep the attribute/length caps already in place.

Regression: a node test on a settings-like fixture (icon anchors whose label is
in a child span) must produce non-empty labels for those lines.

## Comments
