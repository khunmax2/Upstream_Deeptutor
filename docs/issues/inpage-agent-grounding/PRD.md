# In-page agent grounding gaps (from live voice testing)

Status: needs-triage
Owner: Attapon · Drafted: 2026-07-13

Two loop/serializer limitations surfaced while live-testing the new voice intent
classifier → agent loop on DEEP settings pages (2026-07-13). Both are the LOOP's
to fix, not the classifier — routing was correct 4/4 (all four commands →
`ui_task`). Deep navigation itself works when the target is identifiable
(`/settings/models` ✅; `/settings/appearance` + click "English" + "All changes
saved" ✅, the deepest case with an action). The gaps:

- `issues/01-loop-verify-destination.md` — the loop claimed success on the WRONG
  page.
- `issues/02-serialize-settings-nav-labels.md` — the settings sub-nav serializes
  as icon-only links, so the loop can't tell them apart.

## Comments
