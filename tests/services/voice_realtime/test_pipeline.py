"""Tests for the realtime voice pipeline (orchestrator reuse + CONTENT gating)."""

from __future__ import annotations

import asyncio
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

    async def fake_transcribe(audio: bytes, **kwargs: Any) -> tuple[str, float | None]:
        return transcript, None

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        spoken.append(text)
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "transcribe_utterance", fake_transcribe)
    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    monkeypatch.setattr(
        "deeptutor.runtime.orchestrator.ChatOrchestrator", _fake_orchestrator(events)
    )
    return spoken


@pytest.mark.asyncio
async def test_speaks_only_final_response_not_narration(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [
        _content("tool-payload junk", call_kind="tool_result"),  # must NOT be spoken
        _content("ทฤษฎีบทพีทาโกรัส. ", call_kind="agent_loop_round"),
        _content("a²+b²=c² นั่นเอง.", call_kind="llm_final_response"),
        StreamEvent(
            type=StreamEventType.RESULT,
            source="chat",
            metadata={"response": "ทฤษฎีบทพีทาโกรัส. a²+b²=c² นั่นเอง."},
        ),
    ]
    spoken = _patch_common(monkeypatch, events=events)
    emitter = FakeEmitter()

    transcript, reply = await pipe.run_turn(emitter, b"webm-bytes", [], session_id="voice:test")

    assert transcript == "พีทาโกรัส"
    assert reply == "ทฤษฎีบทพีทาโกรัส. a²+b²=c² นั่นเอง."
    # Tool payloads never reached TTS; both speakable rounds did.
    assert not any("junk" in chunk for chunk in spoken), spoken
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
async def test_text_turn_skips_stt_and_replies(monkeypatch: pytest.MonkeyPatch) -> None:
    """user_text path: no transcribe call, straight to LLM → TTS."""
    events = [
        _content("ตอบจากข้อความ.", call_kind="llm_final_response"),
        StreamEvent(
            type=StreamEventType.RESULT, source="chat", metadata={"response": "ตอบจากข้อความ."}
        ),
    ]

    async def boom(*a: Any, **k: Any) -> str:  # noqa: ANN401
        raise AssertionError("transcribe_utterance must not be called for text turns")

    spoken = _patch_common(monkeypatch, events=events)
    monkeypatch.setattr(pipe, "transcribe_utterance", boom)
    emitter = FakeEmitter()

    reply = await pipe.run_text_turn(emitter, "สวัสดี", [], session_id="voice:test")

    assert reply == "ตอบจากข้อความ."
    assert spoken  # TTS ran
    types = [m.get("type") for m in emitter.json]
    assert "transcript" not in types  # no server STT stage
    assert "done" in types


def test_voice_context_injects_speech_style_directive() -> None:
    """The brain must shape answers for speech from token one (persona slot)."""
    ctx = pipe.build_voice_context(
        transcript="สวัสดี", history=[], session_id="voice:x", knowledge_bases=[]
    )
    assert ctx.persona_context == pipe.VOICE_STYLE_DIRECTIVE
    assert "phone call" in ctx.persona_context
    assert ctx.metadata["source"] == "voice"


def test_voice_context_attaches_knowledge_bases_for_rag() -> None:
    """KBs are attached so rag can auto-mount; an explicit list overrides discovery."""
    ctx = pipe.build_voice_context(
        transcript="q", history=[], session_id="s", knowledge_bases=["kb-a", "kb-b"]
    )
    assert ctx.knowledge_bases == ["kb-a", "kb-b"]


def _rag_running() -> StreamEvent:
    """The event the chat capability actually emits when RAG retrieval starts."""
    return StreamEvent(
        type=StreamEventType.PROGRESS,
        source="chat",
        metadata={
            "trace_kind": "call_status",
            "call_state": "running",
            "call_kind": "rag_retrieval",
        },
    )


def test_tool_starting_detects_both_shapes() -> None:
    # genuine tool_call
    ev = StreamEvent(type=StreamEventType.TOOL_CALL, content="web_search")
    assert pipe._tool_starting(ev, ev.metadata) == "web_search"
    # rag retrieval progress → normalized to "rag"
    assert pipe._tool_starting(_rag_running(), _rag_running().metadata) == "rag"
    # the plain LLM round is NOT a tool
    llm = StreamEvent(
        type=StreamEventType.PROGRESS,
        metadata={
            "trace_kind": "call_status",
            "call_state": "running",
            "call_kind": "agent_loop_round",
        },
    )
    assert pipe._tool_starting(llm, llm.metadata) is None


@pytest.mark.asyncio
async def test_rag_retrieval_speaks_filler_and_searching_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RAG (progress/rag_retrieval) → one spoken filler + a 'searching' status frame."""
    events = [
        _rag_running(),
        _content("พบว่าคำตอบคือสี่.", call_kind="llm_final_response"),
        StreamEvent(type=StreamEventType.RESULT, source="chat", metadata={"response": "สี่"}),
    ]
    spoken = _patch_common(monkeypatch, events=events)
    emitter = FakeEmitter()

    await pipe.run_text_turn(emitter, "ในเอกสารว่าไง", [], session_id="voice:test")

    assert any("ค้นข้อมูลในเอกสาร" in chunk for chunk in spoken), spoken
    searching = [
        m for m in emitter.json if m.get("type") == "status" and m.get("state") == "searching"
    ]
    assert searching and searching[0]["tool"] == "rag"


@pytest.mark.asyncio
async def test_watchdog_reassures_then_aborts_on_hang(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tool that goes silent past the limits → reassurance, then a hang abort."""
    monkeypatch.setattr(pipe, "_WATCHDOG_TICK", 0.01)
    monkeypatch.setattr(pipe, "_REASSURE_AFTER", 0.02)
    monkeypatch.setattr(pipe, "_HANG_LIMIT", 0.05)
    spoken: list[str] = []

    async def fake_synth(text: str) -> tuple[bytes, str]:
        spoken.append(text)
        return (b"A", "audio/mpeg")

    class _HangingOrch:
        async def handle(self, context: Any):  # noqa: ANN401
            yield StreamEvent(type=StreamEventType.TOOL_CALL, source="chat", content="rag")
            await asyncio.sleep(1.0)  # tool hangs — no further events
            yield _content("ไม่ควรมาถึง", call_kind="llm_final_response")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synth)
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", _HangingOrch)
    emitter = FakeEmitter()

    reply = await pipe.run_text_turn(emitter, "q", [], session_id="voice:test")

    assert any("ยังค้นข้อมูลอยู่" in s for s in spoken), spoken  # reassurance
    assert any(m.get("type") == "error" for m in emitter.json)  # hang reported
    assert "ไม่ควรมาถึง" not in reply


def test_containerize_audio_wraps_pcm_and_passes_through() -> None:
    pcm = b"\x01\x02" * 24  # fake s16le samples
    wav, ctype = pipe.containerize_audio(pcm, "audio/pcm;rate=24000;channels=1")
    assert ctype == "audio/wav"
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    # rate parsed from params
    import io as _io
    import wave as _wave

    with _wave.open(_io.BytesIO(wav)) as w:
        assert w.getframerate() == 24000 and w.getnchannels() == 1

    mp3, ctype2 = pipe.containerize_audio(b"MP3DATA", "audio/mpeg")
    assert (mp3, ctype2) == (b"MP3DATA", "audio/mpeg")


@pytest.mark.asyncio
async def test_first_audio_streams_before_stream_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Audio for sentence 1 must be emitted before later tokens are consumed."""
    order: list[str] = []

    async def fake_transcribe(audio: bytes, **kwargs: Any) -> tuple[str, float | None]:
        return "q", None

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        order.append(f"tts:{text[:6]}")
        return (b"AUDIO", "audio/mpeg")

    class _Orch:
        async def handle(self, context: Any):  # noqa: ANN401
            yield _content("ประโยคแรกจบ. ", call_kind="llm_final_response")
            order.append("token2")
            yield _content("ประโยคสอง.", call_kind="llm_final_response")
            yield StreamEvent(
                type=StreamEventType.RESULT, source="chat", metadata={"response": "x"}
            )

    monkeypatch.setattr(pipe, "transcribe_utterance", fake_transcribe)
    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", _Orch)

    await pipe.run_turn(FakeEmitter(), b"x", [], session_id="voice:test")

    # First TTS call happened before the second token was yielded.
    assert order[0].startswith("tts:")
    assert order.index("token2") > 0
