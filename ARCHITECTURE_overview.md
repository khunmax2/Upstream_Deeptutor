# ARCHITECTURE — How this fork's work attaches to upstream DeepTutor

This document explains the **three workstreams** in this fork (Thai localization,
the v1.4.8 upstream sync, and the LINE channel) and — the important part — **how
each one hooks into the existing DeepTutor system**. The three use deliberately
different attachment mechanisms, which directly explains the fork's maintenance
cost and merge strategy.

For the upstream core architecture itself, read `AGENTS.md` first — this doc
assumes it and only describes the *fork's* additions on top.

---

## 0. The core spine (shared by all three)

Everything in this fork orbits one axis (see `AGENTS.md` for detail):

```
3 entry points (Typer CLI · WebSocket /api/v1/ws · Python SDK DeepTutorApp)
        │
        ▼
ChatOrchestrator  ──routes──>  UnifiedContext  ──>  Capability (default: chat)
(deeptutor/runtime/orchestrator.py)                  └─> AgenticChatPipeline
        │
   StreamBus events
```

Two registry-driven plugin layers extend it: **Level 1 Tools** (single-shot LLM
functions) and **Level 2 Capabilities** (multi-stage pipelines). A separate
**Partners subsystem** (`deeptutor/partners/`, `deeptutor/services/partners/`)
lets external chat channels drive that same chat loop.

Mental model for the three workstreams:
- **Thai i18n** makes the spine *speak Thai*.
- **Upstream sync** keeps the spine *current with HKUDS*.
- **LINE** opens a *new door* to the spine — reusing the whole pipeline unchanged.

---

## 1. Thai localization — attaches by *threading through existing plumbing* (EDIT)

**Mechanism:** language is cross-cutting, so there is no single insertion point.
The work threads the `th` locale through every place the system already makes a
language decision. This is the **most invasive** attachment: mostly edits to
upstream files, plus additive locale data.

**Where it hooks in:**
- *Frontend (additive + edit):* new `web/locales/th/` (full parity bundle);
  `AppLanguage`/`normalizeLanguage`, lazy-loaded `th` bundle, Settings language
  selector, `th-TH` datetime.
- *Backend plumbing (edit):* `parse_language`, core i18n, settings API accept
  `"th"`; new `normalize_agent_language()` + Thai `language_directive` + `th→en`
  prompt fallback chain.
- *Runtime (edit):* chat pipeline, notebook, co-writer, partners, explore-context,
  obsidian, memory consolidator keep Thai sessions in Thai.
- *Learning/quiz (additive + edit):* `deeptutor/learning/prompts/th.yaml`; quiz
  judge accepts `th`.

**Consequence:** because it edits upstream files, every touched file is recorded
in `FORK_TOUCHPOINTS.txt`, and these are exactly the files that conflict on an
upstream sync. **Thai i18n is the reason a sync is a merge-with-conflicts, not a
fast-forward.** Detail: `REPORT_round1.md`–`REPORT_round4.md`, `REPORT_final_qa.md`.

## 2. Upstream sync v1.4.8 — attaches by *git merge + reconcile* (MAINTENANCE)

**Mechanism:** not a feature — a maintenance operation. It pulls HKUDS's new code
into the fork's `main` and reconciles it with the fork's customizations.

**What happened:**
- Merged upstream **v1.4.8** (release `88c25653`) via merge commit `e62fdd3d`,
  bringing in the upstream **Subagent / Connected-Agents / Partners** stack
  (~33 new files).
- Resolved 4 content conflicts + 2 auto-merged high-risk files, then
  **re-localized** every upstream-changed file (Thai parity restored to 2643 keys;
  added a `th` branch to the new subagent framing prompt).

**Consequence:** `main` is now the **v1.4.8 baseline** that both Thai and LINE build
on; the next sync's merge-base is `88c25653`. Workstream 1 is what makes this step
non-trivial — the more upstream files Thai edits, the more this step costs.
Detail: `REPORT_sync_v1.4.8.md`, `REPORT_impact_v1.4.8.md`,
`REPORT_followup_agents_ui.md`.

## 3. LINE integration — attaches via an *extension point* (ADD)

**Mechanism:** the opposite of workstream 1. Instead of editing the core, it plugs
into a hole the framework already exposes. The entire feature is **one new file**.

**Where it hooks in (zero core edits):**
- `deeptutor/partners/channels/line.py` implements the `BaseChannel` contract; the
  channel **registry auto-discovers it** by module scan (`pkgutil.iter_modules`) —
  no registration edit.
- Config is a Pydantic `LineConfig`; `ChannelsConfig` stores it via `extra="allow"`,
  the schema endpoint introspects it, and secret fields (`channel_secret`,
  `channel_access_token`) are masked by name heuristic — no schema edits.
- The Web UI config form is **generated** by the generic `schema-form.tsx` from
  `LineConfig`'s JSON Schema — **no `web/` code for LINE**.

**Runtime data flow (reuses the existing partner path):**
```
LINE webhook POST
  → verify x-line-signature (HMAC-SHA256 over raw body), ack 200 fast
  → _handle_message()  → MessageBus.publish_inbound()
  → PartnerRunner (one asyncio task per msg, serialised per session_key=line:<userId>)
  → ChatOrchestrator  ← THE SAME LOOP THE PRODUCT CHAT USES
       (partner's KB / skills / soul / tools)
  → reply published to MessageBus.outbound
  → ChannelManager._send_with_retry → LineChannel.send()
       (Reply API if reply-token fresh, else Push API by userId)
  history persisted per user in PartnerSessionStore (data/partners/<id>/sessions/)
```

**Consequence:** because it touches the core in 0 lines, an upstream sync barely
affects LINE. Required fork-policy edit is only `FORK_TOUCHPOINTS.txt` (+ optional
cosmetic icon/locale). Detail: `REPORT_line_integration_feasibility.md`,
`REPORT_line_implementation.md`.

---

## 4. The cross-cutting principle: "add files > edit files"

The three workstreams sit on a spectrum of mergeability:

| Workstream | Attachment | Upstream files edited | Cost on each sync |
|---|---|---|---|
| Thai i18n | thread through plumbing | many | high (re-localize conflicts) |
| Upstream sync | git merge | (reconciles the above) | — (this *is* the sync) |
| LINE channel | extension point (new file) | ~0 (manifest only) | near zero |

The fork policy (`CLAUDE.md` §3) — *prefer adding new files over editing upstream
files* — is exactly this lesson. LINE is the model case (survives syncs untouched);
Thai i18n is the unavoidable exception (i18n is inherently cross-cutting), which is
why it is carefully tracked in `FORK_TOUCHPOINTS.txt` and absorbed during each sync.

## 5. Where to read more

- Upstream core: `AGENTS.md`
- Fork rules / modification log: `CLAUDE.md`, `CHANGES.md`, `FORK_TOUCHPOINTS.txt`
- Thai i18n: `REPORT_round1.md`–`REPORT_round4.md`, `REPORT_final_qa.md`
- Sync v1.4.8: `REPORT_sync_v1.4.8.md`, `REPORT_impact_v1.4.8.md`, `REPORT_followup_agents_ui.md`
- LINE: `REPORT_line_integration_feasibility.md`, `REPORT_line_implementation.md`
