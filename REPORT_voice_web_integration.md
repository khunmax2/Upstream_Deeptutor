# REPORT — Voice Call: web integration, UI control, latency & naturalness

**Date:** 2026-07-07 · **Branch:** `feat/voice-web-integration` (forked from
`feat/voice-prototype`; both pushed to origin) · **Status:** feature-complete
MVP working end-to-end in the real web app; demo-ready.

Self-contained handoff: any agent on any account/machine can continue from
this file + `CHANGES.md`. Read `AGENTS.md` + `CLAUDE.md` (fork rules) first.
Previous chapters: `REPORT_voice_handoff.md` (prototype era),
`REPORT_voice_realtime.md` (production realtime layer).

---

## What works today (demo script)

1. `deeptutor serve` (backend; the web proxy reads `backend_port` from
   `data/user/settings/system.json` — currently 8002) and `cd web && npm run dev`
   (currently :3783).
2. Any workspace page → floating 📞 button (bottom-right, every page).
3. Press it → mascot layer fades in at the corner (transparent 3D canvas,
   Botnoi-widget style; page stays interactive) and the call answers with a
   spoken greeting ("สวัสดีครับ มีอะไรให้ผมช่วยไหมครับ").
4. Talk (browser Web-Speech STT) or type in the panel. Replies stream as
   per-sentence TTS with real-amplitude lip-sync.
5. "ไปหน้า settings / กลับไปหน้าหลัก / เปิดหน้า knowledge" → page changes
   instantly (client-side router; the call survives navigation), bot says
   exactly "ได้เลยครับ".
6. "หยุดพูด / เงียบ / พอแล้ว" → speech stops, bot says "ครับ", nothing else.
7. Ask a KB question → "ขอค้นข้อมูลในเอกสารสักครู่นะครับ" + mascot spins
   purple while RAG runs; watchdog reassures at 8 s, aborts at 45 s.

## Architecture (3 layers, unchanged from the locked design)

```
Browser  web/components/voice/VoiceCallWidget.tsx
         call button · fading corner mascot (three.js via CDN, no bundle dep)
         browser STT + 3-layer echo guard · playback queue + lip-sync
         ui_manifest declaration + ui_action executor (whitelist, re-validated)
   │  WS /api/v1/voice/ws (same-origin; web/proxy.ts forwards to backend)
Voice    deeptutor/services/voice_realtime/   ← all fork-owned
layer    router (greet + control frames) · session (turn serialisation, barge)
         pipeline (STT guard → orchestrator stream → SentenceChunker → TTS)
         narration (fixed lines) · ui_control (manifest/tool/shortcut)
Core     ChatOrchestrator · StreamBus · RAG/KB · tools · Settings catalog
(untouched)
```

Upstream files touched by the whole feature: **2 lines** in
`web/app/layout.tsx` (mount the widget in the root layout so it survives
client-side navigation). Everything else is new files or runtime registration
(`ToolRegistry.register()` + appending to `LOOP_CAPABILITIES` at import of the
voice router).

## The intent ladder (key design of this phase)

Utterances are routed by weight, cheapest first — same taxonomy as
Alexa/Siri:

| Layer | Examples | Path | Reply |
|---|---|---|---|
| Control | หยุด / เงียบ / พอแล้ว / stop | `pipeline.is_stop_command` — exact match after stripping polite particles ("วันหยุดคืออะไร" still reaches the LLM) | cached "ครับ" |
| Action | ไปหน้า X / เปิดหน้า X | `ui_control.match_navigation_intent` — nav verb + "หน้า/page" + exactly one manifest match, ≤48 chars; executes `ui_action` directly, **no LLM** | cached "ได้เลยครับ" |
| Conversation | everything else | ChatOrchestrator with full history/RAG/tools | LLM, per-sentence TTS |

Ambiguous or compound requests ("ไปหน้า settings แล้วอธิบาย…") deliberately
fall through to the LLM.

## Voice UI control (how "สั่งเสียงเปลี่ยนหน้า" works)

1. Widget sends `{"type":"ui_manifest", manifest:{pages:[{id,label},…]}}` on
   WS open. `UI_PAGES` in the widget is the whitelist (12 pages; `/login`,
   `/register` deliberately excluded). Server sanitises (≤64 targets, ≤8 KB).
2. Manifest presence activates `VoiceUICapability` (runtime-registered) which
   mounts the `ui_navigate` tool + a system block listing allowed targets.
3. Pipeline forwards the tool's `TOOL_CALL` as `{"type":"ui_action",…}`; the
   widget re-validates against its own table then `router.push()` — page
   changes *before* the voice arrives (tool call precedes the spoken text).
4. `web/tests/voice-manifest-parity.test.ts` walks `web/app` for real
   top-level routes (route groups + optional catch-alls handled) and fails
   when `UI_PAGES` drifts in either direction — guards upstream syncs.

## Latency: what was learned (important for future work)

- The pipeline was never the bottleneck. ~85–90 % of latency was the LLM:
  hybrid-thinking models (Qwen3.5/Nemotron) reason 20 s+ before the first
  token, and free endpoints (NVIDIA NIM) add wild queue swings (0.8 s → 64 s
  → dead streams, measured live).
- Fixes shipped, all voice-scoped via `set_scoped_llm_config` (task-local
  ContextVar; chat completely unaffected): `reasoning_effort="minimal"`
  (verified TTFT 21 s → <1 s on NIM qwen3.5) + `temperature=0.3` (stops the
  tool-call coin-flip). Currently running Gemini (`gemini-3.1-flash-lite`)
  which is fast AND has thinking off by default in DeepTutor's provider map.
- Fixed lines (greeting, "ได้เลยครับ", "ครับ") go through a synthesise-once
  `_FIXED_LINE_CACHE` — zero TTS latency after first use.
- Remaining known levers (not done): VAD hang 700→400 ms, HTTP connection
  reuse to TTS, overlapping TTS synthesis as a separate task, streaming STT
  with prefetch (arXiv 2305.13794), speech-to-speech transport
  (Gemini-Live-style — what Botnoi actually uses; long-term option).

## Naturalness rules encoded in prompts (fought for, don't regress)

- `VOICE_STYLE_DIRECTIVE` (pipeline.py): ≤4 spoken sentences, no markdown,
  numbers as words, **never end with generic help offers** ("หากมีคำถาม
  เพิ่มเติม…").
- `voice_ui` system block + tool result: after `ui_navigate`, reply EXACTLY
  "ได้เลยครับ" — never "รอสักครู่", never describe the page, never acknowledge
  without actually calling the tool. Validated 3/3 on Gemini.
- Fillers: "please wait" must be earned — only known-slow tools (rag,
  web_search, code…) get an instant cue; unknown tools stay silent and the
  8 s watchdog speaks the generic wait line only if the silence is real.

## Echo defense (browser STT hears the bot's own TTS)

Three layers in the widget: mute guard while playing + 800 ms tail; abort
recognition the instant audio starts (Web Speech buffers during playback and
delivers AFTER the mute window — time guard alone leaks); text fingerprint
(drop transcripts matching recently spoken bot text — Botnoi's technique).
Trade-off: voice barge-in is disabled in browser-STT mode (type to interrupt);
the calibrated server-STT mode (in the bench pages) still supports voice
barge-in via the 2.5× energy gate.

## Test surface

- `tests/services/voice_realtime/` — 70 tests (pipeline, session, stt_guard,
  narration, ui_control incl. shortcut/stop matchers and no-LLM proofs).
- `web/tests/voice-manifest-parity.test.ts` — manifest ↔ routes.
- Bench pages (voice_prototype/, static host :8800): `/` = call.html (full
  mascot + mic-mode selector), `/mock` = mock-app.html (fake DeepTutor UI for
  voice-navigation testing without touching web/).
- Gotcha: these are asyncio tests — a fake `run_turn` missing a new kwarg
  hangs the whole suite (awaits an Event that never sets) rather than failing.
  Fakes take `**kwargs` now; keep it that way.

## Known deferrals / next steps

1. **Curated in-page actions** ("เปิด KB กฎหมาย", "สร้างแชทใหม่") — manifest
   `actions` are already supported end-to-end (mock bench proved `open_kb`
   with an argument); the web widget just doesn't declare any yet.
2. **page-agent** (Alibaba, MIT; cloned at ~/Project/antigravity/page-agent)
   evaluated as the "click anything" tier — defer until curated actions run out.
3. Widget UI strings are Thai literals pending i18n keys (2 eslint warnings).
4. Server STT mode + voice barge-in in the web widget (exists in bench only).
5. Merge plan: squash-merge this branch back into `feat/voice-prototype`
   when validated (history here is intentionally fine-grained).

## Environment notes

- LLM/STT/TTS all resolve from Settings > Voice / Models catalog
  (`data/user/settings/model_catalog.json`) — NOT from any .env. Current:
  Gemini (LLM), Groq whisper-large-v3 (STT), custom PTM `dr_wit` (TTS).
- iApp integration was removed entirely (dead account + API docs mismatch,
  reported to vendor). z.ai is supported natively (binding `zhipu`,
  keyword `zai` — override base_url to `https://api.z.ai/api/paas/v4`).
- `voice_prototype/.env` holds only HOST/PORT for the static bench host.
