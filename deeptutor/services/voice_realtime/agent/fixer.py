"""Repair layer for the agent's LLM output (port of page-agent's autoFixer).

Models — especially over plain text transport — mangle the output contract in
recurring, fixable ways. Each heuristic below is numbered after the case list
in page-agent's ``autoFixer.ts`` (MIT, Alibaba), re-implemented for our
JSON-contract transport where the raw input is the completion *text*:

1. JSON buried in prose / code fences → extract first ``{`` … last ``}``
2. Wrapper levels: ``{"name": "AgentOutput", "arguments": …}`` and
   ``{"type": "function", "function": {…}}`` → unwrap
3. Double-stringified arguments → parse again
4. Action-level-only output (no reflection wrapper) → wrap as ``{action: …}``
5. Primitive action input → coerced in ``validate_action``
6. No action at all → fallback ``wait 1s`` (keeps the loop alive; the next
   observation tells the model what happened)
7. Action named by a FIELD, not the key
   (``{"action_name": "click_element_by_index", "index": 2}``) → reshape to
   ``{"click_element_by_index": {"index": 2}}``. Ours, not page-agent's — the
   shape llama-3.x emits live on Groq's OpenAI-compat endpoint (Phase E).

This layer is WHY the loop tolerates mid-tier models; treat every removed
heuristic as a regression.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from deeptutor.services.voice_realtime.agent.macro_tool import (
    ACTIONS,
    ActionSpec,
    InvalidAction,
    validate_action,
)

logger = logging.getLogger(__name__)

_REFLECTION_KEYS = ("evaluation_previous_goal", "memory", "next_goal", "thinking")
# Fields a model may use to NAME the action instead of making it the object key.
_ACTION_NAME_FIELDS = ("action_name", "action_type", "tool_name", "tool", "name", "action")


class FixerError(ValueError):
    """Output was unrepairable; message is written to be shown to the LLM."""


def _safe_parse(value: Any) -> Any:
    """Parse if it's a JSON string, otherwise return unchanged (their safeJsonParse)."""
    if isinstance(value, str):
        try:
            return json.loads(value.strip())
        except (json.JSONDecodeError, ValueError):
            return value
    return value


def _unwrap_named_action(action: Any, actions: dict[str, ActionSpec]) -> Any:
    """Heuristic #7: the action named by a FIELD, not the object key.

    Some models (llama-3.x observed live on Groq) emit a flat action —
    ``{"action_name": "click_element_by_index", "index": 2}`` — instead of the
    keyed ``{"click_element_by_index": {"index": 2}}`` the contract asks for.
    Reshape it when the object isn't already keyed by a known action but one of
    its name fields points at one. Left unchanged otherwise (validate_action
    still owns the real verdict)."""
    if not isinstance(action, dict) or not action:
        return action
    if next(iter(action)) in actions:
        return action  # already {verb: args}
    for field in _ACTION_NAME_FIELDS:
        verb = action.get(field)
        if isinstance(verb, str) and verb in actions:
            args = {k: v for k, v in action.items() if k not in _ACTION_NAME_FIELDS}
            return {verb: args}
    return action


def _extract_json(text: str) -> Any | None:
    """Heuristic #1: first ``{`` to last ``}`` — survives prose and code fences."""
    match = re.search(r"({[\s\S]*})", text)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return None


def normalize_output(raw_text: str, actions: dict[str, ActionSpec] | None = None) -> dict[str, Any]:
    """Text completion → validated ``{evaluation…, memory, next_goal, action}``.

    Raises :class:`FixerError` when nothing salvageable is present — the loop
    turns that into a system observation and gives the model another step.
    """
    parsed = _extract_json(raw_text)
    if parsed is None:
        raise FixerError(
            "Your reply contained no valid JSON object. Reply with ONLY the JSON output "
            "object described in the system prompt."
        )

    # Heuristic #2: unwrap tool-call shaped envelopes.
    if isinstance(parsed, dict) and parsed.get("name") == "AgentOutput":
        logger.debug("agent fixer #2a: unwrapping name/arguments envelope")
        parsed = _safe_parse(parsed.get("arguments"))
    if isinstance(parsed, dict) and parsed.get("type") == "function":
        logger.debug("agent fixer #2b: unwrapping function envelope")
        parsed = _safe_parse((parsed.get("function") or {}).get("arguments"))

    # Heuristic #3: double-stringified.
    parsed = _safe_parse(parsed)
    if not isinstance(parsed, dict):
        raise FixerError("Your JSON output must be an object, not a list or scalar.")

    # Heuristic #4: bare action object without the reflection wrapper.
    if "action" not in parsed and not any(k in parsed for k in _REFLECTION_KEYS):
        logger.debug("agent fixer #4: wrapping bare action")
        parsed = {"action": parsed}

    parsed["action"] = _safe_parse(parsed.get("action"))

    # Heuristic #6: keep the loop alive rather than crash the turn.
    if not parsed.get("action"):
        logger.debug("agent fixer #6: missing action → wait 1s")
        parsed["action"] = {"wait": {"seconds": 1}}

    # Heuristic #7: action named by a field rather than the object key.
    parsed["action"] = _unwrap_named_action(
        parsed["action"], actions if actions is not None else ACTIONS
    )

    try:
        name, args = validate_action(parsed["action"], actions)  # includes heuristic #5
    except InvalidAction as exc:
        raise FixerError(str(exc)) from exc
    parsed["action"] = {name: args}

    for key in ("evaluation_previous_goal", "memory", "next_goal"):
        value = parsed.get(key)
        parsed[key] = value.strip() if isinstance(value, str) else ""

    return parsed
