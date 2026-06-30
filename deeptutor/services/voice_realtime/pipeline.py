"""One realtime voice turn: STT → LLM (orchestrator) → per-sentence TTS.

This is where the realtime layer's design pays off. Instead of going through the
turn-based partner ``MessageBus``, ``run_turn`` drives ``ChatOrchestrator``
directly and consumes ``StreamBus`` ``CONTENT`` events as they arrive. Only the
assistant's **final answer** is spoken — narration / tool-status rounds are
filtered out exactly the way :class:`PartnerRunner` does it, by keying on
``metadata.call_kind == "llm_final_response"``. Final-answer tokens feed a
:class:`SentenceChunker`, and each completed clause is synthesized and streamed
back immediately, so audio for sentence 1 goes out while the LLM is still
writing sentence 2.

STT and TTS reuse the catalog-driven facade in
:mod:`deeptutor.services.voice` (``transcribe_audio`` / ``synthesize_speech``),
so providers (including the new ElevenLabs / BOTNOI ones) are configured through
the same Settings > Voice catalog as the REST ``/voice`` endpoints.

The whole coroutine is cancellable: a barge-in cancels the turn task, and the
in-flight STT / LLM / TTS awaits unwind on ``CancelledError``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol
import uuid

from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEventType
from deeptutor.services.voice import (
    VoiceProviderError,
    synthesize_speech,
    transcribe_audio,
)
from deeptutor.services.voice_realtime.chunker import SentenceChunker

logger = logging.getLogger(__name__)

# Cap a chunk so a runaway clause can't block first-audio; the chunker already
# soft-breaks near this, this is just the synthesis budget.
_CHUNK_MAX_CHARS = 120


class VoiceEmitter(Protocol):
    """Structural type for the transport sink (FastAPI ``WebSocket`` satisfies it)."""

    async def send_json(self, data: dict[str, Any]) -> None: ...

    async def send_bytes(self, data: bytes) -> None: ...


def build_voice_context(
    *,
    transcript: str,
    history: list[dict[str, Any]],
    session_id: str,
    language: str = "th",
) -> UnifiedContext:
    """Assemble the chat ``UnifiedContext`` for one spoken turn.

    Mirrors ``PartnerRunner._build_context`` but minimal: a voice turn runs in
    the already-active authenticated-user scope (no partner workspace), so
    rag / skills / memory resolve to the caller's own workspace. The default
    chat capability handles the turn; ``source="voice"`` tags the trace.
    """
    return UnifiedContext(
        session_id=session_id,
        user_message=transcript,
        conversation_history=list(history),
        active_capability="chat",
        language=language,
        metadata={
            "turn_id": f"voice-{uuid.uuid4().hex[:12]}",
            "source": "voice",
        },
    )


async def run_turn(
    emitter: VoiceEmitter,
    audio: bytes,
    history: list[dict[str, Any]],
    *,
    session_id: str,
    language: str = "th",
) -> tuple[str, str]:
    """Run one voice turn and stream events/audio to *emitter*.

    Returns ``(transcript, reply)`` so the caller can update conversation
    history. Raises nothing for provider failures — they are reported to the
    client as ``error`` events and yield an empty reply; ``asyncio.CancelledError``
    (barge-in) is allowed to propagate.
    """
    from deeptutor.runtime.orchestrator import ChatOrchestrator

    turn_t0 = time.perf_counter()

    # ── STT ──
    try:
        transcript = await transcribe_audio(audio, language=language)
    except (VoiceProviderError, ValueError) as exc:
        await emitter.send_json({"type": "error", "message": f"STT: {exc}"})
        return "", ""
    transcript = transcript.strip()
    if not transcript:
        await emitter.send_json({"type": "error", "message": "ไม่ได้ยินเสียงพูด"})
        return "", ""
    await emitter.send_json({"type": "transcript", "text": transcript})
    await emitter.send_json(
        {"type": "stage", "stage": "stt", "ms": round((time.perf_counter() - turn_t0) * 1000)}
    )

    # ── LLM stream → sentence chunker → TTS ──
    context = build_voice_context(
        transcript=transcript, history=history, session_id=session_id, language=language
    )
    chunker = SentenceChunker(max_chars=_CHUNK_MAX_CHARS)
    final_text = ""
    spoken_parts: list[str] = []
    seq = 0
    llm_start = time.perf_counter()
    first_token_at: float | None = None
    first_audio_at: float | None = None

    async def speak(chunk: str) -> None:
        nonlocal seq, first_audio_at
        tts_t0 = time.perf_counter()
        try:
            audio_bytes, content_type = await synthesize_speech(chunk)
        except VoiceProviderError as exc:
            # Empty-after-cleaning chunks are expected (markdown-only); skip
            # them quietly and surface anything else as a soft error.
            if "Nothing to speak" not in str(exc):
                await emitter.send_json({"type": "error", "message": f"TTS: {exc}"})
            return
        if not audio_bytes:
            return
        if first_audio_at is None:
            first_audio_at = time.perf_counter()
            await emitter.send_json(
                {"type": "stage", "stage": "tts_first", "ms": round((first_audio_at - tts_t0) * 1000)}
            )
        await emitter.send_json(
            {"type": "audio", "seq": seq, "text": chunk, "content_type": content_type}
        )
        await emitter.send_bytes(audio_bytes)
        seq += 1

    orchestrator = ChatOrchestrator()
    try:
        async for event in orchestrator.handle(context):
            meta = event.metadata or {}
            if event.type == StreamEventType.CONTENT:
                # Speak ONLY the assistant's final answer, never narration /
                # tool-status rounds (same gate PartnerRunner uses).
                if meta.get("call_kind") != "llm_final_response":
                    continue
                token = event.content or ""
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                    await emitter.send_json(
                        {
                            "type": "stage",
                            "stage": "llm_ttft",
                            "ms": round((first_token_at - llm_start) * 1000),
                        }
                    )
                spoken_parts.append(token)
                for chunk in chunker.feed(token):
                    await speak(chunk)
            elif event.type == StreamEventType.RESULT and event.source == "chat":
                final_text = str(meta.get("response") or "")
            elif event.type == StreamEventType.ERROR and event.content:
                await emitter.send_json({"type": "error", "message": event.content})
        tail = chunker.flush()
        if tail:
            await speak(tail)
    except Exception as exc:  # noqa: BLE001 — report, don't crash the socket
        logger.exception("Voice turn failed")
        await emitter.send_json({"type": "error", "message": f"LLM/TTS: {exc}"})
        return transcript, ""

    reply = (final_text or "".join(spoken_parts)).strip()
    await emitter.send_json({"type": "assistant_text", "text": reply})
    await emitter.send_json(
        {
            "type": "done",
            "total_ms": round((time.perf_counter() - turn_t0) * 1000),
            "first_audio_ms": (
                round((first_audio_at - turn_t0) * 1000) if first_audio_at else None
            ),
        }
    )
    return transcript, reply


__all__ = ["VoiceEmitter", "build_voice_context", "run_turn"]
