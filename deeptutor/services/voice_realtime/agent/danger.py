"""Danger gate for the agent loop (PLAN_inpage_agent_parity Phase C).

The page-agent evaluation left one trace we treat as scripture: told to
"press delete but don't confirm", it pressed the real delete button without
hesitation — its only guard is a prompt, i.e. a polite request. This gate is
the MECHANISM version: it sits in front of every click the loop executes
(``pre_act``), verifies the target's REAL serialized line against the same
danger lexicon the fast path uses (``ui_control.is_dangerous_button``), and
pauses the run for a spoken confirmation before anything irreversible fires.
No prompt wording can bypass it, because it never asks the model.

Clicks only, by the codebase's standing philosophy: typing never submits —
a submit press is its own click with its own trip through this gate.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
import re

from deeptutor.services.voice_realtime.ui_control import is_dangerous_button

logger = logging.getLogger(__name__)

# A confirmation that never arrives is a "no": the loop must keep moving (or
# finish honestly) rather than hold a phone line open forever.
DEFAULT_CONFIRM_TIMEOUT_S = 20.0

# Speak-and-listen provided by the session: ask the question aloud, return the
# user's yes/no. Same transport as ask_user — only the meaning differs.
Confirm = Callable[[str], Awaitable[bool]]

_GATED_ACTIONS = ("click_element_by_index",)


def extract_element_line(page_content: str, index: int) -> str | None:
    """The serialized ``[index]<tag …>text />`` line for *index*, if visible.

    This is the verify-before-act source of truth: the danger decision is made
    on what the page actually says the element is — not on what the model
    claims it is.
    """
    pattern = re.compile(rf"^\s*\*?\[{index}\]<.*$", re.MULTILINE)
    match = pattern.search(page_content)
    return match.group(0).strip() if match else None


class DangerGate:
    """``pre_act`` implementation: allow, or block with an LLM-readable reason."""

    def __init__(self, confirm: Confirm, *, timeout_s: float = DEFAULT_CONFIRM_TIMEOUT_S) -> None:
        self._confirm = confirm
        self._timeout_s = timeout_s

    async def __call__(self, name: str, args: dict, page_content: str) -> str | None:
        if name not in _GATED_ACTIONS:
            return None

        index = args.get("index")
        line = extract_element_line(page_content, int(index)) if index is not None else None

        if line is None:
            # Unverifiable target: the page never showed us this index's label,
            # so we cannot rule out ลบ/delete. Rare (truncated content or an
            # invented index) — err on asking rather than trusting the model.
            question = "ผมมองไม่เห็นป้ายของปุ่มที่กำลังจะกดครับ ให้กดเลยไหมครับ"
            if await self._ask(question):
                return None
            return (
                f"User did NOT confirm clicking the unverifiable element [{index}]. "
                "Do not retry it; pick an element whose label is visible, or call done."
            )

        if not is_dangerous_button(line):
            return None

        logger.info("agent danger-gate: pausing for confirmation on %s", line)
        question = f"ปุ่มนี้อาจมีผลถาวรนะครับ ({_spoken_label(line)}) ให้กดเลยไหมครับ"
        if await self._ask(question):
            logger.info("agent danger-gate: user confirmed %s", line)
            return None
        return (
            f"User REJECTED clicking ({line}). Do not click it again; "
            "find another way to satisfy the request, or call done explaining why."
        )

    async def _ask(self, question: str) -> bool:
        try:
            return await asyncio.wait_for(self._confirm(question), timeout=self._timeout_s)
        except (TimeoutError, asyncio.TimeoutError):
            logger.info("agent danger-gate: confirmation timed out → treated as no")
            return False


def _spoken_label(line: str) -> str:
    """The human part of a serialized line, for the spoken question."""
    match = re.search(r">([^>]*?) */>\s*$", line)
    label = (match.group(1).strip() if match else "") or line
    return label[:60]
