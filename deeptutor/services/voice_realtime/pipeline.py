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
    "caller wants more detail. NEVER end with generic offers of further help "
    "('หากมีคำถามเพิ่มเติม…', 'บอกได้เลยนะครับ', 'ผมพร้อมช่วยเสมอ') — this is a "
    "live call, the caller already knows they can keep talking; end at the "
    "content. GARBLED SPEECH: the transcript comes from speech recognition and "
    "is sometimes misheard. If a turn is a very short fragment (a word or two) "
    "that fits neither the conversation nor the screen — e.g. a bare 'เริ่มต้น' "
    "out of nowhere — do NOT guess a topic and explain it: ask one short "
    "clarifying question ('ขอโทษครับ ผมฟังไม่ถนัด พูดอีกครั้งได้ไหมครับ'). "
    "Before any destructive or irreversible action "
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


def _screen_turn_note(ui_context: dict[str, str] | None) -> str:
    """Per-turn current-screen note appended to the user message.

    The full screen outline lives in the ``voice_ui`` system block, but that
    sits at the top of the prompt — live testing showed a recency-biased model
    answering "ตอนนี้อยู่หน้าไหน" from the *navigation turns in history* (loud,
    adjacent) instead of the system block (far away). Pinning the current-page
    identity right next to the question wins that fight. Same mechanism as
    ``_VOICE_TURN_REMINDER``: history commits the bare transcript, so the note
    never leaks into later turns.
    """
    if not ui_context:
        return ""
    where = str(ui_context.get("summary") or "").split("\n", 1)[0].strip()
    if not where:
        where = str(ui_context.get("path") or "").strip()
    if not where:
        return ""
    return (
        f"\n\n[จอของผู้ใช้ขณะพูดประโยคนี้: {where} — คำถามว่าอยู่หน้าไหน/บนจอมีอะไร "
        "ให้ยึดข้อมูลนี้ ไม่ใช่การนำทางในบทสนทนาก่อนหน้า]"
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
    ui_context: dict[str, str] | None = None,
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
    mounts the ``ui_navigate`` tool for this turn. ``ui_context`` (the client's
    current-screen snapshot) rides the same way so the model can describe what
    the caller actually sees.
    """
    kbs = knowledge_bases if knowledge_bases is not None else _list_knowledge_bases()
    metadata: dict[str, Any] = {
        "turn_id": f"voice-{uuid.uuid4().hex[:12]}",
        "source": "voice",
    }
    if ui_manifest:
        metadata["ui_manifest"] = ui_manifest
    if ui_context:
        metadata["ui_context"] = ui_context
    return UnifiedContext(
        session_id=session_id,
        user_message=transcript + _screen_turn_note(ui_context) + _VOICE_TURN_REMINDER,
        conversation_history=list(history),
        active_capability="chat",
        language=language,
        knowledge_bases=kbs,
        persona_context=VOICE_STYLE_DIRECTIVE,
        metadata=metadata,
    )


# ── control commands (stop/quiet) ──────────────────────────────────────
#
# "หยุดพูด" is a control command, not conversation — routing it to the LLM
# produces the absurd "I have stopped talking, and furthermore…" paragraph.
# Assistants handle stop at the system level: the previous turn is already
# cancelled by the session (a new utterance barges in), so all that's left is
# to acknowledge in one syllable and NOT start a new LLM turn.
#
# Matching is exact-after-normalisation, not substring: "วันหยุดคืออะไร"
# contains "หยุด" but is a real question and must reach the LLM.
_POLITE_BITS = ("ครับ", "ค่ะ", "คะ", "นะ", "หน่อย", "ก่อน", "เลย", "โอเค", "ที", "จ้า", " ")
_STOP_COMMANDS = {"หยุด", "หยุดพูด", "เงียบ", "พอ", "พอแล้ว", "stop", "shutup", "quiet"}
_MAX_STOP_CHARS = 24


def is_stop_command(text: str) -> bool:
    """Whether *text* is a bare stop/quiet command (see block comment above)."""
    t = (text or "").strip().lower()
    if not t or len(t) > _MAX_STOP_CHARS:
        return False
    for bit in _POLITE_BITS:
        t = t.replace(bit, "")
    return t in _STOP_COMMANDS


async def _run_stop_shortcut(emitter: VoiceEmitter, *, turn_t0: float) -> str:
    """Acknowledge a stop command in one syllable; no LLM turn."""
    ack = narration.STOP_ACK_LINE
    spoke = await _speak_fixed_line(emitter, ack)
    await emitter.send_json({"type": "assistant_text", "text": ack})
    await emitter.send_json(
        {
            "type": "done",
            "total_ms": round((time.perf_counter() - turn_t0) * 1000),
            "first_audio_ms": (round((time.perf_counter() - turn_t0) * 1000) if spoke else None),
        }
    )
    return ack


# Synthesised-once cache for fixed lines (greeting, navigation ack). These
# never change within a process, so the second call costs zero TTS latency.
# Keyed by text; invalidated implicitly on restart (which also reloads the
# TTS provider config).
_FIXED_LINE_CACHE: dict[str, tuple[bytes, str]] = {}


async def _speak_fixed_line(emitter: VoiceEmitter, text: str, *, seq: int = 0) -> bool:
    """Speak a fixed line through the TTS cache; False = TTS unavailable."""
    cached = _FIXED_LINE_CACHE.get(text)
    if cached is None:
        try:
            audio_bytes, content_type = await synthesize_speech(text)
        except VoiceProviderError:
            logger.debug("Fixed-line TTS unavailable: %r", text, exc_info=True)
            return False
        if not audio_bytes:
            return False
        cached = containerize_audio(audio_bytes, content_type)
        _FIXED_LINE_CACHE[text] = cached
    audio_bytes, content_type = cached
    await emitter.send_json(
        {"type": "audio", "seq": seq, "text": text, "content_type": content_type}
    )
    await emitter.send_bytes(audio_bytes)
    return True


async def _run_click_shortcut(emitter: VoiceEmitter, button: str, *, turn_t0: float) -> str:
    """Press a visible, caller-named button: `ui_action click_element` + ack."""
    await emitter.send_json(
        {"type": "ui_action", "action": "navigate", "target": "click_element", "argument": button}
    )
    return await _speak_short_turn(emitter, narration.NAV_ACK_LINE, turn_t0=turn_t0)


async def _run_fill_shortcut(
    emitter: VoiceEmitter, field: str, value: str, *, turn_t0: float
) -> str:
    """Type a caller-named value into a visible field: `ui_action fill_field` + ack."""
    await emitter.send_json(
        {
            "type": "ui_action",
            "action": "navigate",
            "target": "fill_field",
            "argument": value,
            "field": field,
        }
    )
    return await _speak_short_turn(emitter, narration.NAV_ACK_LINE, turn_t0=turn_t0)


async def _run_focus_shortcut(emitter: VoiceEmitter, field: str, *, turn_t0: float) -> str:
    """Focus a visible form field the caller pointed at: `ui_action focus_field` + ack."""
    await emitter.send_json(
        {
            "type": "ui_action",
            "action": "navigate",
            "target": "focus_field",
            "argument": "",
            "field": field,
        }
    )
    return await _speak_short_turn(emitter, narration.NAV_ACK_LINE, turn_t0=turn_t0)


async def _run_edit_shortcut(emitter: VoiceEmitter, field: str, op: str, *, turn_t0: float) -> str:
    """Undo typing in a visible field: `ui_action edit_field`, silent.

    Correction commands are rapid-fire and their effect is instantly visible
    (same reasoning as scroll) — no spoken ack.
    """
    await emitter.send_json(
        {
            "type": "ui_action",
            "action": "navigate",
            "target": "edit_field",
            "argument": op,
            "field": field,
        }
    )
    await emitter.send_json(
        {
            "type": "done",
            "total_ms": round((time.perf_counter() - turn_t0) * 1000),
            "first_audio_ms": None,
        }
    )
    return ""


async def _run_secretary_turn(emitter: VoiceEmitter, transcript: str, *, turn_t0: float) -> str:
    """Type one dictated utterance into the on-screen chat; say nothing.

    The screen is the responder in secretary mode — the real chat renders the
    full answer — so the voice stays silent apart from the frames the client
    needs (the typed `ui_action` and `done`). Deterministic: no LLM ever runs
    for a dictation turn.
    """
    await emitter.send_json(
        {
            "type": "ui_action",
            "action": "navigate",
            "target": "type_in_chat",
            "argument": transcript,
        }
    )
    await emitter.send_json(
        {
            "type": "done",
            "total_ms": round((time.perf_counter() - turn_t0) * 1000),
            "first_audio_ms": None,
        }
    )
    return ""


async def _set_secretary_mode(
    emitter: VoiceEmitter,
    nav_state: dict[str, Any],
    on: bool,
    *,
    turn_t0: float,
) -> str:
    """Flip secretary mode, announce it, and tell the client (mode indicator)."""
    if on:
        nav_state["secretary"] = True
    else:
        nav_state.pop("secretary", None)
    await emitter.send_json({"type": "voice_mode", "mode": "secretary" if on else "normal"})
    line = narration.SECRETARY_ON_LINE if on else narration.SECRETARY_OFF_LINE
    return await _speak_short_turn(emitter, line, turn_t0=turn_t0)


async def _speak_short_turn(emitter: VoiceEmitter, line: str, *, turn_t0: float) -> str:
    """Emit a complete no-LLM turn (cached audio + assistant_text + done)."""
    spoke = await _speak_fixed_line(emitter, line)
    await emitter.send_json({"type": "assistant_text", "text": line})
    await emitter.send_json(
        {
            "type": "done",
            "total_ms": round((time.perf_counter() - turn_t0) * 1000),
            "first_audio_ms": (round((time.perf_counter() - turn_t0) * 1000) if spoke else None),
        }
    )
    return line


async def _run_where_shortcut(emitter: VoiceEmitter, page: str, *, turn_t0: float) -> str:
    """Answer "ตอนนี้อยู่หน้าไหน" from the streamed screen context; no LLM.

    Deterministic and model-independent: the server already knows the page
    (latest ``ui_context`` frame), so the answer can't be dragged wrong by
    navigation turns in history — the failure mode the prompt-side note only
    mitigates. Line goes through the fixed-line TTS cache (one synthesis per
    distinct page per process).
    """
    line = f"ตอนนี้อยู่{page}ครับ" if page.startswith("หน้า") else f"ตอนนี้อยู่ที่หน้า {page} ครับ"
    return await _speak_short_turn(emitter, line, turn_t0=turn_t0)


async def _run_confirm_shortcut(
    emitter: VoiceEmitter,
    guess: dict[str, str],
    nav_state: dict[str, Any],
    *,
    turn_t0: float,
) -> str:
    """Ask "คุณหมายถึงให้เปิด X ใช่ไหม" for a probable-but-unverbed page command.

    STT garbles verbs often enough ("ไฟหน้า…") that guessing silently would
    misfire and — worse — the LLM sometimes acknowledges such turns without
    acting. Asking back is deterministic, honest, and one syllable away from
    executing: the pending target lands in *nav_state* and the next bare
    "ใช่/ครับ" runs the navigation without any LLM round.
    """
    nav_state["pending"] = guess["target"]
    label = guess.get("label") or guess["target"]
    line = f"คุณหมายถึงให้เปิด{label}ใช่ไหมครับ"
    return await _speak_short_turn(emitter, line, turn_t0=turn_t0)


async def _run_navigation_shortcut(
    emitter: VoiceEmitter,
    action: dict[str, str],
    *,
    turn_t0: float,
) -> str:
    """Execute an unambiguous page command without the LLM.

    Mirrors a normal turn's frames (ui_action → cached ack audio →
    assistant_text → done) so every client behaves identically, just ~an LLM
    round-trip faster and 100% deterministic.
    """
    target = action.get("target", "")
    await emitter.send_json(
        {
            "type": "ui_action",
            "action": "navigate",
            "target": target,
            "argument": action.get("argument", ""),
        }
    )
    # Scroll commands are repeated rapid-fire and their effect is instantly
    # visible — a spoken ack every time ("เลื่อนลง…ได้เลยครับ…เลื่อนลง…") is
    # noise. Voice-Control style: act silently.
    if target.startswith("scroll_"):
        await emitter.send_json(
            {
                "type": "done",
                "total_ms": round((time.perf_counter() - turn_t0) * 1000),
                "first_audio_ms": None,
            }
        )
        return ""
    ack = narration.NAV_ACK_LINE
    spoke = await _speak_fixed_line(emitter, ack)
    first_audio_ms = round((time.perf_counter() - turn_t0) * 1000) if spoke else None
    await emitter.send_json({"type": "assistant_text", "text": ack})
    await emitter.send_json(
        {
            "type": "done",
            "total_ms": round((time.perf_counter() - turn_t0) * 1000),
            "first_audio_ms": first_audio_ms,
        }
    )
    return ack


async def speak_greeting(emitter: VoiceEmitter) -> str:
    """Speak the call-opening greeting; returns the line spoken ("" on failure).

    Sent as a normal audio frame pair (meta + bytes) plus ``assistant_text`` so
    every client renders it exactly like a spoken turn (lip-sync, echo-guard
    fingerprint, chat log). A TTS failure just skips the greeting — a silent
    pickup is worse than crashing a brand-new call over a nicety.
    """
    line = narration.GREETING_LINE
    if not await _speak_fixed_line(emitter, line):
        return ""
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
    ui_context: dict[str, str] | None = None,
    nav_state: dict[str, Any] | None = None,
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
        ui_context=ui_context,
        nav_state=nav_state,
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

# Tool-calling decisions are sampled: at chat's default 0.7 the same
# "ไปหน้า settings" sometimes calls ui_navigate and sometimes just talks.
# 0.3 keeps spoken phrasing natural while making decisions near-deterministic.
# Scoped per voice turn — chat keeps its own temperature.
_VOICE_TEMPERATURE = 0.3


def _enter_fast_voice_llm_scope() -> Any:
    """Scope the LLM config to thinking-off for this voice turn (task-local).

    Returns the reset token (or ``None`` if config isn't resolvable — never
    fail a call over a latency tweak).
    """
    try:
        from deeptutor.services.llm.config import get_llm_config, set_scoped_llm_config

        base = get_llm_config()
        return set_scoped_llm_config(
            base.model_copy(
                {
                    "reasoning_effort": _VOICE_REASONING_EFFORT,
                    "temperature": _VOICE_TEMPERATURE,
                }
            )
        )
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
    ui_context: dict[str, str] | None = None,
    nav_state: dict[str, Any] | None = None,
) -> str:
    """LLM → per-sentence TTS for an already-recognised user utterance.

    Unambiguous page commands short-circuit deterministically (no LLM at
    all — see ``ui_control.match_navigation_intent``); probable-but-unverbed
    ones ask for confirmation first (``match_navigation_guess`` +
    *nav_state*, the session-owned dict carrying the pending target to the
    next turn). Everything else runs under a scoped LLM config with reasoning
    disabled and low temperature (see ``_VOICE_REASONING_EFFORT`` /
    ``_VOICE_TEMPERATURE``).
    """
    from deeptutor.services.llm.config import reset_scoped_llm_config

    t0 = turn_t0 if turn_t0 is not None else time.perf_counter()
    if is_stop_command(transcript):
        # The session already cancelled the previous (speaking) turn when this
        # utterance arrived — just acknowledge, never start an LLM turn. Stop
        # is the universal escape hatch: it also exits secretary mode.
        if nav_state is not None:
            nav_state.pop("pending", None)
            if nav_state.pop("secretary", None):
                await emitter.send_json({"type": "voice_mode", "mode": "normal"})
        logger.info("voice rung=stop %r", transcript)
        return await _run_stop_shortcut(emitter, turn_t0=t0)

    # Secretary (dictation) mode. Boundary commands stay active in BOTH modes
    # so the caller can never be trapped; inside the mode every other
    # utterance is typed into the on-screen chat, bypassing the whole ladder
    # below ("ไปหน้า settings" said while dictating is text, not a command).
    if nav_state is not None:
        mode_cmd = ui_control.match_mode_command(transcript)
        if mode_cmd == "secretary_off":
            logger.info("voice rung=mode-off %r", transcript)
            return await _set_secretary_mode(emitter, nav_state, False, turn_t0=t0)
        if mode_cmd == "secretary_on":
            logger.info("voice rung=mode-on %r", transcript)
            return await _set_secretary_mode(emitter, nav_state, True, turn_t0=t0)
        if nav_state.get("secretary"):
            # Dictation must land where the caller can see it. The screen
            # context (streamed with every turn) tells us where they are; if
            # they clicked away mid-mode, say so briefly and steer back — a
            # silent redirect with only an on-widget note was missed live.
            path = str((ui_context or {}).get("path") or "")
            if path and not path.startswith("/home"):
                logger.info("voice rung=dictate-offpage path=%s %r", path, transcript)
                await emitter.send_json(
                    {"type": "ui_action", "action": "navigate", "target": "chat", "argument": ""}
                )
                return await _speak_short_turn(
                    emitter, narration.SECRETARY_OFFPAGE_LINE, turn_t0=t0
                )
            logger.info("voice rung=dictate %r", transcript)
            return await _run_secretary_turn(emitter, transcript, turn_t0=t0)

    # A pending "คุณหมายถึง X ใช่ไหม" owns the very next utterance: bare yes
    # executes, bare no acknowledges, anything else just clears it and is
    # processed normally (the caller moved on).
    pending_click = nav_state.pop("pending_click", None) if nav_state is not None else None
    if pending_click:
        if ui_control.is_affirmative(transcript):
            logger.info("voice rung=click-confirmed button=%r", pending_click)
            return await _run_click_shortcut(emitter, pending_click, turn_t0=t0)
        if ui_control.is_negative(transcript):
            logger.info("voice rung=click-declined %r", transcript)
            return await _speak_short_turn(emitter, narration.CONFIRM_NO_ACK_LINE, turn_t0=t0)
    pending = nav_state.pop("pending", None) if nav_state is not None else None
    if pending:
        if ui_control.is_affirmative(transcript):
            logger.info("voice rung=confirm-yes target=%s %r", pending, transcript)
            return await _run_navigation_shortcut(emitter, {"target": pending}, turn_t0=t0)
        if ui_control.is_negative(transcript):
            logger.info("voice rung=confirm-no %r", transcript)
            return await _speak_short_turn(emitter, narration.CONFIRM_NO_ACK_LINE, turn_t0=t0)

    if ui_control.match_where_am_i(transcript):
        # Known-true answer held server-side; no page name in the context
        # (page outside the manifest) → fall through to the LLM instead.
        page = ui_control.spoken_page_name(ui_context)
        if page:
            logger.info("voice rung=where page=%s %r", page, transcript)
            return await _run_where_shortcut(emitter, page, turn_t0=t0)

    action = ui_control.match_navigation_intent(transcript, ui_manifest)
    if action is not None:
        logger.info("voice rung=nav target=%s %r", action.get("target"), transcript)
        return await _run_navigation_shortcut(emitter, action, turn_t0=t0)

    # Declared in-page actions with fixed-shape phrasings ("สร้างแชทใหม่",
    # "ย้อนกลับ") — after the page matcher so page-naming utterances win.
    act = ui_control.match_action_intent(transcript, ui_manifest)
    if act is not None:
        logger.info("voice rung=action target=%s %r", act.get("target"), transcript)
        return await _run_navigation_shortcut(emitter, act, turn_t0=t0)

    # Click-by-name: the caller names a button; we only verify it is visible
    # right now (ui_context.buttons) and press exactly that. Dangerous names
    # (ลบ/ยกเลิก/…) are confirmed by voice first; misses are honest dead-ends.
    click_name = ui_control.match_click_intent(transcript)
    if click_name is not None and ui_context is not None:
        # "กดที่ช่อง X" points at a form FIELD, not a button — focus it. An
        # explicit "ช่อง" never falls back to the button tiers (live gap:
        # "กดตรงช่องค้นหา" skeleton-matched the sidebar's "เอเจนต์ของฉัน").
        if click_name.startswith("ช่อง"):
            f_outcome, focus_field = ui_control.resolve_field_target(click_name, ui_context)
            if f_outcome == "hit" and focus_field:
                if nav_state is not None:
                    nav_state["last_field"] = focus_field
                logger.info("voice rung=focus field=%r %r", focus_field, transcript)
                return await _run_focus_shortcut(emitter, focus_field, turn_t0=t0)
            if f_outcome == "ambiguous":
                logger.info("voice rung=focus-ambiguous %r", transcript)
                return await _speak_short_turn(emitter, narration.FILL_AMBIGUOUS_LINE, turn_t0=t0)
            logger.info("voice rung=focus-miss %r", transcript)
            return await _speak_short_turn(emitter, narration.FILL_MISS_LINE, turn_t0=t0)
        # A name that equals a visible field label EXACTLY is that field, even
        # without "ช่อง" — beats any fuzzy button ("กดที่ค้นหาหนังสือ" is the
        # search box, not the "หนังสือ" button it contains).
        exact_field = ui_control.exact_field_hit(click_name, ui_context)
        if exact_field:
            if nav_state is not None:
                nav_state["last_field"] = exact_field
            logger.info("voice rung=focus-exact field=%r %r", exact_field, transcript)
            return await _run_focus_shortcut(emitter, exact_field, turn_t0=t0)
        outcome, button = ui_control.resolve_click_target(click_name, ui_context)
        if outcome == "hit" and button:
            if ui_control.is_dangerous_button(button):
                if nav_state is not None:
                    nav_state["pending_click"] = button
                    logger.info("voice rung=click-danger button=%r %r", button, transcript)
                    return await _speak_short_turn(
                        emitter,
                        f"ปุ่ม{button}อาจมีผลถาวรนะครับ ให้กดเลยไหมครับ",
                        turn_t0=t0,
                    )
            else:
                logger.info("voice rung=click button=%r %r", button, transcript)
                return await _run_click_shortcut(emitter, button, turn_t0=t0)
        elif outcome == "ambiguous":
            logger.info("voice rung=click-ambiguous %r", transcript)
            return await _speak_short_turn(emitter, narration.CLICK_AMBIGUOUS_LINE, turn_t0=t0)
        elif outcome == "missing":
            logger.info("voice rung=click-miss %r", transcript)
            return await _speak_short_turn(emitter, narration.CLICK_MISS_LINE, turn_t0=t0)

    # Fill-by-voice: the caller names a field and the value ("พิมพ์ X ในช่อง
    # Y"); we verify the field is visible right now (ui_context.fields) and
    # set exactly that. The value is corrected against the screen's own
    # vocabulary first (STT says "ลาวไทย", the screen says "LAWs_thai") and a
    # dropdown value must be one of its options — an honest ask beats a
    # silent non-select. Typing never submits — no danger rung needed.
    fill = ui_control.match_fill_intent(transcript)
    if fill is not None and ui_context is not None:
        outcome, field = ui_control.resolve_field_target(fill["field"], ui_context)
        if outcome == "hit" and field:
            value_status, value = ui_control.resolve_fill_value(fill["value"], field, ui_context)
            if value_status != "ok" or value is None:
                logger.info("voice rung=fill-no-option field=%r %r", field, transcript)
                return await _speak_short_turn(emitter, narration.FILL_NO_OPTION_LINE, turn_t0=t0)
            if nav_state is not None:
                nav_state["last_field"] = field  # "ลบคำสุดท้าย" knows where
            logger.info("voice rung=fill field=%r value=%r %r", field, value, transcript)
            return await _run_fill_shortcut(emitter, field, value, turn_t0=t0)
        if outcome == "ambiguous":
            logger.info("voice rung=fill-ambiguous %r", transcript)
            return await _speak_short_turn(emitter, narration.FILL_AMBIGUOUS_LINE, turn_t0=t0)
        logger.info("voice rung=fill-miss %r", transcript)
        return await _speak_short_turn(emitter, narration.FILL_MISS_LINE, turn_t0=t0)

    # Edit-by-voice: undo typing ("ล้างช่องค้นหา", "ลบคำสุดท้าย"). A bare
    # command applies to the last field filled this call (nav_state memory).
    edit = ui_control.match_edit_intent(transcript)
    if edit is not None and ui_context is not None:
        if edit["field"]:
            outcome, field = ui_control.resolve_field_target(edit["field"], ui_context)
        else:
            field = (nav_state or {}).get("last_field")
            outcome = "hit" if field else "missing"
            if not field:
                logger.info("voice rung=edit-no-field %r", transcript)
                return await _speak_short_turn(emitter, narration.EDIT_NO_FIELD_LINE, turn_t0=t0)
        if outcome == "hit" and field:
            if nav_state is not None:
                nav_state["last_field"] = field
            logger.info("voice rung=edit op=%s field=%r %r", edit["op"], field, transcript)
            return await _run_edit_shortcut(emitter, field, edit["op"], turn_t0=t0)
        if outcome == "ambiguous":
            logger.info("voice rung=edit-ambiguous %r", transcript)
            return await _speak_short_turn(emitter, narration.FILL_AMBIGUOUS_LINE, turn_t0=t0)
        logger.info("voice rung=edit-miss %r", transcript)
        return await _speak_short_turn(emitter, narration.FILL_MISS_LINE, turn_t0=t0)

    guess = ui_control.match_navigation_guess(transcript, ui_manifest)
    if guess is not None and nav_state is not None:
        logger.info("voice rung=confirm-ask target=%s %r", guess.get("target"), transcript)
        return await _run_confirm_shortcut(emitter, guess, nav_state, turn_t0=t0)

    logger.info("voice rung=llm %r", transcript)

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
            ui_context=ui_context,
            nav_state=nav_state,
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
    ui_context: dict[str, str] | None = None,
    nav_state: dict[str, Any] | None = None,
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
        ui_context=ui_context,
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
            if (
                event.type == StreamEventType.TOOL_CALL
                and event.content == ui_control.UI_CLICK_TOOL
            ):
                # LLM-initiated click. Same resolver + danger rung as the
                # deterministic shortcut (the tool result the LLM sees is
                # computed from the identical resolve, so speech and action
                # can't disagree): safe hit → press; dangerous hit → arm the
                # spoken-confirmation state, press nothing; miss/ambiguous →
                # nothing (the tool result already tells the LLM to be honest).
                args = meta.get("args") or {}
                outcome, button = ui_control.resolve_click_target(
                    str(args.get("button") or ""), ui_context
                )
                if outcome == "hit" and button:
                    if ui_control.is_dangerous_button(button):
                        if nav_state is not None:
                            nav_state["pending_click"] = button
                        logger.info("voice rung=llm-click-danger button=%r", button)
                    else:
                        logger.info("voice rung=llm-click button=%r", button)
                        await emitter.send_json(
                            {
                                "type": "ui_action",
                                "action": "navigate",
                                "target": "click_element",
                                "argument": button,
                            }
                        )
                else:
                    logger.info("voice rung=llm-click-%s %r", outcome, args.get("button"))
                continue
            if event.type == StreamEventType.TOOL_CALL and event.content == ui_control.UI_FILL_TOOL:
                # LLM-initiated fill. Same resolver as the deterministic
                # shortcut (and as the tool result the LLM sees): hit → the
                # client types the value; miss/ambiguous → nothing (the tool
                # result already tells the LLM to be honest).
                args = meta.get("args") or {}
                value = str(args.get("value") or "")
                outcome, field = ui_control.resolve_field_target(
                    str(args.get("field") or ""), ui_context
                )
                if outcome == "hit" and field and value:
                    # Same value correction as the shortcut (and as the tool
                    # result the LLM sees): dropdown values must be real
                    # options, cross-script garbles take the on-screen form.
                    value_status, final_value = ui_control.resolve_fill_value(
                        value, field, ui_context
                    )
                    if value_status == "ok" and final_value:
                        if nav_state is not None:
                            nav_state["last_field"] = field
                        logger.info("voice rung=llm-fill field=%r value=%r", field, final_value)
                        await emitter.send_json(
                            {
                                "type": "ui_action",
                                "action": "navigate",
                                "target": "fill_field",
                                "argument": final_value,
                                "field": field,
                            }
                        )
                    else:
                        logger.info("voice rung=llm-fill-no-option field=%r", field)
                else:
                    logger.info("voice rung=llm-fill-%s %r", outcome, args.get("field"))
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
                    # Known-slow tools get an immediate spoken cue; unknown
                    # tools stay silent — the watchdog speaks only if the
                    # wait turns out to be real (see narration.filler_for_tool).
                    filler = narration.filler_for_tool(started_tool)
                    if filler:
                        await speak(filler)
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
