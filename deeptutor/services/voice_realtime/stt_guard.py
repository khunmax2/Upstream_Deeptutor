"""STT quality guard for voice turns — vocab biasing, confidence, hallucination filter.

Live-mic testing showed the raw STT path is too trusting for a call: ambient
noise clips make Whisper hallucinate fluent Thai ("โปรดติดตามตอนต่อไป" — a
YouTube-outro artifact from its training data), and domain words come out
mangled ("DeepaTutor"). This module hardens the voice path without touching
upstream files:

* :func:`transcribe_utterance` — when the active catalog STT is the
  OpenAI-compatible multipart cluster (OpenAI/Groq/…), it requests
  ``verbose_json`` with a domain *vocab prompt* (biases Whisper toward our
  terms) and returns ``(text, avg_logprob)``. Any other adapter (bespoke,
  OpenRouter base64) falls back to the plain facade with no confidence.
* :func:`screen_transcript` — rejects empty text, known Whisper-hallucination
  phrases, and low-confidence transcripts, returning a reason the pipeline can
  speak back ("ฟังไม่ชัด ขอพูดอีกครั้ง").

Everything here is voice-layer policy; the shared catalog/adapters stay as
upstream ships them (fork policy §3).
"""

from __future__ import annotations

import logging
import math

import httpx

from deeptutor.services.voice import transcribe_audio
from deeptutor.services.voice.base import (
    VoiceProviderError,
    VoiceProviderHTTPError,
    build_auth_headers,
    join_audio_path,
)
from deeptutor.services.voice.config import STT_MULTIPART, STTConfig

logger = logging.getLogger(__name__)

# Bias Whisper's decoding toward domain terms it otherwise mangles
# ("DeepaTutor", "Deep Thielter", …). Whisper treats this as preceding context,
# so a short comma list of correct spellings is enough.
VOCAB_PROMPT = "DeepTutor, ดีพติวเตอร์, knowledge base, RAG, quiz, mastery path"

# Mean segment avg_logprob below this → the model was guessing (noise input).
# Real speech on whisper-large-v3 typically lands well above -0.5.
MIN_AVG_LOGPROB = -0.7

# Fluent phrases Whisper invents on noise/silence (YouTube-subtitle artifacts).
# Matched as substrings on short transcripts only, so a real sentence that
# happens to contain one is never dropped.
HALLUCINATION_PATTERNS = (
    "โปรดติดตามตอนต่อไป",
    "ขอบคุณสำหรับการรับชม",
    "ขอบคุณที่รับชม",
    "กดไลค์กดแชร์",
    "กดไลก์กดแชร์",
    "ซับไทยโดย",
    "บรรยายไทยโดย",
)
_HALLUCINATION_MAX_CHARS = 40  # only short utterances can be pure hallucination


async def transcribe_utterance(
    audio: bytes,
    *,
    language: str = "th",
    filename: str = "audio.webm",
    content_type: str = "audio/webm",
) -> tuple[str, float | None]:
    """Transcribe one utterance; return ``(text, confidence)``.

    ``confidence`` is the mean segment ``avg_logprob`` when the provider can
    report one (OpenAI-compatible multipart cluster), else ``None``.
    """
    from deeptutor.services.config.provider_runtime import resolve_stt_runtime_config

    config = resolve_stt_runtime_config()
    if language:
        config.language = language
    if config.adapter == "openai_compat" and config.request_style == STT_MULTIPART:
        return await _transcribe_verbose(
            audio, config, filename=filename, content_type=content_type
        )
    # Bespoke providers (OpenRouter base64-JSON, …) — facade path, no confidence.
    text = await transcribe_audio(
        audio, filename=filename, content_type=content_type, language=language
    )
    return text, None


async def _transcribe_verbose(
    audio: bytes,
    config: STTConfig,
    *,
    filename: str,
    content_type: str,
) -> tuple[str, float | None]:
    """Multipart transcription with vocab prompt + ``verbose_json`` confidence."""
    if not audio:
        raise VoiceProviderError("No audio data to transcribe.")
    url = join_audio_path(config.base_url, "audio/transcriptions")
    headers = {
        **build_auth_headers(config.auth_style, config.api_key),
        **(config.extra_headers or {}),
    }
    files = {"file": (filename, audio, content_type or "application/octet-stream")}
    data = {
        "model": config.model,
        "response_format": "verbose_json",
        "prompt": VOCAB_PROMPT,
    }
    if config.language:
        data["language"] = config.language

    try:
        async with httpx.AsyncClient(timeout=config.request_timeout) as client:
            resp = await client.post(url, headers=headers, files=files, data=data)
    except httpx.HTTPError as exc:
        raise VoiceProviderError(f"STT request error: {exc}") from exc
    if resp.status_code >= 400:
        body = resp.text or ""
        raise VoiceProviderHTTPError(
            f"Transcription failed with HTTP {resp.status_code}: {body.strip()[:300]}",
            status_code=resp.status_code,
            body=body,
        )
    payload = resp.json()
    if not isinstance(payload, dict):
        raise VoiceProviderError("Transcription response had an unexpected shape.")
    text = str(payload.get("text") or "").strip()
    segments = payload.get("segments")
    confidence: float | None = None
    if isinstance(segments, list) and segments:
        logprobs = [
            seg["avg_logprob"]
            for seg in segments
            if isinstance(seg, dict) and isinstance(seg.get("avg_logprob"), (int, float))
        ]
        if logprobs:
            confidence = math.fsum(logprobs) / len(logprobs)
    return text, confidence


def screen_transcript(text: str, confidence: float | None) -> tuple[bool, str]:
    """Decide whether a transcript is trustworthy enough to answer.

    Returns ``(ok, reason)`` — ``reason`` is a speakable Thai explanation used
    for the client-facing error event when ``ok`` is False.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return False, "ไม่ได้ยินเสียงพูด"
    compact = cleaned.replace(" ", "")
    if len(compact) <= _HALLUCINATION_MAX_CHARS:
        for pattern in HALLUCINATION_PATTERNS:
            if pattern in compact:
                logger.debug("Dropping hallucinated transcript: %r", cleaned)
                return False, "ไม่ได้ยินชัด ลองพูดอีกครั้งได้ไหมครับ"
    if confidence is not None and confidence < MIN_AVG_LOGPROB:
        logger.debug("Dropping low-confidence transcript (%.2f): %r", confidence, cleaned)
        return False, "ฟังไม่ค่อยชัด รบกวนพูดอีกครั้งครับ"
    return True, ""


__all__ = [
    "VOCAB_PROMPT",
    "MIN_AVG_LOGPROB",
    "HALLUCINATION_PATTERNS",
    "transcribe_utterance",
    "screen_transcript",
]
