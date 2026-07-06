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
