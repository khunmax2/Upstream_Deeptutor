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


# ── screen-context sanitising ──────────────────────────────────────────

SCREEN = {"path": "/settings", "summary": "หัวข้อ: ตั้งค่า\nปุ่ม: บันทึก | ยกเลิก"}


def test_sanitize_ui_context_keeps_path_and_summary() -> None:
    cleaned = ui_control.sanitize_ui_context(SCREEN)
    assert cleaned == SCREEN


def test_sanitize_ui_context_keeps_page_label() -> None:
    cleaned = ui_control.sanitize_ui_context({**SCREEN, "page": "หน้าตั้งค่า (settings)"})
    assert cleaned is not None
    assert cleaned["page"] == "หน้าตั้งค่า (settings)"


# ── deterministic "which page am I on" shortcut ────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "ตอนนี้อยู่หน้าไหน",
        "อยู่หน้าไหนครับ",
        "อยู่ที่หน้าไหนแล้วเนี่ย",
        "นี่หน้าอะไรครับ",
        "นี่คือหน้าอะไร",
        "where am I?",
        "what page is this",
    ],
)
def test_where_matcher_accepts_bare_questions(text: str) -> None:
    assert ui_control.match_where_am_i(text)


@pytest.mark.parametrize(
    "text",
    [
        "หน้าหลักมีเมนูอะไรบ้าง",  # about a page's contents, not location
        "ไปหน้าไหนดี",  # asking for a suggestion
        "อยู่หน้าไหน แล้วหน้านี้ใช้ทำอะไรได้บ้างช่วยบอกหน่อย",  # compound → LLM
        "วันหยุดคืออะไร",
        "",
    ],
)
def test_where_matcher_falls_through_to_llm(text: str) -> None:
    assert not ui_control.match_where_am_i(text)


def test_spoken_page_name_takes_first_alias() -> None:
    assert (
        ui_control.spoken_page_name({"page": "หน้าแชทหลัก / หน้าหลัก / หน้าแรก (home, คุยกับ DeepTutor)"})
        == "หน้าแชทหลัก"
    )
    assert ui_control.spoken_page_name({"page": "หน้าตั้งค่า (settings)"}) == "หน้าตั้งค่า"
    assert ui_control.spoken_page_name({"path": "/x"}) == ""
    assert ui_control.spoken_page_name(None) == ""


@pytest.mark.parametrize("raw", [None, "x", 42, [], {}, {"path": "", "summary": "  "}])
def test_sanitize_ui_context_rejects_garbage(raw: Any) -> None:
    assert ui_control.sanitize_ui_context(raw) is None


def test_sanitize_ui_context_caps_and_strips() -> None:
    cleaned = ui_control.sanitize_ui_context(
        {"path": "/p" * 500, "summary": "x\x00\x07" + "ย" * 5_000}
    )
    assert cleaned is not None
    assert len(cleaned["path"]) == 200
    assert len(cleaned["summary"]) == 3_000
    assert "\x00" not in cleaned["summary"] and "\x07" not in cleaned["summary"]


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
    assert "Current screen" not in block.content  # no context streamed


def test_screen_context_pins_identity_next_to_the_turn() -> None:
    """The current-page line rides the user message itself (recency wins)."""
    ctx = pipe.build_voice_context(
        transcript="ตอนนี้อยู่หน้าไหน",
        history=[],
        session_id="s",
        knowledge_bases=[],
        ui_context={"path": "/notebook", "summary": "หน้าปัจจุบัน: หน้าสมุดโน้ต (/notebook)\nปุ่ม: ลบ"},
    )
    assert "จอของผู้ใช้ขณะพูดประโยคนี้: หน้าปัจจุบัน: หน้าสมุดโน้ต (/notebook)" in ctx.user_message
    assert "ปุ่ม: ลบ" not in ctx.user_message  # only the identity line, not the outline

    bare = pipe.build_voice_context(
        transcript="ตอนนี้อยู่หน้าไหน", history=[], session_id="s", knowledge_bases=[]
    )
    assert "จอของผู้ใช้" not in bare.user_message


def test_screen_context_activates_and_lands_in_system_block() -> None:
    cap = ui_control.VoiceUICapability()
    ctx = pipe.build_voice_context(
        transcript="q",
        history=[],
        session_id="s",
        knowledge_bases=[],
        ui_manifest=MANIFEST,
        ui_context=SCREEN,
    )
    assert cap.is_active(ctx)
    block = cap.system_block(ctx, language="th", prompts={})
    assert block is not None
    # Both halves present: steerable targets AND what the screen shows now.
    assert "`settings`" in block.content
    assert "## Current screen" in block.content
    assert "Path: /settings" in block.content
    assert "ปุ่ม: บันทึก | ยกเลิก" in block.content

    # Context alone (no manifest) still activates — read-only turns work.
    ctx_only = pipe.build_voice_context(
        transcript="q", history=[], session_id="s", knowledge_bases=[], ui_context=SCREEN
    )
    assert cap.is_active(ctx_only)
    block_only = cap.system_block(ctx_only, language="th", prompts={})
    assert block_only is not None
    assert "## Current screen" in block_only.content
    assert "Allowed targets" not in block_only.content


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


def test_shortcut_normalizes_stt_garbles_of_pai_naa() -> None:
    """STT hears "ไฟหน้า"/"ใบหน้า" for "ไปหน้า" — still a direct command."""
    assert ui_control.match_navigation_intent("ไฟหน้าตั้งค่า", MANIFEST) == {"target": "settings"}
    assert ui_control.match_navigation_intent("ใบหน้าตั้งค่าหน่อย", MANIFEST) == {"target": "settings"}


# ── confirm-first navigation guess ─────────────────────────────────────


def test_guess_fires_for_verbless_page_naming() -> None:
    guess = ui_control.match_navigation_guess("หน้าตั้งค่า", MANIFEST)
    assert guess == {"target": "settings", "label": "หน้าตั้งค่า"}
    # Aliased label speaks its first alias only.
    guess = ui_control.match_navigation_guess("หน้าแรก", MANIFEST)
    assert guess is not None and guess["label"] == "หน้าแชทหลัก"


@pytest.mark.parametrize(
    "text",
    [
        "ไปหน้าตั้งค่า",  # verbed → direct shortcut's job, not a guess
        "หน้าตั้งค่าคืออะไร",  # question about the page
        "หน้าตั้งค่ามีอะไรบ้าง",  # question
        "หน้าไหนดี",  # names no page
        "",
    ],
)
def test_guess_stays_quiet_otherwise(text: str) -> None:
    assert ui_control.match_navigation_guess(text, MANIFEST) is None


@pytest.mark.parametrize("text", ["ใช่", "ใช่ครับ", "ครับ", "ตกลงค่ะ", "yes"])
def test_affirmative_forms(text: str) -> None:
    assert ui_control.is_affirmative(text)
    assert not ui_control.is_negative(text)


@pytest.mark.parametrize("text", ["ไม่", "ไม่ใช่ครับ", "ไม่ต้อง", "ยกเลิก"])
def test_negative_forms(text: str) -> None:
    assert ui_control.is_negative(text)
    assert not ui_control.is_affirmative(text)


@pytest.mark.parametrize("text", ["ใช่ไหมนะ ไม่แน่ใจ", "ไปหน้า settings", "อะไรนะ"])
def test_neither_yes_nor_no(text: str) -> None:
    assert not ui_control.is_affirmative(text)
    assert not ui_control.is_negative(text)


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
async def test_where_am_i_short_circuits_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'ตอนนี้อยู่หน้าไหน' answers from ui_context deterministically — no LLM."""

    class _MustNotRun:
        def __init__(self) -> None:
            raise AssertionError("orchestrator must not run for a where-am-i turn")

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", _MustNotRun)
    pipe._FIXED_LINE_CACHE.clear()
    emitter = FakeEmitter()

    reply = await pipe.run_text_turn(
        emitter,
        "ตอนนี้อยู่หน้าไหนครับ",
        [],
        session_id="voice:test",
        ui_manifest=MANIFEST,
        ui_context={"path": "/notebook", "page": "หน้าสมุดโน้ต", "summary": "x"},
    )

    assert reply == "ตอนนี้อยู่หน้าสมุดโน้ตครับ"
    kinds = [m["type"] for m in emitter.json]
    assert kinds == ["audio", "assistant_text", "done"]


@pytest.mark.asyncio
async def test_where_am_i_without_page_falls_through_to_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No page name in the context (unmapped page) → normal LLM turn."""
    events = [
        _content("อยู่หน้ารายละเอียดเอกสารครับ.", call_kind="llm_final_response"),
        StreamEvent(
            type=StreamEventType.RESULT,
            source="chat",
            metadata={"response": "อยู่หน้ารายละเอียดเอกสารครับ"},
        ),
    ]
    _patch_common(monkeypatch, events=events)
    emitter = FakeEmitter()

    reply = await pipe.run_text_turn(
        emitter,
        "ตอนนี้อยู่หน้าไหนครับ",
        [],
        session_id="voice:test",
        ui_manifest=MANIFEST,
        ui_context={"path": "/kb/detail/42", "summary": "หัวข้อ: เอกสาร"},
    )

    # The LLM (not the shortcut) owned the turn — proven by the LLM-path reply.
    assert "อยู่หน้ารายละเอียดเอกสาร" in reply


@pytest.mark.asyncio
async def test_confirm_flow_asks_then_navigates_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verbless page naming → 'คุณหมายถึง…ใช่ไหม' → 'ใช่' → ui_action. No LLM."""

    class _MustNotRun:
        def __init__(self) -> None:
            raise AssertionError("orchestrator must not run in the confirm flow")

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", _MustNotRun)
    pipe._FIXED_LINE_CACHE.clear()
    nav_state: dict[str, Any] = {}

    # Turn 1: probable command, no verb (STT dropped it) → asks back, no ui_action.
    emitter1 = FakeEmitter()
    reply1 = await pipe.run_text_turn(
        emitter1, "หน้าตั้งค่า", [], session_id="v", ui_manifest=MANIFEST, nav_state=nav_state
    )
    assert reply1 == "คุณหมายถึงให้เปิดหน้าตั้งค่าใช่ไหมครับ"
    assert nav_state == {"pending": "settings"}
    assert not [m for m in emitter1.json if m.get("type") == "ui_action"]

    # Turn 2: bare yes → navigation executes, pending cleared.
    emitter2 = FakeEmitter()
    reply2 = await pipe.run_text_turn(
        emitter2, "ใช่ครับ", [], session_id="v", ui_manifest=MANIFEST, nav_state=nav_state
    )
    assert reply2 == "ได้เลยครับ"
    assert emitter2.json[0] == {
        "type": "ui_action",
        "action": "navigate",
        "target": "settings",
        "argument": "",
    }
    assert nav_state == {}


@pytest.mark.asyncio
async def test_confirm_flow_no_clears_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    pipe._FIXED_LINE_CACHE.clear()
    nav_state: dict[str, Any] = {"pending": "settings"}

    emitter = FakeEmitter()
    reply = await pipe.run_text_turn(
        emitter, "ไม่ใช่ครับ", [], session_id="v", ui_manifest=MANIFEST, nav_state=nav_state
    )
    assert reply == "โอเคครับ"
    assert nav_state == {}
    assert not [m for m in emitter.json if m.get("type") == "ui_action"]


@pytest.mark.asyncio
async def test_confirm_flow_unrelated_utterance_moves_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neither yes nor no → pending is dropped and the turn runs normally."""
    events = [
        _content("ตอบตามปกติครับ.", call_kind="llm_final_response"),
        StreamEvent(
            type=StreamEventType.RESULT, source="chat", metadata={"response": "ตอบตามปกติครับ"}
        ),
    ]
    _patch_common(monkeypatch, events=events)
    nav_state: dict[str, Any] = {"pending": "settings"}

    emitter = FakeEmitter()
    reply = await pipe.run_text_turn(
        emitter,
        "มาตรา 112 คืออะไร",
        [],
        session_id="v",
        ui_manifest=MANIFEST,
        nav_state=nav_state,
    )
    assert "ตอบตามปกติ" in reply
    assert nav_state == {}  # a new topic clears the stale question
    assert not [m for m in emitter.json if m.get("type") == "ui_action"]


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
