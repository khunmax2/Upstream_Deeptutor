"""Deep Research: a confirmed outline must fit the queue it is poured into.

Found 2026-09-12 (fork UAT): mode "report", depth "quick", outline confirmed
with five subtopics -> ``RuntimeError: Queue has reached maximum capacity (2),
cannot add new topic.`` The run died after the outline, before any research.
These tests drive the real request-config -> pipeline path.
"""

from __future__ import annotations

import json
import types
from unittest.mock import patch

import pytest

from deeptutor.agents.research.pipeline import ResearchedBlock, ResearchPipeline, SubTopicItem
from deeptutor.agents.research.request_config import (
    build_research_runtime_config,
    validate_research_request_config,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.stream_bus import StreamBus


class _FakeLLM:
    binding = "openai"
    model = "gpt-x"
    api_key = "k"
    base_url = "u"
    api_version = None
    extra_headers: dict = {}
    reasoning_effort = None


class _FakeRegistry:
    def build_openai_schemas(self, _names):
        return []

    def build_prompt_text(self, _names, **_kwargs):
        return "- none"

    def get(self, _name):
        return None

    def get_enabled(self, _names):
        return []


def _pipeline(mode: str, depth: str) -> ResearchPipeline:
    request = validate_research_request_config({"mode": mode, "depth": depth})
    runtime_config = build_research_runtime_config(
        base_config={}, request_config=request, kb_name=None
    )
    with (
        patch("deeptutor.agents.research.pipeline.get_llm_config", lambda: _FakeLLM()),
        patch("deeptutor.agents.research.pipeline.get_tool_registry", lambda: _FakeRegistry()),
    ):
        return ResearchPipeline(language="en", runtime_config=runtime_config)


FIVE = [SubTopicItem(title=f"Subtopic {i}", overview=f"overview {i}") for i in range(1, 6)]


@pytest.mark.asyncio
async def test_quick_report_runs_a_confirmed_outline_longer_than_its_queue_cap() -> None:
    pipeline = _pipeline("report", "quick")

    async def fake_research_block(self, *, block, queue, citations, topic, context, stream, client):
        queue.mark_researching(block.block_id)
        queue.mark_completed(block.block_id)
        return ResearchedBlock(block=block, knowledge=f"knowledge for {block.block_id}")

    async def fake_write_report(self, *, topic, blocks, citations, stream, client):
        return f"REPORT with {len(blocks)} blocks"

    async def fake_emit(*_args, **_kwargs):
        return None

    pipeline._research_block = types.MethodType(fake_research_block, pipeline)
    pipeline._write_report = types.MethodType(fake_write_report, pipeline)
    with patch("deeptutor.agents.research.pipeline.emit_capability_result", fake_emit):
        result = await pipeline._run_inner(
            context=UnifiedContext(session_id="s1", user_message="research this"),
            topic="MacBook Air resale value",
            image_attachments=[],
            confirmed_outline=list(FIVE),
            stream=StreamBus(),
            client=None,
        )
    # Every subtopic the person confirmed is researched -- none dropped.
    assert result["response"] == "REPORT with 5 blocks"


@pytest.mark.parametrize(
    ("mode", "depth"),
    [
        ("report", "quick"),
        ("learning_path", "quick"),
        ("report", "standard"),
        ("notes", "quick"),
        ("comparison", "quick"),
    ],
)
def test_the_proposed_outline_never_exceeds_the_queue_cap(mode: str, depth: str) -> None:
    pipeline = _pipeline(mode, depth)
    raw = json.dumps({"sub_topics": [{"title": f"T{i}", "overview": ""} for i in range(1, 11)]})
    outline = pipeline._parse_outline("topic", raw)
    assert len(outline) <= pipeline.queue_max_length, (
        f"{mode}/{depth}: outline of {len(outline)} for a queue of {pipeline.queue_max_length}"
    )
