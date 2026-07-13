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
import logging
import os
from typing import Any

from deeptutor.services.voice_realtime.agent.types import AgentLLMNotConfigured

logger = logging.getLogger(__name__)

MODEL_ENV = "DEEPTUTOR_AGENT_MODEL"
BASE_URL_ENV = "DEEPTUTOR_AGENT_BASE_URL"
API_KEY_ENV = "DEEPTUTOR_AGENT_API_KEY"
# Force the provider spec by NAME instead of letting it be inferred from the
# model name. An OpenAI-compatible host (e.g. Groq) otherwise misroutes: model
# `qwen/*` resolves to the dashscope provider, which injects dashscope-only
# params the host rejects. Set `openai` (the generic OpenAI-compat spec) so the
# endpoint wins. Unset ⇒ today's model-name inference (Gemini unaffected).
# Pairs with a standalone upstream (BASE_URL + API_KEY). See
# docs/issues/llm-provider-adaptation/ and eval `_install_groq_shim`.
BINDING_ENV = "DEEPTUTOR_AGENT_BINDING"
# D0 feature flag — default OFF. Environment-based like the rest of the agent
# config (the model already requires an env var, so one switchboard, not two).
LOOP_ENV = "DEEPTUTOR_AGENT_LOOP"
# Optional latency/capability tuning knobs — unset ⇒ loop defaults (byte-identical
# to today). Env-driven like the rest of the agent config so a deployment can
# trim per-step delay on light DOMs without a code change.
STEP_DELAY_ENV = "DEEPTUTOR_AGENT_STEP_DELAY"
MAX_STEPS_ENV = "DEEPTUTOR_AGENT_MAX_STEPS"


@dataclass(frozen=True)
class AgentLLMSettings:
    model: str
    base_url: str | None = None
    api_key: str | None = None
    binding: str | None = None


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def is_configured() -> bool:
    return bool(_env(MODEL_ENV))


def agent_loop_enabled() -> bool:
    """D0 gate: the loop takes turns only when explicitly switched on AND a
    model is configured. Off ⇒ the voice pipeline behaves exactly as today."""
    return _env(LOOP_ENV).lower() in {"1", "true", "yes"} and is_configured()


def step_delay_override() -> float | None:
    """Optional override for the loop's between-step settle delay (seconds).

    Unset (or invalid/negative) ⇒ ``None`` so the loop keeps its conservative
    default (``loop.DEFAULT_STEP_DELAY_S``), which suits animation-heavy DOMs. A
    deployment on light pages can set e.g. ``0.4`` (page-agent's default) to trim
    latency."""
    raw = _env(STEP_DELAY_ENV)
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def max_steps_override() -> int | None:
    """Optional override for the loop's max step budget. Unset (or invalid/<1)
    ⇒ ``None`` so the loop keeps ``loop.DEFAULT_MAX_STEPS``."""
    raw = _env(MAX_STEPS_ENV)
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 1 else None


def resolve_agent_llm() -> AgentLLMSettings:
    """Resolve the agent model or raise with a message that names the fix."""
    model = _env(MODEL_ENV)
    base_url = _env(BASE_URL_ENV)
    api_key = _env(API_KEY_ENV)
    binding = _env(BINDING_ENV)

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

    return AgentLLMSettings(
        model=model,
        base_url=base_url or None,
        api_key=api_key or None,
        binding=binding or None,
    )


async def think(system_prompt: str, user_prompt: str, settings: AgentLLMSettings) -> str:
    """One completion for one loop step. Returns raw text; the fixer parses it.

    ``services.llm.complete()`` accepts per-call model/base_url/api_key and
    carries its own retry policy, so this stays a thin seam — tests replace it.

    Three calls the evaluation didn't need but our text-transport does:

    * ``response_format={"type": "json_object"}`` — page-agent's real edge is a
      forced ``tool_choice`` that makes malformed output structurally
      impossible; ``complete()`` has no tool-calling seam (it returns text
      only), so this is the closest equivalent. Already a house pattern (see
      ``tools/question/question_extractor.py``) and self-gating: unsupported
      providers get it silently dropped by ``_sanitize_call_kwargs``.
    * ``reasoning_effort="minimal"`` — a hybrid-thinking model can preface the
      JSON with a long reasoning block; a stray brace in that prose is enough
      to break the fixer's bracket-matching extraction. Same value voice chat
      turns already use (``pipeline._VOICE_REASONING_EFFORT``).
    * ``temperature=0.2`` — action selection should be closer to deterministic
      than prose, same reasoning as ``pipeline._VOICE_TEMPERATURE``.
    """
    from deeptutor.services.llm import complete_with_usage

    kwargs: dict[str, Any] = {
        "response_format": {"type": "json_object"},
        "reasoning_effort": "minimal",
        "temperature": 0.2,
        # Fail FAST: complete()'s default policy retries a 429 up to 9 times
        # with exponential backoff — on a free tier whose binding limit is
        # REQUESTS per minute, that storm re-pins the very limit it is waiting
        # out (observed live: attempt 5/9, 80s backoff, RPM 5/5 solid red).
        # The loop is its own retry mechanism: one quick retry, then end the
        # run with an honest spoken line.
        "max_retries": 1,
    }
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    if settings.api_key:
        kwargs["api_key"] = settings.api_key
    if settings.binding:
        # Force the provider spec by name so an OpenAI-compat endpoint isn't
        # misrouted by model-name inference (see BINDING_ENV).
        kwargs["binding"] = settings.binding

    # Name the upstream on every step. Paid-for lesson: a stale shell env kept
    # the loop on a quota-dead provider while the operator believed they had
    # switched (.env.agent edits only land on re-source + restart) — this line
    # is what makes that visible in the log instead of a silent 429 storm.
    logger.info(
        "agent think: model=%s upstream=%s",
        settings.model,
        settings.base_url or "app-catalog",
    )

    response = await complete_with_usage(
        user_prompt,
        system_prompt=system_prompt,
        model=settings.model,
        **kwargs,
    )
    # Exact per-call token cost — the provider returns it; plain complete()
    # drops it. One line per LLM round; paired with the loop's "steps=N" this
    # gives tokens-per-call AND rounds-per-turn for the voice agent from the log
    # alone (the offline eval had to estimate with tiktoken; this is the real
    # provider count).
    usage = response.usage or {}
    logger.info(
        "agent llm usage: model=%s prompt=%s completion=%s total=%s",
        settings.model,
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
        usage.get("total_tokens", 0),
    )
    return response.content or ""
