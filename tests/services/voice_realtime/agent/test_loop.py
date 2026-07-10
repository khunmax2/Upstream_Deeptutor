"""InPageAgentLoop against a scripted fixture — no browser, no network.

The acceptance case is the plan's Phase-B gate: a 3-step task
(navigate → fill → confirm) runs to completion, with the fixture playing the
page and a canned-think function playing the LLM.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from deeptutor.services.voice_realtime.agent import (
    ActResult,
    AgentResult,
    BrowserState,
    InPageAgentLoop,
)


class FixtureActuator:
    """Plays the page: each act() advances through scripted browser states."""

    def __init__(self, states: list[BrowserState]) -> None:
        self.states = states
        self.cursor = 0
        self.acts: list[tuple[str, dict[str, Any]]] = []

    async def observe(self) -> BrowserState:
        return self.states[min(self.cursor, len(self.states) - 1)]

    async def act(self, name: str, args: dict[str, Any]) -> ActResult:
        self.acts.append((name, args))
        self.cursor += 1
        return ActResult(ok=True, message=f"✅ Did {name}({args}).")


def canned_think(outputs: list[str]):
    """LLM stand-in: pops the next scripted completion."""
    queue = list(outputs)

    async def think(system_prompt: str, user_prompt: str) -> str:
        think.prompts.append(user_prompt)
        return queue.pop(0)

    think.prompts = []  # type: ignore[attr-defined]
    return think


def step(evaluation: str, goal: str, action: dict[str, Any]) -> str:
    return json.dumps(
        {
            "evaluation_previous_goal": evaluation,
            "memory": "m",
            "next_goal": goal,
            "action": action,
        }
    )


PAGES = [
    BrowserState(url="http://x/home", content="[0]<a >ศูนย์ความรู้ />"),
    BrowserState(url="http://x/knowledge", content="[3]<input placeholder=ค้นหา />"),
    BrowserState(url="http://x/knowledge", content="[5]<button >ค้นหา />"),
    BrowserState(url="http://x/knowledge?q=pdpa", content="ผลการค้นหา pdpa"),
]


@pytest.mark.asyncio
async def test_three_step_task_completes():
    """Phase-B acceptance: navigate → fill → confirm → done."""
    actuator = FixtureActuator(PAGES)
    think = canned_think(
        [
            step("start", "ไปที่ศูนย์ความรู้", {"click_element_by_index": {"index": 0}}),
            step("navigated", "พิมพ์ pdpa", {"input_text": {"index": 3, "text": "pdpa"}}),
            step("typed", "กดค้นหา", {"click_element_by_index": {"index": 5}}),
            step("results shown", "", {"done": {"text": "ค้นหา pdpa ให้แล้วครับ", "success": True}}),
        ]
    )
    loop = InPageAgentLoop(actuator, think=think, step_delay_s=0)

    result: AgentResult = await loop.execute("ค้นหา pdpa ในศูนย์ความรู้")

    assert result.success and result.stopped_reason == "done"
    assert result.text == "ค้นหา pdpa ให้แล้วครับ"
    assert [name for name, _ in actuator.acts] == [
        "click_element_by_index",
        "input_text",
        "click_element_by_index",
    ]
    # Navigation must have been observed and surfaced to the LLM as <sys>.
    assert any("Page navigated to" in p for p in think.prompts)
    # Fresh-DOM rule: the LAST prompt carries only the final page's content.
    assert "ผลการค้นหา pdpa" in think.prompts[-1]
    assert "[0]<a >ศูนย์ความรู้ />" not in think.prompts[-1]


@pytest.mark.asyncio
async def test_budget_exhaustion_is_an_honest_failure():
    actuator = FixtureActuator([PAGES[0]])
    spin = step("looking", "scroll more", {"scroll": {"down": True}})
    loop = InPageAgentLoop(actuator, think=canned_think([spin] * 3), max_steps=3, step_delay_s=0)
    result = await loop.execute("do something impossible")
    assert not result.success and result.stopped_reason == "budget"
    assert len(result.steps) == 3


@pytest.mark.asyncio
async def test_budget_warning_reaches_the_llm():
    actuator = FixtureActuator([PAGES[0]])
    spin = step("x", "y", {"scroll": {"down": True}})
    think = canned_think([spin] * 7)
    loop = InPageAgentLoop(actuator, think=think, max_steps=7, step_delay_s=0)
    await loop.execute("t")
    assert any("Only 5 steps remaining" in p for p in think.prompts)
    assert any("only 2 steps left" in p for p in think.prompts)


@pytest.mark.asyncio
async def test_fixer_failure_costs_a_step_then_recovers():
    actuator = FixtureActuator(PAGES)
    think = canned_think(
        [
            "I'm on it!",  # no JSON at all → fixer error → observation
            step("retry", "", {"done": {"text": "ok", "success": True}}),
        ]
    )
    loop = InPageAgentLoop(actuator, think=think, step_delay_s=0)
    result = await loop.execute("t")
    assert result.success
    assert any("previous reply was invalid" in p for p in think.prompts)


@pytest.mark.asyncio
async def test_repeated_invalid_output_ends_the_run():
    actuator = FixtureActuator(PAGES)
    loop = InPageAgentLoop(actuator, think=canned_think(["junk"] * 3), step_delay_s=0)
    result = await loop.execute("t")
    assert not result.success and result.stopped_reason == "error"


@pytest.mark.asyncio
async def test_abort_mid_run_stops_before_next_action():
    actuator = FixtureActuator(PAGES)
    loop = InPageAgentLoop(actuator, think=None, step_delay_s=0)

    async def think(system_prompt: str, user_prompt: str) -> str:
        loop.abort()  # barge-in arrives while the model is thinking
        return step("x", "y", {"click_element_by_index": {"index": 0}})

    loop._think = think  # type: ignore[attr-defined]
    result = await loop.execute("t")
    assert result.stopped_reason == "aborted"
    assert actuator.acts == []  # the click never fired


@pytest.mark.asyncio
async def test_pre_act_gate_blocks_and_informs_the_llm():
    """The Phase-C seam: a blocked action becomes information, not a crash."""
    actuator = FixtureActuator(PAGES)

    async def danger_gate(name: str, args: dict[str, Any], page: str) -> str | None:
        if name == "click_element_by_index":
            return "ปุ่มนี้อาจมีผลถาวร ผู้ใช้ยังไม่ยืนยัน"
        return None

    think = canned_think(
        [
            step("s", "กดลบ", {"click_element_by_index": {"index": 0}}),
            step("blocked", "", {"done": {"text": "ต้องให้คุณยืนยันก่อนครับ", "success": False}}),
        ]
    )
    loop = InPageAgentLoop(actuator, think=think, pre_act=danger_gate, step_delay_s=0)
    result = await loop.execute("ลบ KB")
    assert actuator.acts == []  # gate held the line
    assert result.stopped_reason == "done" and not result.success
    assert "⛔" in result.steps[0].action_output


@pytest.mark.asyncio
async def test_ask_user_roundtrip_and_waiting_flag():
    actuator = FixtureActuator(PAGES)
    seen: dict[str, Any] = {}

    async def ask(question: str) -> str:
        seen["question"] = question
        seen["waiting"] = loop.waiting_on_user
        return "อันที่สอง"

    think = canned_think(
        [
            step("s", "ถามผู้ใช้", {"ask_user": {"question": "หมายถึงอันไหนครับ"}}),
            step("answered", "", {"done": {"text": "เรียบร้อย", "success": True}}),
        ]
    )
    loop = InPageAgentLoop(actuator, think=think, ask_user=ask, step_delay_s=0)
    result = await loop.execute("t")
    assert seen == {"question": "หมายถึงอันไหนครับ", "waiting": True}
    assert loop.waiting_on_user is False
    assert result.success
    assert any("User answered: อันที่สอง" in p for p in think.prompts)


@pytest.mark.asyncio
async def test_ask_user_absent_from_contract_without_callback():
    """No one to answer → the tool must not even be offered to the LLM."""
    actuator = FixtureActuator(PAGES)
    think = canned_think(
        [
            step("s", "ถาม", {"ask_user": {"question": "?"}}),  # LLM tries anyway
            step("told off", "", {"done": {"text": "ok", "success": True}}),
        ]
    )
    loop = InPageAgentLoop(actuator, think=think, step_delay_s=0)
    result = await loop.execute("t")
    # Invalid (unknown) action → fixer error observation → run still completes.
    assert result.success
    assert any("Unknown action" in p for p in think.prompts)


@pytest.mark.asyncio
async def test_narration_speaks_next_goal_but_never_breaks_the_run():
    actuator = FixtureActuator(PAGES)
    spoken: list[str] = []

    async def narrate(text: str) -> None:
        spoken.append(text)
        raise RuntimeError("TTS died")  # must not kill the loop

    think = canned_think(
        [
            step("s", "กำลังไปศูนย์ความรู้", {"click_element_by_index": {"index": 0}}),
            step("done", "จบแล้ว", {"done": {"text": "ok", "success": True}}),
        ]
    )
    loop = InPageAgentLoop(actuator, think=think, narrate=narrate, step_delay_s=0)
    result = await loop.execute("t")
    assert result.success
    # Progress goals are narrated; the ending is ALWAYS spoken too (C4) —
    # done's own next_goal is not (done.text replaces it).
    assert spoken == ["กำลังไปศูนย์ความรู้", "ok"]


@pytest.mark.asyncio
async def test_act_failure_is_information_not_a_crash():
    class BrokenActuator(FixtureActuator):
        async def act(self, name: str, args: dict[str, Any]) -> ActResult:
            raise RuntimeError("socket closed")

    think = canned_think(
        [
            step("s", "กด", {"click_element_by_index": {"index": 0}}),
            step("saw failure", "", {"done": {"text": "หน้าเว็บมีปัญหาครับ", "success": False}}),
        ]
    )
    loop = InPageAgentLoop(BrokenActuator(PAGES), think=think, step_delay_s=0)
    result = await loop.execute("t")
    assert result.stopped_reason == "done" and not result.success
    assert any("Action failed" in p for p in think.prompts)


@pytest.mark.asyncio
async def test_wait_accumulation_warning():
    actuator = FixtureActuator([PAGES[0]])
    w = step("s", "wait", {"wait": {"seconds": 2}})
    think = canned_think([w, w, step("s", "", {"done": {"text": "ok", "success": True}})])
    loop = InPageAgentLoop(actuator, think=think, step_delay_s=0)

    async def instant_sleep(_s: float) -> None:
        return None

    real_sleep = asyncio.sleep
    asyncio.sleep = instant_sleep  # type: ignore[assignment]
    try:
        await loop.execute("t")
    finally:
        asyncio.sleep = real_sleep  # type: ignore[assignment]
    assert any("waited 4 seconds accumulatively" in p for p in think.prompts)
