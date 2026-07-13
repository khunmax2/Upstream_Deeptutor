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


@pytest.fixture(autouse=True)
def _classifier_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the intent classifier OFF for every test unless it opts in.

    ``classifier_enabled()`` reads live env, so a developer shell that sources
    ``.env.agent`` (with ``DEEPTUTOR_VOICE_CLASSIFIER=1``) would otherwise let the
    real classifier seam intercept transcripts and break the tests that assert the
    pre-classifier routing. The classifier-routing tests set their own value via
    ``_patch_classifier``, which wins over this default."""
    monkeypatch.setattr(pipe.intent_classifier, "classifier_enabled", lambda: False)


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


# ── the SEMANTIC door: chat LLM hands off via the ui_agent_task tool ──
#
# Lexical verb-matching (intent.py) can't cover how differently people
# phrase tasks — the catch-all is the chat model itself calling the tool.
# These tests drive run_text_turn with a fake orchestrator emitting the
# TOOL_CALL, exactly the frame the real turn produces.


class _AudioEmitter(FakeEmitter):
    async def send_bytes(self, data: bytes) -> None:
        return None


def _fake_orchestrator(events: list[Any]):
    class _Orch:
        async def handle(self, context: Any):  # noqa: ANN401
            for ev in events:
                yield ev

    return _Orch


def _tool_call(name: str, args: dict[str, Any]):
    from deeptutor.core.stream import StreamEvent, StreamEventType

    return StreamEvent(
        type=StreamEventType.TOOL_CALL, source="chat", content=name, metadata={"args": args}
    )


def _content(text: str):
    from deeptutor.core.stream import StreamEvent, StreamEventType

    return StreamEvent(
        type=StreamEventType.CONTENT,
        source="chat",
        content=text,
        metadata={"call_kind": "llm_final_response", "call_id": "c1"},
    )


def _patch_llm_turn(monkeypatch: pytest.MonkeyPatch, events: list[Any]) -> list[str]:
    spoken: list[str] = []

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        spoken.append(text)
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    monkeypatch.setattr(
        "deeptutor.runtime.orchestrator.ChatOrchestrator", _fake_orchestrator(events)
    )
    return spoken


@pytest.mark.asyncio
async def test_chat_llm_hands_off_to_the_agent_via_tool(monkeypatch):
    """TOOL_CALL(ui_agent_task) → chat turn abandoned, loop takes the task."""
    task = "ไปหน้าหลักแล้วค้นหาราคาทอง"
    spoken = _patch_llm_turn(
        monkeypatch,
        [
            _tool_call("ui_agent_task", {"task": task}),
            _content("ได้เลยครับ"),  # the chat model's own reply — must NOT be spoken
        ],
    )
    runner = runner_recorder("ค้นหาราคาทองให้แล้วครับ")
    emitter = _AudioEmitter()

    # "ช่วย..." opener: no fast-path rung and no lexical match — the exact
    # phrasing class that used to dead-end in navigate-only chat.
    reply = await pipe.run_text_turn(
        emitter,
        "ช่วยไปดูราคาทองที่หน้าหลักหน่อย",
        [],
        session_id="s1",
        agent_runner=runner,
    )

    assert runner.tasks == [task]  # the model's restated task, not the transcript
    assert reply == "ค้นหาราคาทองให้แล้วครับ"
    assert "ได้เลยครับ" not in spoken  # abandoned turn never spoke
    types = [f["type"] for f in emitter.json]
    assert "assistant_text" in types and "done" in types


@pytest.mark.asyncio
async def test_handoff_tool_call_without_task_falls_back_to_transcript(monkeypatch):
    _patch_llm_turn(monkeypatch, [_tool_call("ui_agent_task", {})])
    runner = runner_recorder("ok")
    transcript = "ช่วยจัดการหน้าจอให้หน่อย"

    await pipe.run_text_turn(_AudioEmitter(), transcript, [], session_id="s1", agent_runner=runner)

    assert runner.tasks == [transcript]


@pytest.mark.asyncio
async def test_handoff_without_runner_is_ignored_and_chat_continues(monkeypatch):
    """Flag off: the TOOL_CALL is a no-op; the chat turn finishes normally."""
    spoken = _patch_llm_turn(
        monkeypatch,
        [
            _tool_call("ui_agent_task", {"task": "x"}),
            _content("ผมช่วยแบบอื่นได้ครับ"),
        ],
    )

    reply = await pipe.run_text_turn(
        _AudioEmitter(), "ช่วยจัดการหน้าจอให้หน่อย", [], session_id="s1", agent_runner=None
    )

    assert "ผมช่วยแบบอื่นได้ครับ" in reply
    assert any("ผมช่วยแบบอื่น" in s for s in spoken)


@pytest.mark.asyncio
async def test_connectorless_compound_reaches_the_agent_before_any_llm():
    """Regression for the live bug: 'ไปตั้งค่าเปลี่ยนธีมมืด' (no แล้ว) must be
    taken by the loop deterministically — no chat LLM, no half-done navigate."""
    emitter = FakeEmitter()
    runner = runner_recorder("เปลี่ยนธีมมืดให้แล้วครับ")

    reply = await pipe.run_text_turn(
        emitter,
        "ไปตั้งค่าเปลี่ยนธีมมืด",
        [],
        session_id="s1",
        agent_runner=runner,
    )

    assert runner.tasks == ["ไปตั้งค่าเปลี่ยนธีมมืด"]
    assert reply == "เปลี่ยนธีมมืดให้แล้วครับ"


# ── intent classifier seam (A1): primary router before the chat fallback ──


def _patch_classifier(monkeypatch: pytest.MonkeyPatch, intent: str) -> None:
    monkeypatch.setattr(pipe.intent_classifier, "classifier_enabled", lambda: True)

    async def fake_classify(transcript: str, ui_context: Any = None) -> str:
        return intent

    monkeypatch.setattr(pipe.intent_classifier, "classify", fake_classify)


@pytest.mark.asyncio
async def test_classifier_ui_task_routes_to_the_agent(monkeypatch):
    """A command with no keyword marker ('สร้างหนังสือใหม่') classified ui_task →
    the loop gets the whole task (the live 'half-done navigate' bug)."""
    _patch_classifier(monkeypatch, "ui_task")
    runner = runner_recorder("สร้างหนังสือให้แล้วครับ")

    reply = await pipe.run_text_turn(
        FakeEmitter(), "สร้างหนังสือใหม่ให้หน่อย", [], session_id="s1", agent_runner=runner
    )

    assert runner.tasks == ["สร้างหนังสือใหม่ให้หน่อย"]
    assert reply == "สร้างหนังสือให้แล้วครับ"


@pytest.mark.asyncio
async def test_classifier_chat_leaves_the_loop_untouched(monkeypatch):
    """Classified chat → the loop is never called; the chat turn runs normally."""
    _patch_classifier(monkeypatch, "chat")
    _patch_llm_turn(monkeypatch, [_content("ราคาทองวันนี้บาทละเยอะครับ")])
    runner = runner_recorder("ต้องไม่ถูกเรียก")

    reply = await pipe.run_text_turn(
        _AudioEmitter(), "ราคาทองเท่าไหร่", [], session_id="s1", agent_runner=runner
    )

    assert runner.tasks == []
    assert "ราคาทอง" in reply


@pytest.mark.asyncio
async def test_classifier_unclear_asks_to_repeat_without_rag_or_loop(monkeypatch):
    """Garbled input classified 'unclear' → a spoken 'please repeat', and NEITHER
    the loop NOR the chat+RAG turn runs (the live 'garbled → Searching KB' waste)."""
    _patch_classifier(monkeypatch, "unclear")

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return b"AUDIO", "audio/mpeg"

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    runner = runner_recorder("ต้องไม่ถูกเรียก")
    emitter = _AudioEmitter()

    reply = await pipe.run_text_turn(
        emitter, "แล้วมาวิเคราะห์หรืออะไรสักอย่", [], session_id="s1", agent_runner=runner
    )

    assert reply == pipe._UNCLEAR_LINE  # short-circuited before rung=llm (no RAG)
    assert runner.tasks == []  # loop never invoked
    types = [f["type"] for f in emitter.json]
    assert "assistant_text" in types and "done" in types


@pytest.mark.asyncio
async def test_classifier_off_is_never_consulted(monkeypatch):
    """Flag off (default): the seam is skipped — classify must not be called and
    the turn behaves exactly as before."""
    called = {"n": 0}

    async def boom(transcript: str, ui_context: Any = None) -> str:
        called["n"] += 1
        return "ui_task"

    monkeypatch.setattr(pipe.intent_classifier, "classifier_enabled", lambda: False)
    monkeypatch.setattr(pipe.intent_classifier, "classify", boom)
    _patch_llm_turn(monkeypatch, [_content("โอเคครับ")])
    runner = runner_recorder()

    await pipe.run_text_turn(
        _AudioEmitter(), "สร้างหนังสือใหม่", [], session_id="s1", agent_runner=runner
    )

    assert called["n"] == 0 and runner.tasks == []
