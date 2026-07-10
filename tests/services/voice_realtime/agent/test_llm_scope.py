"""Agent-model resolution: loud failures, never a silent chat-model fallback."""

import pytest

from deeptutor.services.voice_realtime.agent import (
    AgentLLMNotConfigured,
    is_configured,
    resolve_agent_llm,
)
from deeptutor.services.voice_realtime.agent.llm import API_KEY_ENV, BASE_URL_ENV, MODEL_ENV


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (MODEL_ENV, BASE_URL_ENV, API_KEY_ENV):
        monkeypatch.delenv(name, raising=False)


def test_unset_model_disables_with_actionable_message():
    assert not is_configured()
    with pytest.raises(AgentLLMNotConfigured, match=MODEL_ENV):
        resolve_agent_llm()


def test_model_alone_pins_model_on_default_provider(monkeypatch):
    monkeypatch.setenv(MODEL_ENV, "gemini-2.5-flash")
    settings = resolve_agent_llm()
    assert settings.model == "gemini-2.5-flash"
    assert settings.base_url is None and settings.api_key is None


def test_full_standalone_upstream(monkeypatch):
    monkeypatch.setenv(MODEL_ENV, "m")
    monkeypatch.setenv(BASE_URL_ENV, "https://llm.example/v1")
    monkeypatch.setenv(API_KEY_ENV, "k")
    settings = resolve_agent_llm()
    assert settings.base_url == "https://llm.example/v1" and settings.api_key == "k"


@pytest.mark.parametrize("present", [BASE_URL_ENV, API_KEY_ENV])
def test_half_configured_upstream_fails_loudly(monkeypatch, present):
    monkeypatch.setenv(MODEL_ENV, "m")
    monkeypatch.setenv(present, "value")
    with pytest.raises(AgentLLMNotConfigured, match="half-configured"):
        resolve_agent_llm()
