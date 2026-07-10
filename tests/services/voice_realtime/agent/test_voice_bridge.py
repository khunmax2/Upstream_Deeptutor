"""AgentVoiceBridge — the C3 speech routing and spoken Q&A, end to end on fakes."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deeptutor.services.voice_realtime.agent import AgentVoiceBridge, BrowserState

from .test_danger import KB_SETTINGS_PAGE
from .test_loop import FixtureActuator, canned_think, step


def make_bridge(think, states=None):
    sent: list[dict[str, Any]] = []
    spoken: list[str] = []

    async def send(payload: dict[str, Any]) -> None:
        sent.append(payload)

    async def speak(text: str) -> None:
        spoken.append(text)

    actuator = FixtureActuator(
        states or [BrowserState(url="http://x/home", content="[0]<a >ศูนย์ความรู้ />")]
    )
    bridge = AgentVoiceBridge(send, speak, actuator=actuator, think=think)
    # step_delay=0 for tests — reach into the loop deliberately.
    bridge._loop._step_delay_s = 0  # noqa: SLF001
    return bridge, actuator, sent, spoken


@pytest.mark.asyncio
async def test_run_task_narrates_progress_and_the_ending():
    think = canned_think(
        [
            step("s", "กำลังไปศูนย์ความรู้", {"click_element_by_index": {"index": 0}}),
            step("arrived", "", {"done": {"text": "เปิดให้แล้วครับ", "success": True}}),
        ]
    )
    bridge, actuator, _sent, spoken = make_bridge(think)

    reply = await bridge.run_task("เปิดศูนย์ความรู้")

    assert reply == "เปิดให้แล้วครับ"
    assert spoken == ["กำลังไปศูนย์ความรู้", "เปิดให้แล้วครับ"]
    assert [name for name, _ in actuator.acts] == ["click_element_by_index"]


@pytest.mark.asyncio
async def test_ask_user_speaks_and_consumes_delivered_speech():
    think = canned_think(
        [
            step("s", "", {"ask_user": {"question": "หมายถึง KB ไหนครับ"}}),
            step("answered", "", {"done": {"text": "ok", "success": True}}),
        ]
    )
    bridge, _actuator, _sent, spoken = make_bridge(think)

    async def user_answers():
        while not bridge.waiting_on_user:
            await asyncio.sleep(0)
        assert bridge.deliver_speech("LAWs thai")  # consumed as the ANSWER

    answering = asyncio.ensure_future(user_answers())
    reply = await bridge.run_task("เปิด kb")
    await answering

    assert reply == "ok"
    assert "หมายถึง KB ไหนครับ" in spoken
    assert not bridge.waiting_on_user


@pytest.mark.asyncio
async def test_speech_without_a_pending_question_is_not_consumed():
    think = canned_think([step("s", "", {"done": {"text": "ok", "success": True}})])
    bridge, _actuator, _sent, _spoken = make_bridge(think)
    assert bridge.deliver_speech("อะไรก็ได้") is False  # session will treat as barge-in


@pytest.mark.asyncio
async def test_danger_confirm_yes_releases_the_click():
    think = canned_think(
        [
            step("s", "กดลบ", {"click_element_by_index": {"index": 169}}),
            step("deleted", "", {"done": {"text": "ลบแล้วครับ", "success": True}}),
        ]
    )
    bridge, actuator, _sent, spoken = make_bridge(
        think, states=[BrowserState(url="http://x/kb", content=KB_SETTINGS_PAGE)]
    )

    async def user_confirms():
        while not bridge.waiting_on_user:
            await asyncio.sleep(0)
        assert bridge.deliver_speech("ใช่ครับ")

    confirming = asyncio.ensure_future(user_confirms())
    reply = await bridge.run_task("ลบ KB นี้")
    await confirming

    assert reply == "ลบแล้วครับ"
    assert any("ผลถาวร" in line for line in spoken)  # the question was spoken
    assert [name for name, _ in actuator.acts] == ["click_element_by_index"]


@pytest.mark.asyncio
async def test_danger_confirm_no_blocks_the_click():
    think = canned_think(
        [
            step("s", "กดลบ", {"click_element_by_index": {"index": 169}}),
            step("refused", "", {"done": {"text": "ไม่ได้ลบครับ", "success": False}}),
        ]
    )
    bridge, actuator, _sent, _spoken = make_bridge(
        think, states=[BrowserState(url="http://x/kb", content=KB_SETTINGS_PAGE)]
    )

    async def user_refuses():
        while not bridge.waiting_on_user:
            await asyncio.sleep(0)
        assert bridge.deliver_speech("ไม่")

    refusing = asyncio.ensure_future(user_refuses())
    reply = await bridge.run_task("ลบ KB นี้")
    await refusing

    assert reply == "ไม่ได้ลบครับ"
    assert actuator.acts == []  # the delete never fired


@pytest.mark.asyncio
async def test_takeover_frame_aborts_the_run():
    async def think(system_prompt: str, user_prompt: str) -> str:
        bridge.handle_frame({"type": "agent_takeover"})  # mask clicked mid-think
        return step("s", "y", {"click_element_by_index": {"index": 0}})

    bridge, actuator, sent, _spoken = make_bridge(think)
    reply = await bridge.run_task("t")

    assert actuator.acts == []  # takeover held the click
    assert reply == "หยุดให้แล้วครับ"
    # FixtureActuator injected → no WS run frames here; the WS-mode test below
    # proves the mask always comes down.
    assert [f for f in sent if f.get("type") == "agent_run"] == []


@pytest.mark.asyncio
async def test_ws_mode_sends_run_frames_even_when_aborted(monkeypatch):
    """With the real WS actuator, the mask must never be left up."""
    sent: list[dict[str, Any]] = []

    async def send(payload: dict[str, Any]) -> None:
        sent.append(payload)

    async def speak(text: str) -> None:
        return None

    async def think(system_prompt: str, user_prompt: str) -> str:
        raise RuntimeError("LLM died")

    bridge = AgentVoiceBridge(send, speak, think=think)
    bridge._loop._step_delay_s = 0  # noqa: SLF001

    # observe() will time out instantly — shrink the timeout for the test.
    bridge._ws_actuator._observe_timeout_s = 0.01  # noqa: SLF001

    reply = await bridge.run_task("t")

    types = [f["type"] for f in sent]
    assert types[0] == "agent_run" and sent[0]["running"] is True
    assert types[-1] == "agent_run" and sent[-1]["running"] is False
    assert reply  # an honest failure line, never empty
