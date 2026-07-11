# CHANGES — modifications from upstream

This repository is a **modified fork** of
[HKUDS/DeepTutor](https://github.com/HKUDS/DeepTutor), distributed under the
Apache License 2.0. Per **Apache-2.0 Section 4(b)**, this file states that files
in this distribution have been changed, and summarizes those changes relative to
upstream.

- **Fork:** https://github.com/khunmax2/Upstream_Deeptutor
- **Upstream:** https://github.com/HKUDS/DeepTutor
- **Upstream baseline:** v1.4.6 (commit `7ac3a3ba`)

> Detailed, per-round records are in the committed `REPORT_*.md` files and the
> git commit history. This file is the high-level, human-readable summary.
> See also `ARCHITECTURE_overview.md` — how the three workstreams (Thai i18n,
> v1.4.8 sync, LINE) attach to the upstream core.

---

## Upstream bug fixes

These fix bugs that exist in upstream (not fork-specific). Each is kept as a
small, isolated diff so it can be cherry-picked onto a clean branch and proposed
back to HKUDS; once merged upstream the divergence is removed.

- **2026-07-09 — Gemini 3 tool calls no longer 400 on the second agent-loop
  round (`thought_signature`).** Gemini 3 models attach a REQUIRED
  `thought_signature` to every function call (delivered as `extra_content`
  on the streamed tool-call delta via the OpenAI-compat endpoint) and reject
  any follow-up request whose replayed assistant message lacks it
  (`400 INVALID_ARGUMENT: Function call is missing a thought_signature`).
  The agent loop (`deeptutor/agents/chat/agent_loop.py`) accumulated only
  `id`/`name`/`arguments` from stream deltas and rebuilt a minimal
  OpenAI-shape message, so with a Gemini 3 chat model EVERY multi-round turn
  failed at round 2 and degraded to a forced finish — whose summary could
  claim tool actions that never ran (live symptom: voice UI said
  "พิมพ์แล้วครับ" while nothing was typed). Fix: provider extras from
  `model_extra` on the tool-call delta are accumulated and echoed back
  verbatim in `_assistant_message_with_tool_calls`. Provider-agnostic
  (extras pass through untouched; absent extras are a no-op). Reproduced
  red/green against the live API before the fix; regression test
  `tests/agents/chat/test_agent_loop.py::test_tool_call_provider_extras_survive_the_replay`.
  Candidate for an upstream PR.

- **2026-06-20 — `allowFrom` empty no longer crashes the whole backend.**
  `ChannelManager._validate_allow_from` (`deeptutor/partners/channels/manager.py`)
  used to `raise SystemExit` when any *enabled* channel had `allow_from == []`,
  which aborted backend startup entirely (FastAPI lifespan → "Application startup
  failed"). Affects every channel, since `allow_from` defaults to `[]`. Now the
  misconfigured channel is disabled with a logged ERROR and the rest of the
  backend starts normally; the runtime `BaseChannel.is_allowed` already denies all
  senders when the allowlist is empty, so deny-by-default is preserved. Added unit
  tests (`tests/services/partners/test_channel_manager.py::TestValidateAllowFrom`).
  Candidate for an upstream PR (see `REPORT_line_allowfrom_crash.md`).

## Thai (th) localization — 2026-06-17

Added full Thai language support across the whole stack. 5 commits, merged to
`main` via merge commit `fb7a44f0`. ~59 source files changed (+ tests).

- **Frontend i18n:** `AppLanguage`/`normalizeLanguage` (web/i18n, app-shell-storage),
  lazy-load th bundle, Settings language selector, datetime locale (`th-TH`).
- **Locale data:** new `web/locales/th/` (`app.json` at full parity = 2614 keys;
  `common.json`); parity script generalized to check all locales.
- **Backend plumbing:** `parse_language` / core i18n / settings API now accept `"th"`;
  added `normalize_agent_language()` + Thai `language_directive` ("ภาษาไทย") + `th→en`
  prompt fallback chain.
- **Runtime:** chat pipeline, notebook, co-writer, source inventory, partners,
  explore-context, obsidian, and memory consolidator keep Thai sessions in Thai;
  `metadata_i18n` + tool/capability descriptions include `th`; skill taxonomy falls
  back to English (not Chinese) for `th`.
- **Learning / quiz:** `deeptutor/learning/prompts/th.yaml`; quiz judge accepts `th`.
- **Detail:** `REPORT_round1.md`–`REPORT_round4.md`, `REPORT_final_qa.md`.

## Documentation

- **2026-06-25 — Added production deployment guide + deploy templates.** New
  `DEPLOY.md`: step-by-step Docker Compose (production) deploy on a fresh server,
  including LINE webhook setup behind Caddy reverse proxy + auto-TLS, the
  remote-server `next_public_api_base_external`/CORS gotcha, ops (restart/update/
  backup), troubleshooting, and a Claude-CLI checklist. New additive templates
  under `deploy/`: `docker-compose.caddy.yml` (Caddy overlay routing
  app./api./line. → in-container 3782/8001/3979), `Caddyfile.example`,
  `settings/system.json.example`, `settings/partner-line-config.yaml.example`.
  All new files; no upstream files touched. Secrets stay out of git (everything
  under `data/` remains gitignored). Files: `DEPLOY.md`, `deploy/`.
- **2026-06-25 — CLAUDE.md: documented the Partners channels adapter framework.**
  Added a pointer under fork-policy §3 locating the extension point
  (`deeptutor/partners/channels/<name>.py` → `BaseChannel`, discovered by
  `channels/registry.py`, wired by `channels/manager.py` over `partners/bus/`) and its
  tests (`tests/services/partners/`, `tests/api/test_partners_*`), so future agents
  working on channel integrations (e.g. LINE) know where to add code. Files: `CLAUDE.md`.

## LINE integration — (in progress)

Adding LINE Messaging as a Partners channel — primarily a new file
`deeptutor/partners/channels/line.py` (additive; the channel registry auto-discovers
adapters). _Backend DM MVP landed 2026-06-20 (see below); UI touch-ups (channel
icon, Thai labels) deferred._

- **2026-06-20 — feasibility re-verified against v1.4.8.** Added
  `REPORT_line_integration_feasibility.md` (code-traced, file:line). Confirmed the
  channel framework is contract-stable v1.4.6→v1.4.8 and the LINE adapter is
  backend-additive: no edits to `registry.py`, `partners/config/schema.py`,
  `_partners_channel_schema.py`, `channels/manager.py`, or `pyproject.toml`
  (LINE adds no new dependency). Template corrected to `msteams.py` (webhook+HMAC+REST)
  over `slack.py` (socket mode). Documented that the partner runtime does not forward
  inbound metadata to `send()` (reply-token must be stashed in-memory) and that
  per-session concurrency is already handled by `PartnerRunner`. Added a LINE
  retrievability section (Get profile → displayName/picture/status/language only;
  consent/friend/not-blocked conditions; opaque per-OA userId; reply-free vs
  push-counted quota; rate limits) verified against official LINE docs (Jun 2026),
  and put displayName resolution via Get profile into scope. No source code changed
  in this round (docs only).

- **2026-06-20 — DM MVP implemented (backend-only).** New files
  `deeptutor/partners/channels/line.py` (LINE Official Account adapter) and
  `tests/services/partners/test_line_channel.py` (32 unit tests). The adapter
  runs a `ThreadingHTTPServer` webhook (modeled on `msteams.py`): verifies
  `x-line-signature` (HMAC-SHA256 over the raw body) before parsing, acks 200
  fast and bridges work onto the asyncio loop, loops `events[]` for 1:1 text,
  and replies via the Reply API (free, single-use token, ~50s margin) with a
  Push-API fallback. Resolves `displayName` via Get profile (cached) so the
  session list shows a real name instead of the opaque `userId`. No new
  dependency (stdlib `hmac`/`hashlib`/`base64` + existing `httpx`). Verified
  end-to-end that the framework auto-discovers the channel and the schema
  endpoint masks `channel_secret`/`channel_access_token` with **zero** edits to
  `registry.py`/`schema.py`/`manager.py`/`_partners_channel_schema.py`/
  `pyproject.toml` — confirming the feasibility report. Appended
  `line.py` to `FORK_TOUCHPOINTS.txt`. UI touch-ups (channel icon, locale keys)
  deferred; LINE falls back to the generic `Radio` icon. See
  `REPORT_line_implementation.md`. Deferred to phase 2: rich content / images /
  audio / stickers / group chat.

- **2026-06-20 — post-review fixes (pre-integration-test).** Four hardening
  changes to `deeptutor/partners/channels/line.py` (+ tests), all in-file:
  (1) **quota defaults** — `LineConfig` now overrides `send_progress` /
  `send_tool_hints` to `False` (LINE has no in-place edit, so progress narration
  is pure quota-burning Push); effective via the `default_config()` seeding path.
  (2) **allowlist pre-gate** — `_handle_event` checks `is_allowed` before any
  Get-profile call or token storage, so an unauthorized sender can't burn the
  profile rate-limit or fill caches (base `_handle_message` still re-checks).
  (3) **fast-ack** — the webhook handler schedules `_handle_webhook`
  fire-and-forget (done-callback logs failures) instead of blocking the 200 ack
  on `fut.result`, so a new-user Get-profile can't slow the ack (LINE disables
  slow webhooks). (4) **bounded caches** — `_reply_tokens` / `_profile_cache`
  are now `OrderedDict` capped at `LINE_MAX_CACHE_ENTRIES` (10k) with LRU
  eviction; reply-token store also prunes expired entries opportunistically, so
  a public OA can't grow memory without bound. See the "Post-review fixes"
  section in `REPORT_line_implementation.md`.

## Voice call (realtime) — prototype (in progress)

Adding a two-way realtime voice layer (Mic → STT → LLM → TTS → speaker), Thai-first
and low-latency. Design decision: a **separate realtime I/O layer**, not a Partners
channel — it reuses `ChatOrchestrator` directly (bypassing the text/turn-based
`MessageBus`) so it can stream tokens to per-sentence TTS and support barge-in. All
code is additive and isolated for mergeability.

- **2026-07-11 — Vision layer: neon restyle of the highlight boxes.** Live
  feedback: the engine's default look (2px solid borders in a 12-color loud
  palette + opaque label chips) reads as visual chaos on a busy page. New
  `web/lib/page-actuator/neonHighlights.ts`: called right after a highlighted
  dom_tree pass, it restyles the overlays the engine just drew — hues softened
  35% toward white, hairline 1px borders with outer/inner glow (box-shadow),
  near-zero fill, labels as translucent dark pills with glowing text. The
  vendored `dom_tree/engine.ts` stays byte-identical (vendor contract); box↔
  label color correlation survives for free because both derive from the same
  per-index base color, which we read back from the inline styles (computed
  style would return currentcolor-white for the borderless labels). Hooked in
  `actuator.ts` observe(). Files: `web/lib/page-actuator/neonHighlights.ts`,
  `web/lib/page-actuator/actuator.ts`.

- **2026-07-11 — In-page agent: the SEMANTIC door — chat LLM routes tasks via
  a tool (`ui_agent_task`).** The owner's routing critique, accepted: lexical
  verb-matching (`agent/intent.py`) is whack-a-mole — every caller phrases
  tasks differently, and each miss dead-ends in the navigate-only chat path
  doing half the job ("ได้เลยครับ" and nothing more). The model that already
  understood the sentence should make the routing call. New
  `UIAgentTaskTool` in `ui_control.py` (registered alongside
  ui_navigate/click/fill; `owned_tools` +1): the chat LLM calls it with the
  caller's restated `task`; the pipeline intercepts that TOOL_CALL, abandons
  the chat turn (`events.aclose()`, same pattern as the watchdog — one voice
  on the call, never two), and hands the task to the loop via the existing
  `agent_runner`. Gating: `execute()` checks `agent_loop_enabled()` per call
  and refuses with a corrective result when off; the system-block advertises
  the tool ONLY while the loop is available (lazy-imported flag check —
  `agent.danger` imports ui_control, so top-level would cycle). Also fixed en
  route: `run_text_turn` never passed `agent_runner` down to the inner LLM
  turn (`_run_text_turn`) — the parameter existed but arrived as None.
  `intent.py`'s docstring demoted to what it now is: a free short-circuit
  that skips one chat completion on obvious phrasings, not the loop's only
  door. Tests: +9 (`test_agent_task_tool.py` — flag gating both sides,
  prompt advertisement on/off, registration; `test_wiring.py` — handoff with
  the model's restated task, transcript fallback, abandoned-turn-never-
  speaks, flag-off chat continues). Voice suite: 393 green.

- **2026-07-10 — In-page agent: live-test fixes (JSON mode, verb gap, visible
  narration).** First live run against a real page surfaced two real failures
  and one UX gap, all traced to source before fixing:
  1. **Malformed LLM output ("โมเดลตอบผิดรูปแบบซ้ำหลายครั้งครับ")** — the loop
     was asking the model to reply in JSON via prompt instructions alone;
     page-agent's real edge is a provider-level forced `tool_choice`, which
     `services.llm.complete()` has no seam for. Closest equivalent:
     `agent/llm.py::think()` now passes `response_format={"type":
     "json_object"}` (an existing house pattern — see
     `tools/question/question_extractor.py`; self-gating, silently dropped
     for unsupported providers), `reasoning_effort="minimal"` (a hybrid
     model's reasoning preamble can smuggle in a stray brace that breaks the
     fixer's extraction — same value the voice chat turn already scopes to),
     and `temperature=0.2` (near-deterministic action selection).
  2. **"กลับไปหน้าหลักแล้วค้นหาราคาทอง" fell through to the old navigate-only
     chat path** instead of the agent loop (diagnosed from the log signature:
     `🖱 ไปหน้า` + generic "ได้เลยครับ" are the OLD `executeUiAction`
     navigation handler and the existing chat's own `ui_navigate` tool — not
     anything the agent loop emits). Root cause: `agent/intent.py`'s opener
     list had no "กลับ" (back-to) family. Added `กลับไปที่ / กลับไปหน้า /
     กลับไป / กลับ`; writing tests for it also caught a second bug — the
     sequence-connector check used `pos <= 0` when it should have been
     `pos < 0` (rejecting the legitimate case where an object-less opener
     butts straight against the connector, e.g. "กลับไปแล้วเปิด...").
  3. **The loop was audio-only in the widget** — narration/questions were
     spoken via a bare `{"type": "audio"}` frame the client never logs, so a
     TTS hiccup (or just not listening closely) left zero visibility into
     what the agent was doing, unlike page-agent's step-by-step log.
     `AgentVoiceBridge` now also emits `{"type": "agent_note", "text": …}`
     alongside every spoken line; `VoiceCallWidget.tsx` renders it as a `sys`
     log line. Failure-tolerant (`contextlib.suppress`) — a dying socket
     during narration must not take the run down with it.
  Also: fixer-failure logs now include the raw completion text (truncated) —
  previously only the parsed-away `FixerError` message was logged, making a
  run like this undiagnosable from logs alone. Tests: +16
  (`test_llm_scope`, `test_intent`, `test_voice_bridge`, `test_loop`). Voice
  suite: 384 green.

- **2026-07-10 — In-page agent, Phase D (wired end-to-end, behind a
  default-off flag) landed.** The loop now answers the phone. New in
  `services/voice_realtime/agent/`: `ws_actuator.py` (server end of the A4
  frame protocol — observe/act as correlated request/response, chunked
  `agent_state` reassembly, honest timeouts), `voice_bridge.py`
  (`AgentVoiceBridge`: loop + actuator + the C3 speech-routing state machine —
  pending question ⇒ incoming speech is the ANSWER; otherwise ⇒ barge-in
  abort; mask always comes down, even on abort), `intent.py`
  (`match_agent_task`: deterministic multi-step detector — action verb +
  sequence connector + second verb; conservative by design). Pipeline gains
  `agent_runner` threading and three entries into the loop: multi-step task
  (checked BEFORE single-step rungs so "ไปตั้งค่าแล้วเปลี่ยนธีมมืด" cannot
  half-match navigation), click-ambiguous, click-miss-after-graph; plus
  `speak_agent_line` (mid-run narration audio) and `_run_agent_turn` (turn
  framing; a crashed loop speaks the miss line, never a dead line). Session
  owns the bridge lifecycle + routes `agent_*` frames (router passes them
  through); loop terminal lines are now spoken Thai. **D0 flag:**
  `DEEPTUTOR_AGENT_LOOP=1` + `DEEPTUTOR_AGENT_MODEL` both required
  (env-based rather than the planned settings key — one switchboard with the
  rest of the agent config); flag off ⇒ byte-identical behavior, proven by
  the untouched pre-existing suite. Loop robustness: observe() failure now
  ends the run honestly instead of crashing the call. Tests: +27
  (`test_ws_actuator`, `test_intent`, `test_voice_bridge`, `test_wiring` —
  incl. answer-vs-barge-in live routing and mask-always-down). Voice suite:
  376 green. `ui_graph` fate (D4) deliberately deferred to Phase E data.

- **2026-07-10 — In-page agent, Phase C (trust model) landed.** New
  `deeptutor/services/voice_realtime/agent/danger.py`: `DangerGate`, the
  `pre_act` implementation — before ANY loop click fires, the target's real
  serialized `[index]` line is extracted from the page snapshot
  (`extract_element_line`, exact-index match) and checked against the same
  danger lexicon the fast path uses (`ui_control.is_dangerous_button`);
  dangerous or unverifiable targets pause the run for a SPOKEN confirmation
  (timeout ⇒ no). A refusal goes back to the LLM as an explicit
  "User REJECTED …" observation so it re-plans instead of retrying. Typing is
  not gated (codebase philosophy: typing never submits; the submit press is
  its own gated click). Loop additions: `waiting_on_user` now also covers the
  gate's confirmation window (C3 speech routing: answer vs barge-in), and the
  ending (`done.text`) is always narrated — success or honest failure (C4).
  Tests: `tests/.../agent/test_danger.py` — 13 cases, anchored by the replay
  of the real evaluation trace (page-agent pressed "ลบ Knowledge Base" [169]
  unconfirmed; with the gate that click can never fire, even when the task
  says "ไม่ต้องถาม"). Voice suite: 349 green.

- **2026-07-10 — In-page agent, Phase A (eyes + hands) landed.** New package
  `web/lib/page-actuator/`: `serialize.ts` (pure, node-tested port of
  page-agent's LLM-facing DOM format — `[index]` lines, indent hierarchy,
  `*[new]` markers via caller-owned WeakSet, attribute hygiene incl. 20-char
  caps, `data-scrollable` distances, header/footer scroll hints, plus our
  hard 30K-char cap that cuts on a line boundary with an explicit truncation
  notice), `actions.ts` (MIT-attributed port: full W3C pointer+mouse click
  sequence, inner hit-test refinement, native value setter, contenteditable
  Plan A→verify→Plan B; visible hand = our simulatorCursor), `runMask.ts`
  (A5: input shield shown only while the loop runs; click-on-mask = takeover;
  pass-through wrapper for hit-tests), `actuator.ts` (PageActuator: observe →
  vendored dom_tree engine with the highlight/vision layer switched ON +
  react-root blacklist; act by index; devtools handle `window.pageActuator`),
  `wsBridge.ts` (A4 frames `agent_run/agent_observe/agent_state_chunk/`
  `agent_act/agent_acted/agent_takeover`; agent_state is JSON-then-chunked at
  6000 chars because control frames are ~8K-capped server-side). Wired into
  `VoiceCallWidget.tsx` with a bridge ref + one routing line (inert until the
  server loop sends agent frames). Tests:
  `web/tests/page-actuator-serialize.test.ts` — 8 cases pinning the exact
  serialization format on fabricated trees. Node suite: 197 green.

- **2026-07-10 — In-page agent loop, Phase B (the brain) landed.** New package
  `deeptutor/services/voice_realtime/agent/` implementing our own
  observe→think→act loop per `PLAN_inpage_agent_parity.md`: `loop.py`
  (InPageAgentLoop; voice-tuned maxSteps 15 / stepDelay 0.8s; abort;
  `pre_act` danger-gate seam for Phase C; narration + ask_user hooks with a
  `waiting_on_user` flag for speech routing), `macro_tool.py` (action catalog +
  validation, ask_user offered only when answerable), `fixer.py` (all six
  autoFixer heuristics ported for JSON-contract transport), `prompt.py` (our
  own voice-first system prompt + page-agent-shaped assembler: reflections-only
  history, fresh DOM per step), `observations.py` (navigation / wait /
  step-budget `<sys>` notes), `llm.py` (agent model via `DEEPTUTOR_AGENT_MODEL`
  (+ optional `_BASE_URL`/`_API_KEY` standalone upstream) — loud failure, never
  a silent chat-model fallback; per-call kwargs on `services.llm.complete`).
  Transport decision recorded in code: JSON-contract + fixer as the primary
  path (provider-universal; `complete()` returns text only), native forced
  tool_choice can layer on later. Tests:
  `tests/services/voice_realtime/agent/` — 28 cases incl. the Phase-B
  acceptance run (3-step navigate→fill→confirm on a fixture actuator), budget
  exhaustion + warnings, fixer recovery/give-up, mid-run abort, pre_act
  blocking, ask_user round-trip, narration failure tolerance. Not wired into
  the pipeline yet (that is Phase D, behind a default-off flag).

- **2026-07-10 — Deep rung removed; superseded by the in-page agent plan.**
  The 2026-07-10 page-agent evaluation (branch `page-agent-clean-eval`, kept as
  the page-agent test bed) proved a looped observe→think→act agent covers
  everything the deep rung was for — so the plan (`PLAN_inpage_agent_parity.md`,
  now on this branch too) replaces it with our own agent loop. Removed:
  `services/voice_realtime/ui_deep.py` (LLM picks an index from a flat
  inventory), its pipeline caller `_run_deep_click` + both call sites (now
  marked `[agent-loop seam — Phase D2]`, falling through to ask-back /
  honest-miss), the `inventory_getter` threading, and
  `tests/services/voice_realtime/test_ui_deep.py`. **Kept deliberately:** the
  `ui_scan`→`ui_inventory` transport (session future + router handler + web
  responder — becomes the loop's observe channel, Phase B), the vendored
  `dom_tree` engine + `pageInventory.ts` + `click_index` executor (seed of the
  Phase A actuator), and `ui_graph.py` (deterministic fast path; fate decided
  by data in Phase E). `DESIGN_voice_grounding.md` preamble now records what is
  superseded vs still authoritative. Voice suite: 308 tests green.

- **2026-06-30 — Standalone prototype landed** under `voice_prototype/` (outside the
  `deeptutor/` package; no upstream files touched). FastAPI WebSocket server +
  browser mic client (energy-VAD endpointing + barge-in), pipeline = Groq Whisper STT
  (batch-on-endpoint) → OpenAI-compatible LLM stream → `SentenceChunker` →
  pluggable TTS (`openai` / `elevenlabs` / `botnoi`). Per-stage latency instrumentation;
  network-free tests in `voice_prototype/tests/`. Proves the design before integration.
  Production target: `deeptutor/api/routers/voice_realtime.py` +
  `deeptutor/services/voice_realtime/`, reusing the existing `deeptutor/services/voice/`
  STT/TTS adapters.
- **2026-07-02 — Call MVP: first end-to-end voice call against the real
  DeepTutor brain.** Production realtime layer additions
  (`services/voice_realtime/`, `api/routers/voice_realtime.py`): a
  `user_text` control frame (`run_text_turn()`) runs LLM→TTS for a
  client-recognised utterance (browser Web Speech STT) so calls work while no
  server STT provider is available; raw-PCM TTS output (iApp) is wrapped as
  WAV before hitting the socket (`containerize_audio()`); and the speakable
  gate was fixed to match reality — agentic rounds stream as
  `call_kind='agent_loop_round'` (the previous `llm_final_response`-only gate
  silenced entire turns). Test page `voice_prototype/static/call.html`
  (`/call` on the prototype server) connects straight to
  `ws://localhost:8001/api/v1/voice/ws` with browser-STT / server-STT modes,
  typed input, and barge-in. E2E verified live: text turn → ChatOrchestrator →
  20 per-sentence iApp WAV frames streamed while the model was still writing.

- **2026-07-02 — Prototype trimmed to the call page.** Removed the standalone
  `voice_prototype/static/index.html` (`/`) and `mvp.html` (`/mvp`) demos and
  their prototype-local `/ws` / `/ws/chat` handlers; `server.py` is now a thin
  static host serving `call.html` (which talks straight to DeepTutor's
  `/api/v1/voice/ws`). The provider seam remains in `providers.py` / `pipeline.py`
  (covered by `selftest.py` + `tests/`).

- **2026-07-08 — Voice scroll ("เลื่อนลง/ขึ้น/ล่างสุด/บนสุด").** First of the
  page-agent-parity actions. Four new declared actions
  (scroll_down/up/bottom/top) ride the existing action framework: clear
  verb+direction phrasings hit the deterministic shortcut (bare "เลื่อน" —
  reschedule! — never triggers; "เลื่อนลงล่างสุด" is ambiguous → LLM), free
  phrasings go through the LLM's `ui_navigate`. Scroll acts *silently*
  (rapid-fire commands + instantly visible effect — no "ได้เลยครับ" spam).
  Client `scrollByVoice` finds the page's real scroller (DeepTutor's shell is
  `h-screen overflow-hidden`, so `window` never scrolls — pick the largest
  visible scrollable container outside the widget) and scrolls smoothly.
  Files: `services/voice_realtime/ui_control.py`, `pipeline.py`,
  `web/components/voice/VoiceCallWidget.tsx`, `pageContext.ts`.

- **2026-07-09 — Handoff report for account move.** Added
  `REPORT_voice_handoff_2026-07-09.md` — a self-contained handoff of the whole
  voice-UI-control effort (state, branch/merge plan, architecture map, feature
  inventory, verify/run steps, the strategic decisions previously held only in
  auto-memory, the prioritized backlog, and diagnostic patterns) so a fresh
  agent in another cowork account can continue cold. Doc only.

- **2026-07-09 — Implicit fill (Tier A): "พิมพ์ X" without naming the field.**
  The "he didn't even name the field" UX from the grounding design. A bare type
  command now targets, deterministically and without the LLM: the focused field
  (client streams `activeField` = the caret's field in `ui_context`), else the
  last field filled this call (`last_field`, if still on screen), else the only
  visible field; ambiguous (2+ fields, nothing to disambiguate) falls through
  untouched so it never hijacks conversation. Type verbs only
  (พิมพ์/ใส่/กรอก/เขียน) — "เลือก" (implicit dropdown pick) is excluded as too
  ambiguous. Value still corrected against on-screen vocabulary. Files:
  `services/voice_realtime/ui_control.py` (`match_implicit_fill`,
  `implicit_fill_field`, `activeField` in `sanitize_ui_context`), `pipeline.py`,
  `web/components/voice/pageContext.ts` (streams `activeField`); tests
  (pytest 252 green, node 183 green). Also added a **Cost & tradeoffs** section
  to `DESIGN_voice_grounding.md`.

- **2026-07-09 — Implicit fill (Tier B): LLM value→field pick, verified.**
  The ambiguous half Tier A deliberately leaves untouched (2+ fields, none
  focused/remembered) now reaches the LLM with permission to pick the field
  whose *meaning* matches the value — an email address goes in the
  email-typed field. Field entries in `ui_context` now declare a semantic
  input type behind a new marker ("อีเมล (ชนิด: email)", matching the
  existing options marker pattern; plain text stays bare, so the frame
  budget is untouched for unannotated fields). `ui_fill`'s `field` param is
  optional: omitted with one visible field → that field; with several → the
  tool hands the schema back and demands an explicit pick (the server never
  guesses). Trust model intact: every pick — the model's included — still
  goes through `resolve_field_target` against the visible fields. Files:
  `services/voice_realtime/ui_control.py` (`_FIELD_TYPE_MARKER`,
  `field_label`, `UIFillTool` definition/execute, `system_block` FIELD
  CHOICE rule), `web/components/voice/pageContext.ts`
  (`SEMANTIC_INPUT_TYPES`, `formatFieldEntry` type param); tests
  (pytest 258 green, node 184 green).

- **2026-07-09 — Weighted resolver: focus/recency break ties; Tier B dispatch
  parity fix.** The fixed 4-tier resolver ladder (exact → substring → phonetic
  → cross-script) is now one weighted score per candidate. Label-match quality
  still dominates — tier scores are spaced (100) wider than the sum of all
  situational boosts (focus +30, recency +20 = 50), so the boosts can only
  break a tie WITHIN a tier, never promote a weaker label match or resurrect
  a miss; the full regression suite passed unchanged before any new behaviour
  was added. New behaviour: a tie between equally-matching field labels
  ("ค้นหา" vs two ค้นหา-fields) now resolves to the focused field
  (`activeField`) or the last field filled this call instead of asking back.
  `last_field` rides only on the deterministic rungs — the LLM tool + its
  dispatch must resolve identically, so they use `activeField` alone. Also
  fixes a Tier B parity bug from the previous entry: with `field` omitted and
  one visible field, the tool result said "Typed" but the pipeline dispatch
  resolved `""` → missing → nothing typed; both now share
  `effective_fill_field()`. Files: `services/voice_realtime/ui_control.py`
  (`_label_score`, `_resolve_spoken_name` boosts, `resolve_field_target`
  `last_field` kwarg, `effective_fill_field`), `pipeline.py` (rungs pass
  `last_field`; fill dispatch uses the shared fallback); tests
  (pytest 267 green, node 184 green).

- **2026-07-09 — Post-action Verify: the client confirms every UI action
  actually landed.** The grounding design's "Verify (after)" stage — the
  agentic-loop prerequisite. After executing a `ui_action` the client POLLS
  the live DOM until the postcondition holds or a deadline passes (never a
  fixed sleep): fill/edit → the field holds the expected value across two
  consecutive samples (catches React controlled inputs reverting a
  native-setter write; fill retries the write once on failure), navigate /
  open_kb → `location.pathname` reached the target (the poll IS the
  page-load wait), focus → the caret is in the named field. The verdict
  rides to the server as a new client→server WS frame
  `ui_action_result {target, field, ok, detail}`; the server sanitizes it,
  remembers it on `nav_state["last_action_result"]`, and logs failures —
  the honest record of a spoken "ได้เลยครับ" whose action did not stick.
  Executors now return what they wrote (`fillFieldByVoice`/`editFieldByVoice`
  → `string | null`) so verify has an exact expected value (a `<select>`'s
  option value differs from the spoken text). Files:
  `web/components/voice/pageContext.ts` (`verifyFieldValue`,
  `verifyFieldFocused`, `verifyPath`, `readFieldValue`, executor return
  types), `VoiceCallWidget.tsx` (verify + retry + `reportActionResult`),
  `services/voice_realtime/ui_control.py` (`sanitize_action_result`),
  `api/routers/voice_realtime.py` (frame dispatch + protocol doc); tests
  (pytest 276 green, node 184 green).

- **2026-07-09 — Website Graph: cross-page single commands ("เปลี่ยนธีมเป็น
  โหมดมืด" from any page).** The grounding design's Website Graph /
  Navigation Reasoning stage. A curated, provenance-agnostic graph
  (`services/voice_realtime/ui_graph.json`: nodes = routes with an action
  catalog of capability id + visible click text + spoken aliases) lets the
  ladder answer a command whose control is NOT on the current screen:
  resolve the name against the graph (same weighted scorer → same garble
  tolerance), then plan `open_path(/settings/appearance) → click "Dark"`.
  Execution is verify-gated: the pipeline emits `open_path` and PARKS the
  follow-up click on `nav_state["pending_graph_step"]`; the router
  dispatches it only when the client's post-action verify confirms the
  planned route landed (fires once, TTL-bounded, dropped on failed/wrong
  navigation — never a sleep). Two entry rungs: goal phrasings
  ("เปลี่ยนธีมเป็น X", `match_graph_intent`) and the click rung's miss
  branch ("กดโหมดมืด" from /home). Destructive-sounding controls resolve as
  a miss (never auto-pressed cross-page). Client: new `open_path` action
  honours only paths under the UI_PAGES whitelist; click/fill/focus
  executors now POLL for their element (late mounts after navigation).
  Curated controls (phase 1): the four theme tiles on /settings/appearance.
  New parity test `web/tests/voice-graph-parity.test.ts` fails CI when
  graph paths and real routes/whitelist drift. Files: new
  `services/voice_realtime/ui_graph.{py,json}`, `pipeline.py` (graph rungs +
  `_run_graph_plan`), `narration.py` (`GRAPH_CROSS_PAGE_LINE`),
  `ui_control.py` (`argument` in `sanitize_action_result`),
  `api/routers/voice_realtime.py` (pending-step dispatch),
  `web/components/voice/VoiceCallWidget.tsx` (`open_path`, poll-find),
  `pageContext.ts` (`findWithPoll`); tests (pytest 298 green, node 187
  green, incl. new `tests/services/voice_realtime/test_ui_graph.py`).

- **2026-07-10 — Ambiguous ties reach the deep rung; ask-backs name the
  tie; transliteration-hardened deep prompt.** Live round 2 findings:
  (1) a fuzzy tie ("กดที่ลามะ Index" matching several labels) dead-ended
  at "พูดชื่อเต็มอีกครั้ง" because only the *missing* outcome fell through
  to the deep rung — the *ambiguous* outcome now consults it first (the
  LLM with the full indexed screen is exactly the right adjudicator for a
  tie), and when even that declines, the ask-back NAMES the tied
  candidates ("หมายถึง X หรือ Y ครับ", `narration.ambiguous_click_line` +
  `ui_control.resolve_click_candidates`) — answerable for the caller,
  live telemetry for the maintainer. (2) The deep-pick model answered
  NONE for "กราฟเหล็ก" → GraphRAG; the system prompt now teaches Thai
  phonetic renderings of English UI labels with real garble examples and
  instructs sounding names out; a deep-pick NONE is logged at WARNING
  with the raw reply (INFO never reaches the log file), so the next
  tuning round has evidence. Files:
  `services/voice_realtime/pipeline.py`, `ui_control.py`, `ui_deep.py`,
  `narration.py`; tests (pytest 318 green, node 189 green).

- **2026-07-10 — Live-test trio: oversized inventory frame; suffix-twin
  false ambiguity; the LLM's amputated screen view.** Three defects found
  in one live session on the knowledge center (109 buttons on screen):
  (1) the deep rung's ``ui_inventory`` frame budgeted only label lengths,
  not JSON syntax — 150 items overflowed the 8K control-frame cap and the
  server rejected the reply whole ("Control frame too large" → honest
  miss); the scan now budgets the real serialized size (7.2K, envelope
  included). (2) The engine collector reports some cards twice, so the
  duplicate-suffix feature produced ordinal twins ("LlamaIndex",
  "LlamaIndex (2)") that tied in the resolver and asked back "พูดชื่อเต็ม"
  — a dead end for identical names; tied winners whose labels differ only
  by the ordinal now resolve to the first in document order (previously-
  working "ลามะ index" restored). (3) The LLM fallback only saw the
  summary's tightly-capped prose and falsely told callers a visible button
  didn't exist; the system prompt now carries the FULL buttons channel
  (the same list the resolver uses). Server buttons backstop 100→200.
  Files: `web/components/voice/pageContext.ts`,
  `services/voice_realtime/ui_control.py`; tests (pytest 316 green,
  node 189 green).

- **2026-07-10 — Deep target-locking rung (Phase B): an LLM picks the
  element INDEX when every deterministic rung misses.** The page-agent
  accuracy inside our gated pipeline: on a click miss (after the graph
  fallback) the server pulls a full *indexed* inventory of interactive
  elements from the client (new ``ui_scan`` server→client and
  ``ui_inventory`` client→server frames; the client keeps live refs,
  budgets to the 8K frame cap, and always replies — an empty scan beats a
  timeout), then ONE scoped LLM call maps the utterance to an index
  (garble-tolerant by instruction), and the client clicks by index
  (``click_index`` action) — no name matching, no buttons budget, so
  icon-only buttons, duplicate labels and long-tail phrasings become
  reachable. Trust rules pinned by tests: the LLM may only answer with an
  index from the list, destructive-sounding labels are refused
  server-side whatever the model says, every failure mode (scan timeout,
  LLM error, NONE) falls through to the honest miss line, and clear
  commands never pay for any of it. Also adds a per-snapshot diagnosis
  line in the widget log ("📸 อ่านจอ: N ปุ่ม M ช่อง") so collection
  problems and naming problems are distinguishable at a glance. Files:
  new `services/voice_realtime/ui_deep.py`, `pipeline.py`
  (`_run_deep_click` + `inventory_getter` kwarg), `session.py`
  (ui_scan/ui_inventory future round trip, `INVENTORY_TIMEOUT_SECONDS`),
  `api/routers/voice_realtime.py` (frame dispatch + protocol doc),
  `web/components/voice/pageContext.ts` (`scanInventory`,
  `findScannedElement`), `VoiceCallWidget.tsx` (`ui_scan` reply,
  `click_index` executor, snapshot log line); tests (pytest 314 green
  incl. new `test_ui_deep.py`, node 189 green).

- **2026-07-09 — Collector "eyes" upgrade: vendored browser-use dom_tree
  engine; char-budgeted buttons; duplicate suffixes; mutation-aware
  refresh (Phase A of the hybrid plan).** Live testing showed "หาปุ่มไม่เจอ"
  on nearly every busy page. Root causes and fixes: (1) the collector's
  fixed CSS selector missed div-based clickables and icon buttons →
  interactive elements are now discovered by the vendored page-agent/
  browser-use dom_tree walker (behavioral signals: cursor:pointer, event
  handlers, tabindex, contenteditable, ARIA; new
  `web/components/voice/dom_tree/engine.ts` — MIT, attribution added to
  `NOTICE`; wrapped by new `pageInventory.ts`, with the legacy selector as
  an automatic fallback if the engine ever throws); (2) the 25-item cap
  amputated busy pages → the buttons channel is now budgeted by characters
  (~2600, roughly 60–80 labels; server backstop `_MAX_BUTTONS` 40→100 —
  the 8K frame cap is the real bound); (3) duplicate labels were dropped,
  making same-named cards unaddressable → ordinal suffixes ("LlamaIndex
  (2)"), shared by the streamed context and the click executor via the
  single collector; (4) snapshot staleness → a debounced, rate-limited
  MutationObserver re-streams `ui_context` when the page mutates under a
  live call (own-panel mutations ignored). Files:
  `web/components/voice/dom_tree/{engine.ts,type.ts}` (vendored),
  `pageInventory.ts` (new), `pageContext.ts`, `VoiceCallWidget.tsx`,
  `deeptutor/services/voice_realtime/ui_control.py`, `NOTICE`; tests
  (node 189 green incl. suffix/budget units, pytest 305 green, Next build
  green).

- **2026-07-09 — Graph goal matcher: generic "เปลี่ยน/สลับ … เป็น X" form.**
  Live gap: "เปลี่ยนภาษาอินเตอร์เฟสเป็นภาษาอังกฤษ" matched no fixed verb (the
  padding vocabulary between the verb and "เป็น" is unbounded), so the
  command fell to the LLM. `match_graph_intent` now also accepts an
  utterance starting with เปลี่ยน/สลับ that contains "เป็น", taking what
  follows as the target — safe because the name still has to hit the curated
  graph and a miss falls through untouched. Files:
  `services/voice_realtime/ui_graph.py`; tests (pytest 330 green across the
  voice + ws + agent-loop suites).

- **2026-07-09 — Graph catalog: language switch + create-KB; field-kind
  controls.** Extends the Website Graph's curated catalog with
  source-verified controls: the three language buttons on
  /settings/appearance (click texts are endonyms — "ภาษาไทย" / "English" /
  "中文" — identical in every locale, so locale-proof) and the "Knowledge
  Base ใหม่" create button on /knowledge (Thai-locale text; a non-Thai UI
  degrades to an honest verify-failure). New goal verbs
  ("เปลี่ยนภาษาเป็น", bare "สร้าง" last — a graph miss falls through
  untouched). `plan_graph_step` now supports `kind: "field"` controls
  (cross-page plan ends in a FOCUS, caret placed, nothing typed) — the
  mechanism is tested; no field control is curated yet. New guard test:
  every click text and alias in the SHIPPED graph must resolve uniquely to
  its own control, so future catalog entries can't silently shadow each
  other. Files: `services/voice_realtime/ui_graph.{py,json}`,
  `web/tests/voice-graph-parity.test.ts` (field kind); tests
  (pytest 302 green, node 187 green).

- **2026-07-09 — Design doc: voice grounding & target-locking architecture.**
  Added `DESIGN_voice_grounding.md` — the blueprint for the next phase of
  target-locking (Website Graph / Navigation Reasoning / Scoring / post-action
  Verify / implicit field targeting), written to keep the engine portable to a
  future standalone connector: a gated (fast-path + fallback) pipeline, a
  clean core/per-site-knowledge split, a provenance-agnostic Website Graph
  schema (source-generated for DeepTutor, runtime-learnable for foreign sites),
  a signal-priority for grounding (DOM/AX first, vision/OCR deferred), and an
  app-ignorant `lockTarget` interface. Doc only — no code change.

- **2026-07-09 — Cursor snappiness, field visibility robustness, TTS retry.**
  Three live-feedback fixes: (1) the simulator cursor felt like it lagged the
  actual click on first use — it was dashing across the whole screen from its
  hidden corner; now a hidden cursor snaps to a short offset from the target
  and glides only that hop, so every appearance is a brief consistent motion
  the click waits on. (2) `isVisible` (pageContext) fell back to
  `getClientRects()` when `offsetParent` is null — `offsetParent` is null for
  `position:fixed`/sticky elements too, which intermittently dropped a visible
  field/button from the streamed context ("บางครั้งไม่เจอช่อง"). (3) A
  per-sentence TTS failure dropped a WHOLE sentence silently ("เสียงหาย"):
  the active provider is a flaky/slow test endpoint hit 4+ times per reply, so
  `_synthesize_with_retry` now retries a transient failure once and LOGS every
  failure/empty result (previously silent) — a persistent failure still
  surfaces one error frame. Not a rate-limit in our code (none exists; a 429
  already surfaces as an error frame). Files:
  `web/components/voice/simulatorCursor.ts`, `pageContext.ts`,
  `services/voice_realtime/pipeline.py` (pytest 239, node 183 green).

- **2026-07-09 — Field glow: the locked-on field blooms so the caller sees
  the pick.** Companion to focus/fill/edit — once the target field is
  resolved, a halo shimmers around it: one quick flash on focus-lock, a few
  soft pulses while typing/editing. Presentation-only, added to the simulator
  cursor module (`web/components/voice/simulatorCursor.ts`): one singleton
  overlay on <body>, `pointer-events: none`, positioned over the field's rect
  (grown by a 4px pad, corner radius matched), `prefers-reduced-motion` → a
  single static fade, disposed on hang-up alongside the cursor. Wired into the
  `focus_field` / `fill_field` / `edit_field` handlers. Files:
  `simulatorCursor.ts`, `VoiceCallWidget.tsx`; node test for the pure glow-box
  math (node 183 green).

- **2026-07-08 — Click mis-target fixes + faster cursor.** Three live gaps
  from the same session log, plus a speed pass: (1) "กด/คลิกที่ช่อง X" now
  FOCUSES the named form field (new `focus_field` ui_action + client caret
  placement) instead of searching buttons — explicit "ช่อง" never falls back
  to button tiers, and a click name that equals a visible field label
  exactly prefers the field ("กดที่ค้นหาหนังสือ" = the search box, not the
  contained sidebar button "หนังสือ"); the focused field becomes the
  edit-command target (`last_field`). (2) Cross-script skeleton budget
  tightened len//3 → len//4 — "กดตรงช่องค้นหา" (kkkn) can no longer reach
  "เอเจนต์ของฉัน" (jnkkkn, ed 2); every intended cross-script hit sits at
  ed ≤ 1 and stays green. (3) Fill values peel the quoting word "คำว่า"
  ("พิมพ์คำว่าสวัสดี" types "สวัสดี"). Simulator cursor glide 450 ms → 200 ms
  (~quarter-second pointing, no felt delay). Files:
  `services/voice_realtime/ui_control.py`, `pipeline.py`,
  `web/components/voice/VoiceCallWidget.tsx`, `simulatorCursor.ts`; tests
  (pytest 239 green, node 182 green).

- **2026-07-08 — Simulator cursor: the caller sees where the agent acts
  (#6 of the page-agent-parity queue).** Before a voice-driven click / fill /
  edit touches the page, a virtual cursor glides onto the target, pulses,
  and only then does the action execute — the page-agent "SimulatorMask"
  idea. Pure presentation in one new file
  (`web/components/voice/simulatorCursor.ts`): a singleton fixed overlay on
  <body> (survives route changes, `pointer-events: none`, never performs
  actions itself), scrolls off-screen targets into view first, points at the
  entry area of tall textareas rather than their geometric middle, honors
  `prefers-reduced-motion` (jump, no pulse), fades after idle, and is
  disposed on hang-up. `pageContext.ts` gains find-only exports
  (`findClickableByText`, `findFieldElement`) so the widget can point before
  acting while executors stay the only hands. Files: `simulatorCursor.ts`
  (new), `pageContext.ts`, `VoiceCallWidget.tsx`; node test for the pure
  pointing math (node 182 green).

- **2026-07-08 — Edit-by-voice: undo typing ("ล้างช่อง X", "ลบคำสุดท้าย").**
  The correction half of fill-by-voice — typed wrong or changed your mind,
  fix it by voice. Two curated ops: clear the whole field, or remove the
  last word (client-side `removeLastWord` uses `Intl.Segmenter` for Thai's
  space-less word boundaries, whitespace fallback elsewhere). A bare command
  ("ลบคำสุดท้าย") applies to the last field filled this call — the pipeline
  remembers it in nav_state, Voice-Control style; before any fill it asks
  honestly which field. Deterministic and silent (scroll's reasoning: rapid-
  fire, effect visible). Guard: a remainder that names no field ("ลบโน้ตนี้",
  "ล้างจานให้หน่อย") falls through — deleting content elsewhere stays behind
  click/confirm. Prompt: the LLM is told the system owns erase commands and
  that re-filling replaces — never claim text was deleted. Files:
  `services/voice_realtime/ui_control.py`, `pipeline.py`, `narration.py`,
  `web/components/voice/pageContext.ts`, `VoiceCallWidget.tsx`; tests
  (pytest 233 green, node 181 green).

- **2026-07-08 — Mode-command fuzzy anchor compares sound classes, not glyphs
  (the "บิดหมดเลขา" trap).** Live: "ปิดโหมดเลขา" arrived as "บิดหมดเลขา" —
  within the fuzzy edit budget, but the matcher's first-char anchor required
  an exact glyph match (บ ≠ ป), so the exit command was typed into chat as
  dictation text and the caller was trapped in secretary mode. The anchor now
  compares onset *sound classes* (Thai→Latin homophone fold + voiced→voiceless:
  บ/ป, ด/ต, ก/ค one class); dictation sentences that merely start with the
  same sound ("บิดามารดา…", "ปิดเทอม…") still fall through on the edit budget.
  File: `services/voice_realtime/ui_control.py`; regression params in
  `tests/services/voice_realtime/test_ui_control.py` (pytest 219 green).

- **2026-07-08 — Fill values corrected against the screen's vocabulary (the
  "ลาวไทย" gap).** STT transliterates on-screen names (~always: spoken
  "LAWs_thai" arrives as "ลาวไทย"), and typing the transcript verbatim put
  the garble into the form. New `resolve_fill_value` (ui_control): a
  dropdown's value MUST resolve to one of its streamed options (shared
  cross-script tiers; no match → honest "ช่องนั้นไม่มีตัวเลือกตามที่พูดครับ"
  instead of a silent non-select behind an ack); a plain input keeps free
  text verbatim EXCEPT when it uniquely names something visible on screen
  (case-insensitive exact or consonant-skeleton hit vs buttons/cards), in
  which case the on-screen spelling is typed. Applied on all three paths
  (deterministic shortcut, `ui_fill` tool result, LLM tool-call forwarding)
  so speech and action never disagree. Files:
  `services/voice_realtime/ui_control.py`, `pipeline.py`, `narration.py`;
  tests in `tests/services/voice_realtime/test_ui_control.py` (pytest 217
  green).

- **2026-07-08 — Fill-by-voice: type into / pick dropdown options in visible
  form fields (#2 of the page-agent-parity queue).** "พิมพ์ กฎหมายแรงงาน
  ในช่องค้นหา" now types into the search box; "เลือก ไทย ในช่องภาษา" picks a
  native dropdown option. Same see→name→act trust model as click-by-name:
  the client streams the visible fields (`ui_context.fields` — labels from
  aria-label/<label>/placeholder/name; a <select>'s options folded in behind
  the " (เลือกได้:" marker; password/hidden/checkbox/radio/file inputs never
  listed, values never read), the server verifies the caller-named field
  against that list (shared `_resolve_spoken_name` tiers, refactored out of
  the click resolver), and the client sets the value through the native
  prototype setter + input/change events so React controlled inputs accept
  it (the page-agent framework-patch lesson). Two paths: deterministic
  shortcut (`match_fill_intent`, verb + explicit "ช่อง" marker, value keeps
  original casing) and the `ui_fill` LLM tool for free phrasings — both
  converge on one `ui_action fill_field` frame. Filling never submits;
  pressing a button stays a separate (click) step with its own danger rung.
  Frame-size guard: the fields list is char-budgeted client-side (120/entry,
  1500 total) so a dropdown-heavy page can't push the ui_context frame past
  the server's 8K drop threshold. Also made the manifest-parity node test
  quote-agnostic (prettier's repo style uses single quotes). Files:
  `services/voice_realtime/ui_control.py`, `pipeline.py`, `narration.py`,
  `web/components/voice/pageContext.ts`, `VoiceCallWidget.tsx`; tests in
  `tests/services/voice_realtime/test_ui_control.py` (pytest 212 green),
  `web/tests/voice-page-context.test.ts`, `voice-manifest-parity.test.ts`
  (node 180 green).

- **2026-07-08 — Action matcher tolerates STT garbles (voice-scroll gap fix).**
  Live gap: "เลื่อนลง" worked only when STT transcribed it letter-perfect —
  "เลือนลง" (tone mark dropped), "เลื่อน ลง" (space inserted), "เลื่อนหลง"
  (one phonetic edit) all fell past the shortcut to the LLM, which sometimes
  acked "ได้ครับ" without calling the tool (nothing moved). `_ACTION_PATTERNS`
  matching now folds text and patterns through the same phonetic normalisation
  the navigation verbs already use (homophones + tone marks + spaces), plus a
  start-anchored edit-distance-1 pass for patterns ≥5 folded chars — anchored
  to the utterance head so mid-sentence sound-alikes ("เอาเลื่อยลงมา…") stay
  out of reach; bare-"เลื่อน" and ambiguity guards unchanged. Prompt hardening
  for the residue: the no-ack-without-tool-call rule now covers listed
  *actions* (was navigation/click only), and the voice persona asks a short
  clarifying question when a turn is an out-of-context short fragment (whole-
  word mishears like "เริ่มต้น") instead of guessing a topic and lecturing.
  Files: `services/voice_realtime/ui_control.py`, `pipeline.py`; regression
  tests in `tests/services/voice_realtime/test_ui_control.py` (9 new params).

- **2026-07-08 — Card labels: first text chunk, not the whole card.** Second
  half of the "กด LlamaIndex ไม่เจอ" gap: the Knowledge-Center engine cards
  are `<button>`s whose title is a plain `<span>` (no heading, no aria-label),
  so `clickableLabel` fell back to the card's ENTIRE text ("LlamaIndex
  พร้อมใช้งาน Local vector retrieval…") — unmatchable by voice. Labels longer
  than 40 chars now fall back to the element's first rendered text chunk (the
  visible title), via a TreeWalker. Client-side only (refresh, no server
  restart). File: `web/components/voice/pageContext.ts`.

- **2026-07-08 — Skeleton sharpened for mixed-script garbles ("ลามะ index",
  "ลาวไทย").** Live gaps from the Knowledge Center page: STT rendered
  "LlamaIndex" as "ลามะ index" and "LAWs_thai" as "ลาวไทย". Research
  (hotword-retrieval fuzzy matching, arXiv 2512.21828; code-switching
  normalization, AdaCS 2501.07102) confirms the textbook fix is a
  normalization layer over the known on-screen vocabulary — true ASR biasing
  needs recognizer hooks Web Speech doesn't expose (deferred to server STT).
  Sharpened `_consonant_skeleton`: drop `h` (digraph residue: th/ph) and the
  semivowel `y`/ย (written inconsistently across transliteration — ไทย vs
  thai), fold g→k; จ/j kept as a real consonant. All four live garbles now
  hit (ลามะ index, ลาวไทย, กราฟแรก→GraphRAG, เพจ index→PageIndex) with every
  earlier case regression-locked. File: `services/voice_realtime/ui_control.py`.

- **2026-07-08 — Click matching crosses scripts (loanwords).** Live gap: the
  screen says "เพอร์โซนา" but STT romanised the caller's word to "persona" —
  different scripts, so exact/substring/Thai-phonetic tiers all miss. New
  final tier in `resolve_click_target`: compare Latin *consonant skeletons*
  (Thai consonants transliterated, karan-silenced ones dropped, vowels — the
  unstable part of transliteration — ignored, sound-alike Latin letters
  folded): เพอร์โซนา→psn vs persona→prsn, distance 1 → hit. Works both
  directions (Thai speech vs English UI) and covers the network/เน็ตเวิร์ก
  family. Only consulted when every same-script tier found nothing; the
  ambiguity guard still applies. File: `services/voice_realtime/ui_control.py`.

- **2026-07-08 — `ui_click`: the LLM can now press visible buttons too.**
  Click gained the same ladder navigation already had: phrasings the
  deterministic shortcut doesn't recognise ("เปิดประวัติแชต",
  "เลือกสมุดบันทึก") used to dead-end — the LLM understood but had no tool to
  act. New `UIClickTool` (registered runtime like `ui_navigate`): the
  capability injects the turn's streamed `ui_context` into the tool's kwargs,
  so its result is computed from the same `resolve_click_target` the pipeline
  uses — speech and action cannot disagree. Safe hit → pipeline forwards
  `ui_action click_element` (client re-validates); dangerous hit → NOT
  pressed, the existing spoken-confirmation state is armed and the LLM asks;
  miss/ambiguous → the tool result orders honesty ("do NOT claim anything was
  pressed"). System block teaches the press rules (must call the tool, never
  choose a button the caller didn't name). Files:
  `services/voice_realtime/ui_control.py`, `pipeline.py`; tests in
  `test_ui_control.py` (174 green).

- **2026-07-08 — Click matcher: leading connectives no longer leak into the
  name.** Live gap: "กดที่ประวัติแชท" extracted the name as "ที่ประวัติแชท", so
  even the phonetic tier (which handles the ท↔ต mismatch against the real
  "ประวัติแชต" card by itself) never got a clean string to match. The matcher
  now peels leading connectives (ที่/ตรงที่/ตรง/ปุ่ม/การ์ด/เมนู/ลิงก์) after the
  click verb, mirroring the existing trailing-politeness peel. The verbatim
  live utterance is a regression test. File:
  `services/voice_realtime/ui_control.py`.

- **2026-07-08 — Click-by-name now covers links and cards, not just
  `<button>`.** Settings-hub cards ("Network", "Models"…) are `<Link href>`
  around a heading — invisible to the old `button/[role=button]` selector, so
  "กดปุ่ม Network" was an honest miss. New shared `visibleClickables()`
  collector in `pageContext.ts`: selector adds `a[href]`; labels prefer
  aria-label → inner heading (so a card reads as "Network", not its whole
  body text); main-content clickables are listed before sidebar/nav links so
  page actions win under the caps; and BOTH the streamed `buttons` context
  and the click executor use this one collector, so a name the server
  approves is guaranteed pressable. File: `web/components/voice/pageContext.ts`.

- **2026-07-07 — Click-by-name: press a visible button the caller names.**
  The middle rung between curated actions and a full page-agent, completed
  from the previous session's in-progress work: the caller points ("กดปุ่ม
  สร้างโน้ตใหม่"), the system only verifies that name against the buttons the
  page actually shows right now and presses exactly that — no LLM ever
  chooses a button. Server: `ui_context` now carries a structured `buttons`
  list (≤40, sanitised); `match_click_intent` (utterance must START with a
  click verb, question words excluded) + `resolve_click_target` (exact →
  substring → phonetic-fuzzy tiers; ambiguous → "พูดชื่อเต็มอีกครั้ง",
  missing → honest "ไม่เห็นปุ่มชื่อนั้นบนจอ"); dangerous names (ลบ/ยกเลิก/
  รีเซ็ต/logout…) require a spoken yes via the existing confirm rung before
  the press. Client: `clickVisibleByText` presses only elements outside the
  widget's own panel that were visible — the same set the context reported.
  Files: `services/voice_realtime/ui_control.py`, `pipeline.py`,
  `narration.py`, `web/components/voice/pageContext.ts`,
  `VoiceCallWidget.tsx`; tests in `tests/services/voice_realtime/
  test_ui_control.py` (pytest 166 green, node 178 green).

- **2026-07-07 — Voice manifest completed + parity test.** The hand-written
  `UI_PAGES` table had drifted from the app's real routes: `/partners` and
  `/playground` were missing, so the caller was told those pages don't exist.
  Added both, and added `web/tests/voice-manifest-parity.test.ts` — a node
  test that walks `web/app` for top-level `page.tsx` routes (route groups,
  optional catch-alls handled) and fails when the manifest and the real
  routes disagree in either direction, so the table can never drift silently
  again (also guards future upstream syncs that add/rename pages).

- **2026-07-07 — Voice now sees the caller's screen (live `ui_context`).**
  Asking "หน้านี้มีเมนู/ปุ่มอะไรบ้าง" used to get a guess — the model only knew
  the manifest's page ids/labels, nothing about what the page shows. The
  widget (root layout = it sees every page's DOM) now serialises a read-only
  outline of the visible screen — title, headings, nav links, tabs, buttons;
  its own panel excluded; input *values* never read — and streams it as a new
  `ui_context` control frame on connect and before every turn (pages change
  under a live call). Server side: `sanitize_ui_context()` (size caps,
  control-char strip), stored on `VoiceSession`, threaded through the
  pipeline into turn metadata, and injected by `VoiceUICapability` as a
  "Current screen" system-block section with a "describe only what is listed"
  rule. Read side only — acting on the page still goes exclusively through
  the manifest whitelist. E2E-verified live: fabricated button names streamed
  in context came back verbatim in the spoken answer. New files:
  `web/components/voice/pageContext.ts` (pure formatter node-tested in
  `web/tests/voice-page-context.test.ts`); touched: `VoiceCallWidget.tsx`,
  `services/voice_realtime/ui_control.py`, `session.py`, `pipeline.py`,
  `api/routers/voice_realtime.py`. Also repaired
  `tests/api/test_voice_realtime_ws.py`, which had been failing since the
  greeting change (its `FakeSession` lacked `greet()`) — the greeting commit
  only ran the `tests/services/voice_realtime` suite.

- **2026-07-07 — Fix: "ตอนนี้อยู่หน้าไหน" answered from stale navigation
  history.** Live testing found that after voice-navigating and then clicking
  to another page by hand, the model reported the last *steered* page — the
  fresh `ui_context` was streamed correctly, but its raw `Path: /notebook`
  line lost to the louder "ไปหน้า settings → ได้เลยครับ" turns in history.
  Two-sided fix: the summary now leads with a plain-words identity line
  ("หน้าปัจจุบัน: หน้าสมุดโน้ต (/notebook)", label resolved from `UI_PAGES`),
  and the `voice_ui` "Current screen" block gains a STALENESS RULE — the
  caller can navigate by hand at any moment, so for "which page am I on" only
  this section counts, never past navigation turns. Files:
  `web/components/voice/pageContext.ts`, `VoiceCallWidget.tsx`,
  `services/voice_realtime/ui_control.py`.
  **Round 2 (same day):** the system-block rule alone still lost — reproduced
  live: a recency-biased model answered from the adjacent navigation turns in
  history rather than the far-away system block. Decisive fix: the
  current-page identity line now also rides *the user message itself* per
  turn (`_screen_turn_note()` in `pipeline.py`, same mechanism as
  `_VOICE_TURN_REMINDER` — history commits the bare transcript, so it never
  leaks into later turns). E2E scenario (voice-nav to settings → hand-click
  to notebook → "ตอนนี้อยู่หน้าไหน") now passes 2/2 against the live server.
  **Round 3 — made model-independent:** prompt weighting can regress when
  the LLM changes, so "ตอนนี้อยู่หน้าไหน" joined the deterministic intent
  ladder alongside stop and navigation: `match_where_am_i()` (exact after
  stripping polite particles; compound phrasings still fall to the LLM) +
  `spoken_page_name()` answer straight from the streamed context — no LLM
  round at all, ~1 s vs ~10 s, correct on any model. The `ui_context` frame
  gains a `page` field (the manifest label of the current page) so the
  answer needs no parsing. The LLM path with the turn note stays as the
  fallback for unmapped pages and paraphrases. Files:
  `services/voice_realtime/ui_control.py`, `pipeline.py`,
  `web/components/voice/pageContext.ts`.

- **2026-07-07 — Garbled/unclear navigation now confirms instead of
  ack-without-action.** Live log showed two failure shapes: STT garbling the
  verb ("ไฟหน้าหน่วยความจำ" for ไปหน้า…) and unlisted aliases
  ("ศูนย์ความรู้") — both fell to the LLM, which sometimes said "ได้เลยครับ"
  *without navigating*. Three-layer fix, all deterministic: (1) common STT
  garbles of "ไปหน้า" ("ไฟหน้า", "ใบหน้า") are normalised before matching, so
  those become direct commands; (2) manifest labels gain the aliases callers
  actually say ("หน่วยความจำ", "ศูนย์ความรู้"); (3) a **confirm-first rung**
  in the intent ladder — a short utterance that names exactly one page but
  lacks a verb (and isn't a question) gets "คุณหมายถึงให้เปิด X ใช่ไหมครับ";
  a bare "ใช่/ครับ" then executes the navigation, "ไม่" acknowledges, and
  anything else clears the pending question and is processed normally
  (state lives in session-owned `nav_state`; both ask and confirm are no-LLM
  turns through the fixed-line TTS cache). The `voice_ui` system block now
  also hard-forbids a bare acknowledgement — for unmappable navigation the
  model must ask, never say ได้เลยครับ on its own. Turn routing now logs
  which ladder rung handled each utterance (`voice rung=…`). E2E: all three
  failing log lines now navigate (garble → direct, alias → direct, verbless
  → confirm → ใช่ → navigate). Files: `services/voice_realtime/
  ui_control.py`, `pipeline.py`, `narration.py`, `session.py`,
  `web/components/voice/VoiceCallWidget.tsx`.
  **Round 2 — the garble list replaced by a general fix (two industry-style
  layers):** (1) *Phonetic fuzzy verb slot* — the hardcoded "ไฟหน้า/ใบหน้า"
  pairs are gone; the matcher now takes the 2–4 characters before the page
  word, normalises Thai homophone letters (ใ→ไ, ณ→น, ศ/ษ→ส, …) and tone
  marks, and accepts edit distance ≤ 1 from any navigation verb — so
  "ไอหน้า", "ไผ่หน้า" and every future variant work without new entries
  (guarded by the unique-page + short-utterance + question-word checks, and
  `match_navigation_intent` gains the question guard too). (2) *N-best
  rescue* — the widget now requests `maxAlternatives = 3` from Web Speech
  and, when the top hypothesis is nav-adjacent (mentions a page) but fails
  the command shape while a runner-up passes it AND names a known page, the
  runner-up is sent instead; ordinary conversation always keeps rank #1
  (`web/components/voice/speechAlternatives.ts`, node-tested). E2E:
  never-hardcoded garbles now navigate correctly. Files:
  `services/voice_realtime/ui_control.py`,
  `web/components/voice/speechAlternatives.ts` (new),
  `VoiceCallWidget.tsx`, `web/tests/voice-speech-alternatives.test.ts`.

- **2026-07-07 — First curated in-page actions: voice can now DO things, not
  just navigate.** The web widget declares its first `actions` whitelist —
  `new_chat` (สร้างแชทใหม่), `open_kb <ชื่อ>` (เปิดคลังความรู้ตามชื่อ),
  `go_back` (ย้อนกลับ) — and `executeUiAction` gains their handlers. Two
  integration seams: `new_chat` needs the workspace session store, which the
  root-mounted widget can't reach, so a new `VoiceActionBridge` (own file,
  one-line mount inside the workspace provider) executes it with the real
  store functions (cancel streaming turn → new draft session → /home); when
  no bridge is mounted (caller on a non-workspace page) the widget falls
  back to plain `/home` navigation, which is a fresh draft session there by
  design. `open_kb` navigates to `/knowledge?kb=<name>` — E2E showed the
  model calling it with an empty argument, fixed by an ARGUMENT RULE in the
  tool definition + system block (pass the spoken/on-screen name verbatim;
  verified live: 'เปิดคลังความรู้ LAWs_thai' → `open_kb('LAWs_thai')`).
  Fixed-shape action commands ("สร้างแชทใหม่", "ย้อนกลับ") also joined the
  deterministic ladder (`match_action_intent`, declared-actions-only,
  page-naming utterances win first) after E2E caught the LLM coin-flip
  acknowledging go_back without acting. E2E 3/3. Files:
  `web/components/voice/VoiceActionBridge.tsx` (new), `VoiceCallWidget.tsx`,
  `web/app/(workspace)/layout.tsx` (2-line mount),
  `services/voice_realtime/ui_control.py`, `pipeline.py`.

- **2026-07-07 — Secretary (dictation) mode: "เปิดโหมดเลขา" and the voice
  types into the real chat.** Explicit moded dictation in the Dragon /
  macOS-Voice-Control tradition, per design review of how production systems
  do it: enter with "เปิดโหมดเลขา/โหมดพิมพ์" (deterministic matcher, like
  stop) and from then on EVERY utterance is sent verbatim into the on-screen
  chat session — `ui_action type_in_chat` → `VoiceActionBridge` →
  `UnifiedChatContext.sendMessage()` — so answers render fully (markdown,
  citations) and persist in real history; the voice stays silent (the screen
  is the responder). Zero LLM per dictated turn. Mode discipline follows the
  classic lessons: exit commands ("ปิดโหมดเลขา/ออกจากโหมด" + "หยุด") stay
  active inside the mode so the caller can never be trapped; an always-on
  📝 indicator shows the mode on the widget (mode-error mitigation); the mode
  dies with the call; entering the mode auto-navigates to /home since that is
  where typing lands. Nav-shaped sentences said while dictating are typed,
  not executed (mode owns everything — E2E-verified 5/5 against the live
  server, including 'ไปหน้า settings' typed in-mode and navigating again
  after exit). State rides the session-owned `nav_state`; server announces
  boundaries with cached fixed lines and a new `voice_mode` frame. Files:
  `services/voice_realtime/ui_control.py`, `pipeline.py`, `narration.py`,
  `web/components/voice/VoiceCallWidget.tsx`, `VoiceActionBridge.tsx`.
  **Round 2 — two gaps from live testing:** (1) *Trapped in the mode*: STT
  garbled the exit command ("ปิดโหมดเลขา" heard as "ปิดหมดเรขาค"), which
  therefore got typed into the chat instead of exiting — the exact trap the
  design warned about. Mode commands now get the phonetic fuzzy pass too
  (ร→ล joined the homophone table; length-scaled edit budget, first-char
  anchor, and an on/off tie declines rather than guessing) — matching the
  exit generously beats trapping the caller. (2) *Silent off-page redirect*:
  dictating after clicking away from the chat page only showed a widget
  text note; the server now uses the streamed `ui_context.path` to detect
  it, speaks a short "ตอนนี้ไม่ได้อยู่หน้าแชทครับ ผมพาไปแล้ว พูดอีกครั้งนะครับ"
  and steers back — deterministic, before any typing. E2E extended to 6/6
  including the verbatim live garble. Known deferral: answering the chat's
  interactive ask-user prompts by voice while dictating (typed messages
  don't reach a pending option picker). Files:
  `services/voice_realtime/ui_control.py`, `pipeline.py`, `narration.py`.
  **Round 3 — re-entry failed on a heavier garble:** live round 2 heard
  "เปิดโหมดเลขา" as "เปิดหมดเลยค่ะ" — after politeness-stripping ("เลย" is a
  filler but was also the mangled "เลขา") the residue "เปิดหมด" sat outside
  the fuzzy budget of the full-length forms, fell to the LLM, which then
  (a) *claimed* the mode was open and (b) answered a stale dictated
  question. Three fixes: short canonical forms "เปิดโหมด/เข้าโหมด" joined
  the on-set (bare "open the mode" is unambiguous — there is only one mode —
  and keeps name-destroying garbles within budget); a VOICE MODES honesty
  rule in the system block (the LLM has no mode control; a mode request
  reaching it means the system missed it — ask the caller to repeat, never
  claim a mode switched); and `VoiceSession._commit` now only records full
  exchanges — a reply-less dictation turn no longer leaves an unanswered
  user line in voice history for a later LLM turn to answer out of nowhere.
  E2E extended to 9/9 (both live garbles verbatim, round-2 re-entry, no
  stale-answer leakage). Files: `services/voice_realtime/ui_control.py`,
  `session.py`.
  **Round 4 — N-best rescue extended to mode commands:** the widget's
  runner-up promotion previously only recognised the navigation shape, so a
  garbled top hypothesis for "เปิดโหมดเลขา" was sent as-is even when the
  correct phrase sat in hypothesis #2. `pickUtterance` now also knows the
  mode-command shape (เปิด/ปิด/ออกจาก + โหมด), gated on mode-adjacent
  fragments in the top hypothesis (โหมด/หมด/เลขา/เรขา) so ordinary speech
  is still never rewritten. Both live garbles covered by node tests.
  Files: `web/components/voice/speechAlternatives.ts`,
  `web/tests/voice-speech-alternatives.test.ts`.

- **2026-07-07 — Fix: "ไปหน้าหลัก" said ได้เลยครับ but went nowhere.** Three
  gaps closed: the widget's chat-page label gains the aliases callers
  actually say ("หน้าหลัก / หน้าแรก / home") and points at `/home` directly;
  the shortcut matcher keeps unstripped label tokens (so the alias matches
  "ไปที่หน้าหลัก") while excluding generic words like bare "หน้า" that would
  collide every page into ambiguity; and the `voice_ui` system block now
  forbids answering a navigation request with an acknowledgement alone —
  the pinned "ได้เลยครับ" must come *with* the tool call, never instead of
  it. Files: `web/components/voice/VoiceCallWidget.tsx`,
  `services/voice_realtime/ui_control.py`.

- **2026-07-07 — Stop is a control command, not conversation.** "หยุดพูดก่อน"
  used to reach the LLM, which replied with a paragraph about having stopped
  talking. Stop/quiet commands (exact match after stripping polite particles —
  "วันหยุดคืออะไร" still reaches the LLM) now short-circuit like navigation:
  the session has already cancelled the speaking turn, so the reply is a
  cached one-syllable "ครับ" and no LLM turn starts. Also taught
  `VOICE_STYLE_DIRECTIVE` to never end replies with generic offers of further
  help ("หากมีคำถามเพิ่มเติม…") — a live call doesn't need them. Files:
  `services/voice_realtime/pipeline.py`, `narration.py`.

- **2026-07-07 — Closing the navigation-reliability gap (two layers).** The
  same "ไปหน้า settings" sometimes navigated and sometimes just talked — a
  sampling coin-flip at chat's default temperature. Layer 1: the voice turn's
  scoped LLM config now also sets `temperature=0.3` (voice-only; chat
  untouched). Layer 2: a deterministic navigation shortcut
  (`ui_control.match_navigation_intent`) — short utterances with a nav verb +
  "หน้า/page" + exactly one manifest page match execute the `ui_action`
  directly, skipping the LLM round entirely (100% deterministic and faster);
  ambiguous/compound requests still go to the LLM. The shortcut's ack
  ("ได้เลยครับ") and the greeting now go through a synthesise-once
  `_FIXED_LINE_CACHE`, so repeated fixed lines cost zero TTS latency. Files:
  `services/voice_realtime/pipeline.py`, `ui_control.py`, `narration.py`.

- **2026-07-07 — Post-navigation reply pinned to one phrase.** Live testing
  showed two leaks: (1) the generic "รอสักครู่ฯ" heard on navigation was the
  *pipeline's* default filler triggered by the tool round's `PROGRESS`
  call-status event — killed by the "earned wait" change below once the
  server restarts; (2) Gemini watered the "three words max" instruction down
  to polite paragraphs — the `voice_ui` system block and `ui_navigate` tool
  result now pin the reply to exactly one allowed phrase ("ได้เลยครับ"),
  validated 3/3 runs on gemini-3.1-flash-lite. File:
  `services/voice_realtime/ui_control.py`.

- **2026-07-07 — "Please wait" must be earned by a real wait.** Dropped the
  pre-emptive generic filler ("รอสักครู่นะครับ กำลังดำเนินการให้อยู่") that spoke
  the moment *any* unmapped tool started — many finish in under a second, and
  announcing a wait that doesn't happen sounds broken. Now only known-slow
  tools (rag / web_search / code…) get an immediate specific cue; everything
  else stays silent, and the existing 8 s watchdog speaks the (reworded)
  generic wait line only when the silence is real. Files:
  `services/voice_realtime/narration.py`, `pipeline.py`.

- **2026-07-07 — Natural speech around UI navigation.** With a fast LLM the
  screen now changes *before* the voice arrives, but the model still narrated
  politely ("รอสักครู่นะครับ กำลังพาไป…") — announcing an action the caller
  already saw. The `voice_ui` system block and the `ui_navigate` tool result
  now tell the model the change is already visible: say nothing or confirm in
  at most three words, never "wait a moment", never describe the destination.
  File: `services/voice_realtime/ui_control.py`.

- **2026-07-07 — Latency: reasoning disabled for voice turns (TTFT 21 s → <1 s).**
  Diagnosis: ~85–90% of call latency was the LLM's hybrid-thinking phase
  (Qwen3.5/Nemotron reason for 20 s+ before the first token), not the voice
  pipeline. Fix: `run_text_turn` now wraps each voice turn in a scoped LLM
  config (`set_scoped_llm_config`, task-local ContextVar — the same public
  seam `model_selection` uses) with `reasoning_effort="minimal"`, the
  codebase's portable "thinking off" value (top-level for NVIDIA NIM —
  verified live: TTFT 0.8–5.8 s on qwen3.5-122b vs 21–64 s with thinking;
  extra-body flags for DeepSeek/DashScope-style providers). Chat keeps full
  reasoning — the override never escapes the voice turn's task. Zero
  upstream edits. File: `services/voice_realtime/pipeline.py`; test in
  `tests/services/voice_realtime/test_pipeline.py`.

- **2026-07-07 — Spoken greeting on call pickup.** The call now answers with
  "สวัสดีครับ มีอะไรให้ผมช่วยไหมครับ" the moment the WebSocket connects:
  `speak_greeting()` in `services/voice_realtime/pipeline.py` synthesises the
  line through the same TTS catalog and emits it as a normal audio frame pair
  + `assistant_text` (so lip-sync, echo-guard fingerprint and the chat log all
  treat it like a spoken turn); `VoiceSession.greet()` records it in history
  so the model knows it already said hello. TTS failure = silent pickup, never
  a dropped call. Line lives in `narration.GREETING_LINE`; router awaits the
  greeting right after `accept()`. Tests added in `test_pipeline.py`.

- **2026-07-07 — Web widget: mascot no longer idles in a slow spin.** The
  constant yaw drift inherited from the fullscreen prototype looked wrong in
  the small corner pane; the figure now faces the user at rest, still spins
  while `searching`, and eases back to front (nearest full turn) afterwards.
  File: `web/components/voice/VoiceCallWidget.tsx`.

- **2026-07-07 — Voice page-navigation wired into the web widget.**
  `VoiceCallWidget` now declares the app's real pages (chat / knowledge /
  notebook / memory / agents / book / co-writer / space / settings / profile)
  as the `ui_manifest` whitelist on connect, and executes incoming
  `ui_action` frames via the Next router (`router.push`), re-validating the
  target against the same table first. Say "พาไปหน้า settings" mid-call and
  the app navigates while the call continues (the widget lives in the root
  layout). Server side unchanged — same `ui_navigate` seam the mock bench
  proved. File: `web/components/voice/VoiceCallWidget.tsx`.

- **2026-07-07 — Web widget mounted globally (root layout).** The widget was
  mounted in the workspace layout, so navigating to another route group
  unmounted it mid-call (button gone, call dropped). Moved the two mount
  lines from `web/app/(workspace)/layout.tsx` to `web/app/layout.tsx` — the
  root layout persists across client-side navigation, so the call (and the
  future voice page-navigation) survives on every page.

- **2026-07-07 — Web widget: two more echo defenses (abort + fingerprint).**
  The time-based mute guard alone still leaked: Web Speech buffers what it
  hears during playback and delivers the final result *after* the mute
  window. The widget now (1) aborts recognition the instant bot audio starts
  (discarding the buffer) and restarts it 800 ms after playback ends, and
  (2) drops any recognised utterance whose normalised text matches what the
  bot recently spoke (Botnoi's textFingerprint technique). File:
  `web/components/voice/VoiceCallWidget.tsx`.

- **2026-07-07 — Voice call in the real web app (branch
  `feat/voice-web-integration`).** New
  `web/components/voice/VoiceCallWidget.tsx`: a floating 📞 button in the
  workspace; pressing it fades in a full-screen mascot overlay
  (Botnoi-WebAvatar style, 500 ms opacity transition; hang-up fades out then
  unmounts). Ports the prototype call client natively into React: WS to the
  same-origin `/api/v1/voice/ws` (via `wsUrl` + web proxy), browser Web-Speech
  STT with the echo mute-guard, queued TTS playback with real-amplitude
  lip-sync, typed barge-in, and the 3D mascot (Three.js loaded from CDN on
  first open — no bundle dependency). Upstream touch limited to two mount
  lines in `web/app/(workspace)/layout.tsx`. Known deferral: UI strings are
  Thai literals pending i18n keys (2 lint warnings). Revised same day: the
  full-screen overlay became a Botnoi-style floating corner layer — the
  mascot renders on a transparent canvas (no background/fog/floor) in a
  ~330×240 pane above a compact chat panel at the call-button corner, the
  page underneath stays interactive, and open/close fades+slides.

- **2026-07-07 — Mock bench: mic-mode selector + headphone barge-in.**
  `mock-app.html` gains the same STT modes as `call.html`: browser (Web
  Speech) and server STT (MediaRecorder + energy-VAD with noise-floor
  calibration, ported from `call.html`) — server mode allows voice barge-in
  (must be ~2.5× louder than the gate while the bot speaks). New 🎧
  "headphones" checkbox for browser mode: with no speaker-to-mic echo the
  mute guard is bypassed and speaking immediately barges in. File:
  `voice_prototype/static/mock-app.html`.

- **2026-07-06 — Fix: browser-STT echo loop (bot answering its own voice).**
  In browser-STT mode the mic hears the bot's TTS, Web Speech transcribes it
  ("สวัสดีครับ" → new turn → reply → …), looping forever and burning LLM quota.
  `call.html` + `mock-app.html` now drop recognition results while bot audio
  is playing and for an 800 ms tail after it ends (`muteUntil` guard); typing
  now barges in instead (voice barge-in remains in the calibrated server-STT
  mode). Files: `voice_prototype/static/call.html`, `mock-app.html`.

- **2026-07-06 — Voice-driven UI control (Botnoi-WebAvatar style) + mock test
  bench.** A caller can now steer the on-screen UI by voice ("ไปหน้า settings",
  "เปิด KB กฎหมาย"). New `deeptutor/services/voice_realtime/ui_control.py`:
  the client declares a steerable-UI whitelist via a `ui_manifest` WS control
  frame (sanitised, ≤64 targets); its presence activates `VoiceUICapability`
  (appended to `LOOP_CAPABILITIES` at runtime) which mounts a new
  `ui_navigate` tool (registered through the public `ToolRegistry.register()`)
  with a system block listing the allowed targets. The voice pipeline forwards
  the tool's `TOOL_CALL` to the client as a `{"type": "ui_action", ...}` frame
  (no spoken filler — near-instant); the page executes and re-validates it.
  Plumbing in `pipeline.py` / `session.py` / `api/routers/voice_realtime.py`
  (all fork-owned; zero upstream edits). Test bench:
  `voice_prototype/static/mock-app.html` (`/mock`) — a mock DeepTutor UI
  (Chat / Knowledge Base / Mastery / Settings + `open_kb` action) with an
  embedded call panel, so voice-controls the fake app before any `web/`
  wiring. Tests: `tests/services/voice_realtime/test_ui_control.py`.

- **2026-07-06 — Prototype folder slimmed to the static call host.** The
  standalone STT→LLM→TTS pipeline in `voice_prototype/` was superseded by the
  production layer (`deeptutor/services/voice_realtime/`) and had been
  untouched since 2026-07-02; deleted `pipeline.py`, `providers.py`,
  `selftest.py`, `tests/`, and `.env.openrouter.example`. `config.py` /
  `requirements.txt` / `.env.example` shrank to just the static host's
  HOST/PORT (fastapi + uvicorn), and `README.md` was rewritten for what the
  folder is now: a thin `http://localhost` origin serving `static/call.html`,
  which talks to DeepTutor's `/api/v1/voice/ws` directly.

- **2026-07-06 — Removed the iApp STT/TTS integration.** The iApp account ran
  out of credit and its published API docs didn't match the live endpoints
  (reported to the vendor), so the adapter was dead weight. Deleted
  `deeptutor/services/voice/adapters/iapp.py` + `tests/services/test_voice_iapp.py`,
  its registry entries in `deeptutor/services/voice/adapters/__init__.py`, and
  the `iapp` specs this fork had added to TTS/STT provider tables in
  `deeptutor/services/config/provider_runtime.py` (shrinking our diff against
  upstream). Stale iApp mentions in voice_realtime comments/tests reworded.
  Active voice chain is unchanged: Groq whisper STT + custom PTM TTS.

- **2026-07-06 — Fix: "searching" filler no longer fires on small talk.** The
  chat capability runs an automatic KB seed lookup on *every* turn when a KB is
  attached (`call_id` prefix `chat-kb-seed`, same `call_kind=rag_retrieval` as a
  real LLM-chosen `rag` call), so the call spoke "ขอค้นข้อมูลในเอกสารสักครู่"
  for every utterance. `_tool_starting()`
  (`deeptutor/services/voice_realtime/pipeline.py`) now skips the seed lookup;
  the filler + `searching` mascot state fire only for tools/retrievals the LLM
  actually chose. Test added in
  `tests/services/voice_realtime/test_pipeline.py`. Zero upstream edits.

- **2026-07-02 — Voice RAG + spoken "searching" filler + watchdog.** Toward
  chat parity for the call: `build_voice_context` attaches available knowledge
  bases so `rag` auto-mounts (the model searches only when a question needs it;
  small talk never triggers it). When a tool/retrieval starts — the chat
  capability runs RAG as a stage emitting `PROGRESS(call_kind=rag_retrieval,
  call_state=running)`, not a `TOOL_CALL`, so `_tool_starting()` detects both —
  the pipeline speaks a short Thai filler ("ขอค้นข้อมูลในเอกสารสักครู่นะครับ")
  and sends a `searching` status; a `thinking` status goes out at turn start so
  a slow reasoning model doesn't look frozen. A watchdog pulls events as a
  polled task (never `wait_for(__anext__)`, which cancels the generator into a
  running tool): a quiet gap past the soft limit speaks a reassurance, past the
  hard limit aborts the hung turn. New `narration.py`; mascot gains a spinning
  `searching` state. Zero upstream edits; E2E verified against a real KB.

- **2026-07-02 — Call page: 3D talking mascot with audio lip-sync.** Merged a
  Three.js mascot avatar into `voice_prototype/static/call.html` as the call's
  face (all prior call logic — VAD calibration, barge-in, browser-TTS fallback —
  preserved). The mouth is driven by real state: server TTS audio is routed
  through a WebAudio `AnalyserNode` so it opens by actual amplitude (lip-sync),
  the Web-Speech fallback uses a procedural mouth, and the rim light + head pose
  shift per state (idle / listening / thinking / speaking). Prototype-only,
  outside `deeptutor/`.

- **2026-07-02 — Call page: browser-TTS fallback.** When a turn ends with a
  reply but zero audio frames (server TTS down / out of credit — iApp hit
  `INSUFFICIENT_CREDIT` during testing), `call.html` now speaks the reply via
  the browser's Web Speech synthesis (th-TH voice when available) instead of
  going silent; barge-in cancels the fallback voice too. File:
  `voice_prototype/static/call.html`.

- **2026-07-02 — Voice-mode prompt + guarded STT (turn quality).** All inside
  `deeptutor/services/voice_realtime/` (zero upstream edits): `build_voice_context`
  now injects a VOICE CALL MODE directive (persona slot + a reminder appended to
  the current user message — the persona block alone was ignored) so the brain
  answers in short spoken prose; measured 612-char markdown/LaTeX answer →
  297 chars of clean spoken Thai, turn 45 s → 4.8 s. New `stt_guard.py`:
  vocab-biased `verbose_json` transcription with mean `avg_logprob` confidence
  for the OpenAI-compatible STT cluster (facade fallback for bespoke adapters)
  plus `screen_transcript()` rejecting empties, known Whisper hallucination
  phrases, and low-confidence noise with a speakable Thai error. Tests in
  `tests/services/voice_realtime/test_stt_guard.py` (+ pipeline updates).

- **2026-07-02 — Call page VAD hardening (real-mic feedback).** First live mic
  test hit a feedback loop: fixed VAD thresholds fired on ambient noise, whisper
  hallucinated text from the noise clips, and each false trigger barged-in and
  killed playback (replies arrived but were never heard). `call.html` now
  calibrates the room noise floor at call start, requires 150 ms sustained
  speech before an utterance counts (short pops are discarded client-side),
  raises the barge threshold 2.5× while the assistant is speaking, and surfaces
  playback errors instead of failing silently. File: `voice_prototype/static/call.html`.

- **2026-07-02 — iApp (Thai) STT/TTS adapters, catalog-integrated.** New
  `deeptutor/services/voice/adapters/iapp.py` (`IAppTTSAdapter` + `IAppSTTAdapter`
  — the first bespoke STT adapter): auth via `apikey` header under
  `https://api.iapp.co.th/v3/store`. TTS v3 posts `{text, speed}` (speed clamped
  0.8–1.2) and returns raw PCM s16le 24 kHz reported as
  `audio/pcm;rate=24000;channels=1` so the existing PCM→WAV wrapper containers it;
  STT is multipart upload with the catalog *model* selecting the variant
  (`pro` = accurate / anything else = `base` fast + `chunk_size=7`), joining
  `output[].text` segments. Registered in both adapter registries + added
  `iapp` specs to `TTS_PROVIDERS`/`STT_PROVIDERS`, so "iApp (Thai)" appears in
  Settings > Voice for both services. Tests in `tests/services/test_voice_iapp.py`.
  Live-verified with a real key: **TTS works** (144 KB PCM in ~2.5 s);
  **STT confirmed correct earlier in the day** (round-trip transcript matched)
  but iApp's ASR backend degraded to a persistent 500
  (`'50359' is not a valid task`) during verification — an iApp-side outage
  affecting base + pro alike, independent of request shape.

- **2026-07-02 — GLM hybrid-reasoning support (`LLM_DISABLE_THINKING`).** Verified a
  z.ai (Zhipu) key against the prototype: `glm-4.5-flash` (free) works as the LLM
  brain (Thai OK; measured TTFT ≈2.2 s with thinking off), but z.ai exposes no
  usable STT/TTS models to this account, so audio stays with other providers /
  the browser MVP. Added `build_llm_payload()` in `voice_prototype/pipeline.py` +
  `llm_disable_thinking` in `config.py`: `LLM_DISABLE_THINKING=1` sends the
  Zhipu-style `{"thinking":{"type":"disabled"}}` switch so GLM answers without a
  thinking phase (otherwise voice TTFT balloons); off by default so other
  providers never see the unknown field. Test in `tests/test_pipeline.py`.

- **2026-07-02 — Provider interface + playable MVP.** Added `voice_prototype/providers.py`
  (`BaseSTT`/`BaseTTS` ABCs + OpenAI-compatible adapters covering the TokenMind
  `ptm-asr-1`/`ptm-tts-1` endpoints, streaming-first, + Thai number normalizer) and a
  browser-only MVP (`/mvp` route + `static/mvp.html`) that uses the Web Speech API for
  STT/TTS so it runs with no audio keys — only a DeepTutor OpenAI-compatible LLM
  endpoint. Tests in `voice_prototype/tests/test_providers.py`.

- **2026-06-30 — Production realtime layer landed** (prototype → `deeptutor/`,
  additive). New, isolated for mergeability:
  - `deeptutor/services/voice_realtime/{chunker,vad,pipeline,session}.py` — the
    realtime turn machinery. `pipeline.run_turn()` drives `ChatOrchestrator.handle()`
    directly and consumes `StreamBus` `CONTENT` events, speaking **only** the final
    answer by gating on `metadata.call_kind == "llm_final_response"` (the same rule
    `PartnerRunner` uses); final-answer tokens feed `SentenceChunker` → per-sentence
    TTS so audio for sentence 1 streams while the LLM is still writing. STT/TTS reuse
    the catalog-driven facade (`transcribe_audio` / `synthesize_speech`).
    `VoiceSession` owns per-connection history + a single in-flight turn task;
    a new utterance or `barge` control frame cancels it (barge-in).
  - `deeptutor/api/routers/voice_realtime.py` — WebSocket `/api/v1/voice/ws`
    (binary frame = one utterance, `{"type":"barge"}` = cancel); auth via
    `ws_require_auth` like `unified_ws`. Wired in `deeptutor/api/main.py` (one
    `include_router` line).
  - `deeptutor/services/voice/adapters/bespoke.py` — new **ElevenLabs** and
    **BOTNOI** TTS adapters; registered in `adapters/__init__.py` and added to
    `TTS_PROVIDERS` in `services/config/provider_runtime.py` so both are selectable
    from Settings > Voice (Groq STT + OpenAI/Groq TTS already shipped in the catalog).
  - Tests: `tests/services/voice_realtime/` (chunker, pipeline CONTENT-gating,
    session barge-in), `tests/services/test_voice_bespoke.py` (adapter wire shape),
    `tests/api/test_voice_realtime_ws.py` (WS routing).

## Upstream syncs

_Record each upstream version merged into this fork here._

### v1.4.15 (`bca6f6e9`) — merged 2026-07-01

Merged upstream **v1.4.15** into `main` (merge commit `bdb41011`) from the previous
fork point v1.4.8 (`88c25653`). 210 files, **+13,848 / −3,438** — large but mostly
net-new, non-colliding surface: LightRAG-server integration, user profile + avatar,
admin User-Management, MCP-grant gating, docker/rootless hardening, provider
updates, and a new native **Mattermost** partner channel. Upstream CI green
(Tests #538 on `bca6f6e9`).

- **Conflicts: none.** A pre-merge dry-run (`REPORT_dry_merge_v1.4.15.md`) confirmed
  `git merge` produces zero textual conflicts; all 8 collision files auto-merged
  (`agentic_pipeline.py`, `api/routers/settings.py`, `capabilities/mastery/loop.py`,
  `ConnectedAgents.tsx`, `QuizViewer.tsx`, `ServiceConfigEditor.tsx`, `en/app.json`,
  `zh/app.json`). Sanity-checked `agentic_pipeline.py` — the Thai
  `normalize_agent_language` path + `PARTNER_BUILTIN_TOOL_NAMES` import survived
  intact; `ConnectedAgents.tsx` kept its `th` labels while adopting upstream's
  `listConnectablePartners`/`ConnectablePartner` API.
- **Thai i18n delta (+27 / −2).** Added 27 new `th/app.json` keys (profile/avatar,
  LightRAG server config, partners-assigned, conversation-loading) and removed 2
  orphaned keys upstream deleted (`"PDF limit: {{size}}"`,
  `"PDF files must be smaller than {{size}}."`) → `set(th) == set(en)` = **2668**
  (exact parity). Translations pre-drafted in `th_i18n_delta_v1.4.15.json`, reviewed.
- **`Lang`-needs-`th` sweep:** all 49 changed `.tsx`/`.ts` files clean (0 zh/en-only
  objects); `npm run build` (tsc) is the backstop and passed.
- **New Mattermost channel** (`deeptutor/partners/channels/`) is net-new and
  non-colliding — same extension point as the fork's LINE channel; no user-facing
  Thai strings needed for parity.

Verification: `npm run build` OK (50 pages), `npm run i18n:check` parity OK,
`ruff check`/`format` OK, `pytest` **2670 passed** (10 pre-existing optional-dep
partner failures — telegram/slack/msteams SDKs absent — identical to the v1.4.8
baseline, not a regression), live Thai chat replied in fluent Thai. Detail:
`REPORT_sync_v1.4.15.md` (impact `REPORT_impact_v1.4.15.md`, dry-run
`REPORT_dry_merge_v1.4.15.md`).

> Next sync merge-base = `bca6f6e9`.

### v1.4.8 (`88c25653`) — merged 2026-06-19

Merged upstream **v1.4.8** into `main` (merge commit `e62fdd3d`). Brought in the
upstream **Subagent / Connected-Agents / Partners** stack (~33 new files:
`deeptutor/services/subagent/*`, `deeptutor/capabilities/subagent/*`, subagents API
router, `web/.../agents/*` UI). 146 files, +11,674 / −567 from the previous fork
point (v1.4.6). Upstream CI for the target was green before merging.

Conflicts: 4 content conflicts + 2 auto-merged HIGH-risk files, all re-localized:

- `deeptutor/agents/chat/agentic_pipeline.py` — kept both imports
  (`normalize_agent_language` + upstream `PARTNER_BUILTIN_TOOL_NAMES`).
- `web/components/settings/SettingsHub.tsx`, `SettingsSectionGrid.tsx` — took
  upstream's new `tone`/`dot` readiness shape; added `th` labels (the shared
  `Lang` type requires `th`).
- `web/components/space/SpaceDashboard.tsx` — dropped the fork's obsolete
  `/space/agents` tile (upstream relocated agents to top-level `/agents` and
  deleted `/space/agents/page.tsx`).
- `web/lib/settings-nav.ts` (auto-merged) — added `th` to the new **Partners &
  Agents** nav (Claude Code, Codex leaves + category label/blurb).
- `deeptutor/services/session/source_inventory.py` (auto-merged) — added a `th`
  partner label; existing Thai transcript framing verified intact.

Thai work after merge:

- **+29 new UI keys** translated into `web/locales/th/app.json` (the Connected-Agents
  / conversation-command surface); parity restored to 2643 keys vs `en`.
- **New `th` gate** in `deeptutor/capabilities/subagent/capability.py` — the subagent
  framing prompt was zh/en only; added a Thai branch via `normalize_agent_language`
  (lazy import to avoid a circular import).

Deferred (tracked follow-up): the new agents-config components
`web/components/agents/ConnectedAgents.tsx` and
`web/components/settings/SubagentSettingsEditor.tsx` use a local `{zh,en}` `Lang`
and fall back to English for Thai (~72 strings). _Resolved 2026-06-19 — see
"Agents-config UI + th-TH" below._

Verification: web build OK, ruff check+format OK, i18n parity OK, live Thai chat OK,
pytest 2483 passed (10 pre-existing optional-dep failures — telegram/slack/msteams —
confirmed identical on `main`). Detail: `REPORT_sync_v1.4.8.md` (impact analysis in
`REPORT_impact_v1.4.8.md`).

> Note: the fork's customizations are now rebased on **v1.4.8**; the next sync's
> merge-base is `88c25653`.

### v1.4.8 follow-up — Agents-config UI + th-TH (2026-06-19)

Closes the two residuals deferred from the v1.4.8 sync. Branch
`fix/thai-agents-ui` → ff `main`.

- **Localized the agents-config UI (~72 strings).** Added `th` to the local
  `Lang` type and every label in `web/components/agents/ConnectedAgents.tsx` and
  `web/components/settings/SubagentSettingsEditor.tsx`, and made their `tr`
  detect Thai (`zh ? zh : th ? th : en`). `formatTs` in the editor now takes a
  locale (`th-TH` for Thai). Edits kept the files' original double-quote/semicolon
  style for mergeability (no whole-file reformat). Audit confirmed these were the
  only agents components with a local `{zh,en}` `Lang`.
- **th-TH normalization.** `normalize_agent_language()` in
  `deeptutor/services/prompt/language.py` now collapses any `th*` locale to `th`
  (symmetry with the existing `zh*` rule), so `th-TH` / `th_TH` no longer fall
  back to English — fixes the subagent framing prompt for `th-TH` sessions. Added
  `th-TH` / `th_TH` cases to `tests/services/prompt/test_language_th.py`.

Verification: `npm run build` OK, `eslint` OK, `tsc --noEmit` OK, i18n parity OK,
`pytest tests/services/prompt` 19 passed. Detail: `REPORT_followup_agents_ui.md`.

> Thai localization is now **100% on v1.4.8** (no known deferred surfaces).
