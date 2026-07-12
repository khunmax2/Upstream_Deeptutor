"""Intent classifier: the two-bucket voice router. Off unless configured; a
failure defers to today's behaviour and never raises."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.voice_realtime import intent_classifier as ic
from deeptutor.services.voice_realtime.intent_classifier import FLAG_ENV, MODEL_ENV


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (FLAG_ENV, MODEL_ENV, "DEEPTUTOR_VOICE_CLASSIFIER_BASE_URL",
                 "DEEPTUTOR_VOICE_CLASSIFIER_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def _enable(monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "1")
    monkeypatch.setenv(MODEL_ENV, "gemini-flash-lite-latest")


def _mock_complete(monkeypatch, reply: str | Exception):
    calls: dict[str, Any] = {}

    async def fake(prompt: str, **kwargs: Any) -> str:
        calls["prompt"] = prompt
        calls["kwargs"] = kwargs
        if isinstance(reply, Exception):
            raise reply
        return reply

    import deeptutor.services.llm as llm_module

    monkeypatch.setattr(llm_module, "complete", fake)
    return calls


def test_disabled_without_flag_or_model(monkeypatch):
    assert not ic.classifier_enabled()
    monkeypatch.setenv(FLAG_ENV, "1")  # flag but no model
    assert not ic.classifier_enabled()


@pytest.mark.asyncio
async def test_disabled_returns_none(monkeypatch):
    _mock_complete(monkeypatch, '{"intent": "ui_task"}')
    assert await ic.classify("สร้างหนังสือใหม่") is None  # flag off


@pytest.mark.asyncio
async def test_ui_task_and_chat_parsed(monkeypatch):
    _enable(monkeypatch)
    _mock_complete(monkeypatch, '{"intent": "ui_task"}')
    assert await ic.classify("สร้างหนังสือใหม่ให้หน่อย") == "ui_task"
    _mock_complete(monkeypatch, 'sure: {"intent": "chat"}')
    assert await ic.classify("ราคาทองเท่าไหร่") == "chat"


@pytest.mark.asyncio
async def test_unclear_reply_biases_to_ui_task(monkeypatch):
    _enable(monkeypatch)
    _mock_complete(monkeypatch, "I think this is a command")
    assert await ic.classify("อะไรสักอย่าง") == "ui_task"


@pytest.mark.asyncio
async def test_failure_returns_none_not_raises(monkeypatch):
    _enable(monkeypatch)
    _mock_complete(monkeypatch, RuntimeError("429"))
    assert await ic.classify("สร้างหนังสือ") is None


@pytest.mark.asyncio
async def test_empty_transcript_returns_none(monkeypatch):
    _enable(monkeypatch)
    _mock_complete(monkeypatch, '{"intent": "ui_task"}')
    assert await ic.classify("   ") is None


@pytest.mark.asyncio
async def test_context_and_model_passed(monkeypatch):
    _enable(monkeypatch)
    calls = _mock_complete(monkeypatch, '{"intent": "ui_task"}')
    await ic.classify("สร้างหนังสือ", {"path": "/home", "summary": "หน้าหลัก"})
    assert calls["kwargs"]["model"] == "gemini-flash-lite-latest"
    assert "หน้าปัจจุบัน: /home" in calls["prompt"]
    assert calls["kwargs"]["response_format"] == {"type": "json_object"}
