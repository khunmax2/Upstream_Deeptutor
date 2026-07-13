"""Agent-model resolution: loud failures, never a silent chat-model fallback."""

from typing import Any

import pytest

from deeptutor.services.llm.types import TutorResponse
from deeptutor.services.voice_realtime.agent import (
    AgentLLMNotConfigured,
    AgentLLMSettings,
    is_configured,
    resolve_agent_llm,
)
from deeptutor.services.voice_realtime.agent.llm import (
    API_KEY_ENV,
    BASE_URL_ENV,
    MAX_STEPS_ENV,
    MODEL_ENV,
    STEP_DELAY_ENV,
    max_steps_override,
    step_delay_override,
    think,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (MODEL_ENV, BASE_URL_ENV, API_KEY_ENV, STEP_DELAY_ENV, MAX_STEPS_ENV):
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


# ── optional loop tuning knobs (unset ⇒ None ⇒ loop keeps its defaults) ──


def test_step_delay_override_unset_is_none():
    assert step_delay_override() is None
    assert max_steps_override() is None


def test_step_delay_override_parses_float(monkeypatch):
    monkeypatch.setenv(STEP_DELAY_ENV, "0.4")
    assert step_delay_override() == 0.4


@pytest.mark.parametrize("bad", ["", "abc", "-1"])
def test_step_delay_override_rejects_invalid_or_negative(monkeypatch, bad):
    monkeypatch.setenv(STEP_DELAY_ENV, bad)
    assert step_delay_override() is None


def test_step_delay_override_allows_zero(monkeypatch):
    monkeypatch.setenv(STEP_DELAY_ENV, "0")
    assert step_delay_override() == 0.0


def test_max_steps_override_parses_int(monkeypatch):
    monkeypatch.setenv(MAX_STEPS_ENV, "40")
    assert max_steps_override() == 40


@pytest.mark.parametrize("bad", ["", "abc", "0", "-3", "2.5"])
def test_max_steps_override_rejects_invalid_or_below_one(monkeypatch, bad):
    monkeypatch.setenv(MAX_STEPS_ENV, bad)
    assert max_steps_override() is None


# ── think(): the JSON-mode / reasoning / temperature scoping ──
#
# page-agent's real edge over a bare "please reply in JSON" prompt is a
# provider-level forced tool_choice. complete() has no tool-calling seam, so
# response_format=json_object is the closest equivalent — these tests pin
# that every call actually carries it (a regression here silently degrades
# reliability back to prompt-only, which is what motivated this in the
# first place).


def _capture_complete(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    async def fake_complete(prompt: str, **kwargs: Any):
        calls["prompt"] = prompt
        calls["kwargs"] = kwargs
        # think() now calls complete_with_usage() → a TutorResponse, so it can
        # log exact per-call token usage (plain complete() drops it).
        return TutorResponse(
            content='{"action": {"wait": {"seconds": 1}}}',
            usage={"prompt_tokens": 123, "completion_tokens": 7, "total_tokens": 130},
        )

    import deeptutor.services.llm as llm_module

    monkeypatch.setattr(llm_module, "complete_with_usage", fake_complete)
    return calls


@pytest.mark.asyncio
async def test_think_forces_json_mode_and_scopes_reasoning_and_temperature(monkeypatch):
    calls = _capture_complete(monkeypatch)
    settings = AgentLLMSettings(model="gemini-2.5-flash")

    await think("system prompt", "user prompt", settings)

    assert calls["prompt"] == "user prompt"
    assert calls["kwargs"]["system_prompt"] == "system prompt"
    assert calls["kwargs"]["model"] == "gemini-2.5-flash"
    assert calls["kwargs"]["response_format"] == {"type": "json_object"}
    assert calls["kwargs"]["reasoning_effort"] == "minimal"
    assert calls["kwargs"]["temperature"] == 0.2
    # Fail-fast: the default 9-attempt backoff storm burned RPM against the
    # very limit it was waiting out (observed live on the free tier).
    assert calls["kwargs"]["max_retries"] == 1


@pytest.mark.asyncio
async def test_think_forwards_standalone_upstream(monkeypatch):
    calls = _capture_complete(monkeypatch)
    settings = AgentLLMSettings(model="m", base_url="https://llm.example/v1", api_key="k")

    await think("s", "u", settings)

    assert calls["kwargs"]["base_url"] == "https://llm.example/v1"
    assert calls["kwargs"]["api_key"] == "k"


@pytest.mark.asyncio
async def test_think_omits_base_url_and_api_key_in_model_alone_mode(monkeypatch):
    calls = _capture_complete(monkeypatch)
    settings = AgentLLMSettings(model="m")

    await think("s", "u", settings)

    assert "base_url" not in calls["kwargs"]
    assert "api_key" not in calls["kwargs"]


@pytest.mark.asyncio
async def test_think_returns_content_and_logs_exact_usage(monkeypatch, caplog):
    """think() surfaces the provider's real token counts (not a tiktoken guess)
    and still returns just the text, so the loop's `think` contract is unchanged."""
    _capture_complete(monkeypatch)
    settings = AgentLLMSettings(model="gemini-2.5-flash")

    with caplog.at_level("INFO"):
        out = await think("system prompt", "user prompt", settings)

    assert out == '{"action": {"wait": {"seconds": 1}}}'  # still text only
    assert any(
        "agent llm usage" in r.message and "total=130" in r.message and "prompt=123" in r.message
        for r in caplog.records
    )
