# REPORT — Voice UI Control: full handoff (2026-07-09)

**Self-contained handoff** so any agent in a fresh account/cowork can pick up
the voice work cold. Read `AGENTS.md` + `CLAUDE.md` (fork rules) first, then
`DESIGN_voice_grounding.md` (the forward blueprint), then this file.

> Why this exists: the owner is switching cowork accounts. Auto-memory in
> `~/.claude/.../memory/` does **not** travel with the account, so the strategic
> decisions it held are embedded inline here (§6).

---

## 1. One-paragraph state

A two-way realtime **voice call** for DeepTutor (mic → STT → LLM → per-sentence
TTS → speaker), Thai-first, that can also **steer the web UI by voice**:
navigate pages, click buttons/cards/links, fill form fields & dropdowns, edit
text, scroll — with a visible simulator cursor + field glow. All work is on
branch **`feat/voice-web-integration`** (a strict superset of
`feat/voice-prototype`; the prototype tip is its ancestor, nothing unique lives
on prototype). Everything is committed and pushed to `origin`. Tests: **pytest
252 green** (voice suite) + **node 183 green**; ruff/tsc/eslint/prettier clean.

## 2. Branches & how to continue

- **Work branch:** `feat/voice-web-integration` — the main line. Keep building here.
- `feat/voice-prototype` — historical bench (mock server + `call.html`); fully
  contained in the work branch. Safe to keep as a bookmark; don't merge INTO it.
- **Merge plan (agreed):** when the system is stable, PR
  `feat/voice-web-integration` → `main`, then delete both feature branches.
  Do NOT merge work→prototype (backwards).
- `web/next-env.d.ts` shows as modified — it's Next.js-generated churn, ignore.

## 3. Architecture (where things live)

**Server** (`deeptutor/services/voice_realtime/`):
- `pipeline.py` — the turn spine. `run_text_turn()` is a **decision ladder**:
  each rung matches the transcript with rules and acts WITHOUT the LLM; only the
  final fallback calls `ChatOrchestrator`. Rungs, in order: stop → secretary
  mode on/off → (in-mode dictation) → pending click-confirm → pending
  nav-confirm → "which page am I on" → navigate → declared action (scroll/new
  chat/back) → click-by-name (+ focus-a-field) → explicit fill → **implicit
  fill (Tier A)** → edit (clear/delete-word) → nav guess (ask back) → LLM.
- `ui_control.py` — the biggest file. Manifest/context sanitizing, all the
  matchers (`match_*_intent`, `match_implicit_fill`, `match_mode_command`,
  `match_where_am_i`), the resolvers (`resolve_click_target`,
  `resolve_field_target`, `resolve_fill_value`, `implicit_fill_field`), the
  phonetic/cross-script helpers (`_phonetic`, `_consonant_skeleton`,
  `_onset_class`), and the tools (`UINavigateTool`, `UIClickTool`, `UIFillTool`)
  + `VoiceUICapability`. Registered at runtime via `install_ui_control()` — zero
  upstream file edits (fork policy §3).
- `narration.py` — all fixed spoken lines.
- `stt_guard.py`, `chunker.py`, `session.py`, `vad.py` — STT screening,
  sentence chunking, session state, VAD.
- Router: `deeptutor/api/routers/voice_realtime.py` (WS `/api/v1/voice/ws`,
  control-frame dispatch, 8K frame cap).
- Voice providers: `deeptutor/services/voice/` (catalog-driven TTS/STT adapters,
  openai-compat). Active TTS/STT resolved from `data/user/settings/model_catalog.json`.

**Client** (`web/components/voice/`):
- `VoiceCallWidget.tsx` — the widget (call button, mascot overlay, WS transport,
  browser STT + echo guard, audio playback queue, `executeUiAction` dispatch).
- `pageContext.ts` — the **portable core**: reads the live DOM into `ui_context`
  (buttons/fields/activeField), and the executors: `clickVisibleByText` /
  `findClickableByText`, `fillFieldByVoice`, `editFieldByVoice` (+ Thai-aware
  `removeLastWord`), `scrollByVoice`, focus, `findFieldElement`. Native-setter
  writes so React controlled inputs accept programmatic values.
- `simulatorCursor.ts` — virtual cursor (`pointAt`/`clickPulse`) + field glow
  (`glowField`), presentation-only overlays.
- `speechAlternatives.ts` — N-best re-rank (`pickUtterance`).
- `VoiceActionBridge.tsx` — secretary-mode chat typing bridge.
- Node tests: `web/tests/voice-page-context.test.ts`,
  `voice-manifest-parity.test.ts`, `voice-speech-alternatives.test.ts`.

**Protocol** (system-agnostic): client → `ui_manifest` (whitelist of pages +
actions) and `ui_context` (live screen: summary, buttons, fields, activeField)
before each turn; server → `ui_action` frames the client executes and
re-validates.

## 4. What works today (feature inventory)

- Call pickup with spoken greeting; fading mascot overlay; lip-sync from audio.
- **Navigation** by voice (deterministic shortcut + LLM fallback), STT-garble
  tolerant verbs ("ไฟหน้า"→"ไปหน้า"), "ตอนนี้อยู่หน้าไหน" answered from live screen.
- **Scroll** (เลื่อนลง/ขึ้น/ล่างสุด/บนสุด), silent + deterministic.
- **Click-by-name** — buttons/cards/links; 4-tier resolve (exact→substring→
  phonetic→cross-script skeleton), so spoken "persona"↔on-screen "เพอร์โซนา",
  "ลามะ index"→"LlamaIndex". Danger words (ลบ/ล้าง/reset…) require spoken confirm.
- **Fill-by-voice** — "พิมพ์ X ในช่อง Y", dropdowns included; value corrected
  against on-screen vocabulary ("ลาวไทย"→"LAWs_thai"); dropdown value must be a
  real option.
- **Implicit fill (Tier A)** — "พิมพ์ X" with no field named → focused field
  (`activeField`) / last field / only field.
- **Click a field** — "กดที่ช่อง X" focuses the input (not a look-alike button).
- **Edit-by-voice** — "ล้างช่อง X", "ลบคำสุดท้าย" (Thai-aware word boundary).
- **Secretary (dictation) mode** — "เปิด/ปิดโหมดเลขา" (garble-tolerant, sound-class
  onset anchor so "บิดหมดเลขา" still exits); every utterance types into chat.
- **Simulator cursor + field glow** — cursor glides to target then acts; field
  blooms on focus/fill/edit.
- Perf: per-turn LLM config scoped to reasoning-off + low temp; per-sentence TTS
  with one retry for transient failures; watchdog reassure/abort.

## 5. Verify / run / test

```bash
# Python voice suite (fast, run this after any server change)
.venv/bin/pytest -q tests/services/voice_realtime
.venv/bin/ruff check deeptutor tests && .venv/bin/ruff format --check deeptutor/services/voice_realtime

# Web (in web/)
npm run test:node && npx tsc --noEmit && npx prettier --check components/voice

# Run the app
deeptutor start            # backend + frontend
```

To exercise live: open the app, press the call button, speak Thai commands.
Server changes need a **restart**; client-only changes need a **refresh**.
`data/user/settings/model_catalog.json` selects the active TTS/STT provider —
the current TTS is a **test endpoint** (`ptm-audio-tts-test`), flaky under
burst; if voice drops, check server logs for `voice TTS failed/empty` (now
logged) or switch to a production provider in Settings > Voice.

## 6. Strategic decisions (embedded — these were in auto-memory)

1. **Endgame:** the voice work is a stepping stone to a **standalone universal
   voice connector**, then a **computer-use agent**. Keep the core portable — no
   DeepTutor-specific logic in the resolvers/executors. Curated tiers are
   accepted stepping stones, not the destination.
2. **Active focus (agreed):** make voice **control everything in-app as if by
   hand** (full in-app coverage) BEFORE extracting the connector or OS-level
   work. Autonomous multi-step loop is acknowledged but NOT the active target.
3. **Gemini Live decision (2026-07-09):** evaluated swapping the pipeline to
   Gemini Live (speech-to-speech). It **inverts control** (Gemini becomes the
   brain; DeepTutor's ChatOrchestrator/RAG drop to a called-tool), which fights
   the "voice = DeepTutor tutor" architecture. **Deferred to the standalone-split
   phase**, where the inversion is a feature. The portable layers (client
   executors, resolvers, safety, manifest) port over; only the turn spine
   (`pipeline.py`) + STT/TTS get rewritten. Keep `pipeline.py` a clean swappable
   seam for this.
4. **Grounding design (`DESIGN_voice_grounding.md`):** the forward plan —
   **gated pipeline** (fast deterministic path + deep fallback, never linear),
   **core vs per-site-knowledge split**, a **provenance-agnostic Website Graph**
   (source-generated for DeepTutor, runtime-learnable for foreign sites),
   grounding signal priority (DOM/AX first; vision/OCR deferred), scoring +
   post-action verify, and an app-ignorant `lockTarget` interface. Has a
   Cost & tradeoffs section (§11).

## 7. Backlog / what's next (priority order)

**Pending with known repros (do first):**
- Small edit-by-voice gap the owner flagged (deferred by them) — details not
  captured; ask the owner to reproduce with the widget log line.

**Design-doc phases (agreed direction):**
1. **Implicit fill Tier B** — when ambiguous (2+ fields, none focused/remembered),
   let `ui_fill` omit the field and the LLM pick by semantics from the streamed
   schema; resolver still verifies the chosen field is real.
2. **Scoring** — collapse the fixed 4-tier resolver into one weighted
   multi-signal score (label+type+focus+recency+proximity). Guard with the 250+
   regression tests.
3. **Post-action Verify** — confirm the value landed / route changed. Prereq for
   the agentic loop.
4. **Website Graph + Navigation Reasoning** — cross-page single commands
   ("เปลี่ยนธีมจากหน้าอื่น"). The owner sees this as agentic-loop territory; build
   the catalog as a data asset first (source-generated + parity test).

**Deferred (connector / computer-use phase):** runtime graph learner for foreign
sites, ref/index + AX-tree grounding for black-box DOM, spatial reasoning,
vision/OCR, cross-tab, full autonomous planner, Gemini Live swap.

## 8. Fork policy reminders (every change)

- **`CHANGES.md`** — add an entry (what + which files). Never skip.
- **Conventional Commit** messages; end with the `Co-Authored-By` trailer.
- **`graphify update .`** after code changes (refreshes `graphify-out/`).
- Prefer NEW files over editing upstream files; the voice work already lives in
  isolated modules — keep it that way.

## 9. Diagnostic tips (patterns that recur)

- **"ไม่เจอปุ่ม/ช่อง" intermittently** → usually STT garbled the name, OR the
  element wasn't laid out at snapshot. Get the widget's transcript log line for
  the miss; add the garble to the resolver's regression tests (that's how every
  cross-script/phonetic case was fixed).
- **"acknowledges but nothing happens"** ("ได้ครับ" + no action) → a command fell
  past the deterministic ladder to the LLM, which acked without calling the tool.
  Fix by widening the matcher (phonetic fold / new alias), not by prompt alone.
- **Voice drops mid-reply** → TTS test endpoint failing per-sentence; check the
  new `voice TTS failed/empty` warnings; consider a production TTS provider.
- Every fix in this project became a regression test — keep that discipline; the
  test suites are the safety net for the fuzzy matching.
