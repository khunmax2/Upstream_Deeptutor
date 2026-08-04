"""Bespoke TTS adapters that don't fit the OpenAI ``/v1/audio/speech`` shape.

ElevenLabs and BOTNOI Voice each have their own request/response contract and
auth header, so — unlike the OpenAI-compatible cluster — they get dedicated
adapters keyed in :mod:`deeptutor.services.voice.adapters`:

* **ElevenLabs** — ``POST {base}/text-to-speech/{voice_id}`` with an
  ``xi-api-key`` header; returns raw MP3 bytes. The catalog's *voice* is the
  ElevenLabs ``voice_id`` and the *model* is the ``model_id``.
* **BOTNOI Voice** — ``POST {base}/generate_audio`` with a ``Botnoi-Token``
  header; returns JSON carrying an ``audio_url`` that is then fetched. The
  catalog's *voice* is the numeric ``speaker`` id.

Both read ``api_key`` / ``base_url`` / ``voice`` off the resolved
:class:`TTSConfig` exactly like the OpenAI adapter, so they resolve through the
same Settings > Voice catalog (see ``TTS_PROVIDERS`` in ``provider_runtime``).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from deeptutor.services.voice.base import (
    BaseTTSAdapter,
    VoiceProviderError,
    VoiceProviderHTTPError,
)
from deeptutor.services.voice.config import TTSConfig

logger = logging.getLogger(__name__)

_DEFAULT_ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"
_DEFAULT_BOTNOI_BASE = "https://api-voice.botnoi.ai/openapi/v1"


def _raise_for_provider(resp: httpx.Response, action: str) -> None:
    """Surface a provider error with a trimmed body for diagnostics."""
    if resp.status_code < 400:
        return
    body = resp.text or ""
    detail = body.strip()[:400]
    message = f"{action} failed with HTTP {resp.status_code}" + (f": {detail}" if detail else ".")
    raise VoiceProviderHTTPError(message, status_code=resp.status_code, body=body)


class ElevenLabsTTSAdapter(BaseTTSAdapter):
    """ElevenLabs text-to-speech (``POST /text-to-speech/{voice_id}``)."""

    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        voice_id = (config.voice or "").strip()
        if not voice_id:
            raise VoiceProviderError(
                "ElevenLabs needs a voice id. Set the voice in Settings > Voice."
            )
        if not config.api_key:
            raise VoiceProviderError("No API key configured for ElevenLabs.")
        base = (config.base_url or _DEFAULT_ELEVENLABS_BASE).rstrip("/")
        url = f"{base}/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": config.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
            **(config.extra_headers or {}),
        }
        payload: dict[str, Any] = {
            "text": text,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        if config.model:
            payload["model_id"] = config.model

        logger.debug("ElevenLabs TTS voice=%s model=%s chars=%d", voice_id, config.model, len(text))
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise VoiceProviderError(f"ElevenLabs request error: {exc}") from exc
        _raise_for_provider(resp, "ElevenLabs synthesis")
        audio = resp.content
        if not audio:
            raise VoiceProviderError("ElevenLabs returned empty audio.")
        content_type = resp.headers.get("content-type") or "audio/mpeg"
        if "json" in content_type:  # some gateways mislabel binary audio
            content_type = "audio/mpeg"
        return audio, content_type


class BotnoiTTSAdapter(BaseTTSAdapter):
    """BOTNOI Voice (Thai TTS): ``POST /generate_audio`` then fetch ``audio_url``.

    NOTE: BOTNOI's contract has shifted across versions. The request/response
    field names here (``speaker`` / ``audio_url``) match the current OpenAPI
    ``generate_audio`` shape; if BOTNOI changes them, only this adapter needs a
    fix. ``config.voice`` is the numeric speaker id; ``config.model`` is unused.
    """

    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        if not config.api_key:
            raise VoiceProviderError("No Botnoi-Token configured for BOTNOI Voice.")
        base = (config.base_url or _DEFAULT_BOTNOI_BASE).rstrip("/")
        url = f"{base}/generate_audio"
        headers = {
            "Botnoi-Token": config.api_key,
            "Content-Type": "application/json",
            **(config.extra_headers or {}),
        }
        payload: dict[str, Any] = {
            "text": text,
            "speaker": (config.voice or "1"),
            "volume": 1,
            "speed": 1,
            "type_media": "mp3",
            "language": "th",
        }

        logger.debug("BOTNOI TTS speaker=%s chars=%d", config.voice, len(text))
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                _raise_for_provider(resp, "BOTNOI synthesis")
                audio_url = self._extract_audio_url(resp)
                audio_resp = await client.get(audio_url)
                _raise_for_provider(audio_resp, "BOTNOI audio fetch")
                audio = audio_resp.content
        except httpx.HTTPError as exc:
            raise VoiceProviderError(f"BOTNOI request error: {exc}") from exc
        if not audio:
            raise VoiceProviderError("BOTNOI returned empty audio.")
        content_type = audio_resp.headers.get("content-type") or "audio/mpeg"
        if "json" in content_type:
            content_type = "audio/mpeg"
        return audio, content_type

    @staticmethod
    def _extract_audio_url(resp: httpx.Response) -> str:
        try:
            data = resp.json()
        except ValueError as exc:
            raise VoiceProviderError("BOTNOI response was not JSON.") from exc
        if not isinstance(data, dict):
            raise VoiceProviderError(f"BOTNOI returned an unexpected payload: {data!r}")
        audio_url = data.get("audio_url") or (data.get("data") or {}).get("audio_url")
        if not isinstance(audio_url, str) or not audio_url:
            raise VoiceProviderError(f"BOTNOI response had no audio_url: {data}")
        return audio_url


__all__ = ["ElevenLabsTTSAdapter", "BotnoiTTSAdapter"]
