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


# ── scroll shortcuts ───────────────────────────────────────────────────

SCROLL_MANIFEST = {
    "pages": [{"id": "settings", "label": "หน้าตั้งค่า"}],
    "actions": [
        {"id": "scroll_down", "label": "เลื่อนลง"},
        {"id": "scroll_up", "label": "เลื่อนขึ้น"},
        {"id": "scroll_bottom", "label": "ล่างสุด"},
        {"id": "scroll_top", "label": "บนสุด"},
    ],
}


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("เลื่อนลงหน่อย", "scroll_down"),
        ("เลื่อนขึ้นหน่อยครับ", "scroll_up"),
        ("เลื่อนไปล่างสุดเลย", "scroll_bottom"),
        ("ไปบนสุดของหน้า", "scroll_top"),
        ("scroll down", "scroll_down"),
    ],
)
def test_scroll_commands_match(text: str, target: str) -> None:
    assert ui_control.match_action_intent(text, SCROLL_MANIFEST) == {"target": target}


@pytest.mark.parametrize(
    "text",
    [
        "เลื่อนนัดประชุมให้หน่อย",  # "เลื่อน" = reschedule, no direction word
        "ช่วยเลื่อนวันสอบได้ไหม",
        "เลื่อนลงล่างสุด",  # hits two ids → ambiguous → LLM decides
    ],
)
def test_scroll_commands_fall_through(text: str) -> None:
    assert ui_control.match_action_intent(text, SCROLL_MANIFEST) is None


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("เลื่อน ลง", "scroll_down"),  # STT inserts a space
        ("เลื่อน ลง หน่อย", "scroll_down"),
        ("เลือนลง", "scroll_down"),  # STT drops the tone mark
        ("เลื่อนหลง", "scroll_down"),  # ลง → หลง, one phonetic edit
        ("เลือนขึ้น", "scroll_up"),
        ("เรื่อนลงหน่อย", "scroll_down"),  # ล↔ร homophone swap
    ],
)
def test_scroll_commands_match_stt_garbles(text: str, target: str) -> None:
    """Live gap: STT-garbled scroll commands fell past the shortcut to the
    LLM, which sometimes acked without acting ("ได้ครับ" + nothing moves)."""
    assert ui_control.match_action_intent(text, SCROLL_MANIFEST) == {"target": target}


@pytest.mark.parametrize(
    "text",
    [
        "เริ่มต้น",  # whole-word mishear of "เลื่อนลง" — no anchor left, must not guess
        "เลื่อนนัดประชุมให้หน่อย",  # still safe with fuzzy folding on
        "ช่วยเอาเลื่อยลงมาให้หน่อยนะ",  # เลื่อย (saw) ≠ เลื่อน, and utterance is long
    ],
)
def test_scroll_fuzzy_stays_conservative(text: str) -> None:
    assert ui_control.match_action_intent(text, SCROLL_MANIFEST) is None


@pytest.mark.asyncio
async def test_scroll_shortcut_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scroll acts without a spoken ack (rapid-fire commands, visible effect)."""

    class _MustNotRun:
        def __init__(self) -> None:
            raise AssertionError("orchestrator must not run for a scroll command")

    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", _MustNotRun)
    emitter = FakeEmitter()

    reply = await pipe.run_text_turn(
        emitter, "เลื่อนลงหน่อย", [], session_id="voice:test", ui_manifest=SCROLL_MANIFEST
    )

    assert reply == ""
    assert [m["type"] for m in emitter.json] == ["ui_action", "done"]
    assert emitter.json[0]["target"] == "scroll_down"
    assert emitter.audio == []  # silent


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


@pytest.mark.parametrize(
    "text",
    [
        "ไฟหน้าตั้งค่า",  # ไฟ ~ ไป (1 sub)
        "ใบหน้าตั้งค่าหน่อย",  # ใบ →(homophone ใ→ไ)→ ไบ ~ ไป
        "ไอหน้าตั้งค่า",  # ไอ ~ ไป — never seen live yet; the fuzzy rule covers it
        "ไผ่หน้าตั้งค่า",  # tone mark stripped, ไผ ~ ไป
    ],
)
def test_shortcut_tolerates_garbled_nav_verbs(text: str) -> None:
    """STT-garbled "ไปหน้า" variants are direct commands via phonetic fuzz."""
    assert ui_control.match_navigation_intent(text, MANIFEST) == {"target": "settings"}


def test_garbled_verb_does_not_hijack_plain_speech() -> None:
    # Question guard still wins even with a garble-like prefix.
    assert ui_control.match_navigation_intent("ไฟหน้าตั้งค่าคืออะไร", MANIFEST) is None
    # No page named → nothing to navigate to, however verb-like it sounds.
    assert ui_control.match_navigation_intent("ไฟหน้ารถเสีย", MANIFEST) is None


# ── deterministic in-page action shortcut ──────────────────────────────

ACTIONS_MANIFEST = {
    **MANIFEST,
    "actions": [
        {"id": "new_chat", "label": "สร้างแชทใหม่"},
        {"id": "go_back", "label": "ย้อนกลับ"},
        {"id": "open_kb", "label": "เปิดคลังความรู้", "argument": "ชื่อ KB"},
    ],
}


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("สร้างแชทใหม่ให้หน่อย", "new_chat"),
        ("ขอเริ่มแชทใหม่", "new_chat"),
        ("ย้อนกลับหน้าที่แล้วหน่อย", "go_back"),
        ("ถอยกลับที", "go_back"),
    ],
)
def test_action_matcher_fires_for_declared_actions(text: str, target: str) -> None:
    assert ui_control.match_action_intent(text, ACTIONS_MANIFEST) == {"target": target}


@pytest.mark.parametrize(
    "text",
    [
        "เปิดคลังความรู้ LAWs_thai",  # open_kb needs the LLM (name argument)
        "สร้างแชทใหม่ยังไง",  # question, not a command
        "ย้อนกลับไปดูมาตราที่แล้วอีกทีได้ไหม",  # long/compound + question word
        "",
    ],
)
def test_action_matcher_falls_through(text: str) -> None:
    assert ui_control.match_action_intent(text, ACTIONS_MANIFEST) is None


def test_action_matcher_requires_declaration() -> None:
    # Same phrasing, but the manifest declares no actions → LLM's turn.
    assert ui_control.match_action_intent("สร้างแชทใหม่", MANIFEST) is None


def test_page_naming_beats_go_back() -> None:
    """'ย้อนกลับไปหน้าหลัก' names a page → navigation, not go_back."""
    nav = ui_control.match_navigation_intent("ย้อนกลับไปหน้าหลัก", ACTIONS_MANIFEST)
    assert nav == {"target": "chat"}


# ── click-by-name ──────────────────────────────────────────────────────

CLICK_CONTEXT = {
    "path": "/notebook",
    "summary": "x",
    "buttons": ["สร้างโน้ตใหม่", "ลบโน้ต", "บันทึก", "Export"],
}


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("กดปุ่มสร้างโน้ตใหม่", "สร้างโน้ตใหม่"),
        ("ช่วยกดปุ่มบันทึกให้หน่อยครับ", "บันทึก"),
        ("คลิก export", "export"),
        ("แตะปุ่มลบโน้ตหน่อย", "ลบโน้ต"),
        # Leading connectives must not leak into the name (live gap:
        # "กดที่ประวัติแชท" resolved as "ที่ประวัติแชท" and missed).
        ("กดที่ประวัติแชท", "ประวัติแชท"),
        ("กดที่ปุ่มบันทึก", "บันทึก"),
        ("คลิกตรงที่การ์ดสมุดบันทึก", "สมุดบันทึก"),
    ],
)
def test_click_matcher_extracts_button_name(text: str, name: str) -> None:
    assert ui_control.match_click_intent(text) == name


@pytest.mark.parametrize(
    "text",
    [
        "อย่ากดดันผมสิ",  # mid-sentence กด is conversation
        "กดปุ่มไหนดีครับ",  # question
        "ไปหน้า settings",
        "",
    ],
)
def test_click_matcher_falls_through(text: str) -> None:
    assert ui_control.match_click_intent(text) is None


# ── ui_click: the LLM fallback tool for click phrasings ────────────────

CLICK_SCREEN = {"path": "/space", "summary": "x", "buttons": ["ประวัติแชต", "สมุดบันทึก", "ลบโน้ต"]}


def test_capability_owns_and_wires_the_click_tool() -> None:
    cap = ui_control.VoiceUICapability()
    assert ui_control.UI_CLICK_TOOL in cap.owned_tools
    ctx = pipe.build_voice_context(
        transcript="q", history=[], session_id="s", knowledge_bases=[], ui_context=CLICK_SCREEN
    )
    # augment injects the screen into the click tool's kwargs (and only its)
    injected = cap.augment_kwargs(ui_control.UI_CLICK_TOOL, {"button": "x"}, ctx)
    assert injected["_ui_context"] == CLICK_SCREEN
    assert "_ui_context" not in cap.augment_kwargs("rag", {}, ctx)
    block = cap.system_block(ctx, language="th", prompts={})
    assert block is not None and ui_control.UI_CLICK_TOOL in block.content


@pytest.mark.asyncio
async def test_click_tool_execute_outcomes() -> None:
    tool = ui_control.UIClickTool()
    hit = await tool.execute(button="ประวัติแชท", _ui_context=CLICK_SCREEN)  # ท↔ต fuzzy
    assert hit.success and "ประวัติแชต" in hit.content and "ได้เลยครับ" in hit.content
    missing = await tool.execute(button="ปุ่มที่ไม่มีจริง", _ui_context=CLICK_SCREEN)
    assert not missing.success and "NOT claim" in missing.content
    danger = await tool.execute(button="ลบโน้ต", _ui_context=CLICK_SCREEN)
    assert danger.success and "NOT pressed" in danger.content
    empty = await tool.execute(_ui_context=CLICK_SCREEN)
    assert not empty.success


@pytest.mark.asyncio
async def test_llm_click_tool_call_presses_safe_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TOOL_CALL ui_click (safe hit) → ui_action click_element with the resolved name."""
    events = [
        StreamEvent(
            type=StreamEventType.TOOL_CALL,
            source="chat",
            content=ui_control.UI_CLICK_TOOL,
            metadata={"args": {"button": "ประวัติแชท"}},
        ),
        _content("ได้เลยครับ", call_kind="llm_final_response"),
        StreamEvent(type=StreamEventType.RESULT, source="chat", metadata={"response": "ได้เลยครับ"}),
    ]
    _patch_common(monkeypatch, events=events)
    emitter = FakeEmitter()

    await pipe.run_text_turn(
        emitter, "ช่วยเปิดประวัติแชตให้หน่อยสิ", [], session_id="voice:test", ui_context=CLICK_SCREEN
    )

    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert actions == [
        {
            "type": "ui_action",
            "action": "navigate",
            "target": "click_element",
            "argument": "ประวัติแชต",
        }
    ]


@pytest.mark.asyncio
async def test_llm_click_tool_call_arms_confirmation_for_dangerous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TOOL_CALL ui_click on a dangerous button → pending_click armed, nothing pressed."""
    events = [
        StreamEvent(
            type=StreamEventType.TOOL_CALL,
            source="chat",
            content=ui_control.UI_CLICK_TOOL,
            metadata={"args": {"button": "ลบโน้ต"}},
        ),
        _content("ปุ่มลบโน้ตอาจมีผลถาวรนะครับ ให้กดเลยไหมครับ", call_kind="llm_final_response"),
    ]
    _patch_common(monkeypatch, events=events)
    emitter = FakeEmitter()
    nav_state: dict = {}

    await pipe.run_text_turn(
        emitter,
        "ช่วยเปิดลบโน้ตหน่อย",
        [],
        session_id="voice:test",
        ui_context=CLICK_SCREEN,
        nav_state=nav_state,
    )

    assert nav_state.get("pending_click") == "ลบโน้ต"
    assert not [m for m in emitter.json if m.get("type") == "ui_action"]


# ── fill-by-voice: type into / select in a caller-named field ──────────

FILL_SCREEN = {
    "path": "/knowledge",
    "summary": "x",
    "fields": ["ค้นหา", "ชื่อคลังความรู้", "ภาษา (เลือกได้: ไทย | English)"],
}


@pytest.mark.parametrize(
    ("text", "field", "value"),
    [
        ("พิมพ์กฎหมายแรงงานในช่องค้นหา", "ค้นหา", "กฎหมายแรงงาน"),
        ("พิมพ์ LAWs_thai ลงในช่องชื่อคลังความรู้ให้หน่อย", "ชื่อคลังความรู้", "LAWs_thai"),
        ("ช่วยกรอก สมุดกฎหมาย ในช่องชื่อคลังความรู้", "ชื่อคลังความรู้", "สมุดกฎหมาย"),
        ("เลือกไทยในช่องภาษา", "ภาษา", "ไทย"),
        ("ใส่ 42 ที่ช่องค้นหาหน่อยครับ", "ค้นหา", "42"),
    ],
)
def test_fill_matcher_extracts_field_and_value(text: str, field: str, value: str) -> None:
    assert ui_control.match_fill_intent(text) == {"field": field, "value": value}


@pytest.mark.parametrize(
    "text",
    [
        "พิมพ์อะไรในช่องนี้ได้บ้าง",  # question
        "พิมพ์สวัสดีครับ",  # no field marker → not a fill command
        "เลือกสมุดบันทึก",  # click-ish "เลือก", no marker
        "ช่องค้นหาอยู่ตรงไหน",  # question, no verb start
        "",
    ],
)
def test_fill_matcher_falls_through(text: str) -> None:
    assert ui_control.match_fill_intent(text) is None


def test_fill_value_keeps_original_casing() -> None:
    got = ui_control.match_fill_intent("พิมพ์ LAWs_thai ในช่องค้นหา")
    assert got is not None and got["value"] == "LAWs_thai"


def test_fill_value_peels_quoting_kham_wa() -> None:
    """ "พิมพ์คำว่าสวัสดี…" — "คำว่า" is quoting, not content (live gap)."""
    got = ui_control.match_fill_intent("พิมพ์คำว่าสวัสดีในช่องแชท")
    assert got == {"field": "แชท", "value": "สวัสดี"}


def test_resolve_field_target_matches_on_label_part() -> None:
    # The dropdown's options suffix never joins the match; garbles get the
    # same tiers as buttons (shared resolver).
    assert ui_control.resolve_field_target("ภาษา", FILL_SCREEN) == ("hit", "ภาษา")
    assert ui_control.resolve_field_target("ช่องค้นหา", FILL_SCREEN)[0] == "hit"
    assert ui_control.resolve_field_target("คนหา", FILL_SCREEN) == ("hit", "ค้นหา")  # tone drop
    assert ui_control.resolve_field_target("ช่องที่ไม่มี", FILL_SCREEN) == ("missing", None)
    assert ui_control.resolve_field_target("ค้นหา", None) == ("missing", None)
    assert ui_control.field_label("ภาษา (เลือกได้: ไทย | English)") == "ภาษา"


# The knowledge page as the caller sees it: KB names visible as cards
# (buttons) plus a search box and a dropdown of engines.
FILL_KB_SCREEN = {
    "path": "/knowledge",
    "summary": "x",
    "buttons": ["LAWs_thai", "GraphRAG", "สร้างคลังใหม่"],
    "fields": ["ค้นหา", "ชื่อคลังความรู้", "เครื่องมือ (เลือกได้: LlamaIndex | GraphRAG)"],
}


def test_field_options_parses_the_marker() -> None:
    assert ui_control.field_options("เครื่องมือ (เลือกได้: LlamaIndex | GraphRAG)") == [
        "LlamaIndex",
        "GraphRAG",
    ]
    assert ui_control.field_options("ค้นหา") == []
    assert ui_control.field_options_for("เครื่องมือ", FILL_KB_SCREEN) == [
        "LlamaIndex",
        "GraphRAG",
    ]
    assert ui_control.field_options_for("ค้นหา", FILL_KB_SCREEN) == []


def test_fill_value_dropdown_resolves_cross_script() -> None:
    """The "ลาวไทย gap": STT transliterates on-screen names — a dropdown value
    must resolve to a real option, never be typed as the garble."""
    assert ui_control.resolve_fill_value("ลามะ index", "เครื่องมือ", FILL_KB_SCREEN) == (
        "ok",
        "LlamaIndex",
    )
    assert ui_control.resolve_fill_value("GraphRAG", "เครื่องมือ", FILL_KB_SCREEN) == (
        "ok",
        "GraphRAG",
    )
    # Not an option → honest no_option, nothing typed behind an ack.
    assert ui_control.resolve_fill_value("ฝรั่งเศส", "เครื่องมือ", FILL_KB_SCREEN) == (
        "no_option",
        None,
    )


def test_fill_value_text_field_takes_on_screen_spelling() -> None:
    # "ใส่ LAWs_thai" arrives as "ลาวไทย"; the KB card on screen carries the
    # real spelling — the unique cross-script hit wins.
    assert ui_control.resolve_fill_value("ลาวไทย", "ชื่อคลังความรู้", FILL_KB_SCREEN) == (
        "ok",
        "LAWs_thai",
    )
    # Free text that names nothing on screen stays verbatim.
    assert ui_control.resolve_fill_value("กฎหมายแรงงาน", "ค้นหา", FILL_KB_SCREEN) == (
        "ok",
        "กฎหมายแรงงาน",
    )
    # No screen context at all → verbatim.
    assert ui_control.resolve_fill_value("อะไรก็ได้", "ค้นหา", None) == ("ok", "อะไรก็ได้")


def test_sanitize_action_result_trims_and_validates() -> None:
    got = ui_control.sanitize_action_result(
        {"target": "fill_field", "field": "ค้นหา", "ok": True, "detail": "value_set"}
    )
    assert got == {"target": "fill_field", "field": "ค้นหา", "ok": True, "detail": "value_set"}
    # ok coerces to a real bool; missing detail/field are tolerated.
    got = ui_control.sanitize_action_result({"target": "chat", "ok": ""})
    assert got == {"target": "chat", "ok": False, "detail": ""}
    # No target (or not a dict) → unusable, dropped silently.
    assert ui_control.sanitize_action_result({"ok": True}) is None
    assert ui_control.sanitize_action_result("junk") is None
    # Control chars stripped, lengths capped.
    got = ui_control.sanitize_action_result({"target": "x\x00y", "ok": True, "detail": "d" * 500})
    assert got is not None and got["target"] == "xy" and len(got["detail"]) == 80
    # open_path results carry the landed path as `argument`.
    got = ui_control.sanitize_action_result(
        {"target": "open_path", "argument": "/settings/appearance", "ok": True, "detail": ""}
    )
    assert got is not None and got["argument"] == "/settings/appearance"


def test_sanitize_ui_context_keeps_fields_capped() -> None:
    cleaned = ui_control.sanitize_ui_context({**SCREEN, "fields": [f"ช่อง{i}" for i in range(50)]})
    assert cleaned is not None
    assert len(cleaned["fields"]) == 20
    assert cleaned["fields"][0] == "ช่อง0"


def test_capability_owns_and_wires_the_fill_tool() -> None:
    cap = ui_control.VoiceUICapability()
    assert ui_control.UI_FILL_TOOL in cap.owned_tools
    ctx = pipe.build_voice_context(
        transcript="q", history=[], session_id="s", knowledge_bases=[], ui_context=FILL_SCREEN
    )
    injected = cap.augment_kwargs(ui_control.UI_FILL_TOOL, {"field": "x", "value": "y"}, ctx)
    assert injected["_ui_context"] == FILL_SCREEN
    block = cap.system_block(ctx, language="th", prompts={})
    assert block is not None and ui_control.UI_FILL_TOOL in block.content
    # The streamed field list (with the dropdown's options) reaches the prompt.
    assert "ภาษา (เลือกได้: ไทย | English)" in block.content


@pytest.mark.asyncio
async def test_fill_tool_execute_outcomes() -> None:
    tool = ui_control.UIFillTool()
    hit = await tool.execute(field="ช่องค้นหา", value="กฎหมาย", _ui_context=FILL_SCREEN)
    assert hit.success and "ค้นหา" in hit.content and "ได้เลยครับ" in hit.content
    missing = await tool.execute(field="ช่องที่ไม่มีจริง", value="x", _ui_context=FILL_SCREEN)
    assert not missing.success and "NOT claim" in missing.content
    no_value = await tool.execute(field="ค้นหา", _ui_context=FILL_SCREEN)
    assert not no_value.success


# ── Tier B: implicit fill through the LLM (value→field by meaning) ──────

# A form with several typed fields — what Tier A can't resolve (nothing
# focused/remembered) and Tier B exists for.
TIER_B_SCREEN = {
    "path": "/settings",
    "summary": "x",
    "fields": ["ชื่อ", "อีเมล (ชนิด: email)", "วันเกิด (ชนิด: date)"],
}


def test_field_label_strips_the_type_marker() -> None:
    assert ui_control.field_label("อีเมล (ชนิด: email)") == "อีเมล"
    # A typed entry declares no dropdown options.
    assert ui_control.field_options("อีเมล (ชนิด: email)") == []
    # Resolution runs on the label part, so the model's semantic pick
    # ("อีเมล") matches the annotated entry.
    assert ui_control.resolve_field_target("อีเมล", TIER_B_SCREEN) == ("hit", "อีเมล")


@pytest.mark.asyncio
async def test_fill_tool_semantic_pick_is_still_verified() -> None:
    """The model's value→field pick goes through the same resolver."""
    tool = ui_control.UIFillTool()
    hit = await tool.execute(field="อีเมล", value="aom@example.com", _ui_context=TIER_B_SCREEN)
    assert hit.success and "อีเมล" in hit.content
    invented = await tool.execute(field="เบอร์โทร", value="0812345678", _ui_context=TIER_B_SCREEN)
    assert not invented.success and "NOT claim" in invented.content


@pytest.mark.asyncio
async def test_fill_tool_omitted_field_single_field_fills_it() -> None:
    """One visible field → an omitted `field` is unambiguous."""
    tool = ui_control.UIFillTool()
    one_field = {"path": "/x", "summary": "x", "fields": ["ค้นหา"]}
    got = await tool.execute(value="กฎหมาย", _ui_context=one_field)
    assert got.success and "ค้นหา" in got.content


@pytest.mark.asyncio
async def test_fill_tool_omitted_field_ambiguous_hands_schema_back() -> None:
    """2+ fields and no `field` → the tool demands an explicit pick; the
    schema (with type annotations) rides in the result so the model can
    choose. Nothing is typed."""
    tool = ui_control.UIFillTool()
    got = await tool.execute(value="aom@example.com", _ui_context=TIER_B_SCREEN)
    assert not got.success
    assert "อีเมล (ชนิด: email)" in got.content
    assert "Nothing was typed" in got.content


@pytest.mark.asyncio
async def test_fill_tool_omitted_field_no_fields_fails_honestly() -> None:
    tool = ui_control.UIFillTool()
    got = await tool.execute(value="x", _ui_context={"path": "/x", "summary": "x"})
    assert not got.success and "Nothing was typed" in got.content


# ── weighted resolver: focus/recency break ties, never cross tiers ──────

# Two fields that substring-match the same spoken "ค้นหา" — the shape the old
# 4-tier ladder could only answer with "ช่องไหนครับ".
TIE_SCREEN = {"path": "/x", "summary": "x", "fields": ["ค้นหาเอกสาร", "ค้นหาหนังสือ"]}


def test_score_tie_stays_ambiguous_without_signals() -> None:
    assert ui_control.resolve_field_target("ค้นหา", TIE_SCREEN) == ("ambiguous", None)


def test_score_focus_breaks_a_label_tie() -> None:
    focused = {**TIE_SCREEN, "activeField": "ค้นหาหนังสือ"}
    assert ui_control.resolve_field_target("ค้นหา", focused) == ("hit", "ค้นหาหนังสือ")


def test_score_recency_breaks_a_label_tie() -> None:
    got = ui_control.resolve_field_target("ค้นหา", TIE_SCREEN, last_field="ค้นหาเอกสาร")
    assert got == ("hit", "ค้นหาเอกสาร")


def test_score_focus_outweighs_recency() -> None:
    focused = {**TIE_SCREEN, "activeField": "ค้นหาหนังสือ"}
    got = ui_control.resolve_field_target("ค้นหา", focused, last_field="ค้นหาเอกสาร")
    assert got == ("hit", "ค้นหาหนังสือ")


def test_score_boosts_never_promote_across_tiers() -> None:
    # "ค้นหา" matches "ค้นหา" exactly (top tier); the focused sibling only by
    # substring — every boost combined must not lift it past the exact match.
    screen = {
        "path": "/x",
        "summary": "x",
        "fields": ["ค้นหา", "ค้นหาเอกสาร"],
        "activeField": "ค้นหาเอกสาร",
    }
    got = ui_control.resolve_field_target("ค้นหา", screen, last_field="ค้นหาเอกสาร")
    assert got == ("hit", "ค้นหา")


def test_score_boosts_never_resurrect_a_miss() -> None:
    focused = {**TIE_SCREEN, "activeField": "ค้นหาหนังสือ"}
    assert ui_control.resolve_field_target("ปฏิทิน", focused) == ("missing", None)


def test_score_boost_ignores_a_field_not_on_screen() -> None:
    # A remembered field that scrolled away must not shadow the live screen.
    got = ui_control.resolve_field_target("ค้นหา", TIE_SCREEN, last_field="ช่องเก่าที่หายไป")
    assert got == ("ambiguous", None)


# ── Tier B dispatch parity: effective_fill_field ────────────────────────


def test_effective_fill_field_fallbacks() -> None:
    one = {"fields": ["ค้นหา"]}
    many = {"fields": ["ก", "ข"]}
    assert ui_control.effective_fill_field("ชื่อ", many) == "ชื่อ"  # named → verbatim
    assert ui_control.effective_fill_field("", one) == "ค้นหา"  # single field
    assert ui_control.effective_fill_field("", {"fields": ["อีเมล (ชนิด: email)"]}) == "อีเมล"
    assert ui_control.effective_fill_field("", many) == ""  # ambiguous
    assert ui_control.effective_fill_field("", None) == ""


@pytest.mark.asyncio
async def test_llm_fill_omitted_field_dispatches_to_the_only_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier B parity: the tool's single-field fallback and the pipeline's
    dispatch resolve identically — an omitted `field` with one visible field
    actually types (the live bug this guards: tool said 'Typed', dispatch
    resolved '' → missing → nothing happened)."""
    events = [
        StreamEvent(
            type=StreamEventType.TOOL_CALL,
            source="chat",
            content=ui_control.UI_FILL_TOOL,
            metadata={"args": {"value": "กฎหมาย"}},  # no field
        ),
        _content("ได้เลยครับ", call_kind="llm_final_response"),
    ]
    _patch_common(monkeypatch, events=events)
    emitter = FakeEmitter()

    await pipe.run_text_turn(
        emitter,
        "ช่วยหาคำว่ากฎหมายให้หน่อย",
        [],
        session_id="voice:test",
        ui_context={"path": "/x", "summary": "x", "fields": ["ค้นหา"]},
    )

    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert actions == [
        {
            "type": "ui_action",
            "action": "navigate",
            "target": "fill_field",
            "argument": "กฎหมาย",
            "field": "ค้นหา",
        }
    ]


def test_system_block_carries_the_field_choice_rule() -> None:
    """The prompt must both allow the semantic pick and forbid guessing."""
    cap = ui_control.VoiceUICapability()
    ctx = pipe.build_voice_context(
        transcript="q", history=[], session_id="s", knowledge_bases=[], ui_context=TIER_B_SCREEN
    )
    block = cap.system_block(ctx, language="th", prompts={})
    assert block is not None
    assert "FIELD CHOICE" in block.content
    assert "(ชนิด: email)" in block.content
    # The annotated schema itself reaches the prompt.
    assert "อีเมล (ชนิด: email)" in block.content


@pytest.mark.asyncio
async def test_fill_shortcut_types_without_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic rung: "พิมพ์ X ในช่อง Y" → ui_action fill_field + ack, no LLM."""

    class _MustNotRun:
        def __init__(self) -> None:
            raise AssertionError("orchestrator must not run for a fill command")

    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", _MustNotRun)

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    pipe._FIXED_LINE_CACHE.clear()
    emitter = FakeEmitter()

    await pipe.run_text_turn(
        emitter,
        "พิมพ์กฎหมายแรงงานในช่องค้นหา",
        [],
        session_id="voice:test",
        ui_context=FILL_SCREEN,
    )

    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert actions == [
        {
            "type": "ui_action",
            "action": "navigate",
            "target": "fill_field",
            "argument": "กฎหมายแรงงาน",
            "field": "ค้นหา",
        }
    ]


@pytest.mark.asyncio
async def test_fill_shortcut_miss_is_honest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Named field not on screen → honest dead-end line, nothing dispatched."""

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    pipe._FIXED_LINE_CACHE.clear()
    emitter = FakeEmitter()

    reply = await pipe.run_text_turn(
        emitter,
        "พิมพ์ทดสอบในช่องอีเมล",
        [],
        session_id="voice:test",
        ui_context=FILL_SCREEN,
    )

    assert reply == "ไม่เห็นช่องชื่อนั้นบนจอครับ"
    assert not [m for m in emitter.json if m.get("type") == "ui_action"]


@pytest.mark.asyncio
async def test_fill_shortcut_corrects_value_to_screen_spelling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "ใส่ ลาวไทย ในช่องชื่อคลังความรู้" types the on-screen "LAWs_thai"."""

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    pipe._FIXED_LINE_CACHE.clear()
    emitter = FakeEmitter()

    await pipe.run_text_turn(
        emitter,
        "ใส่ลาวไทยในช่องชื่อคลังความรู้ให้หน่อย",
        [],
        session_id="voice:test",
        ui_context=FILL_KB_SCREEN,
    )

    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert actions and actions[0]["argument"] == "LAWs_thai"
    assert actions[0]["field"] == "ชื่อคลังความรู้"


@pytest.mark.asyncio
async def test_fill_shortcut_dropdown_without_matching_option_asks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dropdown value that matches no option → honest line, nothing dispatched."""

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    pipe._FIXED_LINE_CACHE.clear()
    emitter = FakeEmitter()

    reply = await pipe.run_text_turn(
        emitter,
        "เลือกฝรั่งเศสในช่องเครื่องมือ",
        [],
        session_id="voice:test",
        ui_context=FILL_KB_SCREEN,
    )

    assert reply == "ช่องนั้นไม่มีตัวเลือกตามที่พูดครับ ลองพูดชื่อตัวเลือกอีกครั้งครับ"
    assert not [m for m in emitter.json if m.get("type") == "ui_action"]


# ── click on fields: focus, and the live mis-target regressions ────────

SIDEBAR_BUTTONS = ["หน้าหลัก", "พาร์ทเนอร์", "เอเจนต์ของฉัน", "Co-Writer", "หนังสือ", "การตั้งค่า"]


def test_cross_skeleton_budget_blocks_the_agent_misclick() -> None:
    """Live gap: "กดตรงช่องค้นหา" skeleton-matched "เอเจนต์ของฉัน" (ed 2 under
    the old //3 budget). The tightened budget rejects it; real cross-script
    hits (all ed ≤ 1) keep working."""
    assert ui_control.resolve_click_target("ช่องค้นหา", {"buttons": SIDEBAR_BUTTONS}) == (
        "missing",
        None,
    )


def test_exact_field_hit_prefers_the_field_over_contained_buttons() -> None:
    ctx = {"buttons": SIDEBAR_BUTTONS, "fields": ["ค้นหาหนังสือ"]}
    assert ui_control.exact_field_hit("ค้นหาหนังสือ", ctx) == "ค้นหาหนังสือ"
    assert ui_control.exact_field_hit("ช่องค้นหาหนังสือ", ctx) == "ค้นหาหนังสือ"
    assert ui_control.exact_field_hit("หนังสือ", ctx) is None  # not exact → buttons' turn
    assert ui_control.exact_field_hit("ค้นหาหนังสือ", None) is None


@pytest.mark.asyncio
async def test_click_on_chong_focuses_the_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "กดตรงช่องค้นหา" → focus_field on the search box, never a button."""

    class _MustNotRun:
        def __init__(self) -> None:
            raise AssertionError("orchestrator must not run for a focus command")

    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", _MustNotRun)

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    pipe._FIXED_LINE_CACHE.clear()
    emitter = FakeEmitter()
    nav_state: dict = {}

    await pipe.run_text_turn(
        emitter,
        "กดตรงช่องค้นหา",
        [],
        session_id="voice:test",
        ui_context={**FILL_KB_SCREEN, "buttons": SIDEBAR_BUTTONS},
        nav_state=nav_state,
    )

    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert actions == [
        {
            "type": "ui_action",
            "action": "navigate",
            "target": "focus_field",
            "argument": "",
            "field": "ค้นหา",
        }
    ]
    assert nav_state.get("last_field") == "ค้นหา"


@pytest.mark.asyncio
async def test_click_exact_field_name_beats_contained_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "กดที่ค้นหาหนังสือ" → the search box, not the "หนังสือ" sidebar button."""

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    pipe._FIXED_LINE_CACHE.clear()
    emitter = FakeEmitter()

    await pipe.run_text_turn(
        emitter,
        "กดที่ค้นหาหนังสือ",
        [],
        session_id="voice:test",
        ui_context={
            "path": "/book",
            "summary": "x",
            "buttons": SIDEBAR_BUTTONS,
            "fields": ["ค้นหาหนังสือ"],
        },
        nav_state={},
    )

    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert [a["target"] for a in actions] == ["focus_field"]
    assert actions[0]["field"] == "ค้นหาหนังสือ"


@pytest.mark.asyncio
async def test_click_on_missing_chong_is_honest(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "กดที่ช่องอีเมล" with no such field → field-miss line, no button fallback."""

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    pipe._FIXED_LINE_CACHE.clear()
    emitter = FakeEmitter()

    reply = await pipe.run_text_turn(
        emitter,
        "กดที่ช่องอีเมล",
        [],
        session_id="voice:test",
        ui_context={**FILL_KB_SCREEN, "buttons": SIDEBAR_BUTTONS},
        nav_state={},
    )

    assert reply == "ไม่เห็นช่องชื่อนั้นบนจอครับ"
    assert not [m for m in emitter.json if m.get("type") == "ui_action"]


# ── implicit fill (Tier A): "พิมพ์ X" with no field named ──────────────


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("พิมพ์สวัสดี", "สวัสดี"),
        ("พิมพ์ว่าสวัสดี", "สวัสดี"),
        ("พิมพ์คำว่ากฎหมายแรงงาน", "กฎหมายแรงงาน"),
        ("ใส่ 42 หน่อยครับ", "42"),
        ("เขียนว่าทดสอบ", "ทดสอบ"),
    ],
)
def test_match_implicit_fill_extracts_value(text: str, value: str) -> None:
    assert ui_control.match_implicit_fill(text) == value


@pytest.mark.parametrize(
    "text",
    [
        "พิมพ์กฎหมายในช่องค้นหา",  # names a field → explicit path owns it
        "พิมพ์อะไรดีครับ",  # question
        "เลือกไทย",  # select is not an implicit-type verb (too ambiguous)
        "กดที่ค้นหา",  # not a type verb
        "",
    ],
)
def test_match_implicit_fill_falls_through(text: str) -> None:
    assert ui_control.match_implicit_fill(text) is None


def test_implicit_fill_field_priority() -> None:
    fields = ["ค้นหา", "ชื่อคลังความรู้"]
    ctx_active = {"fields": fields, "activeField": "ชื่อคลังความรู้"}
    # Focused field wins outright.
    assert ui_control.implicit_fill_field(ctx_active, {"last_field": "ค้นหา"}) == "ชื่อคลังความรู้"
    # No focus → last_field, but only if still on screen.
    assert ui_control.implicit_fill_field({"fields": fields}, {"last_field": "ค้นหา"}) == "ค้นหา"
    assert ui_control.implicit_fill_field({"fields": fields}, {"last_field": "อีเมล"}) is None
    # No focus, no memory, single field → that one.
    assert ui_control.implicit_fill_field({"fields": ["ค้นหา"]}, {}) == "ค้นหา"
    # Ambiguous (2+ fields, nothing to disambiguate) → None (don't guess).
    assert ui_control.implicit_fill_field({"fields": fields}, {}) is None


def test_sanitize_ui_context_keeps_active_field() -> None:
    cleaned = ui_control.sanitize_ui_context({**SCREEN, "activeField": "ค้นหา"})
    assert cleaned is not None and cleaned["activeField"] == "ค้นหา"


@pytest.mark.asyncio
async def test_implicit_fill_targets_focused_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "พิมพ์สวัสดี" with a focused field → fill_field on it, no LLM."""

    class _MustNotRun:
        def __init__(self) -> None:
            raise AssertionError("orchestrator must not run for an implicit fill")

    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", _MustNotRun)

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    pipe._FIXED_LINE_CACHE.clear()
    emitter = FakeEmitter()
    nav_state: dict = {}

    await pipe.run_text_turn(
        emitter,
        "พิมพ์สวัสดี",
        [],
        session_id="voice:test",
        ui_context={**FILL_KB_SCREEN, "activeField": "ค้นหา"},
        nav_state=nav_state,
    )

    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert actions == [
        {
            "type": "ui_action",
            "action": "navigate",
            "target": "fill_field",
            "argument": "สวัสดี",
            "field": "ค้นหา",
        }
    ]
    assert nav_state.get("last_field") == "ค้นหา"


# ── edit-by-voice: undo typing ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "op", "field"),
    [
        ("ล้างช่องค้นหา", "clear", "ค้นหา"),
        ("ลบข้อความในช่องชื่อคลังความรู้", "clear", "ชื่อคลังความรู้"),
        ("เคลียร์ช่องค้นหาให้หน่อย", "clear", "ค้นหา"),
        ("ล้าง", "clear", ""),  # bare → last filled field
        ("ลบคำสุดท้าย", "delete_word", ""),
        ("ลบคำสุดท้ายในช่องค้นหาหน่อยครับ", "delete_word", "ค้นหา"),
        ("ช่วยลบคำล่าสุดออก", "delete_word", ""),
    ],
)
def test_edit_matcher_extracts_op_and_field(text: str, op: str, field: str) -> None:
    assert ui_control.match_edit_intent(text) == {"op": op, "field": field}


@pytest.mark.parametrize(
    "text",
    [
        "ลบโน้ตนี้ทิ้ง",  # deleting content elsewhere — click/confirm territory
        "ล้างจานให้หน่อย",  # remainder names no field
        "ลบคำว่ากฎหมายออก",  # names a word, not a field position
        "ลบยังไง",  # question
        "",
    ],
)
def test_edit_matcher_falls_through(text: str) -> None:
    assert ui_control.match_edit_intent(text) is None


@pytest.mark.asyncio
async def test_edit_shortcut_remembers_last_filled_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fill then a bare "ลบคำสุดท้าย" — the edit lands on the same field, silently."""

    class _MustNotRun:
        def __init__(self) -> None:
            raise AssertionError("orchestrator must not run for fill/edit commands")

    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", _MustNotRun)

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    pipe._FIXED_LINE_CACHE.clear()
    emitter = FakeEmitter()
    nav_state: dict = {}

    await pipe.run_text_turn(
        emitter,
        "พิมพ์กฎหมายแรงงานในช่องค้นหา",
        [],
        session_id="voice:test",
        ui_context=FILL_KB_SCREEN,
        nav_state=nav_state,
    )
    assert nav_state.get("last_field") == "ค้นหา"

    reply = await pipe.run_text_turn(
        emitter,
        "ลบคำสุดท้าย",
        [],
        session_id="voice:test",
        ui_context=FILL_KB_SCREEN,
        nav_state=nav_state,
    )

    assert reply == ""  # silent, like scroll
    edits = [m for m in emitter.json if m.get("target") == "edit_field"]
    assert edits == [
        {
            "type": "ui_action",
            "action": "navigate",
            "target": "edit_field",
            "argument": "delete_word",
            "field": "ค้นหา",
        }
    ]


@pytest.mark.asyncio
async def test_edit_without_any_field_asks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bare edit before any fill this call → honest ask, nothing dispatched."""

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    pipe._FIXED_LINE_CACHE.clear()
    emitter = FakeEmitter()

    reply = await pipe.run_text_turn(
        emitter,
        "ลบคำสุดท้าย",
        [],
        session_id="voice:test",
        ui_context=FILL_KB_SCREEN,
        nav_state={},
    )

    assert "ยังไม่รู้ว่าช่องไหน" in reply
    assert not [m for m in emitter.json if m.get("type") == "ui_action"]


@pytest.mark.asyncio
async def test_llm_fill_tool_call_dispatches_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    """TOOL_CALL ui_fill (hit) → ui_action fill_field with the resolved label."""
    events = [
        StreamEvent(
            type=StreamEventType.TOOL_CALL,
            source="chat",
            content=ui_control.UI_FILL_TOOL,
            metadata={"args": {"field": "ชื่อคลังความรู้", "value": "LAWs_thai"}},
        ),
        _content("ได้เลยครับ", call_kind="llm_final_response"),
    ]
    _patch_common(monkeypatch, events=events)
    emitter = FakeEmitter()

    await pipe.run_text_turn(
        emitter,
        "ช่องชื่อคลังความรู้ใส่คำว่า LAWs_thai ให้หน่อย",
        [],
        session_id="voice:test",
        ui_context=FILL_SCREEN,
    )

    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert actions == [
        {
            "type": "ui_action",
            "action": "navigate",
            "target": "fill_field",
            "argument": "LAWs_thai",
            "field": "ชื่อคลังความรู้",
        }
    ]


def test_suffixed_duplicate_twins_resolve_to_the_first() -> None:
    """Live regression: the engine collector reports a card twice ("LlamaIndex",
    "LlamaIndex (2)") — a tie between ordinal twins must NOT ask back (the
    visible names are identical; "พูดชื่อเต็ม" is a dead end)."""
    ctx = {"buttons": ["LlamaIndex", "LlamaIndex (2)", "GraphRAG"]}
    assert ui_control.resolve_click_target("ลามะ index", ctx) == ("hit", "LlamaIndex")
    assert ui_control.resolve_click_target("LlamaIndex", ctx) == ("hit", "LlamaIndex")
    # Distinct labels that merely tie are still a real ambiguity.
    two = {"buttons": ["โน้ตเก่า", "โน้ตใหม่"]}
    assert ui_control.resolve_click_target("โน้ต", two) == ("ambiguous", None)


def test_system_block_carries_the_full_buttons_channel() -> None:
    """Live regression: the LLM only saw the summary's capped prose and told
    callers a plainly-visible button didn't exist — the full clickables
    channel must reach the prompt."""
    cap = ui_control.VoiceUICapability()
    ctx = pipe.build_voice_context(
        transcript="q",
        history=[],
        session_id="s",
        knowledge_bases=[],
        ui_context={"path": "/knowledge", "summary": "x", "buttons": ["PageIndex", "LAWs_thai"]},
    )
    block = cap.system_block(ctx, language="th", prompts={})
    assert block is not None
    assert "PageIndex | LAWs_thai" in block.content


def test_click_matches_mixed_script_garbles_knowledge_center() -> None:
    """เคสจริงหน้าศูนย์ความรู้: STT ถอดครึ่งไทยครึ่งอังกฤษ / ทับศัพท์เพี้ยน."""
    ctx = {
        "buttons": [
            "LlamaIndex",
            "PageIndex",
            "GraphRAG",
            "LightRAG",
            "Obsidian",
            "LAWs_thai",
        ]
    }
    assert ui_control.resolve_click_target("ลามะ index", ctx) == ("hit", "LlamaIndex")
    assert ui_control.resolve_click_target("ลาวไทย", ctx) == ("hit", "LAWs_thai")
    assert ui_control.resolve_click_target("กราฟแรก", ctx) == ("hit", "GraphRAG")
    assert ui_control.resolve_click_target("เพจ index", ctx) == ("hit", "PageIndex")


def test_click_matches_loanwords_across_scripts() -> None:
    """คำสั่งจริงที่เคยพลาด: STT ถอด 'persona' แต่จอเขียน 'เพอร์โซนา' (คนละอักษร)."""
    ctx = {"buttons": ["เพอร์โซนา", "สกิล", "เส้นทางสู่ความเชี่ยวชาญ"]}
    assert ui_control.resolve_click_target("persona", ctx) == ("hit", "เพอร์โซนา")
    # And the reverse: English UI, Thai speech.
    ctx_en = {"buttons": ["Persona", "Skills", "Mastery Path"]}
    assert ui_control.resolve_click_target("เพอร์โซนา", ctx_en) == ("hit", "Persona")
    # Another common loanword shape.
    assert ui_control.resolve_click_target("network", {"buttons": ["เน็ตเวิร์ก", "โมเดล"]}) == (
        "hit",
        "เน็ตเวิร์ก",
    )
    # Unrelated names must not cross-match.
    assert ui_control.resolve_click_target("persona", {"buttons": ["สมุดบันทึก"]}) == (
        "missing",
        None,
    )


def test_click_resolves_the_live_chat_history_gap() -> None:
    """คำสั่งจริงที่เคยพลาด: 'กดที่ประวัติแชท' ปะทะปุ่มจริง 'ประวัติแชต' (ท↔ต)."""
    ctx = {"buttons": ["ประวัติแชต", "สมุดบันทึก", "คลังคำถาม"]}
    name = ui_control.match_click_intent("กดที่ประวัติแชท")
    assert name == "ประวัติแชท"
    assert ui_control.resolve_click_target(name, ctx) == ("hit", "ประวัติแชต")


def test_resolve_click_target_tiers() -> None:
    assert ui_control.resolve_click_target("สร้างโน้ตใหม่", CLICK_CONTEXT) == (
        "hit",
        "สร้างโน้ตใหม่",
    )
    # Substring: "โน้ตใหม่" names one button; "โน้ต" alone names two → ambiguous.
    assert ui_control.resolve_click_target("โน้ตใหม่", CLICK_CONTEXT) == ("hit", "สร้างโน้ตใหม่")
    assert ui_control.resolve_click_target("โน้ต", CLICK_CONTEXT) == ("ambiguous", None)
    # Phonetic fuzz on a garbled name.
    assert ui_control.resolve_click_target("บันทึด", CLICK_CONTEXT) == ("hit", "บันทึก")
    assert ui_control.resolve_click_target("ปุ่มที่ไม่มี", CLICK_CONTEXT) == ("missing", None)
    assert ui_control.resolve_click_target("บันทึก", None) == ("missing", None)


def test_dangerous_button_words() -> None:
    assert ui_control.is_dangerous_button("ลบโน้ต")
    assert ui_control.is_dangerous_button("Delete all")
    assert not ui_control.is_dangerous_button("บันทึก")


@pytest.mark.asyncio
async def test_click_by_name_presses_visible_button_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MustNotRun:
        def __init__(self) -> None:
            raise AssertionError("orchestrator must not run for a click turn")

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", _MustNotRun)
    pipe._FIXED_LINE_CACHE.clear()
    nav_state: dict[str, Any] = {}

    emitter = FakeEmitter()
    reply = await pipe.run_text_turn(
        emitter,
        "กดปุ่มสร้างโน้ตใหม่",
        [],
        session_id="v",
        ui_manifest=MANIFEST,
        ui_context=CLICK_CONTEXT,
        nav_state=nav_state,
    )
    assert reply == "ได้เลยครับ"
    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert actions == [
        {
            "type": "ui_action",
            "action": "navigate",
            "target": "click_element",
            "argument": "สร้างโน้ตใหม่",
        }
    ]

    # Missing button = honest dead-end, still no LLM.
    emitter2 = FakeEmitter()
    reply2 = await pipe.run_text_turn(
        emitter2,
        "กดปุ่มชำระเงิน",
        [],
        session_id="v",
        ui_manifest=MANIFEST,
        ui_context=CLICK_CONTEXT,
        nav_state=nav_state,
    )
    assert "ไม่เห็นปุ่ม" in reply2
    assert not [m for m in emitter2.json if m.get("type") == "ui_action"]


@pytest.mark.asyncio
async def test_dangerous_click_requires_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    pipe._FIXED_LINE_CACHE.clear()
    nav_state: dict[str, Any] = {}

    # Turn 1: names a dangerous button → asks, does NOT click.
    emitter = FakeEmitter()
    reply = await pipe.run_text_turn(
        emitter,
        "กดปุ่มลบโน้ต",
        [],
        session_id="v",
        ui_manifest=MANIFEST,
        ui_context=CLICK_CONTEXT,
        nav_state=nav_state,
    )
    assert "ให้กดเลยไหม" in reply
    assert nav_state == {"pending_click": "ลบโน้ต"}
    assert not [m for m in emitter.json if m.get("type") == "ui_action"]

    # Turn 2: bare yes → the click executes.
    emitter2 = FakeEmitter()
    reply2 = await pipe.run_text_turn(
        emitter2,
        "ใช่ครับ",
        [],
        session_id="v",
        ui_manifest=MANIFEST,
        ui_context=CLICK_CONTEXT,
        nav_state=nav_state,
    )
    assert reply2 == "ได้เลยครับ"
    actions = [m for m in emitter2.json if m.get("type") == "ui_action"]
    assert actions and actions[0]["argument"] == "ลบโน้ต"
    assert nav_state == {}


# ── secretary (dictation) mode ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("เปิดโหมดเลขา", "secretary_on"),
        ("เปิดโหมดเลขาให้หน่อยครับ", "secretary_on"),
        ("โหมดพิมพ์", "secretary_on"),
        ("ปิดโหมดเลขาครับ", "secretary_off"),
        ("ออกจากโหมดเลขา", "secretary_off"),
        ("ออกจากโหมด", "secretary_off"),
    ],
)
def test_mode_command_matcher(text: str, expected: str) -> None:
    assert ui_control.match_mode_command(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "โหมดเลขาคืออะไร",  # question about the mode
        "เลขาช่วยจดหน่อย",  # not a mode command shape
        "เปิดโหมดเลขาแล้วช่วยสรุปเอกสารให้หน่อยนะครับผม",  # compound/long
        "",
    ],
)
def test_mode_command_matcher_falls_through(text: str) -> None:
    assert ui_control.match_mode_command(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ปิดหมดเรขาค", "secretary_off"),  # the exact garble caught live
        ("ปิดโหมดเรขา", "secretary_off"),  # ร↔ล homophone
        ("ปิดหมดเลขา", "secretary_off"),  # โ dropped
        ("เปิดโหมดเรขา", "secretary_on"),  # garbled enter still enters
        ("เปิดหมดเลยค่ะ", "secretary_on"),  # live garble round 2: เลขา → เลยค่ะ
        ("ปิดหมดเลยครับ", "secretary_off"),  # same garble shape on exit
        ("ออกจากหมดเลขา", "secretary_off"),  # โหมด → หมด on the long form
        ("บิดหมดเลขา", "secretary_off"),  # live garble round 3: ป → บ on the FIRST char
        ("เบิดโหมดเลขา", "secretary_on"),  # same swap on enter
    ],
)
def test_mode_command_matcher_tolerates_stt_garbles(text: str, expected: str) -> None:
    """Trapped-in-mode is the worst failure — exit matches generously."""
    assert ui_control.match_mode_command(text) == expected


@pytest.mark.asyncio
async def test_secretary_mode_types_everything_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """on → dictate (even a nav-shaped sentence!) → off; no LLM anywhere."""

    class _MustNotRun:
        def __init__(self) -> None:
            raise AssertionError("orchestrator must not run in secretary mode")

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", _MustNotRun)
    pipe._FIXED_LINE_CACHE.clear()
    nav_state: dict[str, Any] = {}

    # Enter: mode frame + spoken contract.
    emitter1 = FakeEmitter()
    reply1 = await pipe.run_text_turn(
        emitter1, "เปิดโหมดเลขา", [], session_id="v", ui_manifest=MANIFEST, nav_state=nav_state
    )
    assert nav_state.get("secretary") is True
    assert {"type": "voice_mode", "mode": "secretary"} in emitter1.json
    assert "เปิดโหมดเลขา" in reply1

    # Dictation: a sentence that would otherwise navigate is TYPED instead.
    emitter2 = FakeEmitter()
    reply2 = await pipe.run_text_turn(
        emitter2,
        "ไปหน้า settings แปลว่าอะไร",
        [],
        session_id="v",
        ui_manifest=MANIFEST,
        nav_state=nav_state,
    )
    assert reply2 == ""
    actions = [m for m in emitter2.json if m.get("type") == "ui_action"]
    assert actions == [
        {
            "type": "ui_action",
            "action": "navigate",
            "target": "type_in_chat",
            "argument": "ไปหน้า settings แปลว่าอะไร",
        }
    ]
    assert not [m for m in emitter2.json if m.get("type") == "audio"]  # silent

    # Exit: mode frame back to normal.
    emitter3 = FakeEmitter()
    await pipe.run_text_turn(
        emitter3, "ปิดโหมดเลขาครับ", [], session_id="v", ui_manifest=MANIFEST, nav_state=nav_state
    )
    assert "secretary" not in nav_state
    assert {"type": "voice_mode", "mode": "normal"} in emitter3.json


@pytest.mark.asyncio
async def test_dictation_off_the_chat_page_warns_and_steers_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In-mode dictation while not on /home → spoken warning + navigate, no typing."""

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    pipe._FIXED_LINE_CACHE.clear()
    nav_state: dict[str, Any] = {"secretary": True}

    emitter = FakeEmitter()
    reply = await pipe.run_text_turn(
        emitter,
        "ช่วยสรุปมาตรานี้หน่อย",
        [],
        session_id="v",
        ui_manifest=MANIFEST,
        ui_context={"path": "/settings", "summary": "x"},
        nav_state=nav_state,
    )

    assert "ไม่ได้อยู่หน้าแชท" in reply
    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert actions == [
        {"type": "ui_action", "action": "navigate", "target": "chat", "argument": ""}
    ]
    assert nav_state.get("secretary") is True  # still in the mode

    # Back on the chat page, the same dictation types normally.
    emitter2 = FakeEmitter()
    await pipe.run_text_turn(
        emitter2,
        "ช่วยสรุปมาตรานี้หน่อย",
        [],
        session_id="v",
        ui_manifest=MANIFEST,
        ui_context={"path": "/home", "summary": "x"},
        nav_state=nav_state,
    )
    typed = [m for m in emitter2.json if m.get("type") == "ui_action"]
    assert typed and typed[0]["target"] == "type_in_chat"


@pytest.mark.asyncio
async def test_stop_exits_secretary_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    pipe._FIXED_LINE_CACHE.clear()
    nav_state: dict[str, Any] = {"secretary": True}

    emitter = FakeEmitter()
    reply = await pipe.run_text_turn(
        emitter, "หยุดก่อน", [], session_id="v", ui_manifest=MANIFEST, nav_state=nav_state
    )
    assert reply == "ครับ"
    assert "secretary" not in nav_state
    assert {"type": "voice_mode", "mode": "normal"} in emitter.json


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
