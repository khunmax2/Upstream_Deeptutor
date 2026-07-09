"""Tests for the Website Graph — cross-page voice commands.

The graph turns a goal ("เปลี่ยนธีมเป็นโหมดมืด" spoken anywhere) into a plan:
navigate to the owning page, then press the control — released step-by-step
by the client's post-action verify. These tests cover the matcher, the
resolver (weighted, same garble tolerance as on-screen), the plan shapes,
and the pending-step lifecycle (fires once, verify-gated, TTL-bounded).
"""

from __future__ import annotations

import time

import pytest

from deeptutor.services.voice_realtime import pipeline as pipe
from deeptutor.services.voice_realtime import ui_graph
from tests.services.voice_realtime.test_pipeline import FakeEmitter


def _patch_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic-rung turns need only a fake TTS (no LLM runs at all)."""

    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    pipe._FIXED_LINE_CACHE.clear()


# A miniature graph so tests don't couple to the curated deeptutor one.
GRAPH = {
    "origin": "test",
    "nodes": [
        {
            "id": "settings_appearance",
            "path": "/settings/appearance",
            "label": "หน้าธีม",
            "controls": [
                {
                    "capability": "theme_dark",
                    "click": "Dark",
                    "kind": "button",
                    "aliases": ["โหมดมืด", "ธีมมืด", "dark mode"],
                },
                {
                    "capability": "theme_cream",
                    "click": "ครีม",
                    "kind": "button",
                    "aliases": ["ธีมครีม"],
                },
                {
                    "capability": "delete_everything",
                    "click": "ลบทั้งหมด",
                    "kind": "button",
                    "aliases": ["ล้างข้อมูล"],
                },
            ],
        }
    ],
    "edges": [{"from": "*", "to": "*", "via": "navigate", "cost": 1}],
}


# ── goal matcher ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("เปลี่ยนธีมเป็นโหมดมืด", "โหมดมืด"),
        ("ช่วยเปลี่ยนธีมเป็นโหมดมืดให้หน่อยครับ", "โหมดมืด"),
        ("ใช้ธีมครีม", "ครีม"),
        ("สลับเป็นโหมดมืดหน่อย", "โหมดมืด"),
        # Generic "เปลี่ยน …padding… เป็น X" — live gap: the caller said
        # "เปลี่ยนภาษาอินเตอร์เฟสเป็นภาษาอังกฤษ" and no fixed verb matched.
        ("เปลี่ยนภาษาอินเตอร์เฟสเป็นภาษาอังกฤษ", "ภาษาอังกฤษ"),
        ("เปลี่ยนภาษา interface เป็นภาษาไทยให้หน่อย", "ภาษาไทย"),
        ("สลับธีมของแอปเป็นครีมหน่อยครับ", "ครีม"),
    ],
)
def test_graph_intent_extracts_the_target(text: str, name: str) -> None:
    assert ui_graph.match_graph_intent(text) == name


@pytest.mark.parametrize(
    "text",
    [
        "เปลี่ยนธีมได้ไหม",  # question → conversation, not a command
        "เปลี่ยนธีม",  # no target named → nothing to resolve
        "โหมดมืดคืออะไร",  # question
        "สวัสดีครับ",  # not a goal phrasing
        "",
    ],
)
def test_graph_intent_falls_through(text: str) -> None:
    assert ui_graph.match_graph_intent(text) is None


# ── control resolver ────────────────────────────────────────────────────


def test_find_graph_control_resolves_aliases_and_garbles() -> None:
    outcome, node, control = ui_graph.find_graph_control("โหมดมืด", GRAPH)
    assert outcome == "hit" and control is not None
    assert control["capability"] == "theme_dark"
    assert node is not None and node["path"] == "/settings/appearance"
    # Click text itself works too, cross-script tolerant like the screen.
    assert ui_graph.find_graph_control("ธีมครีม", GRAPH)[0] == "hit"
    assert ui_graph.find_graph_control("ไม่มีจริง", GRAPH) == ("missing", None, None)
    assert ui_graph.find_graph_control("", GRAPH) == ("missing", None, None)


def test_find_graph_control_ambiguous_between_controls() -> None:
    # "ธีม" substring-matches both theme controls' aliases equally → ask, not guess.
    outcome, _, _ = ui_graph.find_graph_control("ธีม", GRAPH)
    assert outcome == "ambiguous"


def test_find_graph_control_never_auto_presses_danger() -> None:
    # A destructive-sounding control resolves as a MISS: cross-page auto-press
    # must never reach something the confirm rung was built to guard.
    assert ui_graph.find_graph_control("ล้างข้อมูล", GRAPH) == ("missing", None, None)


def test_curated_graph_has_no_vocabulary_collisions() -> None:
    """Every control in the SHIPPED graph must be reachable by its own click
    text and every alias — uniquely. This is the guard that keeps future
    catalog entries from silently shadowing each other."""
    graph = ui_graph.load_graph()
    for node in graph["nodes"]:
        for control in node["controls"]:
            for spoken in [control["click"], *control["aliases"]]:
                outcome, _, hit = ui_graph.find_graph_control(spoken, graph)
                assert outcome == "hit" and hit is not None, (
                    f"{control['capability']}: {spoken!r} → {outcome}"
                )
                assert hit["capability"] == control["capability"], (
                    f"{spoken!r} resolved to {hit['capability']} instead of {control['capability']}"
                )


# ── plan shapes ─────────────────────────────────────────────────────────


def _dark() -> tuple[dict, dict]:
    node = GRAPH["nodes"][0]
    return node, node["controls"][0]


def test_plan_cross_page_navigates_then_acts() -> None:
    node, control = _dark()
    navigate, action = ui_graph.plan_graph_step(node, control, "/home")
    assert navigate == {
        "type": "ui_action",
        "action": "navigate",
        "target": "open_path",
        "argument": "/settings/appearance",
    }
    assert action["target"] == "click_element" and action["argument"] == "Dark"


def test_plan_same_page_skips_navigation() -> None:
    node, control = _dark()
    navigate, action = ui_graph.plan_graph_step(node, control, "/settings/appearance")
    assert navigate is None
    assert action["argument"] == "Dark"


def test_plan_field_kind_focuses_instead_of_clicking() -> None:
    node = {"id": "kb", "path": "/knowledge", "label": "x", "controls": []}
    control = {"capability": "kb_search", "click": "ค้นหา", "kind": "field", "aliases": []}
    _, action = ui_graph.plan_graph_step(node, control, "/home")
    assert action == {
        "type": "ui_action",
        "action": "navigate",
        "target": "focus_field",
        "argument": "",
        "field": "ค้นหา",
    }


# ── pending step lifecycle ──────────────────────────────────────────────


def test_pending_step_fires_once_on_verified_arrival() -> None:
    node, control = _dark()
    _, action = ui_graph.plan_graph_step(node, control, "/home")
    nav_state = {"pending_graph_step": ui_graph.make_pending_step(node, action)}
    ok = {"target": "open_path", "argument": "/settings/appearance", "ok": True, "detail": ""}
    assert ui_graph.take_pending_step(nav_state, ok) == action
    assert "pending_graph_step" not in nav_state  # consumed
    assert ui_graph.take_pending_step(nav_state, ok) is None  # fires once


def test_pending_step_dropped_on_failed_or_wrong_navigation() -> None:
    node, control = _dark()
    _, action = ui_graph.plan_graph_step(node, control, "/home")
    for result in (
        {"target": "open_path", "argument": "/settings/appearance", "ok": False, "detail": "x"},
        {"target": "open_path", "argument": "/notebook", "ok": True, "detail": ""},
    ):
        nav_state = {"pending_graph_step": ui_graph.make_pending_step(node, action)}
        assert ui_graph.take_pending_step(nav_state, result) is None
        assert "pending_graph_step" not in nav_state  # consumed either way


def test_pending_step_ignores_unrelated_results() -> None:
    node, control = _dark()
    _, action = ui_graph.plan_graph_step(node, control, "/home")
    nav_state = {"pending_graph_step": ui_graph.make_pending_step(node, action)}
    fill = {"target": "fill_field", "field": "ค้นหา", "ok": True, "detail": ""}
    assert ui_graph.take_pending_step(nav_state, fill) is None
    assert "pending_graph_step" in nav_state  # still parked, awaiting its page


def test_pending_step_expires() -> None:
    node, control = _dark()
    _, action = ui_graph.plan_graph_step(node, control, "/home")
    pending = ui_graph.make_pending_step(node, action)
    pending["expires_at"] = time.time() - 1
    nav_state = {"pending_graph_step": pending}
    ok = {"target": "open_path", "argument": "/settings/appearance", "ok": True, "detail": ""}
    assert ui_graph.take_pending_step(nav_state, ok) is None


# ── pipeline rungs ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_goal_phrasing_plans_cross_page_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "เปลี่ยนธีมเป็นโหมดมืด" from /home → open_path + parked click, no LLM."""

    class _MustNotRun:
        def __init__(self) -> None:
            raise AssertionError("orchestrator must not run for a graph command")

    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", _MustNotRun)
    _patch_tts(monkeypatch)
    emitter = FakeEmitter()
    nav_state: dict = {}

    await pipe.run_text_turn(
        emitter,
        "เปลี่ยนธีมเป็นโหมดมืด",
        [],
        session_id="voice:test",
        ui_context={"path": "/home", "summary": "x"},
        nav_state=nav_state,
    )

    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert actions == [
        {
            "type": "ui_action",
            "action": "navigate",
            "target": "open_path",
            "argument": "/settings/appearance",
        }
    ]
    pending = nav_state["pending_graph_step"]
    assert pending["page_path"] == "/settings/appearance"
    assert pending["action"]["target"] == "click_element"
    assert pending["action"]["argument"] == "Dark"


@pytest.mark.asyncio
async def test_click_miss_falls_back_to_the_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "กดโหมดมืด" with no such button on-screen → graph plan, not a dead-end."""
    _patch_tts(monkeypatch)
    emitter = FakeEmitter()
    nav_state: dict = {}

    await pipe.run_text_turn(
        emitter,
        "กดโหมดมืด",
        [],
        session_id="voice:test",
        ui_context={"path": "/home", "summary": "x", "buttons": ["ส่ง", "ยกเลิก"]},
        nav_state=nav_state,
    )

    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert [a["target"] for a in actions] == ["open_path"]
    assert nav_state["pending_graph_step"]["action"]["argument"] == "Dark"


@pytest.mark.asyncio
async def test_language_switch_plans_cross_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "เปลี่ยนภาษาเป็นไทย" from /home → open the appearance page, press ภาษาไทย."""
    _patch_tts(monkeypatch)
    emitter = FakeEmitter()
    nav_state: dict = {}

    await pipe.run_text_turn(
        emitter,
        "เปลี่ยนภาษาเป็นไทย",
        [],
        session_id="voice:test",
        ui_context={"path": "/home", "summary": "x"},
        nav_state=nav_state,
    )

    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert [a["target"] for a in actions] == ["open_path"]
    assert actions[0]["argument"] == "/settings/appearance"
    assert nav_state["pending_graph_step"]["action"]["argument"] == "ภาษาไทย"


@pytest.mark.asyncio
async def test_create_kb_plans_cross_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "สร้างคลังความรู้" from /home → open /knowledge, press the create button."""
    _patch_tts(monkeypatch)
    emitter = FakeEmitter()
    nav_state: dict = {}

    await pipe.run_text_turn(
        emitter,
        "สร้างคลังความรู้ให้หน่อย",
        [],
        session_id="voice:test",
        ui_context={"path": "/home", "summary": "x"},
        nav_state=nav_state,
    )

    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert [a["target"] for a in actions] == ["open_path"]
    assert actions[0]["argument"] == "/knowledge"
    assert nav_state["pending_graph_step"]["action"]["argument"] == "Knowledge Base ใหม่"


@pytest.mark.asyncio
async def test_graph_same_page_clicks_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Already on the control's page → click now, nothing parked."""
    _patch_tts(monkeypatch)
    emitter = FakeEmitter()
    nav_state: dict = {}

    await pipe.run_text_turn(
        emitter,
        "เปลี่ยนธีมเป็นโหมดมืด",
        [],
        session_id="voice:test",
        ui_context={"path": "/settings/appearance", "summary": "x"},
        nav_state=nav_state,
    )

    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert [a["target"] for a in actions] == ["click_element"]
    assert actions[0]["argument"] == "Dark"
    assert "pending_graph_step" not in nav_state
