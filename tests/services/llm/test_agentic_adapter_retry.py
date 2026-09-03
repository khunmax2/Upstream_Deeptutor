"""The agentic adapter must retry transient provider errors.

Every Level-2 capability runs through ``runtime.agentic``'s OpenAI facade, not
through ``services.llm.factory``. The facade used to call ``provider.chat()``
directly, so the retry loop the factory path relies on — 8 attempts with
backoff, with "429" and "rate limit" already classified transient — never ran
for a capability turn. A rate-limited turn died on the first error.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.runtime.agentic.client import _ProviderOpenAIAdapter
from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse


class _RateLimited(Exception):
    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("Error code: 429 - rate limit exceeded")
        self.retry_after = retry_after


class _FlakyProvider(LLMProvider):
    """Fails the first ``failures`` calls with a 429, then answers."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self._remaining = failures
        self.chat_calls = 0
        self.stream_calls = 0

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        self.chat_calls += 1
        if self._remaining:
            self._remaining -= 1
            raise _RateLimited(0.0)
        return LLMResponse(content="ok", finish_reason="stop")

    async def chat_stream(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        self.stream_calls += 1
        if self._remaining:
            self._remaining -= 1
            raise _RateLimited(0.0)
        return LLMResponse(content="ok", finish_reason="stop")

    def get_default_model(self) -> str:
        return "test-model"


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.base.asyncio.sleep",
        _fake_sleep,
    )


@pytest.mark.asyncio
async def test_completion_retries_a_rate_limit() -> None:
    provider = _FlakyProvider(failures=2)
    adapter = _ProviderOpenAIAdapter(provider)

    result = await adapter.chat.completions.create(
        messages=[{"role": "user", "content": "hi"}],
        model="m",
    )

    assert provider.chat_calls == 3
    assert result.choices[0].message.content == "ok"


@pytest.mark.asyncio
async def test_completion_surfaces_the_error_once_retries_are_exhausted() -> None:
    provider = _FlakyProvider(failures=99)
    adapter = _ProviderOpenAIAdapter(provider)

    result = await adapter.chat.completions.create(
        messages=[{"role": "user", "content": "hi"}],
        model="m",
    )

    # The loop gives up rather than looping forever, and the failure reaches the
    # caller instead of being silently swallowed.
    assert provider.chat_calls > 1
    assert "429" in (result.choices[0].message.content or "")


@pytest.mark.asyncio
async def test_streaming_retries_a_rate_limit() -> None:
    provider = _FlakyProvider(failures=1)
    adapter = _ProviderOpenAIAdapter(provider)

    stream = await adapter.chat.completions.create(
        messages=[{"role": "user", "content": "hi"}],
        model="m",
        stream=True,
    )
    async for _chunk in stream:
        pass

    assert provider.stream_calls == 2
