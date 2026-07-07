"""Per-connection voice session — conversation state + barge-in.

One WebSocket connection == one :class:`VoiceSession` == one ongoing "call".
The session owns the in-memory conversation history and, crucially, the *single
in-flight turn task*. A barge-in (the user starts talking while the assistant is
still speaking) cancels that task so STT / LLM / TTS unwind immediately and the
client stops receiving audio for the abandoned turn.

Turns are serialised: a new utterance cancels any turn still running before
starting its own, so the model never answers two utterances at once on the same
call. History is kept in memory for the life of the connection only — voice is a
live medium; durable transcripts are out of scope for the MVP.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
import uuid

from deeptutor.services.voice_realtime.pipeline import (
    VoiceEmitter,
    run_text_turn,
    run_turn,
    speak_greeting,
)

logger = logging.getLogger(__name__)


class VoiceSession:
    """Drive voice turns for one WebSocket connection, with barge-in support."""

    def __init__(self, emitter: VoiceEmitter, *, language: str = "th") -> None:
        self._emitter = emitter
        self._language = language
        self.session_id = f"voice:{uuid.uuid4().hex}"
        self.history: list[dict[str, Any]] = []
        # Steerable-UI whitelist the client declared (see ui_control); None
        # until a ``ui_manifest`` control frame arrives.
        self.ui_manifest: dict[str, Any] | None = None
        # Latest current-screen snapshot the client streamed (``ui_context``
        # frames); refreshed per turn by the client, read-only on this side.
        self.ui_context: dict[str, str] | None = None
        # Cross-turn navigation state (pending "คุณหมายถึง X ใช่ไหม"
        # confirmation); owned here, mutated by the pipeline each turn.
        self.nav_state: dict[str, Any] = {}
        self._current: asyncio.Task[None] | None = None

    async def greet(self) -> None:
        """Open the call with a short spoken self-introduction.

        The line lands in history as the assistant's first message so the
        model knows it already said hello and doesn't greet twice.
        """
        try:
            line = await speak_greeting(self._emitter)
        except Exception:  # noqa: BLE001 — a failed nicety must not kill the call
            logger.debug("Greeting failed; continuing silent", exc_info=True)
            return
        if line:
            self.history.append({"role": "assistant", "content": line})

    async def handle_utterance(self, audio: bytes) -> None:
        """Start a new turn for *audio*, cancelling any turn still in flight."""
        await self.cancel_current_turn()
        self._current = asyncio.create_task(self._run(audio), name="voice:turn")

    async def handle_text(self, text: str) -> None:
        """Start a turn from client-recognised text (browser STT), skipping server STT."""
        text = (text or "").strip()
        if not text:
            return
        await self.cancel_current_turn()
        self._current = asyncio.create_task(self._run_text(text), name="voice:text-turn")

    async def cancel_current_turn(self) -> None:
        """Barge-in: stop the running turn (if any) and wait for it to unwind."""
        task = self._current
        self._current = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            # The turn was deliberately cancelled; any error during unwinding is
            # not the caller's concern (the turn is being abandoned anyway).
            logger.debug("Cancelled in-flight voice turn", exc_info=True)

    async def aclose(self) -> None:
        """Tear the session down (connection closed)."""
        await self.cancel_current_turn()

    async def _run(self, audio: bytes) -> None:
        try:
            transcript, reply = await run_turn(
                self._emitter,
                audio,
                self.history,
                session_id=self.session_id,
                language=self._language,
                ui_manifest=self.ui_manifest,
                ui_context=self.ui_context,
                nav_state=self.nav_state,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Voice turn crashed")
            return
        self._commit(transcript, reply)

    async def _run_text(self, text: str) -> None:
        try:
            reply = await run_text_turn(
                self._emitter,
                text,
                self.history,
                session_id=self.session_id,
                language=self._language,
                ui_manifest=self.ui_manifest,
                ui_context=self.ui_context,
                nav_state=self.nav_state,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Voice text turn crashed")
            return
        self._commit(text, reply)

    def _commit(self, transcript: str, reply: str) -> None:
        # Commit to history only after the turn completed without barge-in,
        # and only as a full exchange: a turn with no spoken reply (dictation
        # — the utterance belongs to the on-screen chat, not this call) must
        # not leave an unanswered user question behind, or a later LLM turn
        # will see it dangling and answer it out of nowhere.
        if transcript and reply:
            self.history.append({"role": "user", "content": transcript})
            self.history.append({"role": "assistant", "content": reply})


__all__ = ["VoiceSession"]
