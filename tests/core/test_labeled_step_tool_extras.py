"""Regression: the shared agentic loop must preserve Gemini 3's REQUIRED
``thought_signature`` through a tool round, exactly like the chat agent loop does.

Gemini 3 rides a mandatory ``thought_signature`` in ``extra_content`` on each
streamed tool-call delta (OpenAI-compat endpoint, via pydantic ``model_extra``)
and 400s any follow-up request whose replayed assistant message drops it
("missing a thought_signature in functionCall parts"). ``deep_question`` /
``deep_research`` run on ``core.agentic`` (``labeled_step`` + ``loop``), so the
signature must survive (a) accumulation into ``tool_calls`` and (b) the
assistant-message replay. See ``tests/agents/chat/test_agent_loop.py`` for the
chat-loop equivalent.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.core.agentic.labeled_step import run_labeled_step
from deeptutor.core.stream_bus import StreamBus

SIGNATURE = {"extra_content": {"google": {"thought_signature": "sig-xyz789"}}}


def _tool_chunk() -> SimpleNamespace:
    """A single streamed chunk: the TOOL label plus one tool call whose delta
    carries the Gemini ``model_extra`` (thought_signature)."""
    delta = SimpleNamespace(
        content="``TOOL``",
        tool_calls=[
            SimpleNamespace(
                index=0,
                id="call_1",
                function=SimpleNamespace(name="rag", arguments='{"q":"x"}'),
                # Unrecognized provider fields ride pydantic's model_extra on the
                # real SDK objects (Gemini 3's extra_content lives here).
                model_extra=SIGNATURE,
            )
        ],
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason="tool_calls")],
        usage=None,
    )


async def _async_stream(chunks: list[SimpleNamespace]):
    for chunk in chunks:
        yield chunk


class _Client:
    def __init__(self, chunks: list[SimpleNamespace]) -> None:
        self._chunks = chunks

        class _Completions:
            def __init__(self, parent: _Client) -> None:
                self.parent = parent

            async def create(self, **kwargs: Any):
                return _async_stream(self.parent._chunks)

        class _Chat:
            def __init__(self, parent: _Client) -> None:
                self.completions = _Completions(parent)

        self.chat = _Chat(self)


async def _run_step() -> Any:
    bus = StreamBus()

    async def _consume() -> None:
        async for _ in bus.subscribe():
            pass

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    try:
        return await run_labeled_step(
            client=_Client([_tool_chunk()]),
            model="gemini-3-pro",
            messages=[{"role": "user", "content": "hi"}],
            completion_kwargs={},
            tool_schemas=[
                {
                    "type": "function",
                    "function": {
                        "name": "rag",
                        "description": "retrieve",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            allowed_labels=("FINISH", "TOOL", "THINK", "PAUSE"),
            final_labels=frozenset({"FINISH"}),
            tool_label="TOOL",
            stream=bus,
            source="chat",
            stage="responding",
            iter_meta={"label": "Reasoning", "trace_id": "iter-1"},
        )
    finally:
        await bus.close()
        await consumer


@pytest.mark.asyncio
async def test_labeled_step_preserves_gemini_thought_signature() -> None:
    """Accumulation seam: the tool call keeps its provider extra."""
    result = await _run_step()
    assert result.label == "TOOL"
    assert result.tool_calls and result.tool_calls[0]["name"] == "rag"
    assert result.tool_calls[0].get("extra") == SIGNATURE, (
        "thought_signature (model_extra) was dropped during accumulation"
    )


def test_build_tool_call_entries_echoes_provider_extras() -> None:
    """Replay seam: the shared entry builder echoes the extra back verbatim."""
    from deeptutor.core.agentic.loop import build_tool_call_entries

    entries = build_tool_call_entries(
        [{"id": "call_1", "name": "rag", "arguments": "{}", "extra": SIGNATURE}]
    )
    assert entries[0]["function"]["name"] == "rag"
    assert entries[0]["extra_content"] == SIGNATURE["extra_content"]
