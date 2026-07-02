"""Standalone config for the voice-call prototype (env-driven).

This prototype is intentionally decoupled from DeepTutor: the LLM stage talks to
any OpenAI-compatible /chat/completions endpoint (your DeepTutor wrap), STT uses
Groq Whisper, and TTS is pluggable (openai-compatible / elevenlabs / botnoi).
"""

from __future__ import annotations

from dataclasses import dataclass
import os


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


@dataclass(slots=True)
class Config:
    # ── ONE key for everything on OpenRouter — put your key HERE ──
    # Feeds LLM / STT / TTS below whenever their own *_API_KEY is left blank.
    openrouter_api_key: str = _env("OPENROUTER_API_KEY")

    # ── LLM / brain (OpenAI-compatible — DeepTutor wrap OR OpenRouter) ──
    llm_base_url: str = _env("LLM_BASE_URL", "http://localhost:8001/v1")
    llm_api_key: str = _env("LLM_API_KEY") or _env("OPENROUTER_API_KEY") or "sk-local"
    llm_model: str = _env("LLM_MODEL", "deeptutor")
    # "1" → send Zhipu-style {"thinking":{"type":"disabled"}} so hybrid-reasoning
    # models (GLM-4.5+) skip the thinking phase — voice needs fast first tokens.
    llm_disable_thinking: bool = _env("LLM_DISABLE_THINKING") in ("1", "true", "yes")
    system_prompt: str = _env(
        "SYSTEM_PROMPT",
        "คุณเป็นติวเตอร์ที่พูดไทยเป็นกันเอง ตอบสั้น กระชับ เหมือนกำลังคุยโทรศัพท์ หลีกเลี่ยง markdown และการอ่านสัญลักษณ์",
    )

    # ── STT (batch-on-endpoint) ──
    stt_backend: str = _env("STT_BACKEND", "groq")  # groq | openrouter
    stt_base_url: str = _env("STT_BASE_URL", "https://openrouter.ai/api/v1")
    stt_api_key: str = _env("STT_API_KEY") or _env("OPENROUTER_API_KEY") or _env("GROQ_API_KEY")
    stt_model: str = _env("STT_MODEL", "whisper-large-v3")
    stt_language: str = _env("STT_LANGUAGE", "th")
    groq_api_key: str = _env("GROQ_API_KEY")  # used only when stt_backend=groq

    # ── TTS (pluggable) ──
    tts_backend: str = _env("TTS_BACKEND", "openai")  # openai | elevenlabs | botnoi

    # openai-compatible /audio/speech (OpenAI, OpenRouter, or a local TTS server)
    tts_openai_base_url: str = _env("TTS_OPENAI_BASE_URL", "https://api.openai.com/v1")
    tts_openai_api_key: str = _env("TTS_OPENAI_API_KEY") or _env("OPENROUTER_API_KEY")
    tts_openai_model: str = _env("TTS_OPENAI_MODEL", "gpt-4o-mini-tts")
    tts_openai_voice: str = _env("TTS_OPENAI_VOICE", "alloy")

    # elevenlabs
    elevenlabs_api_key: str = _env("ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str = _env("ELEVENLABS_VOICE_ID", "")
    elevenlabs_model: str = _env("ELEVENLABS_MODEL", "eleven_multilingual_v2")

    # botnoi  (NOTE: verify endpoint/fields against current BOTNOI Voice docs)
    botnoi_token: str = _env("BOTNOI_TOKEN")
    botnoi_speaker: str = _env("BOTNOI_SPEAKER", "1")

    # ── chunking / server ──
    chunk_max_chars: int = int(_env("CHUNK_MAX_CHARS", "120"))
    host: str = _env("HOST", "127.0.0.1")
    port: int = int(_env("PORT", "8800"))


CONFIG = Config()
