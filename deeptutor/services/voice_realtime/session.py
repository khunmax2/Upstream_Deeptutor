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

from deeptutor.services.voice_realtime.agent import AgentVoiceBridge, agent_loop_enabled
from deeptutor.services.voice_realtime.pipeline import (
    VoiceEmitter,
    run_text_turn,
    run_turn,
    speak_agent_line,
    speak_greeting,
)

logger = logging.getLogger(__name__)

# How long an inventory request waits for the client's ui_inventory reply. A
# silent client costs the caller this much at worst and degrades gracefully.
INVENTORY_TIMEOUT_SECONDS = 2.5


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
        # In-flight inventory request (ui_scan → ui_inventory): the caller
        # awaits this future; the router resolves it when the client's reply
        # frame arrives. No caller right now — the deep rung that consumed it
        # was superseded; kept as the observe transport for the in-page agent
        # loop (PLAN_inpage_agent_parity Phase B).
        self._inventory_future: asyncio.Future[Any] | None = None
        # In-page agent bridge (loop + WS actuator + spoken Q&A) — created
        # lazily on first use, only when the D0 flag + agent model are set.
        self._agent: AgentVoiceBridge | None = None

    # ── in-page agent (Phase D wiring) ──

    def _ensure_agent(self) -> AgentVoiceBridge | None:
        """The session's agent bridge, or ``None`` while the flag is off."""
        if not agent_loop_enabled():
            return None
        if self._agent is None:
            self._agent = AgentVoiceBridge(
                self._emitter.send_json,
                lambda text: speak_agent_line(self._emitter, text),
                language=self._language,
            )
        return self._agent

    def _agent_runner(self) -> Any:
        """The pipeline-facing runner (``task → spoken reply``), or ``None``."""
        bridge = self._ensure_agent()
        if bridge is None:
            return None
        return bridge.run_task

    def handle_agent_frame(self, msg: dict[str, Any]) -> bool:
        """Route client ``agent_*`` frames (state chunks, act results, takeover)."""
        bridge = self._agent
        return bridge is not None and bridge.handle_frame(msg)

    async def request_ui_inventory(self) -> Any:
        """Ask the client for its indexed element inventory; ``None`` on timeout.

        The agent's eyes: sends a ``ui_scan`` frame and awaits the client's
        ``ui_inventory`` reply (resolved by the router via
        :meth:`resolve_ui_inventory`). Bounded — a silent client costs the
        caller 2.5s at worst and degrades gracefully.
        """
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._inventory_future = future
        try:
            await self._emitter.send_json({"type": "ui_scan"})
            return await asyncio.wait_for(future, timeout=INVENTORY_TIMEOUT_SECONDS)
        except (TimeoutError, asyncio.TimeoutError):
            return None
        finally:
            self._inventory_future = None

    def resolve_ui_inventory(self, items: Any) -> None:
        """Deliver a client ``ui_inventory`` frame to the awaiting turn."""
        future = self._inventory_future
        if future is not None and not future.done():
            future.set_result(items)

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
        if self._agent is not None and self._agent.running:
            self._agent.abort()  # audio arriving mid-run is a barge-in
        await self.cancel_current_turn()
        self._current = asyncio.create_task(self._run(audio), name="voice:turn")

    async def handle_text(self, text: str) -> None:
        """Start a turn from client-recognised text (browser STT), skipping server STT."""
        text = (text or "").strip()
        if not text:
            return
        # C3 speech routing: while the agent loop has a question pending
        # (ask_user / danger confirm), the utterance IS THE ANSWER — feed it to
        # the waiting future instead of cancelling the run it belongs to.
        # Any other mid-run speech is a barge-in.
        if self._agent is not None and self._agent.running:
            if self._agent.deliver_speech(text):
                logger.info("voice: speech consumed as agent answer %r", text)
                return
            self._agent.abort()
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
        if self._agent is not None:
            self._agent.abort()
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
                agent_runner=self._agent_runner(),
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
                agent_runner=self._agent_runner(),
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
