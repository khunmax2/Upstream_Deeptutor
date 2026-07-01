"""Voice pipeline stages: STT (batch) → LLM (stream) → sentence-chunked TTS.

Each stage is provider-agnostic and independently testable. Latency is measured
per stage so the prototype can prove the "feels like a phone call" target
(start speaking the first sentence while the LLM is still generating).
"""

from __future__ import annotations

import json
import re
import time
from typing import AsyncIterator

from config import CONFIG
import httpx


# ──────────────────────────────────────────────────────────────────────────
# STT — Groq Whisper, batch-on-endpoint (one short utterance per call)
# ──────────────────────────────────────────────────────────────────────────
async def transcribe(
    audio: bytes, *, filename: str = "audio.webm", content_type: str = "audio/webm"
) -> tuple[str, float]:
    """Transcribe one utterance. Returns (text, elapsed_seconds)."""
    if not CONFIG.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set")
    t0 = time.perf_counter()
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    files = {
        "file": (filename, audio, content_type),
        "model": (None, CONFIG.stt_model),
    }
    if CONFIG.stt_language:
        files["language"] = (None, CONFIG.stt_language)
    headers = {"Authorization": f"Bearer {CONFIG.groq_api_key}"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, files=files)
        resp.raise_for_status()
        text = resp.json().get("text", "").strip()
    return text, time.perf_counter() - t0


# ──────────────────────────────────────────────────────────────────────────
# LLM — OpenAI-compatible /chat/completions, streamed token-by-token
# ──────────────────────────────────────────────────────────────────────────
async def stream_llm(messages: list[dict]) -> AsyncIterator[str]:
    """Yield content tokens from an OpenAI-compatible streaming endpoint."""
    url = f"{CONFIG.llm_base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {CONFIG.llm_api_key}", "Content-Type": "application/json"}
    payload = {"model": CONFIG.llm_model, "messages": messages, "stream": True}
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0]["delta"]
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                token = delta.get("content")
                if token:
                    yield token


# ──────────────────────────────────────────────────────────────────────────
# Sentence chunker — flush complete clauses to TTS as early as possible
# ──────────────────────────────────────────────────────────────────────────
_TERMINALS = "。．.!?！？\n…"
# Thai has no word spaces; treat spaces and the mai-yamok as soft break points
# so a long clause still flushes before the model finishes the whole answer.
_SOFT = " \t ๆ,;:、，"


class SentenceChunker:
    """Accumulate streamed tokens; emit speakable chunks at clause boundaries."""

    def __init__(self, max_chars: int = 120) -> None:
        self.max_chars = max_chars
        self._buf = ""

    def feed(self, token: str) -> list[str]:
        out: list[str] = []
        self._buf += token
        while True:
            cut = self._find_cut()
            if cut is None:
                break
            chunk, self._buf = self._buf[:cut].strip(), self._buf[cut:].lstrip()
            if chunk:
                out.append(chunk)
        return out

    def _find_cut(self) -> int | None:
        # Hard terminal anywhere → cut right after it.
        for i, ch in enumerate(self._buf):
            if ch in _TERMINALS:
                return i + 1
        # Otherwise, once we're over budget, cut at the last soft break.
        if len(self._buf) >= self.max_chars:
            soft = max((self._buf.rfind(c) for c in _SOFT), default=-1)
            if soft > 0:
                return soft + 1
            return len(self._buf)  # no break available — flush as-is
        return None

    def flush(self) -> str:
        chunk, self._buf = self._buf.strip(), ""
        return chunk


_MD = re.compile(r"[*_`#>\[\]()~]|!\[")


def clean_for_speech(text: str) -> str:
    """Drop the markdown noise the LLM might emit so TTS reads natural prose."""
    return _MD.sub("", text).strip()


# ──────────────────────────────────────────────────────────────────────────
# TTS — pluggable backend; returns (audio_bytes, content_type, elapsed_seconds)
# ──────────────────────────────────────────────────────────────────────────
async def synthesize(text: str) -> tuple[bytes, str, float]:
    text = clean_for_speech(text)
    if not text:
        return b"", "audio/mpeg", 0.0
    t0 = time.perf_counter()
    backend = CONFIG.tts_backend.lower()
    if backend == "elevenlabs":
        audio, ctype = await _tts_elevenlabs(text)
    elif backend == "botnoi":
        audio, ctype = await _tts_botnoi(text)
    else:
        audio, ctype = await _tts_openai(text)
    return audio, ctype, time.perf_counter() - t0


async def _tts_openai(text: str) -> tuple[bytes, str]:
    """OpenAI-compatible /audio/speech (OpenAI or a local TTS server)."""
    url = f"{CONFIG.tts_openai_base_url.rstrip('/')}/audio/speech"
    headers = {
        "Authorization": f"Bearer {CONFIG.tts_openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": CONFIG.tts_openai_model,
        "voice": CONFIG.tts_openai_voice,
        "input": text,
        "response_format": "mp3",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.content, "audio/mpeg"


async def _tts_elevenlabs(text: str) -> tuple[bytes, str]:
    voice = CONFIG.elevenlabs_voice_id
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
    headers = {"xi-api-key": CONFIG.elevenlabs_api_key, "Content-Type": "application/json"}
    payload = {
        "text": text,
        "model_id": CONFIG.elevenlabs_model,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.content, "audio/mpeg"


async def _tts_botnoi(text: str) -> tuple[bytes, str]:
    """BOTNOI Voice. NOTE: verify endpoint + field names against current docs."""
    url = "https://api-voice.botnoi.ai/openapi/v1/generate_audio"
    headers = {"Botnoi-Token": CONFIG.botnoi_token, "Content-Type": "application/json"}
    payload = {
        "text": text,
        "speaker": CONFIG.botnoi_speaker,
        "volume": 1,
        "speed": 1,
        "type_media": "mp3",
        "language": "th",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        audio_url = data.get("audio_url") or (data.get("data") or {}).get("audio_url")
        if not audio_url:
            raise RuntimeError(f"BOTNOI: no audio_url in response: {data}")
        audio = (await client.get(audio_url)).content
        return audio, "audio/mpeg"
