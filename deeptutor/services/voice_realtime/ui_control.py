"""Voice-driven UI control — the "say it, the page does it" seam.

Lets a caller steer the client UI by voice ("ไปหน้า settings", "เปิด knowledge
base"), Botnoi-WebAvatar style but with DeepTutor's own brain:

1. The client declares what can be steered — it sends a **UI manifest** control
   frame after connecting (``{"type": "ui_manifest", "manifest": {...}}``).
   The manifest is a whitelist: pages/actions the page is willing to perform.
2. When a manifest is present on the turn, :class:`VoiceUICapability` activates
   and mounts the :class:`UINavigateTool` on top of chat's normal surface,
   with a system block listing the allowed targets.
3. The LLM calls ``ui_navigate(target=...)``; the voice pipeline forwards the
   ``TOOL_CALL`` to the client as a ``{"type": "ui_action", ...}`` frame; the
   page executes it (switch view, scroll, highlight). The tool itself is a
   server-side no-op — the *client* owns the effect, and only for targets it
   declared.

Everything here is fork-additive: the tool registers through the public
``ToolRegistry.register()`` and the capability is appended to
``deeptutor.capabilities.registry.LOOP_CAPABILITIES`` at runtime by
:func:`install_ui_control` — zero upstream file edits (fork policy §3). The
capability's ``is_active`` is gated on the manifest metadata, so non-voice
turns never see any of this.

Manifest shape (all fields optional, unknown fields ignored)::

    {
      "pages":   [{"id": "settings", "label": "หน้าตั้งค่า"}, ...],
      "actions": [{"id": "open_kb",  "label": "เปิด knowledge base",
                   "argument": "ชื่อ KB"}, ...]
    }

Besides the manifest (what the page *can do*), the client may also stream
**UI context** (what the page *currently shows*): a ``ui_context`` control
frame carrying ``{"path": "/settings", "summary": "หัวข้อ: … | ปุ่ม: …"}``.
The summary is an opaque, size-capped text outline the client serialised from
its own visible DOM — the server never parses it, it only injects it into the
system block so the model can answer "หน้านี้มีเมนูอะไรบ้าง" from the real
screen instead of guessing. Read-only by design: the whitelist above stays the
only path that *acts* on the page.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import UnifiedContext
from deeptutor.core.tool_protocol import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolResult,
)

logger = logging.getLogger(__name__)

UI_NAVIGATE_TOOL = "ui_navigate"

# Guard rails on the client-supplied manifest (it rides a WS control frame).
MAX_MANIFEST_BYTES = 8_192
_MAX_TARGETS = 64

# Guard rails on the client-supplied screen context. The router already caps
# whole control frames at MAX_MANIFEST_BYTES; these keep what we *store* (and
# re-inject into every turn's prompt) well under that.
_MAX_CONTEXT_SUMMARY_CHARS = 3_000
_MAX_CONTEXT_PATH_CHARS = 200


def sanitize_manifest(raw: Any) -> dict[str, Any] | None:
    """Validate + trim a client manifest; ``None`` when unusable.

    Only the fields the prompt/tool actually use survive: ``pages`` and
    ``actions`` as lists of ``{"id", "label", "argument"}`` string entries,
    capped at ``_MAX_TARGETS`` total. Anything malformed is dropped silently —
    a UI manifest must never be able to crash a call.
    """
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    total = 0
    for section in ("pages", "actions"):
        entries = raw.get(section)
        if not isinstance(entries, list):
            continue
        kept: list[dict[str, str]] = []
        for entry in entries:
            if total >= _MAX_TARGETS:
                break
            if not isinstance(entry, dict):
                continue
            target_id = str(entry.get("id") or "").strip()
            if not target_id:
                continue
            row = {"id": target_id, "label": str(entry.get("label") or target_id).strip()}
            argument = str(entry.get("argument") or "").strip()
            if argument:
                row["argument"] = argument
            kept.append(row)
            total += 1
        if kept:
            out[section] = kept
    return out or None


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def sanitize_ui_context(raw: Any) -> dict[str, str] | None:
    """Validate + trim a client screen-context frame; ``None`` when unusable.

    Keeps only ``path`` and ``summary`` as control-char-stripped, size-capped
    strings. Like the manifest, malformed input is dropped silently — screen
    context is a nicety and must never be able to crash a call.
    """
    if not isinstance(raw, dict):
        return None
    path = _CONTROL_CHARS.sub("", str(raw.get("path") or "").strip())
    summary = _CONTROL_CHARS.sub("", str(raw.get("summary") or "").strip())
    out: dict[str, str] = {}
    if path:
        out["path"] = path[:_MAX_CONTEXT_PATH_CHARS]
    if summary:
        out["summary"] = summary[:_MAX_CONTEXT_SUMMARY_CHARS]
    return out or None


# ── deterministic navigation shortcut ─────────────────────────────────
#
# Clear navigation commands ("ไปหน้า X", "เปิดหน้า settings") are a fixed-shape
# intent — the same trick production assistants use: match them with rules and
# execute directly, skipping the LLM round entirely. 100% deterministic for
# unambiguous phrasings AND faster (no LLM latency at all). Anything long,
# ambiguous, or multi-intent falls through to the LLM as before.

_NAV_VERBS = ("ไป", "เปิด", "พา", "เข้า", "กลับ", "สลับ", "ขอ", "go", "open", "show")
_NAV_PAGE_WORDS = ("หน้า", "page")
# Longer than this = probably a compound request ("ไปหน้า settings แล้วช่วย…")
# where the LLM should own the turn.
_MAX_SHORTCUT_CHARS = 48
_LABEL_SPLIT = re.compile(r"[\s()/—·,\-]+")


def _page_match_strings(entry: dict[str, Any]) -> set[str]:
    """Strings that count as 'the caller named this page'.

    Each label token is kept both as-is and with a leading "หน้า" stripped, so
    a label alias like "หน้าหลัก" matches "ไปที่หน้าหลัก" (full form) as well
    as looser phrasings.
    """
    out = {str(entry.get("id") or "").strip().lower()}
    label = str(entry.get("label") or "").lower()
    for token in _LABEL_SPLIT.split(label):
        token = token.strip()
        if len(token) >= 3:
            out.add(token)
        if token.startswith("หน้า"):
            token = token[len("หน้า") :]
            if len(token) >= 3:
                out.add(token)
    # Generic words ("หน้า" from a label like "หน้า KB") match every
    # navigation phrase and would make all pages collide into ambiguity.
    out -= set(_NAV_PAGE_WORDS)
    out.discard("")
    return out


def match_navigation_intent(text: str, manifest: dict[str, Any] | None) -> dict[str, str] | None:
    """Return ``{"target": id}`` when *text* is an unambiguous page command.

    Conservative on purpose: requires a navigation verb, a page word, a short
    utterance, and exactly ONE matching manifest page. Everything else returns
    ``None`` and the LLM decides (multi-intent, ambiguity, non-UI questions).
    """
    if not manifest:
        return None
    t = (text or "").strip().lower()
    if not t or len(t) > _MAX_SHORTCUT_CHARS:
        return None
    if not any(w in t for w in _NAV_PAGE_WORDS):
        return None
    if not any(v in t for v in _NAV_VERBS):
        return None
    hits: list[str] = []
    for entry in manifest.get("pages") or []:
        if not isinstance(entry, dict):
            continue
        if any(m in t for m in _page_match_strings(entry)):
            target = str(entry.get("id") or "")
            if target and target not in hits:
                hits.append(target)
    if len(hits) != 1:
        return None
    return {"target": hits[0]}


def allowed_target_ids(manifest: dict[str, Any]) -> set[str]:
    """Every target id the client declared (the whitelist)."""
    return {
        str(entry.get("id"))
        for section in ("pages", "actions")
        for entry in manifest.get(section, [])
        if isinstance(entry, dict) and entry.get("id")
    }


class UINavigateTool(BaseTool):
    """Steer the caller's UI. Server-side no-op — the client executes.

    The pipeline forwards the ``TOOL_CALL`` frame to the client, which is the
    component that actually performs (and re-validates) the action, so the
    tool result only tells the LLM the command was dispatched.
    """

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=UI_NAVIGATE_TOOL,
            description=(
                "Navigate or control the user's on-screen UI during a voice call. "
                "Call this when the user asks to open/go to a page or trigger a UI "
                "action. `target` MUST be one of the target ids listed in the "
                "'Voice UI control' section of the system prompt — never invent one."
            ),
            parameters=[
                ToolParameter(
                    name="target",
                    type="string",
                    description="Target id from the declared UI manifest.",
                ),
                ToolParameter(
                    name="argument",
                    type="string",
                    description="Optional argument for the target (e.g. a KB name).",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        target = str(kwargs.get("target") or "").strip()
        if not target:
            return ToolResult(content="No target given; nothing dispatched.", success=False)
        return ToolResult(
            content=(
                f"Done — the caller's screen already shows {target!r}. "
                "Reply with EXACTLY 'ได้เลยครับ' and nothing else."
            )
        )


class VoiceUICapability:
    """LoopCapability that mounts ``ui_navigate`` when a UI manifest is present.

    Also injects the client's current-screen context (when streamed) so the
    model can answer questions about what the caller sees — read side and act
    side of the same "voice knows the screen" seam.
    """

    name = "voice_ui"
    owned_tools = (UI_NAVIGATE_TOOL,)

    def is_active(self, context: UnifiedContext) -> bool:
        return bool(context.metadata.get("ui_manifest")) or bool(context.metadata.get("ui_context"))

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        _ = language, prompts
        manifest = context.metadata.get("ui_manifest")
        screen = context.metadata.get("ui_context")
        lines: list[str] = []
        if isinstance(manifest, dict):
            lines += [
                "## Voice UI control",
                "The caller is looking at a screen you can steer with the "
                f"`{UI_NAVIGATE_TOOL}` tool. Allowed targets (id — what it does):",
            ]
            for section, header in (("pages", "Pages"), ("actions", "Actions")):
                entries = manifest.get(section) or []
                if not entries:
                    continue
                lines.append(f"{header}:")
                for entry in entries:
                    row = f"- `{entry['id']}` — {entry.get('label', entry['id'])}"
                    if entry.get("argument"):
                        row += f" (argument: {entry['argument']})"
                    lines.append(row)
            lines.append(
                "Use the tool only for explicit UI requests; answer normal questions "
                "with speech alone. Never pass a target that is not listed above. "
                "When the caller asks to go to / open a page, you MUST actually call "
                f"`{UI_NAVIGATE_TOOL}` — never answer with an acknowledgement alone: "
                "saying 'ได้เลยครับ' without the tool call means nothing happened. "
                "TIMING: the screen changes the instant you call the tool — before "
                "your voice reaches the caller. HARD RULE for the reply after a "
                "ui_navigate call: output EXACTLY one short phrase — 'ได้เลยครับ' or "
                "'จัดให้ครับ' — and STOP. No unprompted page description, no "
                "'รอสักครู่', no 'กำลังเปิด', no offers of further help, no "
                "follow-up questions. A one-phrase reply is correct behaviour, not "
                "rudeness: the caller is watching the screen, not waiting for "
                "narration."
            )
        if isinstance(screen, dict) and screen.get("summary"):
            if lines:
                lines.append("")
            lines += [
                "## Current screen",
                "What the caller's screen shows right now (captured when they last spoke):",
            ]
            if screen.get("path"):
                lines.append(f"Path: {screen['path']}")
            lines.append(str(screen["summary"]))
            lines.append(
                "When the caller ASKS what is on their screen (เมนู/ปุ่ม/หัวข้อ "
                "อะไรบ้าง), answer from this section only — never invent menus or "
                "buttons that are not listed here. STALENESS RULE: the caller can "
                "navigate by hand (clicking) at any moment, so pages you steered "
                "to in earlier turns are NOT evidence of where they are now. For "
                "'ตอนนี้อยู่หน้าไหน' trust ONLY this section — it always reflects "
                "the screen at their latest utterance and overrides anything the "
                "conversation history suggests. This overrides nothing else "
                "above: the one-phrase rule applies to your reply right after a "
                "ui_navigate call, while answering the caller's own question "
                "about the screen is normal conversation."
            )
        if not lines:
            return None
        return PromptBlock(self.name, "\n".join(lines))

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        _ = tool_name, context
        return kwargs

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        _ = context
        return ""


def install_ui_control() -> None:
    """Register the tool + capability (idempotent, runtime-only).

    Called from the voice router at import time. Uses only public extension
    surfaces: ``ToolRegistry.register()`` and rebinding the capability
    registry's ``LOOP_CAPABILITIES`` tuple — no upstream file is edited.
    """
    from deeptutor.capabilities import registry as capability_registry
    from deeptutor.runtime.registry.tool_registry import get_tool_registry

    tool_registry = get_tool_registry()
    if tool_registry.get(UI_NAVIGATE_TOOL) is None:
        tool_registry.register(UINavigateTool())
        logger.info("voice_ui: registered %s tool", UI_NAVIGATE_TOOL)

    caps = capability_registry.LOOP_CAPABILITIES
    if not any(getattr(cap, "name", "") == VoiceUICapability.name for cap in caps):
        capability_registry.LOOP_CAPABILITIES = (*caps, VoiceUICapability())
        logger.info("voice_ui: appended VoiceUICapability to LOOP_CAPABILITIES")


__all__ = [
    "MAX_MANIFEST_BYTES",
    "UI_NAVIGATE_TOOL",
    "UINavigateTool",
    "VoiceUICapability",
    "allowed_target_ids",
    "install_ui_control",
    "match_navigation_intent",
    "sanitize_manifest",
    "sanitize_ui_context",
]
