"""Tests for the iApp Thai STT/TTS adapters and their catalog wiring."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from deeptutor.services.config.provider_runtime import STT_PROVIDERS, TTS_PROVIDERS
from deeptutor.services.voice.adapters import (
    STT_ADAPTERS,
    TTS_ADAPTERS,
    get_stt_adapter,
    get_tts_adapter,
)
from deeptutor.services.voice.adapters.iapp import IAppSTTAdapter, IAppTTSAdapter
from deeptutor.services.voice.base import VoiceProviderError, VoiceProviderHTTPError
from deeptutor.services.voice.config import STTConfig, TTSConfig


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


# ── registry / catalog wiring ────────────────────────────────────────────────


def test_iapp_adapters_are_registered() -> None:
    assert isinstance(get_tts_adapter("iapp"), IAppTTSAdapter)
    assert isinstance(get_stt_adapter("iapp"), IAppSTTAdapter)


def test_iapp_catalog_specs_resolve_to_registered_adapters() -> None:
    assert TTS_PROVIDERS["iapp"].adapter in TTS_ADAPTERS
    assert STT_PROVIDERS["iapp"].adapter in STT_ADAPTERS
    assert STT_PROVIDERS["iapp"].default_model == "pro"


# ── TTS ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_iapp_tts_posts_text_and_reports_pcm(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["json"] = kwargs.get("json")
        return _resp(200, content=b"\x01\x02" * 8, content_type="application/octet-stream")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    config = TTSConfig(
        model="kaitom-v3",
        adapter="iapp",
        api_key="iapp-key",
        base_url="https://api.iapp.co.th/v3/store",
        speed=1.5,  # out of range — must be clamped to 1.2
    )
    audio, content_type = await IAppTTSAdapter().synthesize("สวัสดีครับ", config)

    assert audio == b"\x01\x02" * 8
    assert content_type.startswith("audio/pcm")
    assert "rate=24000" in content_type
    assert captured["url"].endswith("/audio/tts")
    assert captured["headers"]["apikey"] == "iapp-key"
    assert captured["json"]["text"] == "สวัสดีครับ"
    assert captured["json"]["speed"] == 1.2


@pytest.mark.asyncio
async def test_iapp_tts_rejects_json_body_masquerading_as_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        return _resp(200, json_body={"detail": "queued"}, content_type="application/json")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    config = TTSConfig(model="kaitom-v3", adapter="iapp", api_key="k", base_url="https://x")
    with pytest.raises(VoiceProviderError, match="JSON instead of audio"):
        await IAppTTSAdapter().synthesize("hi", config)


@pytest.mark.asyncio
async def test_iapp_tts_raises_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        return _resp(401, content=b"bad key")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    config = TTSConfig(model="kaitom-v3", adapter="iapp", api_key="bad", base_url="https://x")
    with pytest.raises(VoiceProviderHTTPError) as exc:
        await IAppTTSAdapter().synthesize("hi", config)
    assert exc.value.status_code == 401


# ── STT ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_iapp_stt_pro_variant_joins_output_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["files"] = kwargs.get("files")
        captured["data"] = kwargs.get("data")
        return _resp(
            200,
            json_body={
                "output": [
                    {"text": "สวัสดีครับ", "segment": 0},
                    {"text": "ยินดีต้อนรับ", "segment": 1},
                ],
                "audio_duration_in_seconds": 3.2,
            },
            content_type="application/json",
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    config = STTConfig(
        model="pro", adapter="iapp", api_key="iapp-key", base_url="https://x/v3/store"
    )
    text = await IAppSTTAdapter().transcribe(
        b"WAVDATA", config, filename="u.wav", content_type="audio/wav"
    )

    assert text == "สวัสดีครับ ยินดีต้อนรับ"
    assert captured["url"].endswith("/speech/speech-to-text/pro")
    assert captured["headers"]["apikey"] == "iapp-key"
    assert captured["files"]["file"][0] == "u.wav"
    assert not captured["data"]  # pro variant sends no chunk_size


@pytest.mark.asyncio
async def test_iapp_stt_base_variant_endpoint_and_chunk_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["url"] = url
        captured["data"] = kwargs.get("data")
        return _resp(200, json_body={"output": [{"text": "ok"}]}, content_type="application/json")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    config = STTConfig(model="base", adapter="iapp", api_key="k", base_url="https://x/v3/store")
    await IAppSTTAdapter().transcribe(b"AUDIO", config)

    assert captured["url"].endswith("/speech/speech-to-text/base")
    assert captured["data"] == {"chunk_size": "7"}


@pytest.mark.asyncio
async def test_iapp_stt_raises_on_error_body(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        return _resp(
            500,
            json_body={"detail": "Error transcribing file: '50359' is not a valid task"},
            content_type="application/json",
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    config = STTConfig(model="base", adapter="iapp", api_key="k", base_url="https://x")
    with pytest.raises(VoiceProviderHTTPError) as exc:
        await IAppSTTAdapter().transcribe(b"AUDIO", config)
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_iapp_stt_no_transcript_in_body_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        return _resp(200, json_body={"output": []}, content_type="application/json")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    config = STTConfig(model="pro", adapter="iapp", api_key="k", base_url="https://x")
    with pytest.raises(VoiceProviderError, match="no transcript"):
        await IAppSTTAdapter().transcribe(b"AUDIO", config)
