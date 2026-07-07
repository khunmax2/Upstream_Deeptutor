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
