# Rebrand sweep — every user-visible "DeepTutor" → "DeepWitya"

**Date:** 2026-09-04 · **Branch:** `main` · **Base:** `32fdd77c`
**Scope:** finish the 2026-07-20 brand change (which moved the logo art only) by
renaming the product **name** on every surface a person can read, and park the
voice-call button.

---

## 1. The rule the sweep applied

One substitution, `DeepTutor` → `DeepWitya`, gated by three conditions:

| Condition | Effect |
|---|---|
| followed by a letter | **skip** — `DeepTutorApp`, `DeepTutorError`, `DeepTutorParser`, `DeepTutorLightRAG` are symbols |
| preceded by `HKUDS/` | **skip** — a real repository path |
| lowercase `deeptutor` | **never matched** — the command, the package, `deeptutor.info`, import paths, `DEEPTUTOR_*` env vars |

`DeepTutor` and `DeepWitya` are both 9 characters, so **no line reflowed** and no
formatter had anything to do.

## 2. What was changed, by surface

### Web UI — locale **values** only

`web/locales/{en,th,zh}/app.json`: 66 / 64 / 67 values. The keys in these files
*are* the English source strings that the `t("…")` call sites pass, so they were
left byte-identical to upstream. Consequence: ~50 components that mention
DeepTutor inside a `t()` call needed **no edit**, and the locale files add zero
merge surface at the next upstream sync. Verified with `npm run i18n:parity` — OK
against `en` for both `th` and `zh`, 4739 keys each, still in parity.

One value deliberately kept: `"e.g. HKUDS/DeepTutor"` (a repo placeholder).

### Web UI — hardcoded strings

Renamed in place where the string is *not* an i18n key:

- `app/layout.tsx` — browser-tab title
- `app/(auth)/{login,register}/page.tsx` — wordmark heading + footer line
- `app/(utility)/avatar-preview/page.tsx` — sample session titles
- `app/(workspace)/co-writer/sampleTemplate.ts` — the sample document, **and** its
  heading anchors (`#deeptutor-co-writer` → `#deepwitya-co-writer`), so the
  in-document links still resolve after the headings changed
- `alt` / `aria-label` in `SidebarShell.tsx`, `AppShell.tsx`, `ChatWorkspace.tsx`,
  `SessionLoadingView.tsx`
- inline `{zh,en,th}` description objects in `settings-nav.ts`,
  `SubagentSettingsEditor.tsx`, `SettingsOverview.tsx`
- `TracePresentation.tsx` — the streaming-status fallback agent name
- `lib/codex-oauth.ts` — the invalid-response error
- `VoiceCallWidget.tsx` — the Thai call-button `title` and the route label

### Backend — string literals only

103 renames across 53 files. Found by **walking each file's AST** and rewriting
only the line spans covered by a non-docstring string constant — so comments and
docstrings were left untouched (they are pure merge surface and no user reads
them). Covers: launcher and CLI banners, update/install errors, the Codex
sign-in callback HTML, engine and parser prerequisite messages, partner `/link`
copy, the macOS reminder-notification title, and the MCP consent-screen client
name.

### Agent identity

- 64 occurrences across 46 prompt YAMLs (`agents/chat`, `agents/notebook`,
  `agents/visualize`, `book/prompts`, `services/memory/**/prompts`)
- 7 shipped system-prompt Markdown files (`capabilities/{mastery,setup,
  partner_authoring}/prompts`, `skills/builtin/skill-creator/SKILL.md`)

This is the part that makes the assistant introduce *itself* correctly. The Thai
STT vocabulary hint also moved `ดีพติวเตอร์` → `ดีพวิทยา`
(`services/voice_realtime/stt_guard.py`).

## 3. What was deliberately left alone

Machine-read identity, not display: the `deeptutor` command and package, the
`DeepTutorApp` / `DeepTutorError` / `DeepTutorParser` / `DeepTutorLightRAG`
symbols, every `HKUDS/DeepTutor` URL and the release-check path parsed out of it,
`deeptutor.info`, `DEEPTUTOR_*` env vars, `pip install deeptutor[...]`, the
`User-Agent` strings (`DeepTutor/1.0`, `DeepTutor-Version-Check`,
`Mozilla/5.0 DeepTutor/ImmersiveReading`) and the OpenRouter `X-OpenRouter-Title`
/ Codex client headers — changing those risks breaking a provider handshake for
no user-visible gain. All comments and docstrings.

**Two things worth a decision, not changed here:**

1. `agents/chat/prompts/{en,zh}/chat_agent.yaml` now reads *"You are DeepWitya, an
   intelligent AI learning assistant developed by the Data Intelligence Lab at
   HKU."* The name is the fork's; the attribution clause is upstream's. Apache-2.0
   attribution lives in `NOTICE`, not in a system prompt, so this line can say
   whatever the fork wants it to say.
2. The co-writer sample template has a link labelled "DeepWitya Website" pointing
   at `https://deeptutor.info`. It is demo content for a markdown-feature
   showcase, so the URL was left real.

Saved chat titles under `data/` (LLM-generated, e.g. *"แนะนำตัวและทำความรู้จักกับ
ผู้ช่วย DeepTutor"*) are the user's own history, not source, and were not rewritten.

## 4. Voice call button — parked

`web/components/voice/VoiceCallWidgetMount.tsx` returns `null` unless
`NEXT_PUBLIC_VOICE_CALL` is `1`/`true`. The guard sits before the `dynamic()`
component is rendered, so the widget chunk — the DOM-tree engine plus the page
actuator, the app's largest client chunk — is never requested. Nothing was
deleted: widget, realtime backend and voice settings all remain, and setting the
variable restores the button. The composer's separate "Record voice" dictation
button is a different (upstream) feature and was not touched.

## 5. Verification

| Gate | Result |
|---|---|
| `ruff check .` | All checks passed |
| `ruff format --check .` | 1792 files already formatted |
| `pytest -q tests deeptutor/learning/tests` | 28 failures, **all** also failing at `HEAD` before this change; the two that differed (`test_isolated_worker::test_child_allocation_does_not_raise_parent_rss_plateau`, `test_router::test_main_mounts_settings_as_admin_only_and_learning_policy_scoped`) pass in isolation, mention neither name, and are order-dependent |
| `npm run test:node` | 1082 pass, 0 fail |
| `npm run lint` | 0 errors, 76 warnings (all pre-existing) |
| `npm run i18n:check` | parity OK vs `en` for `th`, `zh` |
| Live app (`localhost:3000`) | tab title **DeepWitya**; Settings renders "ตั้งค่ากับ DeepWitya", "เวอร์ชัน DeepWitya…", "พิจารณาเฉพาะรุ่น DeepWitya…"; the only remaining `DeepTutor` on screen is a saved chat title in the sidebar |
| Voice button | absent from the DOM — `find "โทรคุยกับ"` returns no matches |
| CLI | `deeptutor --help` → "DeepWitya CLI – agent-first interface…", command name unchanged |
| graphify | `graphify update .` → 54520 nodes, 115974 edges |

### Baseline caveat

The pytest baseline was captured by stashing the change and re-running the failing
subset, not the whole suite, so the comparison is subset-scoped. The two deltas
were then confirmed individually to pass in isolation and to contain neither name.

## 6. One process note

Five files (`avatar-preview/page.tsx`, `SubagentSettingsEditor.tsx`,
`ChatWorkspace.tsx`, `TracePresentation.tsx`, `lib/codex-oauth.ts`) are **already**
non-conformant to `web/.prettierrc.json` at `HEAD` — confirmed by running
prettier 3.9.6 against the stashed originals. Since the rename is length-neutral
it introduced none of that, and a `prettier --write` was reverted so the diff
stays rename-only. The pre-commit prettier hook will want to reformat them when
they are next staged; that reformat is pre-existing debt, unrelated to this change.
