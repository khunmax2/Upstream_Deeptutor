"""UIAgentTaskTool — the semantic door into the loop, gated on the D0 flag.

The routing lesson from live testing: lexical verb-matching can't cover how
people actually phrase tasks, so the chat LLM routes via this tool. These
tests pin the gate (flag off ⇒ the tool refuses and says why), the handoff
result, and the system-prompt advertisement that must appear ONLY while the
loop is really available — a model must never be sold a tool that goes
nowhere.
"""

from __future__ import annotations

import pytest

from deeptutor.services.voice_realtime import pipeline as pipe
from deeptutor.services.voice_realtime import ui_control

MANIFEST = {
    "pages": [{"id": "settings", "label": "หน้าตั้งค่า"}],
    "actions": [],
}


def _flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_AGENT_LOOP", "1")
    monkeypatch.setenv("DEEPTUTOR_AGENT_MODEL", "gemini-2.5-flash")


def _flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPTUTOR_AGENT_LOOP", raising=False)
    monkeypatch.delenv("DEEPTUTOR_AGENT_MODEL", raising=False)


# ── execute(): availability is checked per call, not at registration ──


@pytest.mark.asyncio
async def test_execute_refuses_when_the_loop_is_off(monkeypatch):
    _flag_off(monkeypatch)
    result = await ui_control.UIAgentTaskTool().execute(task="ไปตั้งค่าแล้วเปลี่ยนธีม")
    assert not result.success
    assert "not available" in result.content
    assert ui_control.UI_NAVIGATE_TOOL in result.content  # steers the model back


@pytest.mark.asyncio
async def test_execute_hands_off_when_enabled(monkeypatch):
    _flag_on(monkeypatch)
    result = await ui_control.UIAgentTaskTool().execute(task="ไปตั้งค่าแล้วเปลี่ยนธีม")
    assert result.success
    assert "Say NOTHING" in result.content  # one voice on the call, not two


@pytest.mark.asyncio
async def test_execute_rejects_an_empty_task(monkeypatch):
    _flag_on(monkeypatch)
    result = await ui_control.UIAgentTaskTool().execute(task="   ")
    assert not result.success


# ── system-block advertisement: only sold while actually available ──


def _system_block(monkeypatch: pytest.MonkeyPatch) -> str:
    ctx = pipe.build_voice_context(
        transcript="q", history=[], session_id="s", knowledge_bases=[], ui_manifest=MANIFEST
    )
    block = ui_control.VoiceUICapability().system_block(ctx, language="th", prompts={})
    assert block is not None
    return block.content


def test_prompt_advertises_the_tool_when_enabled(monkeypatch):
    _flag_on(monkeypatch)
    content = _system_block(monkeypatch)
    assert ui_control.UI_AGENT_TASK_TOOL in content
    assert "MULTI-STEP TASKS" in content


def test_prompt_stays_silent_when_disabled(monkeypatch):
    _flag_off(monkeypatch)
    content = _system_block(monkeypatch)
    assert ui_control.UI_AGENT_TASK_TOOL not in content


def test_tool_is_registered_and_owned():
    ui_control.install_ui_control()
    from deeptutor.runtime.registry.tool_registry import get_tool_registry

    assert get_tool_registry().get(ui_control.UI_AGENT_TASK_TOOL) is not None
    assert ui_control.UI_AGENT_TASK_TOOL in ui_control.VoiceUICapability.owned_tools


def test_prompt_carves_the_override_into_the_navigate_rules(monkeypatch):
    """The live bug: ui_navigate's imperatives won over the far-away MULTI-STEP
    paragraph. The override must live inside the navigate section itself."""
    _flag_on(monkeypatch)
    content = _system_block(monkeypatch)
    assert "OVERRIDE — WHEN THE REQUEST IS MORE THAN NAVIGATION" in content
    assert "ไปตั้งค่าเปลี่ยนธีมมืด" in content  # the exact failure, taught back


def test_navigate_override_absent_when_disabled(monkeypatch):
    _flag_off(monkeypatch)
    content = _system_block(monkeypatch)
    assert "OVERRIDE — WHEN THE REQUEST IS MORE THAN NAVIGATION" not in content
