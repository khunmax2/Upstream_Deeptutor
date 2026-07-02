"""Tests for the voice STT guard — vocab prompt, confidence, hallucination filter."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from deeptutor.services.voice.config import STTConfig
from deeptutor.services.voice_realtime import stt_guard
from deeptutor.services.voice_realtime.stt_guard import (
    MIN_AVG_LOGPROB,
    VOCAB_PROMPT,
    screen_transcript,
    transcribe_utterance,
)

# ── screen_transcript ────────────────────────────────────────────────────────


def test_screen_accepts_normal_speech() -> None:
    ok, reason = screen_transcript("อธิบายทฤษฎีบทพีทาโกรัสหน่อย", confidence=-0.2)
    assert ok and reason == ""


def test_screen_rejects_empty() -> None:
    ok, reason = screen_transcript("   ", confidence=None)
    assert not ok and reason


def test_screen_rejects_known_hallucinations() -> None:
    for phrase in ("โปรดติดตามตอนต่อไป", "ขอบคุณสำหรับการรับชม", "กดไลค์กดแชร์ด้วยนะ"):
        ok, _ = screen_transcript(phrase, confidence=-0.3)
        assert not ok, phrase


def test_screen_keeps_long_sentence_containing_pattern() -> None:
    # A real, long utterance that merely contains a pattern must NOT be dropped.
    text = "ช่วยสรุปหน่อยว่าทำไมช่องยูทูบชอบพูดว่าโปรดติดตามตอนต่อไปตอนจบคลิป และมันมีผลกับคนดูยังไง"
    ok, _ = screen_transcript(text, confidence=-0.2)
    assert ok


def test_screen_rejects_low_confidence_but_allows_unknown() -> None:
    ok, reason = screen_transcript("อะไรสักอย่าง", confidence=MIN_AVG_LOGPROB - 0.2)
    assert not ok and reason
    # No confidence available (bespoke adapters) → text stands on its own.
    ok, _ = screen_transcript("อะไรสักอย่าง", confidence=None)
    assert ok


# ── transcribe_utterance routing ─────────────────────────────────────────────


def _stt_config(adapter: str = "openai_compat") -> STTConfig:
    return STTConfig(
        model="whisper-large-v3",
        adapter=adapter,
        api_key="k",
        base_url="https://api.groq.com/openai/v1",
    )


@pytest.mark.asyncio
async def test_verbose_path_sends_vocab_prompt_and_returns_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["url"] = url
        captured["data"] = kwargs.get("data")
        captured["files"] = kwargs.get("files")
        resp = httpx.Response(
            200,
            json={
                "text": "สวัสดีครับ DeepTutor",
                "segments": [{"avg_logprob": -0.2}, {"avg_logprob": -0.4}],
            },
        )
        resp.request = httpx.Request("POST", url)
        return resp

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(
        "deeptutor.services.config.provider_runtime.resolve_stt_runtime_config",
        lambda **kw: _stt_config(),
    )

    text, confidence = await transcribe_utterance(b"webm", language="th")

    assert text == "สวัสดีครับ DeepTutor"
    assert confidence == pytest.approx(-0.3)
    assert captured["url"].endswith("/audio/transcriptions")
    assert captured["data"]["prompt"] == VOCAB_PROMPT
    assert captured["data"]["response_format"] == "verbose_json"
    assert captured["data"]["language"] == "th"


@pytest.mark.asyncio
async def test_bespoke_adapter_falls_back_to_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_facade(audio: bytes, **kwargs: Any) -> str:
        return "ผ่าน facade"

    monkeypatch.setattr(stt_guard, "transcribe_audio", fake_facade)
    monkeypatch.setattr(
        "deeptutor.services.config.provider_runtime.resolve_stt_runtime_config",
        lambda **kw: _stt_config(adapter="iapp"),
    )

    text, confidence = await transcribe_utterance(b"webm")

    assert text == "ผ่าน facade"
    assert confidence is None
