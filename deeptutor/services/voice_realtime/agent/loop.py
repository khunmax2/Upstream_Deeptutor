"""InPageAgentLoop — the observe → think → act loop (our own brain).

Shape proven by the page-agent evaluation (PLAN_inpage_agent_parity §1.2):
one LLM call per step produces reflection + exactly one action; history keeps
only reflections and action results; the DOM snapshot is always fresh. What is
ours by design: the actuator seam (hands live across a WebSocket), the
``pre_act`` gate (Phase C wires the danger rung there — a mechanism, not a
prompt request), voice narration hooks, and voice-tuned budgets.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
import time
from typing import Any

from deeptutor.services.voice_realtime.agent import llm as agent_llm
from deeptutor.services.voice_realtime.agent.fixer import FixerError, normalize_output
from deeptutor.services.voice_realtime.agent.macro_tool import ActionSpec, available_actions
from deeptutor.services.voice_realtime.agent.observations import ObservationTracker
from deeptutor.services.voice_realtime.agent.prompt import (
    assemble_user_prompt,
    build_system_prompt,
)
from deeptutor.services.voice_realtime.agent.types import (
    ActResult,
    Actuator,
    AgentResult,
    HistoryEvent,
    StepRecord,
)

logger = logging.getLogger(__name__)

# Voice-tuned defaults — NOT page-agent's. A caller on a phone line cannot sit
# through 40 steps (their default); 15 covers every task in the evaluation set.
# stepDelay 0.8s is the suanrao lesson for animation-heavy DOMs (theirs: 0.4).
DEFAULT_MAX_STEPS = 15
DEFAULT_STEP_DELAY_S = 0.8

# Unrepairable LLM outputs tolerated per task before giving up. Each one costs
# a step anyway (the error goes back as an observation), so this only stops
# runs where the model clearly cannot hold the contract at all.
MAX_FIXER_FAILURES = 3

AskUser = Callable[[str], Awaitable[str]]
Narrate = Callable[[str], Awaitable[None]]
# Phase C danger gate: return None to allow, or a spoken-refusal/observation
# string to block the action (the string goes to the LLM as <sys>).
PreAct = Callable[[str, dict[str, Any], str], Awaitable[str | None]]
Think = Callable[[str, str], Awaitable[str]]


class InPageAgentLoop:
    """One instance drives one task at a time against one page/actuator."""

    def __init__(
        self,
        actuator: Actuator,
        *,
        ask_user: AskUser | None = None,
        narrate: Narrate | None = None,
        pre_act: PreAct | None = None,
        think: Think | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        step_delay_s: float = DEFAULT_STEP_DELAY_S,
        language: str = "th",
    ) -> None:
        self._actuator = actuator
        self._ask_user = ask_user
        self._narrate = narrate
        self._pre_act = pre_act
        self._think = think or self._default_think
        self._max_steps = max_steps
        self._step_delay_s = step_delay_s
        self._language = language
        self._abort = asyncio.Event()
        self.running = False
        # ask_user is only offered to the LLM when someone can actually answer.
        self._actions: dict[str, ActionSpec] = available_actions(
            include_ask_user=ask_user is not None
        )

    def abort(self) -> None:
        """Barge-in / user takeover: stop after the in-flight await settles."""
        self._abort.set()

    @property
    def waiting_on_user(self) -> bool:
        """True while an ask_user/pending-action answer is expected — the
        session uses this to route incoming speech (answer vs barge-in)."""
        return self._waiting_on_user

    _waiting_on_user = False

    async def execute(self, task: str) -> AgentResult:
        if self.running:
            raise RuntimeError("A task is already running on this loop.")
        if not task.strip():
            raise ValueError("Task is required.")

        self.running = True
        self._abort.clear()
        history: list[HistoryEvent] = []
        steps: list[StepRecord] = []
        tracker = ObservationTracker(max_steps=self._max_steps)
        system_prompt = build_system_prompt(self._actions, language=self._language)
        fixer_failures = 0
        t0 = time.perf_counter()

        try:
            for step in range(self._max_steps):
                if self._abort.is_set():
                    return self._finish("aborted", False, "Task aborted by user.", steps, t0)
                if step > 0:
                    await asyncio.sleep(self._step_delay_s)

                # ── observe ──
                state = await self._actuator.observe()
                for note in tracker.collect(state.url, step):
                    history.append(("sys", note))
                    logger.info("agent obs: %s", note)

                # ── think ──
                user_prompt = assemble_user_prompt(
                    task, history, state, step=step, max_steps=self._max_steps
                )
                try:
                    raw = await self._think(system_prompt, user_prompt)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — LLM failure ends the run honestly
                    logger.exception("agent think failed")
                    return self._finish("error", False, f"LLM call failed: {exc}", steps, t0)

                if self._abort.is_set():
                    return self._finish("aborted", False, "Task aborted by user.", steps, t0)

                try:
                    output = normalize_output(raw, self._actions)
                except FixerError as exc:
                    fixer_failures += 1
                    logger.warning("agent fixer gave up on step %d: %s", step, exc)
                    if fixer_failures >= MAX_FIXER_FAILURES:
                        return self._finish(
                            "error",
                            False,
                            "The model repeatedly produced invalid output.",
                            steps,
                            t0,
                        )
                    history.append(("sys", f"Your previous reply was invalid: {exc}"))
                    continue

                action = output["action"]
                name = next(iter(action))
                args: dict[str, Any] = action[name]
                record = StepRecord(
                    index=step,
                    evaluation=output["evaluation_previous_goal"],
                    memory=output["memory"],
                    next_goal=output["next_goal"],
                    action_name=name,
                    action_input=args,
                )
                logger.info("agent step=%d action=%s goal=%r", step, name, record.next_goal[:80])

                # The caller HEARS progress — this is the voice-native part.
                if self._narrate and record.next_goal and name != "done":
                    await self._call_quietly(self._narrate, record.next_goal)

                # ── done? ──
                if name == "done":
                    success = bool(args.get("success", True))
                    text = str(args.get("text") or "").strip() or "งานจบแล้วครับ"
                    record.action_output = "Task completed"
                    steps.append(record)
                    # C4: the ending is ALWAYS spoken — success summary or an
                    # honest failure; a silent finish reads as a dead line.
                    if self._narrate:
                        await self._call_quietly(self._narrate, text)
                    return self._finish("done", success, text, steps, t0)

                # ── act (with the Phase C gate in front) ──
                record.action_output = await self._act(name, args, state.content, tracker)
                steps.append(record)
                history.append(("step", record))

            return self._finish(
                "budget", False, "Step budget exhausted before the task finished.", steps, t0
            )
        finally:
            self.running = False

    async def _act(
        self, name: str, args: dict[str, Any], page_content: str, tracker: ObservationTracker
    ) -> str:
        """Execute one action; ALWAYS returns a sentence for the history."""
        if self._pre_act:
            # The gate may pause for a spoken confirmation — while it does,
            # incoming speech is the ANSWER, not a barge-in (C3 state machine).
            self._waiting_on_user = True
            try:
                verdict = await self._pre_act(name, args, page_content)
            finally:
                self._waiting_on_user = False
            if verdict is not None:
                logger.info("agent pre_act blocked %s: %s", name, verdict)
                return f"⛔ Action blocked: {verdict}"

        tracker.note_action(name, args)

        if name == "wait":
            seconds = min(float(args.get("seconds") or 1), 10.0)
            await asyncio.sleep(seconds)
            return f"✅ Waited for {seconds:g} seconds."

        if name == "ask_user":
            assert self._ask_user is not None  # action absent from catalog otherwise
            self._waiting_on_user = True
            try:
                answer = await self._ask_user(str(args.get("question") or ""))
            finally:
                self._waiting_on_user = False
            return f"User answered: {answer}"

        try:
            result: ActResult = await self._actuator.act(name, args)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — an act failure is information, not a crash
            logger.warning("agent act %s failed", name, exc_info=True)
            return f"❌ Action failed: {exc}"
        return result.message

    def _finish(
        self, reason: str, success: bool, text: str, steps: list[StepRecord], t0: float
    ) -> AgentResult:
        logger.info(
            "agent finished reason=%s success=%s steps=%d in %.1fs",
            reason,
            success,
            len(steps),
            time.perf_counter() - t0,
        )
        return AgentResult(success=success, text=text, stopped_reason=reason, steps=steps)

    async def _call_quietly(self, fn: Callable[[str], Awaitable[None]], arg: str) -> None:
        """Narration must never break the run."""
        try:
            await fn(arg)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.debug("agent narration failed", exc_info=True)

    async def _default_think(self, system_prompt: str, user_prompt: str) -> str:
        settings = agent_llm.resolve_agent_llm()
        return await agent_llm.think(system_prompt, user_prompt, settings)
