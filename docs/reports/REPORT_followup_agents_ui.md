# Follow-up Report — Agents-config UI Thai + th-TH

**Date:** 2026-06-19 · **Branch:** `fix/thai-agents-ui` → ff `main`
**Closes:** the 2 residuals deferred from the v1.4.8 sync (`REPORT_sync_v1.4.8.md`).

---

## Task A — Localize agents-config UI (~72 strings)

Two new upstream components rendered their own `{zh,en}` `Lang` (not the i18n
catalog), so Thai users saw English. Both now cover Thai.

| File | Strings | Change |
|---|---|---|
| `web/components/agents/ConnectedAgents.tsx` | ~24 | `Lang` → `{zh,en,th}`; `tr` detects `th`; `th` added to every label. |
| `web/components/settings/SubagentSettingsEditor.tsx` | ~48 | Same; plus `formatTs(value, locale)` now takes a locale string (`th-TH` for Thai instead of the old `zh`-boolean); the 3 module-level option arrays (permission modes, sandboxes, approvals) all get `th`. |

`tr` pattern (matches the rest of the fork):
```ts
const zh = lang?.startsWith("zh");
const th = lang?.startsWith("th");
const tr = (l: Lang) => (zh ? l.zh : th ? l.th : l.en);
```

**Style note:** a first pass accidentally ran a stray global Prettier config that
reformatted both files to single-quote/no-semicolon (192/297-line churn,
diverging from the repo's double-quote/semicolon style and upstream). Reverted to
pristine and re-applied **only** the `th` additions, preserving original style —
final diff is +47/−19 and +91/−40 (additions + necessary line-wraps), which keeps
these upstream files mergeable for future syncs.

**Audit:** `ConnectedAgents` and `SubagentSettingsEditor` were the *only* agents
components carrying a local `{zh,en}` `Lang`; the other new `web/.../agents/*`
files (AgentsHub, AgentSelector, SubagentTabBody, SubagentRunTranscript) hold no
UI literals of their own.

## Task B — th-TH robustness (1-liner)

`deeptutor/services/prompt/language.py` → `normalize_agent_language()` handled
`zh*` via `startswith` but matched Thai only as exact `"th"`, so `"th-TH"` →
`"en"`. Added the symmetric rule:
```py
if s.startswith("th"):
    return "th"
```
Now `th-TH` / `th_TH` → `th`. This fixes the subagent framing prompt
(`capabilities/subagent/capability.py`), which keys off `normalize_agent_language`
— verified `_system_text("th-TH", …)` now returns Thai (was English).

Added `("th-TH","th")` and `("th_TH","th")` to the parametrized
`test_normalize_agent_language` in `tests/services/prompt/test_language_th.py`.

## Verification

| Gate | Result |
|---|---|
| `npm run build` (fresh, after clearing stale `.next` type cache) | ✅ Compiled, 49/49 pages |
| `npx tsc --noEmit` | ✅ (the earlier error was stale `.next/dev/types` for the deleted `/space/agents` page) |
| `npx eslint` (both files) | ✅ exit 0 |
| `npm run i18n:parity` | ✅ OK (no catalog change — local-Lang components) |
| `ruff check` / `ruff format --check` | ✅ |
| `pytest tests/services/prompt` | ✅ 19 passed (incl. new th-TH cases) |
| `normalize_agent_language("th-TH"/"th_TH")` | ✅ → `th` |
| `_system_text("th-TH", …)` | ✅ → Thai framing |

🟡 Manual (recommend on a running instance): open **Settings → Partners & Agents →
Claude Code / Codex** and the **Connected agents** panel in Thai UI mode → confirm
no English leaks. Headless verification covered build/type/lint/parity; the strings
render through the same `tr` path exercised above.

## Files changed

- `web/components/agents/ConnectedAgents.tsx`
- `web/components/settings/SubagentSettingsEditor.tsx`
- `deeptutor/services/prompt/language.py`
- `tests/services/prompt/test_language_th.py`
- `CHANGES.md`

## Outcome

Both v1.4.8 residuals closed. **Thai localization is now 100% on v1.4.8** with no
known deferred surfaces.
