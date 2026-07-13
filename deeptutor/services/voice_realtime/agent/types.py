"""Shared types for the in-page agent loop (PLAN_inpage_agent_parity Phase B).

The loop is the *brain* only. Everything that touches a real page hides behind
the :class:`Actuator` protocol, so the whole loop is testable against a scripted
fixture — the same seam page-agent proved with its LLM-free PageController.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class BrowserState:
    """One observation of the page, already serialized for the LLM.

    ``content`` is the indexed element listing (``[12]<button …>… />`` lines);
    ``header``/``footer`` carry the page identity and scroll-position hints.
    Produced browser-side (Phase A actuator); the loop never parses it.
    """

    url: str
    title: str = ""
    header: str = ""
    content: str = ""
    footer: str = ""


@dataclass(frozen=True)
class ActResult:
    """Outcome of one action, as a human/LLM-readable sentence."""

    ok: bool
    message: str


class Actuator(Protocol):
    """The hands and eyes. Implementations: WS bridge (Phase D), test fixture."""

    async def observe(self) -> BrowserState: ...

    async def act(self, name: str, args: dict[str, Any]) -> ActResult: ...


@dataclass
class StepRecord:
    """Reflection + action of one loop step (this is ALL the history keeps —
    no old DOM ever re-enters the context; that is the context-budget rule)."""

    index: int
    evaluation: str = ""
    memory: str = ""
    next_goal: str = ""
    action_name: str = ""
    action_input: dict[str, Any] = field(default_factory=dict)
    action_output: str = ""


# History events: ("step", StepRecord) or ("sys", str) — kept in arrival order
# so the prompt renders observations between the steps that produced them.
HistoryEvent = tuple[str, Any]


@dataclass
class AgentResult:
    """Terminal outcome of one task run."""

    success: bool
    text: str
    # "done" | "budget" | "aborted" | "error" | "grounding_miss"
    # (grounding_miss = the model said done+success but the loop hard-verified it
    #  did NOT land on the route the task named — issue 01; success is False.)
    stopped_reason: str
    steps: list[StepRecord] = field(default_factory=list)


class AgentLLMNotConfigured(RuntimeError):
    """The agent model is not (fully) configured — refuse loudly, never fall
    back to the chat model (paid-for lesson: a lite chat tier wrecks the loop)."""
