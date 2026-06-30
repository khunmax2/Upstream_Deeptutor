"""Tests for the bespoke ElevenLabs / BOTNOI TTS adapters and their catalog wiring."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from deeptutor.services.config.provider_runtime import TTS_PROVIDERS
from deeptutor.services.voice.adapters import TTS_ADAPTERS, get_tts_adapter
from deeptutor.services.voice.adapters.bespoke import BotnoiTTSAdapter, ElevenLabsTTSAdapter
from deeptutor.services.voice.base import VoiceProviderError, VoiceProviderHTTPError
from deeptutor.services.voice.config import TTSConfig


def _resp(
    status: int, *, content: bytes = b"", json_body: Any = None, content_type: str = ""
) -> httpx.Response:
    headers = {"content-type": content_type} if content_type else None
    if json_body is not None:
        resp = httpx.Response(status, json=json_body, headers=headers)
    else:
        resp = httpx.Response(status, content=content, headers=headers)
    resp.request = httpx.Request("POST", "https://example.test")
    return resp


# ── registry wiring ─────────────────────────────────────────────────────────


def test_new_adapters_are_registered() -> None:
    assert isinstance(get_tts_adapter("elevenlabs"), ElevenLabsTTSAdapter)
    assert isinstance(get_tts_adapter("botnoi"), BotnoiTTSAdapter)


def test_catalog_specs_point_at_new_adapter_keys() -> None:
    assert TTS_PROVIDERS["elevenlabs"].adapter == "elevenlabs"
    assert TTS_PROVIDERS["botnoi"].adapter == "botnoi"
    # Every spec's adapter must resolve to a registered adapter.
    for spec in TTS_PROVIDERS.values():
        assert spec.adapter in TTS_ADAPTERS, spec


# ── ElevenLabs ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_elevenlabs_posts_voice_url_and_returns_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["json"] = kwargs.get("json")
        return _resp(200, content=b"MP3DATA", content_type="audio/mpeg")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    config = TTSConfig(
        model="eleven_multilingual_v2",
        adapter="elevenlabs",
        api_key="xi-key",
        base_url="https://api.elevenlabs.io/v1",
        voice="VOICE123",
    )
    audio, content_type = await ElevenLabsTTSAdapter().synthesize("สวัสดี", config)

    assert audio == b"MP3DATA"
    assert content_type == "audio/mpeg"
    assert captured["url"].endswith("/text-to-speech/VOICE123")
    assert captured["headers"]["xi-api-key"] == "xi-key"
    assert captured["json"]["model_id"] == "eleven_multilingual_v2"
    assert captured["json"]["text"] == "สวัสดี"


@pytest.mark.asyncio
async def test_elevenlabs_requires_voice_id() -> None:
    config = TTSConfig(model="m", adapter="elevenlabs", api_key="k", base_url="https://x/v1")
    with pytest.raises(VoiceProviderError, match="voice id"):
        await ElevenLabsTTSAdapter().synthesize("hi", config)


@pytest.mark.asyncio
async def test_elevenlabs_raises_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        return _resp(401, content=b"unauthorized")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    config = TTSConfig(
        model="m", adapter="elevenlabs", api_key="bad", base_url="https://x/v1", voice="v"
    )
    with pytest.raises(VoiceProviderHTTPError) as exc:
        await ElevenLabsTTSAdapter().synthesize("hi", config)
    assert exc.value.status_code == 401


# ── BOTNOI ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_botnoi_generates_then_fetches_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["post_url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["json"] = kwargs.get("json")
        return _resp(
            200,
            json_body={"audio_url": "https://cdn.botnoi/clip.mp3"},
            content_type="application/json",
        )

    async def fake_get(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["get_url"] = url
        return _resp(200, content=b"BOTNOIMP3", content_type="audio/mpeg")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    config = TTSConfig(
        model="botnoi-voice",
        adapter="botnoi",
        api_key="tok",
        base_url="https://api-voice.botnoi.ai/openapi/v1",
        voice="3",
    )
    audio, content_type = await BotnoiTTSAdapter().synthesize("สวัสดีครับ", config)

    assert audio == b"BOTNOIMP3"
    assert content_type == "audio/mpeg"
    assert captured["post_url"].endswith("/generate_audio")
    assert captured["headers"]["Botnoi-Token"] == "tok"
    assert captured["json"]["speaker"] == "3"
    assert captured["get_url"] == "https://cdn.botnoi/clip.mp3"


@pytest.mark.asyncio
async def test_botnoi_errors_when_no_audio_url(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        return _resp(200, json_body={"message": "quota exceeded"}, content_type="application/json")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    config = TTSConfig(
        model="m", adapter="botnoi", api_key="tok", base_url="https://x/v1", voice="1"
    )
    with pytest.raises(VoiceProviderError, match="audio_url"):
        await BotnoiTTSAdapter().synthesize("hi", config)
