"""A 429 carrying Retry-After decides the wait, not the fixed backoff schedule.

The provider tells us exactly how long the window is (Gemini's free tier returns
``retryDelay: 21s``). Before this, the exception was flattened into a string
before anything could read that hint, so the loop slept its own schedule —
hammering the provider early or idling far past the window.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse


class _RateLimited(Exception):
    """A provider error shaped like an SDK rate-limit error."""

    def __init__(self, retry_after: float | None) -> None:
        super().__init__("Error code: 429 - rate limit exceeded")
        self.retry_after = retry_after


class _FailsThenSucceeds(LLMProvider):
    """Raises the given exceptions in order, then answers."""

    def __init__(self, failures: list[Exception]) -> None:
        super().__init__()
        self._failures = list(failures)
        self.attempts = 0

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        self.attempts += 1
        if self._failures:
            raise self._failures.pop(0)
        return LLMResponse(content="ok", finish_reason="stop")

    def get_default_model(self) -> str:
        return "test-model"


@pytest.fixture
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record sleep durations instead of waiting them out."""
    recorded: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.base.asyncio.sleep",
        _fake_sleep,
    )
    return recorded


@pytest.mark.asyncio
async def test_server_retry_after_overrides_the_schedule(slept: list[float]) -> None:
    provider = _FailsThenSucceeds([_RateLimited(21.0)])

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hi"}],
        model="m",
        retry_delays=(5.0, 10.0),
    )

    assert response.content == "ok"
    assert provider.attempts == 2
    assert slept == [21.0]


@pytest.mark.asyncio
async def test_falls_back_to_the_schedule_without_a_hint(slept: list[float]) -> None:
    provider = _FailsThenSucceeds([_RateLimited(None)])

    await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hi"}],
        model="m",
        retry_delays=(5.0, 10.0),
    )

    assert slept == [5.0]


@pytest.mark.asyncio
async def test_a_long_retry_after_is_capped(slept: list[float]) -> None:
    provider = _FailsThenSucceeds([_RateLimited(9999.0)])

    await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hi"}],
        model="m",
        retry_delays=(5.0,),
    )

    assert slept == [LLMProvider._MAX_RETRY_DELAY_SECONDS]


@pytest.mark.asyncio
async def test_each_attempt_reads_its_own_hint(slept: list[float]) -> None:
    provider = _FailsThenSucceeds([_RateLimited(3.0), _RateLimited(None)])

    await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hi"}],
        model="m",
        retry_delays=(5.0, 10.0),
    )

    # First wait comes from the server, the second falls back to the schedule
    # — a stale hint must not leak into the next attempt.
    assert slept == [3.0, 10.0]
