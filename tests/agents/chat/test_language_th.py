"""Thai is preserved through the chat pipeline and surfaces in the directive."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.agents.chat.prompt_blocks import ChatPromptAssembler


@pytest.fixture(autouse=True)
def _fake_llm_config(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(
        binding="openai",
        model="gpt-test",
        api_key="sk-test",
        base_url="https://example.test/v1",
        api_version=None,
    )
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: cfg,
    )
    monkeypatch.setattr("deeptutor.agents.base_agent.get_llm_config", lambda: cfg)


def test_pipeline_keeps_thai_language() -> None:
    # th must NOT be collapsed back to en/zh.
    assert AgenticChatPipeline(language="th").language == "th"
    assert AgenticChatPipeline(language="thai").language == "th"
    assert AgenticChatPipeline(language="zh-CN").language == "zh"


def test_prompt_assembler_keeps_thai_language() -> None:
    assert ChatPromptAssembler(prompts={}, language="th").language == "th"


def test_agentic_chat_system_prompt_has_thai_directive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRegistry:
        def build_prompt_text(self, *_args, **_kwargs) -> str:
            return "- tool"

    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_tool_registry",
        lambda: FakeRegistry(),
    )

    from deeptutor.core.context import UnifiedContext

    ctx = UnifiedContext()
    th_prompt = AgenticChatPipeline(language="th")._build_system_prompt([], ctx)

    # The shared directive must name the Thai language, never echo the raw code.
    assert "ภาษาไทย" in th_prompt
    assert "strictly in th" not in th_prompt
