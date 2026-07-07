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
        {"id": "chat", "label": "หน้าแชทหลัก / หน้าหลัก / หน้าแรก (home)"},
    ],
    "actions": [{"id": "open_kb", "label": "เปิด KB", "argument": "ชื่อ KB"}],
}


# ── manifest sanitising ────────────────────────────────────────────────


def test_sanitize_manifest_keeps_declared_targets() -> None:
    cleaned = ui_control.sanitize_manifest(MANIFEST)
    assert cleaned is not None
    assert [p["id"] for p in cleaned["pages"]] == ["settings", "knowledge", "chat"]
    assert cleaned["actions"][0]["argument"] == "ชื่อ KB"
    assert ui_control.allowed_target_ids(cleaned) == {"settings", "knowledge", "chat", "open_kb"}


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


# ── deterministic navigation shortcut ─────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ไปหน้า settings หน่อย", "settings"),
        ("พาไปที่หน้าตั้งค่าให้หน่อย", "settings"),
        ("เปิดหน้า knowledge หน่อยครับ", "knowledge"),
        ("open the settings page", "settings"),
        ("ไปที่หน้าหลัก", "chat"),
        ("กลับไปหน้าหลัก", "chat"),
        ("ไปหน้าหลัก", "chat"),
        ("ไปหน้าแรกหน่อย", "chat"),
    ],
)
def test_shortcut_matches_clear_commands(text: str, expected: str) -> None:
    assert ui_control.match_navigation_intent(text, MANIFEST) == {"target": expected}


@pytest.mark.parametrize(
    "text",
    [
        "มาตรา 112 คืออะไร",  # not a UI request at all
        "ตั้งค่าเสียงยังไงดี",  # mentions a page word-ish but no "หน้า"+verb shape
        "ไปหน้า settings แล้วช่วยอธิบายวิธีเปลี่ยนโมเดลแบบละเอียดหน่อย",  # compound → LLM
        "",
    ],
)
def test_shortcut_falls_through_to_llm(text: str) -> None:
    assert ui_control.match_navigation_intent(text, MANIFEST) is None


def test_shortcut_requires_unambiguous_page() -> None:
    both = "ไปหน้า settings กับหน้า knowledge หน่อย"  # two pages → ambiguous
    assert ui_control.match_navigation_intent(both, MANIFEST) is None
    assert ui_control.match_navigation_intent("ไปหน้า settings", None) is None


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


@pytest.mark.asyncio
async def test_clear_command_short_circuits_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'ไปหน้า settings' → ui_action + cached ack, and the LLM is never touched."""

    class _MustNotRun:
        def __init__(self) -> None:
            raise AssertionError("orchestrator must not run for a shortcut turn")

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", _MustNotRun)
    pipe._FIXED_LINE_CACHE.clear()
    emitter = FakeEmitter()

    reply = await pipe.run_text_turn(
        emitter, "ไปหน้า settings หน่อย", [], session_id="voice:test", ui_manifest=MANIFEST
    )

    assert reply == "ได้เลยครับ"
    kinds = [m["type"] for m in emitter.json]
    assert kinds == ["ui_action", "audio", "assistant_text", "done"]
    assert emitter.json[0]["target"] == "settings"

    # Second shortcut reuses the cached audio — no new synthesis call needed.
    async def broken_synthesize(text: str) -> tuple[bytes, str]:
        raise AssertionError("should have used the cache")

    monkeypatch.setattr(pipe, "synthesize_speech", broken_synthesize)
    emitter2 = FakeEmitter()
    reply2 = await pipe.run_text_turn(
        emitter2, "เปิดหน้า knowledge หน่อย", [], session_id="voice:test", ui_manifest=MANIFEST
    )
    assert reply2 == "ได้เลยครับ"
    assert emitter2.json[0]["target"] == "knowledge"
