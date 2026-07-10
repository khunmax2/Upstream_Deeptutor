"""Deep target-locking rung — an LLM picks an element INDEX on a fast-path miss.

Phase B of the hybrid plan (page-agent's accuracy, our gated pipeline): when
every deterministic rung misses, the server pulls a full *indexed* inventory
of interactive elements from the client (``ui_scan`` → ``ui_inventory``
frames) and ONE scoped LLM call maps the spoken intent to an index. The
client then clicks by index — no name matching, no character budget, so
icon-only buttons, duplicate labels and long-tail phrasing all become
reachable. Runs ONLY after the fast path failed: clear commands never pay
for it.

Trust model: the inventory is what the caller's screen actually shows (same
see→name→act provenance as ``ui_context``); the LLM may only answer with an
index from the list; destructive-sounding targets are refused here — the
deep rung must never auto-press what the confirm rung was built to guard.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from deeptutor.services.voice_realtime.ui_control import (
    _CONTROL_CHARS,
    is_dangerous_button,
)

logger = logging.getLogger(__name__)

# Inventory caps — the ui_inventory frame rides the same 8K control-frame
# limit as everything else; the client budgets too, this is the backstop.
_MAX_ITEMS = 150
_MAX_LABEL_CHARS = 60
_MAX_HINT_CHARS = 40

_SYSTEM_PROMPT = (
    "You map a spoken UI command (Thai or English) to EXACTLY ONE on-screen "
    "element. You are given a numbered list of the interactive elements "
    "currently visible on the caller's screen. Reply with ONLY the number of "
    "the element the caller wants to activate — no words, no punctuation. "
    "CRITICAL: the caller SPOKE the name and speech recognition transcribed "
    "it — English UI labels arrive as Thai phonetic renderings, often badly "
    "garbled. SOUND THE NAME OUT and match by pronunciation, not spelling. "
    "Real examples of garbles you MUST catch: "
    "'กราบเหล็ก'/'กราฟเหล็ก'/'กราฟแรก' → GraphRAG; 'ลามะ อินเด็ก'/'ลามะ index' → "
    "LlamaIndex; 'เพจอินเด็กซ์' → PageIndex; 'ไลท์แร็ก' → LightRAG; "
    "'อ๊อบซิเดียน' → Obsidian. A partial phonetic match to exactly one "
    "element is a match. Reply NONE only when nothing is even phonetically "
    "close. Never pick destructive elements (delete/clear/reset) unless the "
    "caller unmistakably named them."
)


def sanitize_inventory(raw: Any) -> list[dict[str, Any]]:
    """Validate + trim a client ``ui_inventory`` payload; ``[]`` when unusable.

    Same discipline as the other client frames: malformed input drops
    silently — a bad scan must never crash the turn, it just falls back to
    the honest miss line.
    """
    if not isinstance(raw, list):
        return []
    items: list[dict[str, Any]] = []
    for entry in raw[:_MAX_ITEMS]:
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry.get("i"))
        except (TypeError, ValueError):
            continue
        label = _CONTROL_CHARS.sub("", str(entry.get("label") or "").strip())
        hint = _CONTROL_CHARS.sub("", str(entry.get("hint") or "").strip())
        tag = _CONTROL_CHARS.sub("", str(entry.get("tag") or "").strip())[:16]
        if index < 0 or (not label and not hint):
            continue  # unaddressable even for the LLM
        items.append(
            {
                "i": index,
                "tag": tag,
                "label": label[:_MAX_LABEL_CHARS],
                "hint": hint[:_MAX_HINT_CHARS],
            }
        )
    return items


def format_inventory(items: list[dict[str, Any]]) -> str:
    """The numbered element list the LLM reads."""
    lines: list[str] = []
    for item in items:
        parts = [p for p in (item["label"], item["hint"]) if p]
        lines.append(f"[{item['i']}] <{item['tag'] or 'el'}> {' — '.join(parts)}")
    return "\n".join(lines)


def parse_index_reply(reply: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The chosen item for an LLM *reply*, or ``None`` (miss / refused).

    Index authoritative, strict: the first integer in the reply must name a
    real inventory index. Destructive-sounding labels are refused HERE —
    server-side, whatever the model said.
    """
    text = (reply or "").strip()
    if not text or text.upper().startswith("NONE"):
        return None
    match = re.search(r"\d+", text)
    if not match:
        return None
    index = int(match.group())
    for item in items:
        if item["i"] == index:
            if is_dangerous_button(item["label"]):
                logger.info("voice deep-pick refused dangerous label %r", item["label"])
                return None
            return item
    return None


async def pick_element(
    spoken: str, transcript: str, items: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """One scoped LLM call: spoken intent → inventory item (or ``None``)."""
    if not items:
        return None
    from deeptutor.services.llm.client import LLMClient
    from deeptutor.services.llm.config import get_llm_config

    prompt = (
        f"Caller's utterance: {transcript!r}\n"
        f"Extracted target name (may be garbled): {spoken!r}\n\n"
        f"Interactive elements on screen:\n{format_inventory(items)}\n\n"
        "Which element number? (number only, or NONE)"
    )
    try:
        client = LLMClient(get_llm_config())
        reply = await client.complete(prompt, system_prompt=_SYSTEM_PROMPT)
    except Exception:  # noqa: BLE001 — a deep-rung failure = honest miss, never a crash
        logger.warning("voice deep-pick LLM call failed", exc_info=True)
        return None
    choice = parse_index_reply(reply, items)
    if choice is None:
        # WARNING on purpose: a deep-rung NONE is a miss the caller heard —
        # the raw reply is the evidence the next tuning round needs (INFO
        # does not reach the log file under the default config).
        logger.warning(
            "voice deep-pick NONE spoken=%r reply=%r items=%d", spoken, reply[:80], len(items)
        )
    return choice


__all__ = [
    "format_inventory",
    "parse_index_reply",
    "pick_element",
    "sanitize_inventory",
]
