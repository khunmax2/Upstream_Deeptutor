# REPORT — Voice Call feature: handoff to continue in Claude Code

**Date:** 2026-07-02 · **Status:** prototype + provider interface + playable MVP done; waiting on production STT/TTS endpoint.

This is a self-contained handoff so any agent (Claude Code, etc.) can pick up the
voice work with full context. Read `AGENTS.md` + `CLAUDE.md` (fork rules) first.

---

## Goal

Two-way realtime "voice call" for DeepTutor: **Mic → STT → LLM → TTS → speaker**,
Thai-first, low latency ("feels like a phone call"), local-first capable.

## Locked architecture decisions

1. **Separate realtime I/O layer, NOT a Partners channel.** Reason: keeps it
   mergeable on upstream syncs (fork policy §3) and lets us stream tokens to
   per-sentence TTS + support barge-in (the partner `MessageBus` is text/turn-based).
2. **Plug-and-play / reusable (mentor's requirement).** The voice engine talks to
   the "brain" ONLY via an **OpenAI-compatible `/chat/completions` endpoint** — it
   does NOT import `ChatOrchestrator` internals. So it works with DeepTutor today
   and any other system tomorrow. STT/TTS/transport are swappable adapters.
3. **Future goal: computer-use agentic voice** — because the brain is behind a
   generic endpoint, later we swap DeepTutor for a computer-use agent without
   touching the voice engine. Design the protocol to allow tool-call passthrough;
   barge-in matters even more for long agent actions.
4. **Transport: WebSocket now, WebRTC/LiveKit later** (optional). LiveKit Agents
   was evaluated: usable (DeepTutor plugs in as its OpenAI-compatible LLM), gives
   turn-detection/barge-in/telephony/avatar for free, but adds infra (media server
   + worker + client SDK). Its turn-detector model has a separate non-Apache
   "LiveKit Model License". Keep LiveKit as a future WebRTC transport option only.

## Verified against code

DeepTutor core contract is stable v1.4.6→v1.4.8→**v1.4.15** (current `main`).
Unchanged: `runtime/orchestrator.py` (`ChatOrchestrator.handle` streams `StreamBus`
`CONTENT` tokens), `core/stream.py`, `services/voice/` (batch STT/TTS + adapter
registry), `partners/channels/base.py`. DeepTutor already exposes batch STT/TTS at
`/api/v1/voice/{tts,stt}` and has `deeptutor/services/voice/` adapters — the
production voice-realtime layer should REUSE those adapters.

## What's built — everything lives in `voice_prototype/` (standalone, outside `deeptutor/`)

| File | What |
| --- | --- |
| `providers.py` | **The plug-and-play seam.** `BaseSTT`/`BaseTTS` ABCs, `AudioChunk`/`STTResult`, `OpenAICompatSTT` (multipart), `OpenAICompatTTS` (streaming PCM), `OpenRouterSTT` (base64-JSON), `read_thai_number()`/`normalize_thai_for_tts()`. |
| `pipeline.py` | `transcribe()` (STT backend switch: groq \| openrouter), `stream_llm()` (OpenAI-compat SSE), `SentenceChunker` (Thai-aware early flush), `synthesize()` (TTS backends), `clean_for_speech()`. |
| `server.py` | FastAPI. `/ws` = audio mode (STT→LLM→per-sentence TTS, returns mp3). `/ws/chat` + `/mvp` = browser-Web-Speech MVP (server does LLM only). Per-stage latency in every turn. |
| `static/index.html` | Full audio client: mic + energy-VAD + barge-in, plays server audio. |
| `static/mvp.html` | Zero-key MVP: browser Web Speech STT/TTS (th-TH) + barge-in. |
| `selftest.py` | No-mic latency probe (LLM+TTS against real endpoints). |
| `tests/test_pipeline.py`, `tests/test_providers.py` | Network-free tests (chunker early-flush, Thai number reader, OpenRouter base64 STT, streaming). All pass. |
| `.env.example`, `.env.openrouter.example` | Config presets. |

## How to run (two playable paths)

**A) Zero-key MVP (browser does STT/TTS):** set `LLM_BASE_URL`/`LLM_MODEL` to a
DeepTutor OpenAI-compatible wrap → `python server.py` → open Chrome at
`http://127.0.0.1:8800/mvp`.

**B) OpenRouter server-side (real gpt-audio-mini voice):**
`cp .env.openrouter.example .env`, put key in **`OPENROUTER_API_KEY`** (one place,
feeds LLM+STT+TTS) → `source` it → `python server.py` → open `http://127.0.0.1:8800/`
(the main page, audio mode). Models chosen: brain `google/gemini-3.1-flash-lite`,
STT+TTS `openai/gpt-audio-mini`.

## Known facts to keep

- **User's production STT/TTS = TokenMind, OpenAI-compatible.** base_url was
  `https://tokenmind.abdul.in.th/v1` (DEAD — waiting for a new endpoint/key). STT
  `ptm-asr-1` (`/audio/transcriptions`), TTS `ptm-tts-1` (`/audio/speech`, streams
  PCM; voices: baifern, ped, pop, tun, dr_wit, dr_chai, bantita). Guideline:
  normalize Thai before TTS (numbers→words, English→transliteration, `\n` phrase
  breaks). When the new endpoint arrives it drops into `OpenAICompatSTT` /
  `OpenAICompatTTS` by config — no code change.
- **OpenRouter STT is base64-JSON** (`{model, input_audio:{data, format}}`), NOT
  OpenAI multipart — handled by `OpenRouterSTT`. OpenRouter TTS is OpenAI-compatible.

## Suggested next steps (pick per priority)

1. **Run + measure** paths A/B on real endpoints; record per-stage latency; tune
   `CHUNK_MAX_CHARS` and VAD thresholds for Thai.
2. **Swap TTS to true PCM streaming** in the audio path (`server.py` `/ws`) using
   `OpenAICompatTTS.stream()` instead of per-sentence mp3 — lowers first-audio latency.
3. **English→Thai transliteration** hook in `normalize_thai_for_tts` (needs a lexicon).
4. **Productionize** into `deeptutor/services/voice_realtime/` +
   `deeptutor/api/routers/voice_realtime.py` (WS `/api/v1/voice/ws`), reusing
   `deeptutor/services/voice/` adapters; mount via one `include_router` line in
   `deeptutor/api/main.py`. Keep the OpenAI-compatible-brain seam.
5. Optional: LiveKit WebRTC transport for phone-grade quality + telephony.

## Fork policy reminders (REQUIRED on any change)

Log every change in `CHANGES.md` (already has a "Voice call (realtime)" section),
commit with Conventional Commits, add a `REPORT_voice_*.md` per phase, keep `NOTICE`
current. After code changes: `ruff check . && ruff format --check .`, run tests,
`graphify update .`. Prefer NEW files over editing upstream ones.
