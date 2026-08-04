"""Canonical message builders for agentic conversations."""

from __future__ import annotations

from typing import Any


def assistant_message_with_tool_calls(
    content: str,
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the assistant message that precedes tool result messages.

    Provider extras captured from the stream are echoed back verbatim. Gemini 3
    rides a REQUIRED ``thought_signature`` in ``extra_content`` on each tool-call
    delta (``run_labeled_step`` accumulates it into ``tool_call["extra"]``); the
    provider 400s any follow-up round whose replayed function call omits it, and
    the turn degrades to a forced finish. Absent extras are a no-op, so this
    stays provider-agnostic.
    """
    entries: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        entry: dict[str, Any] = {
            "id": tool_call["id"],
            "type": "function",
            "function": {
                "name": tool_call["name"],
                "arguments": tool_call.get("arguments") or "{}",
            },
        }
        for key, value in (tool_call.get("extra") or {}).items():
            entry.setdefault(key, value)
        entries.append(entry)
    return {
        "role": "assistant",
        "content": content or None,
        "tool_calls": entries,
    }


__all__ = ["assistant_message_with_tool_calls"]
