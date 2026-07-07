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
"""

from __future__ import annotations

import logging
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
    """LoopCapability that mounts ``ui_navigate`` when a UI manifest is present."""

    name = "voice_ui"
    owned_tools = (UI_NAVIGATE_TOOL,)

    def is_active(self, context: UnifiedContext) -> bool:
        return bool(context.metadata.get("ui_manifest"))

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        _ = language, prompts
        manifest = context.metadata.get("ui_manifest")
        if not isinstance(manifest, dict):
            return None
        lines = [
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
            "TIMING: the screen changes the instant you call the tool — before "
            "your voice reaches the caller. HARD RULE for the reply after a "
            "ui_navigate call: output EXACTLY one short phrase — 'ได้เลยครับ' or "
            "'จัดให้ครับ' — and STOP. No page description, no 'รอสักครู่', no "
            "'กำลังเปิด', no offers of further help, no follow-up questions. "
            "A one-phrase reply is correct behaviour, not rudeness: the caller "
            "is watching the screen, not waiting for narration."
        )
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
    "sanitize_manifest",
]
