"""AgentVoiceBridge — one object that makes the loop a voice citizen (Phase D).

Owns the loop + WS actuator for a session and implements the C3 speech-routing
state machine the plan pinned as "the easiest place to get wrong":

    speech arrives while the loop runs
        ├─ a question is pending (ask_user / danger confirm)
        │       → the speech IS THE ANSWER: resolve the waiting future
        └─ nothing pending
                → it is a BARGE-IN: abort the run

The session stays thin: it asks :meth:`deliver_speech` first and only cancels
the turn when the answer wasn't consumed. Speaking is injected (a callable
that TTS-es one line) so this module never imports the pipeline — no cycles.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
import logging

from deeptutor.services.voice_realtime.agent.danger import DangerGate
from deeptutor.services.voice_realtime.agent.loop import InPageAgentLoop, Think
from deeptutor.services.voice_realtime.agent.types import Actuator
from deeptutor.services.voice_realtime.agent.ws_actuator import SendJson, WsPageActuator
from deeptutor.services.voice_realtime.ui_control import is_affirmative

logger = logging.getLogger(__name__)

# ask_user answers ride the phone line; a caller who says nothing for this
# long isn't answering. (Danger confirms carry their own timeout in the gate.)
ANSWER_TIMEOUT_S = 30.0

Speak = Callable[[str], Awaitable[None]]


class AgentVoiceBridge:
    """Per-session agent runtime: loop + actuator + spoken Q&A routing."""

    def __init__(
        self,
        send_json: SendJson,
        speak: Speak,
        *,
        language: str = "th",
        actuator: Actuator | None = None,
        think: Think | None = None,
    ) -> None:
        self._speak = speak
        self._language = language
        self._ws_actuator = None if actuator is not None else WsPageActuator(send_json)
        self._actuator: Actuator = actuator if actuator is not None else self._ws_actuator
        self._loop = InPageAgentLoop(
            self._actuator,
            ask_user=self._ask_user,
            narrate=self._narrate,
            pre_act=DangerGate(self._confirm),
            think=think,
            language=language,
        )
        self._answer: asyncio.Future[str] | None = None

    # ── state the session routes on ──

    @property
    def running(self) -> bool:
        return self._loop.running

    @property
    def waiting_on_user(self) -> bool:
        return self._loop.waiting_on_user

    def abort(self) -> None:
        """Barge-in / takeover / hang-up: stop the run, release any waiter."""
        self._loop.abort()
        answer = self._answer
        if answer is not None and not answer.done():
            answer.cancel()

    def deliver_speech(self, text: str) -> bool:
        """Feed incoming speech; True when it was consumed as an answer."""
        answer = self._answer
        if self._loop.waiting_on_user and answer is not None and not answer.done():
            answer.set_result(text)
            return True
        return False

    def handle_frame(self, msg: dict) -> bool:
        """Client agent frames: takeover aborts; the rest feed the actuator."""
        if msg.get("type") == "agent_takeover":
            logger.info("agent takeover: user clicked the mask — aborting run")
            self.abort()
            return True
        if self._ws_actuator is not None:
            return self._ws_actuator.handle_frame(msg)
        return False

    # ── the run ──

    async def run_task(self, task: str) -> str:
        """Execute one spoken task; returns the reply to show as assistant text.

        The mask goes up for exactly the lifetime of the run — including the
        abort path, where hiding it is best-effort (the socket may be dying).
        """
        if self._ws_actuator is not None:
            await self._ws_actuator.start_run()
        try:
            result = await self._loop.execute(task)
        finally:
            if self._ws_actuator is not None:
                with contextlib.suppress(Exception):
                    await self._ws_actuator.end_run()
        logger.info(
            "agent task finished reason=%s success=%s", result.stopped_reason, result.success
        )
        return result.text

    # ── loop hooks (spoken side) ──

    async def _narrate(self, text: str) -> None:
        await self._speak(text)

    async def _ask_user(self, question: str) -> str:
        await self._speak(question)
        try:
            return await asyncio.wait_for(self._new_answer(), timeout=ANSWER_TIMEOUT_S)
        except (TimeoutError, asyncio.TimeoutError):
            return "(no answer — the user stayed silent)"
        finally:
            self._answer = None

    async def _confirm(self, question: str) -> bool:
        """Danger-gate confirm: strict — only a clear yes releases the click."""
        await self._speak(question)
        try:
            answer = await self._new_answer()
        except asyncio.CancelledError:
            # The gate's own timeout cancels us: no answer is a no.
            raise
        finally:
            self._answer = None
        return is_affirmative(answer)

    def _new_answer(self) -> asyncio.Future[str]:
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._answer = future
        return future
