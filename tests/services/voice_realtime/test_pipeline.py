"""Tests for the realtime voice pipeline (orchestrator reuse + CONTENT gating)."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.voice_realtime import pipeline as pipe


class FakeEmitter:
    """Capture JSON events and binary audio frames in send order."""

    def __init__(self) -> None:
        self.json: list[dict[str, Any]] = []
        self.audio: list[bytes] = []

    async def send_json(self, data: dict[str, Any]) -> None:
        self.json.append(data)

    async def send_bytes(self, data: bytes) -> None:
        self.audio.append(data)


def _content(text: str, *, call_kind: str) -> StreamEvent:
    return StreamEvent(
        type=StreamEventType.CONTENT,
        source="chat",
        content=text,
        metadata={"call_kind": call_kind, "call_id": "c1"},
    )


def _fake_orchestrator(events: list[StreamEvent]) -> Any:
    class _Orch:
        async def handle(self, context: Any):  # noqa: ANN401
            for ev in events:
                yield ev

    return _Orch


def _patch_common(
    monkeypatch: pytest.MonkeyPatch, *, events: list[StreamEvent], transcript: str = "พีทาโกรัส"
) -> list[str]:
    """Patch STT/TTS/orchestrator; return the list that records spoken chunks."""
    spoken: list[str] = []

    async def fake_transcribe(audio: bytes, *, language: str = "th") -> str:
        return transcript

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        spoken.append(text)
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    monkeypatch.setattr(
        "deeptutor.runtime.orchestrator.ChatOrchestrator", _fake_orchestrator(events)
    )
    return spoken


@pytest.mark.asyncio
async def test_speaks_only_final_response_not_narration(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [
        _content("กำลังค้นหา...", call_kind="narration"),  # must NOT be spoken
        _content("ทฤษฎีบทพีทาโกรัส. ", call_kind="llm_final_response"),
        _content("a²+b²=c² นั่นเอง.", call_kind="llm_final_response"),
        StreamEvent(
            type=StreamEventType.RESULT,
            source="chat",
            metadata={"response": "ทฤษฎีบทพีทาโกรัส. a²+b²=c² นั่นเอง."},
        ),
    ]
    spoken = _patch_common(monkeypatch, events=events)
    emitter = FakeEmitter()

    transcript, reply = await pipe.run_turn(
        emitter, b"webm-bytes", [], session_id="voice:test"
    )

    assert transcript == "พีทาโกรัส"
    assert reply == "ทฤษฎีบทพีทาโกรัส. a²+b²=c² นั่นเอง."
    # Narration never reached TTS; both final-answer sentences did.
    assert not any("ค้นหา" in chunk for chunk in spoken), spoken
    assert any("พีทาโกรัส" in chunk for chunk in spoken), spoken
    # One binary audio frame per spoken chunk.
    assert len(emitter.audio) == len(spoken)
    assert all(frame.startswith(b"AUDIO:") for frame in emitter.audio)


@pytest.mark.asyncio
async def test_emits_transcript_stages_and_done(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [
        _content("คำตอบสั้นๆ.", call_kind="llm_final_response"),
        StreamEvent(type=StreamEventType.RESULT, source="chat", metadata={"response": "คำตอบสั้นๆ."}),
    ]
    _patch_common(monkeypatch, events=events)
    emitter = FakeEmitter()

    await pipe.run_turn(emitter, b"x", [], session_id="voice:test")

    types = [m.get("type") for m in emitter.json]
    stages = {m.get("stage") for m in emitter.json if m.get("type") == "stage"}
    assert types[0] == "transcript"
    assert "done" in types
    assert {"stt", "llm_ttft", "tts_first"} <= stages
    done = next(m for m in emitter.json if m["type"] == "done")
    assert done["first_audio_ms"] is not None


@pytest.mark.asyncio
async def test_empty_transcription_reports_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch, events=[], transcript="   ")
    emitter = FakeEmitter()

    transcript, reply = await pipe.run_turn(emitter, b"x", [], session_id="voice:test")

    assert (transcript, reply) == ("", "")
    assert emitter.json[-1]["type"] == "error"
    assert not emitter.audio


@pytest.mark.asyncio
async def test_first_audio_streams_before_stream_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Audio for sentence 1 must be emitted before later tokens are consumed."""
    order: list[str] = []

    async def fake_transcribe(audio: bytes, *, language: str = "th") -> str:
        return "q"

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        order.append(f"tts:{text[:6]}")
        return (b"AUDIO", "audio/mpeg")

    class _Orch:
        async def handle(self, context: Any):  # noqa: ANN401
            yield _content("ประโยคแรกจบ. ", call_kind="llm_final_response")
            order.append("token2")
            yield _content("ประโยคสอง.", call_kind="llm_final_response")
            yield StreamEvent(type=StreamEventType.RESULT, source="chat", metadata={"response": "x"})

    monkeypatch.setattr(pipe, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", _Orch)

    await pipe.run_turn(FakeEmitter(), b"x", [], session_id="voice:test")

    # First TTS call happened before the second token was yielded.
    assert order[0].startswith("tts:")
    assert order.index("token2") > 0
