"""In-page agent loop (PLAN_inpage_agent_parity Phase B) — the voice layer's
own observe→think→act brain. Server-side, actuator-agnostic, danger-gateable.
"""

from deeptutor.services.voice_realtime.agent.danger import DangerGate
from deeptutor.services.voice_realtime.agent.llm import (
    AgentLLMSettings,
    is_configured,
    resolve_agent_llm,
)
from deeptutor.services.voice_realtime.agent.loop import InPageAgentLoop
from deeptutor.services.voice_realtime.agent.types import (
    ActResult,
    Actuator,
    AgentLLMNotConfigured,
    AgentResult,
    BrowserState,
    StepRecord,
)

__all__ = [
    "ActResult",
    "Actuator",
    "AgentLLMNotConfigured",
    "AgentLLMSettings",
    "AgentResult",
    "BrowserState",
    "DangerGate",
    "InPageAgentLoop",
    "StepRecord",
    "is_configured",
    "resolve_agent_llm",
]
