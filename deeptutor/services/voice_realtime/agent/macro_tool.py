"""Action catalog + validation for the agent's single structured output.

Mirrors page-agent's MacroTool idea: every LLM turn must produce ONE object
carrying reflection fields plus exactly one action chosen from this catalog.
We enforce it via a JSON output contract in the prompt (provider-universal —
``services.llm.complete()`` returns text only) and repair/validate here; a
native forced tool_choice can be layered on later without changing callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class InvalidAction(ValueError):
    """Action failed validation; the message is written to be shown to the LLM."""


@dataclass(frozen=True)
class ActionSpec:
    description: str
    # {param: (json_type, required)} — deliberately shallow; deep schema rigor
    # buys little here and the fixer needs to stay forgiving.
    params: dict[str, tuple[str, bool]]

    @property
    def required(self) -> list[str]:
        return [k for k, (_, req) in self.params.items() if req]

    @property
    def primary_key(self) -> str | None:
        """The key a bare primitive coerces into (single-required-param tools:
        ``{"click_element_by_index": 2}`` → ``{"index": 2}``)."""
        req = self.required
        return req[0] if len(req) == 1 else None


ACTIONS: dict[str, ActionSpec] = {
    "done": ActionSpec(
        "Complete the task. `text` is your final spoken reply to the user — one or two "
        "short sentences in the user's language. Set `success` false if anything is "
        "missing or uncertain.",
        {"text": ("string", True), "success": ("boolean", False)},
    ),
    "wait": ActionSpec(
        "Wait for the page or data to finish loading.",
        {"seconds": ("number", True)},
    ),
    "ask_user": ActionSpec(
        "Ask the user one short question (it will be SPOKEN aloud) and wait for their "
        "answer. Use when you are missing information or unsure which element is meant.",
        {"question": ("string", True)},
    ),
    "click_element_by_index": ActionSpec(
        "Click the interactive element with this [index].",
        {"index": ("integer", True)},
    ),
    "input_text": ActionSpec(
        "Type text into the input element with this [index] (replaces its content).",
        {"index": ("integer", True), "text": ("string", True)},
    ),
    "select_dropdown_option": ActionSpec(
        "Select the option with this visible text in the dropdown at [index].",
        {"index": ("integer", True), "text": ("string", True)},
    ),
    "scroll": ActionSpec(
        "Scroll vertically. Without `index`: the page. With `index`: that element's "
        "scroll container (use an element marked data-scrollable).",
        {
            "down": ("boolean", False),
            "num_pages": ("number", False),
            "index": ("integer", False),
        },
    ),
}

_JSON_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}


def available_actions(*, include_ask_user: bool) -> dict[str, ActionSpec]:
    if include_ask_user:
        return ACTIONS
    return {k: v for k, v in ACTIONS.items() if k != "ask_user"}


def validate_action(
    action: dict[str, Any], actions: dict[str, ActionSpec] | None = None
) -> tuple[str, dict[str, Any]]:
    """Validate ``{tool_name: args}``; returns ``(name, args)`` or raises
    :class:`InvalidAction` with a message the LLM can act on next step."""
    actions = actions if actions is not None else ACTIONS

    if not isinstance(action, dict) or not action:
        raise InvalidAction('`action` must be an object like {"tool_name": {...params}}.')

    name = next(iter(action.keys()))
    if name not in actions:
        raise InvalidAction(f'Unknown action "{name}". Available: {", ".join(actions)}.')
    spec = actions[name]

    args = action[name]
    # Primitive coercion for single-required-param tools (page-agent's fixer rule).
    if not isinstance(args, dict):
        if spec.primary_key is not None and args is not None:
            args = {spec.primary_key: args}
        else:
            raise InvalidAction(f'Input for "{name}" must be an object of parameters.')

    for param in spec.required:
        if param not in args:
            raise InvalidAction(f'Action "{name}" is missing required parameter "{param}".')
    for param, value in args.items():
        expected = spec.params.get(param)
        if expected is None:
            continue  # tolerate extras — never fail a run over a harmless key
        json_type = expected[0]
        # An integer-looking float/string is common LLM output; coerce indexes.
        if json_type == "integer" and isinstance(value, (float, str)):
            try:
                args[param] = int(value)
                continue
            except (TypeError, ValueError):
                pass
        if not _JSON_TYPE_CHECKS[json_type](value):
            raise InvalidAction(f'Parameter "{param}" of "{name}" must be a {json_type}.')

    return name, args


def contract_lines(actions: dict[str, ActionSpec]) -> str:
    """Render the action catalog for the system prompt (name, params, purpose)."""
    lines = []
    for name, spec in actions.items():
        params = ", ".join(
            f"{p}: {t}" + ("" if req else "?") for p, (t, req) in spec.params.items()
        )
        lines.append(f"- {name}({params}) — {spec.description}")
    return "\n".join(lines)
