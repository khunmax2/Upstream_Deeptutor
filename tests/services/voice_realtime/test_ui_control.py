"""Tests for voice-driven UI control (manifest → capability → ui_action frame)."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.voice_realtime import pipeline as pipe
from deeptutor.services.voice_realtime import ui_control
from tests.services.voice_realtime.test_pipeline import FakeEmitter, _content, _patch_common

MANIFEST = {
    "pages": [
        {"id": "settings", "label": "หน้าตั้งค่า"},
        {"id": "knowledge", "label": "หน้า KB"},
    ],
    "actions": [{"id": "open_kb", "label": "เปิด KB", "argument": "ชื่อ KB"}],
}


# ── manifest sanitising ────────────────────────────────────────────────


def test_sanitize_manifest_keeps_declared_targets() -> None:
    cleaned = ui_control.sanitize_manifest(MANIFEST)
    assert cleaned is not None
    assert [p["id"] for p in cleaned["pages"]] == ["settings", "knowledge"]
    assert cleaned["actions"][0]["argument"] == "ชื่อ KB"
    assert ui_control.allowed_target_ids(cleaned) == {"settings", "knowledge", "open_kb"}


@pytest.mark.parametrize("raw", [None, "x", 42, [], {}, {"pages": "nope"}, {"pages": [{}]}])
def test_sanitize_manifest_rejects_garbage(raw: Any) -> None:
    assert ui_control.sanitize_manifest(raw) is None


def test_sanitize_manifest_caps_target_count() -> None:
    huge = {"pages": [{"id": f"p{i}"} for i in range(500)]}
    cleaned = ui_control.sanitize_manifest(huge)
    assert cleaned is not None
    assert len(cleaned["pages"]) == 64


# ── capability gating ──────────────────────────────────────────────────


def test_capability_active_only_with_manifest() -> None:
    cap = ui_control.VoiceUICapability()
    with_manifest = pipe.build_voice_context(
        transcript="q", history=[], session_id="s", knowledge_bases=[], ui_manifest=MANIFEST
    )
    without = pipe.build_voice_context(
        transcript="q", history=[], session_id="s", knowledge_bases=[]
    )
    assert cap.is_active(with_manifest)
    assert not cap.is_active(without)
    assert "ui_manifest" not in without.metadata


def test_system_block_lists_targets() -> None:
    cap = ui_control.VoiceUICapability()
    ctx = pipe.build_voice_context(
        transcript="q", history=[], session_id="s", knowledge_bases=[], ui_manifest=MANIFEST
    )
    block = cap.system_block(ctx, language="th", prompts={})
    assert block is not None
    assert "`settings`" in block.content
    assert "`open_kb`" in block.content


def test_install_is_idempotent() -> None:
    from deeptutor.capabilities import registry as capability_registry
    from deeptutor.runtime.registry.tool_registry import get_tool_registry

    ui_control.install_ui_control()
    ui_control.install_ui_control()
    names = [getattr(c, "name", "") for c in capability_registry.LOOP_CAPABILITIES]
    assert names.count("voice_ui") == 1
    assert get_tool_registry().get(ui_control.UI_NAVIGATE_TOOL) is not None


@pytest.mark.asyncio
async def test_tool_execute_requires_target() -> None:
    tool = ui_control.UINavigateTool()
    ok = await tool.execute(target="settings")
    missing = await tool.execute()
    assert ok.success and "settings" in ok.content
    assert not missing.success


# ── pipeline forwarding ────────────────────────────────────────────────


def _ui_tool_call(target: str, argument: str = "") -> StreamEvent:
    args: dict[str, Any] = {"target": target}
    if argument:
        args["argument"] = argument
    return StreamEvent(
        type=StreamEventType.TOOL_CALL,
        source="chat",
        content=ui_control.UI_NAVIGATE_TOOL,
        metadata={"args": args},
    )


@pytest.mark.asyncio
async def test_ui_navigate_forwarded_as_ui_action_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ui_navigate TOOL_CALL → one ui_action frame, no spoken filler for it."""
    events = [
        _ui_tool_call("open_kb", "LAWs_thai"),
        _content("เปิดหน้า KB ให้แล้วครับ.", call_kind="llm_final_response"),
        StreamEvent(type=StreamEventType.RESULT, source="chat", metadata={"response": "เปิดให้แล้ว"}),
    ]
    spoken = _patch_common(monkeypatch, events=events)
    emitter = FakeEmitter()

    await pipe.run_text_turn(
        emitter, "เปิดคลังกฎหมายให้หน่อย", [], session_id="voice:test", ui_manifest=MANIFEST
    )

    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert actions == [
        {"type": "ui_action", "action": "navigate", "target": "open_kb", "argument": "LAWs_thai"}
    ]
    # The near-instant UI hop must not trigger the "searching" filler…
    assert not any(m.get("state") == "searching" for m in emitter.json if m.get("type") == "status")
    # …but the spoken confirmation still flows.
    assert any("เปิดหน้า" in chunk for chunk in spoken), spoken
