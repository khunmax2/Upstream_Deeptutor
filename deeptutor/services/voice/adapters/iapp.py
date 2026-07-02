"""iApp Technology (iapp.co.th) Thai STT/TTS adapters.

iApp's speech APIs are not OpenAI-compatible — auth is an ``apikey`` header and
the endpoints live under ``/v3/store``:

* **TTS v3 (Kaitom voice)** — ``POST {base}/audio/tts`` with ``{"text", "speed"}``;
  returns **raw PCM** (signed 16-bit LE, mono, 24 kHz) as an octet-stream. The
  adapter reports ``audio/pcm;rate=24000;channels=1`` so downstream consumers
  (e.g. the REST voice router's PCM→WAV wrapper) can container it for browsers.
  There is no voice selection — ``config.voice``/``config.model`` are cosmetic.
* **ASR (STT)** — multipart ``file`` upload. The catalog *model* selects the
  variant: ``pro`` → ``{base}/speech/speech-to-text/pro`` (accurate, slower),
  anything else → ``{base}/speech/speech-to-text/base`` (fast per docs).
  Response carries segments in ``output[].text`` which are joined.

Note: iApp documents MP3/WAV/AAC/M4A input for ASR; browser-recorded webm is
undocumented — callers recording webm should test or transcode first.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from deeptutor.services.voice.base import (
    BaseSTTAdapter,
    BaseTTSAdapter,
    VoiceProviderError,
    VoiceProviderHTTPError,
)
from deeptutor.services.voice.config import STTConfig, TTSConfig

logger = logging.getLogger(__name__)

_DEFAULT_IAPP_BASE = "https://api.iapp.co.th/v3/store"

# iApp TTS v3 output is raw PCM s16le mono @ 24 kHz (per docs).
_PCM_CONTENT_TYPE = "audio/pcm;rate=24000;channels=1"
# Docs: speed accepted range.
_SPEED_MIN, _SPEED_MAX = 0.8, 1.2


def _raise_for_provider(resp: httpx.Response, action: str) -> None:
    """Surface a provider error with a trimmed body for diagnostics."""
    if resp.status_code < 400:
        return
    body = resp.text or ""
    detail = body.strip()[:400]
    message = f"{action} failed with HTTP {resp.status_code}" + (f": {detail}" if detail else ".")
    raise VoiceProviderHTTPError(message, status_code=resp.status_code, body=body)


def _headers(api_key: str, *, extra: dict[str, str] | None) -> dict[str, str]:
    if not api_key:
        raise VoiceProviderError("No API key configured for iApp.")
    return {"apikey": api_key, **(extra or {})}


class IAppTTSAdapter(BaseTTSAdapter):
    """iApp Thai TTS v3 (``POST /audio/tts`` → raw PCM 24 kHz)."""

    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        base = (config.base_url or _DEFAULT_IAPP_BASE).rstrip("/")
        url = f"{base}/audio/tts"
        headers = {
            "Content-Type": "application/json",
            **_headers(config.api_key, extra=config.extra_headers),
        }
        payload: dict[str, Any] = {"text": text}
        if config.speed is not None:
            payload["speed"] = min(_SPEED_MAX, max(_SPEED_MIN, config.speed))

        logger.debug("iApp TTS chars=%d speed=%s", len(text), payload.get("speed"))
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise VoiceProviderError(f"iApp TTS request error: {exc}") from exc
        _raise_for_provider(resp, "iApp TTS synthesis")
        audio = resp.content
        if not audio:
            raise VoiceProviderError("iApp TTS returned empty audio.")
        # Providers label the raw PCM stream as octet-stream (or occasionally
        # JSON on gateway errors that slipped a 200) — report the documented
        # PCM shape so the PCM→WAV wrapper downstream can act on it.
        content_type = resp.headers.get("content-type") or ""
        if "json" in content_type:
            raise VoiceProviderError(f"iApp TTS returned JSON instead of audio: {resp.text[:200]}")
        return audio, _PCM_CONTENT_TYPE


class IAppSTTAdapter(BaseSTTAdapter):
    """iApp Thai ASR (multipart upload; catalog model picks ``pro`` or ``base``)."""

    async def transcribe(
        self,
        audio: bytes,
        config: STTConfig,
        *,
        filename: str = "audio.webm",
        content_type: str = "application/octet-stream",
    ) -> str:
        if not audio:
            raise VoiceProviderError("No audio data to transcribe.")
        base = (config.base_url or _DEFAULT_IAPP_BASE).rstrip("/")
        variant = "pro" if (config.model or "").strip().lower() == "pro" else "base"
        url = f"{base}/speech/speech-to-text/{variant}"
        headers = _headers(config.api_key, extra=config.extra_headers)
        files = {"file": (filename, audio, content_type or "application/octet-stream")}
        data = {"chunk_size": "7"} if variant == "base" else {}

        logger.debug("iApp STT variant=%s bytes=%d", variant, len(audio))
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                resp = await client.post(url, headers=headers, files=files, data=data)
        except httpx.HTTPError as exc:
            raise VoiceProviderError(f"iApp STT request error: {exc}") from exc
        _raise_for_provider(resp, "iApp transcription")
        return self._parse_text(resp)

    @staticmethod
    def _parse_text(resp: httpx.Response) -> str:
        try:
            data = resp.json()
        except ValueError as exc:
            raise VoiceProviderError("iApp STT response was not JSON.") from exc
        if isinstance(data, dict):
            # v3 shape: {"output": [{"text": ...}, ...], ...}
            output = data.get("output")
            if isinstance(output, list):
                parts = [
                    str(seg.get("text", "")).strip()
                    for seg in output
                    if isinstance(seg, dict) and seg.get("text")
                ]
                if parts:
                    return " ".join(parts)
            # Defensive fallback for a flat {"text": ...} shape.
            text = data.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
        raise VoiceProviderError(f"iApp STT response had no transcript: {str(data)[:200]}")


__all__ = ["IAppTTSAdapter", "IAppSTTAdapter"]
