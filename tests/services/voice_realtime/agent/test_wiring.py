"""Phase D wiring: pipeline seams route to the agent, session routes speech.

These are the integration stitches — each one small, each one the difference
between "the loop exists" and "the loop answers the phone".
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deeptutor.services.voice_realtime import pipeline as pipe
from deeptutor.services.voice_realtime import session as session_mod
from deeptutor.services.voice_realtime.session import VoiceSession


class FakeEmitter:
    def __init__(self) -> None:
        self.json: list[dict[str, Any]] = []

    async def send_json(self, data: dict[str, Any]) -> None:
        self.json.append(data)

    async def send_bytes(self, data: bytes) -> None:  # pragma: no cover
        return None


def runner_recorder(reply: str = "เรียบร้อยครับ"):
    async def run(task: str) -> str:
        run.tasks.append(task)
        return reply

    run.tasks = []  # type: ignore[attr-defined]
    return run


# ── pipeline seam: multi-step utterance hands the turn to the loop ──


@pytest.mark.asyncio
async def test_multi_step_utterance_routes_to_the_agent():
    emitter = FakeEmitter()
    runner = runner_recorder("เปลี่ยนธีมมืดให้แล้วครับ")

    reply = await pipe.run_text_turn(
        emitter,
        "ไปตั้งค่าแล้วเปลี่ยนธีมมืด",
        [],
        session_id="s1",
        agent_runner=runner,
    )

    assert runner.tasks == ["ไปตั้งค่าแล้วเปลี่ยนธีมมืด"]
    assert reply == "เปลี่ยนธีมมืดให้แล้วครับ"
    types = [f["type"] for f in emitter.json]
    assert "assistant_text" in types and "done" in types


@pytest.mark.asyncio
async def test_agent_crash_becomes_an_honest_spoken_miss(monkeypatch):
    emitter = FakeEmitter()

    async def exploding_runner(task: str) -> str:
        raise RuntimeError("bridge died")

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return b"AUDIO", "audio/mpeg"

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)

    reply = await pipe.run_text_turn(
        emitter,
        "ไปตั้งค่าแล้วเปลี่ยนธีมมืด",
        [],
        session_id="s1",
        agent_runner=exploding_runner,
    )

    assert reply  # the honest miss line, spoken — never a dead line
    assert any(f["type"] == "done" for f in emitter.json)


# ── session routing: answer vs barge-in (the C3 state machine, live) ──


class StubBridge:
    def __init__(self, *, waiting: bool) -> None:
        self.running = True
        self._waiting = waiting
        self.delivered: list[str] = []
        self.aborted = False

    def deliver_speech(self, text: str) -> bool:
        if self._waiting:
            self.delivered.append(text)
            return True
        return False

    def abort(self) -> None:
        self.aborted = True

    def handle_frame(self, msg: dict[str, Any]) -> bool:  # pragma: no cover
        return False


@pytest.mark.asyncio
async def test_speech_during_pending_question_is_the_answer(monkeypatch):
    session = VoiceSession(FakeEmitter())
    bridge = StubBridge(waiting=True)
    session._agent = bridge  # noqa: SLF001

    called: list[str] = []

    async def fake_run_text_turn(*args: Any, **kwargs: Any) -> str:
        called.append("turn")
        return ""

    monkeypatch.setattr(session_mod, "run_text_turn", fake_run_text_turn)

    await session.handle_text("ใช่ครับ")

    assert bridge.delivered == ["ใช่ครับ"]  # consumed as the answer
    assert not bridge.aborted
    assert called == []  # no new turn started — the run keeps going


@pytest.mark.asyncio
async def test_speech_without_pending_question_is_a_barge_in(monkeypatch):
    session = VoiceSession(FakeEmitter())
    bridge = StubBridge(waiting=False)
    session._agent = bridge  # noqa: SLF001

    async def fake_run_text_turn(*args: Any, **kwargs: Any) -> str:
        return "คำตอบใหม่"

    monkeypatch.setattr(session_mod, "run_text_turn", fake_run_text_turn)

    await session.handle_text("ไปหน้าหลัก")
    await asyncio.sleep(0)  # let the new turn task start

    assert bridge.aborted  # the run was killed…
    assert bridge.delivered == []
    await session.cancel_current_turn()  # …and a fresh turn took the utterance


@pytest.mark.asyncio
async def test_flag_off_means_no_agent_runner(monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_AGENT_LOOP", raising=False)
    session = VoiceSession(FakeEmitter())
    assert session._agent_runner() is None  # noqa: SLF001 — pipeline sees None → today's behavior


@pytest.mark.asyncio
async def test_flag_needs_model_too(monkeypatch):
    monkeypatch.setenv("DEEPTUTOR_AGENT_LOOP", "1")
    monkeypatch.delenv("DEEPTUTOR_AGENT_MODEL", raising=False)
    session = VoiceSession(FakeEmitter())
    assert session._agent_runner() is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_flag_and_model_enable_the_runner(monkeypatch):
    monkeypatch.setenv("DEEPTUTOR_AGENT_LOOP", "1")
    monkeypatch.setenv("DEEPTUTOR_AGENT_MODEL", "gemini-2.5-flash")
    session = VoiceSession(FakeEmitter())
    assert session._agent_runner() is not None  # noqa: SLF001
