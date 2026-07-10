"""Agent-model resolution + the one LLM call the loop makes per step.

The loop must NOT run on the app's chat model: the chat catalog may be a lite
tier, and the evaluation proved a lite tier wrecks agentic loops (erratic
behavior that looked like product bugs). So the agent model is configured
separately and a half-configured or missing setup fails LOUDLY — never a
silent fallback to the chat model, because a silently-wrong model produces
conclusions that get trusted.

Configuration (environment):
- ``DEEPTUTOR_AGENT_MODEL``      required to enable the loop
- ``DEEPTUTOR_AGENT_BASE_URL``   optional — together with _API_KEY, a fully
- ``DEEPTUTOR_AGENT_API_KEY``    standalone OpenAI-compatible upstream
Model alone = use the app's provider chain but pin this model (the pattern
``LLM_PROXY_MODEL`` proved on the evaluation branch, recreated here because
that branch's proxy is not part of this one).
"""

from __future__ import annotations

from dataclasses import dataclass
import os

from deeptutor.services.voice_realtime.agent.types import AgentLLMNotConfigured

MODEL_ENV = "DEEPTUTOR_AGENT_MODEL"
BASE_URL_ENV = "DEEPTUTOR_AGENT_BASE_URL"
API_KEY_ENV = "DEEPTUTOR_AGENT_API_KEY"
# D0 feature flag — default OFF. Environment-based like the rest of the agent
# config (the model already requires an env var, so one switchboard, not two).
LOOP_ENV = "DEEPTUTOR_AGENT_LOOP"


@dataclass(frozen=True)
class AgentLLMSettings:
    model: str
    base_url: str | None = None
    api_key: str | None = None


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def is_configured() -> bool:
    return bool(_env(MODEL_ENV))


def agent_loop_enabled() -> bool:
    """D0 gate: the loop takes turns only when explicitly switched on AND a
    model is configured. Off ⇒ the voice pipeline behaves exactly as today."""
    return _env(LOOP_ENV).lower() in {"1", "true", "yes"} and is_configured()


def resolve_agent_llm() -> AgentLLMSettings:
    """Resolve the agent model or raise with a message that names the fix."""
    model = _env(MODEL_ENV)
    base_url = _env(BASE_URL_ENV)
    api_key = _env(API_KEY_ENV)

    if not model:
        raise AgentLLMNotConfigured(
            f"In-page agent is disabled: set {MODEL_ENV} (a full-tier model — "
            "lite tiers cannot hold the agent loop)."
        )
    # A standalone upstream needs both halves; half-configured must not fall
    # back silently to the app's provider with a key meant for another host.
    if bool(base_url) != bool(api_key):
        missing = API_KEY_ENV if base_url else BASE_URL_ENV
        raise AgentLLMNotConfigured(f"In-page agent upstream is half-configured: set {missing}.")

    return AgentLLMSettings(model=model, base_url=base_url or None, api_key=api_key or None)


async def think(system_prompt: str, user_prompt: str, settings: AgentLLMSettings) -> str:
    """One completion for one loop step. Returns raw text; the fixer parses it.

    ``services.llm.complete()`` accepts per-call model/base_url/api_key and
    carries its own retry policy, so this stays a thin seam — tests replace it.
    """
    from deeptutor.services.llm import complete

    kwargs: dict[str, str] = {}
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    if settings.api_key:
        kwargs["api_key"] = settings.api_key

    return await complete(
        user_prompt,
        system_prompt=system_prompt,
        model=settings.model,
        **kwargs,
    )
