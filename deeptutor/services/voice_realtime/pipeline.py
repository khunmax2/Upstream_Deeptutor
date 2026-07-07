"""One realtime voice turn: STT → LLM (orchestrator) → per-sentence TTS.

This is where the realtime layer's design pays off. Instead of going through the
turn-based partner ``MessageBus``, ``run_turn`` drives ``ChatOrchestrator``
directly and consumes ``StreamBus`` ``CONTENT`` events as they arrive. Spoken
content is gated by ``metadata.call_kind`` (see ``_SPEAKABLE_CALL_KINDS``): the
agentic loop's user-visible rounds are voiced — including narration while tools
run, which suits a call — while tool payloads and other machinery stay silent.
Speakable tokens feed a :class:`SentenceChunker`, and each completed clause is
synthesized and streamed back immediately, so audio for sentence 1 goes out
while the LLM is still writing sentence 2.

STT and TTS reuse the catalog-driven facade in
:mod:`deeptutor.services.voice` (``transcribe_audio`` / ``synthesize_speech``),
so providers (including the new ElevenLabs / BOTNOI ones) are configured through
the same Settings > Voice catalog as the REST ``/voice`` endpoints.

The whole coroutine is cancellable: a barge-in cancels the turn task, and the
in-flight STT / LLM / TTS awaits unwind on ``CancelledError``.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import time
from typing import Any, Protocol
import uuid
import wave

from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEventType
from deeptutor.services.voice import VoiceProviderError, synthesize_speech
from deeptutor.services.voice_realtime import narration, ui_control
from deeptutor.services.voice_realtime.chunker import SentenceChunker
from deeptutor.services.voice_realtime.stt_guard import screen_transcript, transcribe_utterance

logger = logging.getLogger(__name__)

# Watchdog: the agentic loop streams events continuously, so a long silence
# means a tool is running (or has hung). We pull events with a per-event
# timeout — event flowing = healthy; quiet past REASSURE = say "still working";
# quiet past HANG = abort the turn so a stuck tool can't freeze the call.
_WATCHDOG_TICK = 5.0
_REASSURE_AFTER = 8.0
_HANG_LIMIT = 45.0


def _list_knowledge_bases() -> list[str]:
    """Every available KB name, so ``rag`` can auto-mount and the model may
    search when a question needs it (it stays unused for small talk)."""
    try:
        from deeptutor.knowledge.manager import KnowledgeBaseManager
        from deeptutor.services.path_service import get_path_service

        kb_root = get_path_service().get_knowledge_bases_root()
        if not kb_root.is_dir():
            return []
        return KnowledgeBaseManager(base_dir=str(kb_root)).list_knowledge_bases()
    except Exception:
        logger.warning("voice: failed to list knowledge bases", exc_info=True)
        return []


# Eagerly injected into the system prompt (persona slot) so the brain shapes
# its ANSWER for speech from the first token — rewriting afterwards would
# throw away the per-sentence streaming advantage. Spoken and written answers
# have different ideal lengths; this closes that gap at the source.
VOICE_STYLE_DIRECTIVE = (
    "VOICE CALL MODE — THIS OVERRIDES ALL FORMATTING RULES ABOVE AND BELOW. "
    "You are speaking on a live phone call; everything you write is read aloud "
    "by text-to-speech, so formatting characters get spoken as garbage. "
    "Answer in the caller's language. HARD RULES: at most four short spoken "
    "sentences per reply; absolutely no markdown, asterisks, headings, lists, "
    "tables, LaTeX, code or emojis; write numbers, units, and formulas out as "
    "words (say 'a squared plus b squared equals c squared', never '$a^2$'). "
    "If the full answer is long, give only the key point, then ask whether the "
    "caller wants more detail. Before any destructive or irreversible action "
    "(deleting, overwriting, sending something), say what you are about to do "
    "and get the caller's confirmation first."
)

# Appended to the current user message — the position models follow most
# reliably. History still stores the clean transcript (the session commits the
# bare text), so this never pollutes later turns.
_VOICE_TURN_REMINDER = (
    "\n\n[voice call: answer as natural speech, max four short sentences, "
    "no markdown or symbols — they will be read aloud]"
)

# Cap a chunk so a runaway clause can't block first-audio; the chunker already
# soft-breaks near this, this is just the synthesis budget.
_CHUNK_MAX_CHARS = 120

# CONTENT rounds that are user-visible speech. The agentic chat loop streams
# its rounds as ``agent_loop_round`` (including narration while tools run —
# speaking those suits a call: the tutor says what it's doing) and tags
# terminator/ask_user text ``llm_final_response``. Everything else (tool
# payloads, thinking) stays silent. Narration vs final can only be told apart
# when a round *completes*, which is too late for early per-sentence TTS.
_SPEAKABLE_CALL_KINDS = {"agent_loop_round", "llm_final_response"}

# Raw-PCM content types some TTS providers emit (s16le mono, typically 24 kHz).
# Browsers can't play bare PCM, so those chunks are wrapped in a WAV container
# before hitting the wire (mirrors the REST voice router's behaviour).
_PCM_TYPES = {"audio/pcm", "audio/x-pcm", "audio/l16"}
_PCM_PARAM = re.compile(r"(rate|sample-rate|samplerate|channels?)\s*=\s*\"?(\d+)\"?")


def _tool_starting(event: Any, meta: dict[str, Any]) -> str | None:
    """Name of the tool/retrieval this event announces the *start* of, else None.

    Two shapes reach us: a genuine ``TOOL_CALL`` (``content`` = tool name, e.g.
    ``web_search``), and RAG which the chat capability runs as a retrieval stage
    emitting ``PROGRESS`` with ``call_kind='rag_retrieval'`` + ``call_state=
    'running'`` (no TOOL_CALL). The plain agent LLM round (``agent_loop_round``)
    is not a tool and is ignored — as is the chat capability's automatic KB
    seed lookup (``call_id`` prefix ``chat-kb-seed``), which runs on *every*
    turn whenever a KB is attached; announcing it would say "searching the
    documents" even for small talk. Only retrievals the LLM chose get a filler.
    """
    if event.type == StreamEventType.TOOL_CALL and event.content:
        return str(event.content)
    if (
        event.type == StreamEventType.PROGRESS
        and meta.get("trace_kind") == "call_status"
        and meta.get("call_state") == "running"
        and not str(meta.get("call_id") or "").startswith("chat-kb-seed")
    ):
        call_kind = str(meta.get("call_kind") or "")
        if call_kind and call_kind != "agent_loop_round":
            # "rag_retrieval" → "rag" so it maps to the rag filler line.
            return (
                call_kind[: -len("_retrieval")] if call_kind.endswith("_retrieval") else call_kind
            )
    return None


def containerize_audio(audio: bytes, content_type: str) -> tuple[bytes, str]:
    """Wrap raw PCM16 in a WAV header; pass every other format through."""
    media_type, _, params = (content_type or "").partition(";")
    if media_type.strip().lower() not in _PCM_TYPES:
        return audio, content_type
    rate, channels = 24_000, 1
    for key, value in _PCM_PARAM.findall(params.lower()):
        if key.startswith("rate") or key.endswith("rate"):
            rate = int(value) or rate
        else:
            channels = int(value) or channels
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(audio)
    return buf.getvalue(), "audio/wav"


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
    knowledge_bases: list[str] | None = None,
    ui_manifest: dict[str, Any] | None = None,
) -> UnifiedContext:
    """Assemble the chat ``UnifiedContext`` for one spoken turn.

    Mirrors ``PartnerRunner._build_context`` but minimal: a voice turn runs in
    the already-active authenticated-user scope (no partner workspace), so
    rag / skills / memory resolve to the caller's own workspace. The default
    chat capability handles the turn; ``source="voice"`` tags the trace.

    Knowledge bases are attached so ``rag`` auto-mounts — the model then decides
    per turn whether to search (small talk never triggers it). Pass an explicit
    list to override; ``None`` discovers all available KBs.

    ``ui_manifest`` (the client's declared steerable UI, see ``ui_control``)
    rides in metadata; its presence activates :class:`VoiceUICapability` which
    mounts the ``ui_navigate`` tool for this turn.
    """
    kbs = knowledge_bases if knowledge_bases is not None else _list_knowledge_bases()
    metadata: dict[str, Any] = {
        "turn_id": f"voice-{uuid.uuid4().hex[:12]}",
        "source": "voice",
    }
    if ui_manifest:
        metadata["ui_manifest"] = ui_manifest
    return UnifiedContext(
        session_id=session_id,
        user_message=transcript + _VOICE_TURN_REMINDER,
        conversation_history=list(history),
        active_capability="chat",
        language=language,
        knowledge_bases=kbs,
        persona_context=VOICE_STYLE_DIRECTIVE,
        metadata=metadata,
    )


async def speak_greeting(emitter: VoiceEmitter) -> str:
    """Speak the call-opening greeting; returns the line spoken ("" on failure).

    Sent as a normal audio frame pair (meta + bytes) plus ``assistant_text`` so
    every client renders it exactly like a spoken turn (lip-sync, echo-guard
    fingerprint, chat log). A TTS failure just skips the greeting — a silent
    pickup is worse than crashing a brand-new call over a nicety.
    """
    line = narration.GREETING_LINE
    try:
        audio_bytes, content_type = await synthesize_speech(line)
    except VoiceProviderError:
        logger.debug("Greeting TTS unavailable; starting the call silent", exc_info=True)
        return ""
    if not audio_bytes:
        return ""
    audio_bytes, content_type = containerize_audio(audio_bytes, content_type)
    await emitter.send_json({"type": "audio", "seq": 0, "text": line, "content_type": content_type})
    await emitter.send_bytes(audio_bytes)
    await emitter.send_json({"type": "assistant_text", "text": line})
    return line


async def run_turn(
    emitter: VoiceEmitter,
    audio: bytes,
    history: list[dict[str, Any]],
    *,
    session_id: str,
    language: str = "th",
    ui_manifest: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Run one voice turn (audio in) and stream events/audio to *emitter*.

    Returns ``(transcript, reply)`` so the caller can update conversation
    history. Raises nothing for provider failures — they are reported to the
    client as ``error`` events and yield an empty reply; ``asyncio.CancelledError``
    (barge-in) is allowed to propagate.
    """
    turn_t0 = time.perf_counter()

    # ── STT (guarded: vocab-biased, confidence + hallucination screened) ──
    try:
        transcript, confidence = await transcribe_utterance(audio, language=language)
    except (VoiceProviderError, ValueError) as exc:
        await emitter.send_json({"type": "error", "message": f"STT: {exc}"})
        return "", ""
    transcript = transcript.strip()
    ok, reason = screen_transcript(transcript, confidence)
    if not ok:
        await emitter.send_json({"type": "error", "message": reason})
        return "", ""
    await emitter.send_json({"type": "transcript", "text": transcript})
    await emitter.send_json(
        {"type": "stage", "stage": "stt", "ms": round((time.perf_counter() - turn_t0) * 1000)}
    )
    reply = await run_text_turn(
        emitter,
        transcript,
        history,
        session_id=session_id,
        language=language,
        turn_t0=turn_t0,
        ui_manifest=ui_manifest,
    )
    return transcript, reply


# A call cannot sit through a reasoning phase: hybrid-thinking models
# (Qwen3.5, Nemotron, GLM…) burn 20 s+ before the first token, which reads as
# a dead line. "minimal" is this codebase's portable "thinking off" value —
# top-level ``reasoning_effort`` for providers like NVIDIA NIM (verified:
# TTFT 21 s → <1 s on qwen3.5), extra_body thinking flags for the
# extra-body providers (see services/llm/reasoning_params.py). Chat keeps
# full reasoning: the override is scoped to the voice turn's task only.
_VOICE_REASONING_EFFORT = "minimal"


def _enter_fast_voice_llm_scope() -> Any:
    """Scope the LLM config to thinking-off for this voice turn (task-local).

    Returns the reset token (or ``None`` if config isn't resolvable — never
    fail a call over a latency tweak).
    """
    try:
        from deeptutor.services.llm.config import get_llm_config, set_scoped_llm_config

        base = get_llm_config()
        return set_scoped_llm_config(base.model_copy({"reasoning_effort": _VOICE_REASONING_EFFORT}))
    except Exception:  # noqa: BLE001
        logger.debug("voice: could not scope LLM config; using defaults", exc_info=True)
        return None


async def run_text_turn(
    emitter: VoiceEmitter,
    transcript: str,
    history: list[dict[str, Any]],
    *,
    session_id: str,
    language: str = "th",
    turn_t0: float | None = None,
    ui_manifest: dict[str, Any] | None = None,
) -> str:
    """LLM → per-sentence TTS for an already-recognised user utterance.

    Runs under a scoped LLM config with reasoning disabled (see
    ``_VOICE_REASONING_EFFORT``) so hybrid-thinking models answer immediately.
    """
    from deeptutor.services.llm.config import reset_scoped_llm_config

    token = _enter_fast_voice_llm_scope()
    try:
        return await _run_text_turn(
            emitter,
            transcript,
            history,
            session_id=session_id,
            language=language,
            turn_t0=turn_t0,
            ui_manifest=ui_manifest,
        )
    finally:
        if token is not None:
            reset_scoped_llm_config(token)


async def _run_text_turn(
    emitter: VoiceEmitter,
    transcript: str,
    history: list[dict[str, Any]],
    *,
    session_id: str,
    language: str = "th",
    turn_t0: float | None = None,
    ui_manifest: dict[str, Any] | None = None,
) -> str:
    """LLM → per-sentence TTS for an already-recognised user utterance.

    Serves two callers: ``run_turn`` after server-side STT, and the ``user_text``
    control frame where the client did its own STT (e.g. browser Web Speech) —
    the turn is identical from the brain onward. Returns the reply text.
    """
    from deeptutor.runtime.orchestrator import ChatOrchestrator

    if turn_t0 is None:
        turn_t0 = time.perf_counter()

    # Show activity immediately: a reasoning model can take seconds before the
    # first token, and that silence shouldn't look like a frozen call.
    await emitter.send_json({"type": "status", "state": "thinking"})

    # ── LLM stream → sentence chunker → TTS ──
    context = build_voice_context(
        transcript=transcript,
        history=history,
        session_id=session_id,
        language=language,
        ui_manifest=ui_manifest,
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
        # Browsers can't play bare PCM — container it as WAV.
        audio_bytes, content_type = containerize_audio(audio_bytes, content_type)
        if first_audio_at is None:
            first_audio_at = time.perf_counter()
            await emitter.send_json(
                {
                    "type": "stage",
                    "stage": "tts_first",
                    "ms": round((first_audio_at - tts_t0) * 1000),
                }
            )
        await emitter.send_json(
            {"type": "audio", "seq": seq, "text": chunk, "content_type": content_type}
        )
        await emitter.send_bytes(audio_bytes)
        seq += 1

    orchestrator = ChatOrchestrator()
    events = orchestrator.handle(context).__aiter__()
    tool_announced = False  # spoke the "looking it up" filler this turn?
    tool_pending = False  # a tool is running (drives reassurance wording)
    reassured = False  # spoke the watchdog reassurance already?
    idle = 0.0  # seconds since the last event (watchdog)
    try:
        # Pull each event as its OWN task and poll it with a timeout — never
        # wait_for(__anext__) directly, since that cancels the generator into
        # its current await (a running tool) and corrupts the stream. A quiet
        # gap = a tool working; the watchdog reassures, then aborts if it hangs.
        pending = asyncio.ensure_future(events.__anext__())
        while True:
            done, _ = await asyncio.wait({pending}, timeout=_WATCHDOG_TICK)
            if not done:
                idle += _WATCHDOG_TICK
                if idle >= _HANG_LIMIT:
                    logger.warning("Voice turn watchdog: aborting hung turn")
                    pending.cancel()
                    await emitter.send_json({"type": "error", "message": narration.HANG_LINE})
                    await speak(narration.HANG_LINE)
                    await events.aclose()  # unwind the stuck orchestrator turn
                    return (final_text or "".join(spoken_parts)).strip()
                if tool_pending and not reassured and idle >= _REASSURE_AFTER:
                    reassured = True
                    await speak(narration.REASSURE_LINE)
                continue

            try:
                event = pending.result()
            except StopAsyncIteration:
                break
            pending = asyncio.ensure_future(events.__anext__())  # queue the next
            idle = 0.0
            meta = event.metadata or {}
            if (
                event.type == StreamEventType.TOOL_CALL
                and event.content == ui_control.UI_NAVIGATE_TOOL
            ):
                # UI steering: forward to the client, which executes it (and
                # re-validates against its own manifest). Near-instant, so no
                # filler/searching state — the model confirms it in speech.
                args = meta.get("args") or {}
                await emitter.send_json(
                    {
                        "type": "ui_action",
                        "action": "navigate",
                        "target": str(args.get("target") or ""),
                        "argument": str(args.get("argument") or ""),
                    }
                )
                continue
            started_tool = _tool_starting(event, meta)
            if started_tool is not None:
                # A tool/retrieval started — fill the coming silence with a
                # spoken cue and flag the client's "searching" state (once).
                tool_pending = True
                if not tool_announced:
                    tool_announced = True
                    await emitter.send_json(
                        {"type": "status", "state": "searching", "tool": started_tool}
                    )
                    await speak(narration.filler_for_tool(started_tool))
            elif event.type == StreamEventType.CONTENT:
                # Speak the user-visible rounds only (see _SPEAKABLE_CALL_KINDS).
                if meta.get("call_kind") not in _SPEAKABLE_CALL_KINDS:
                    continue
                tool_pending = False  # the answer is streaming; no tool to wait on
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
        return ""

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
    return reply


__all__ = [
    "VoiceEmitter",
    "build_voice_context",
    "containerize_audio",
    "run_text_turn",
    "run_turn",
    "speak_greeting",
]
