"""Tests for the deep target-locking rung (LLM picks an element index).

The rung only runs after every deterministic rung missed; these tests pin
its trust rules — index must exist, destructive labels refused server-side,
every failure mode a silent fall-through — and the pipeline/session/router
plumbing that carries the ui_scan → ui_inventory round trip.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deeptutor.services.voice_realtime import pipeline as pipe
from deeptutor.services.voice_realtime import ui_deep
from deeptutor.services.voice_realtime.session import VoiceSession
from tests.services.voice_realtime.test_pipeline import FakeEmitter

RAW_INVENTORY = [
    {"i": 0, "tag": "button", "label": "ส่ง", "hint": ""},
    {"i": 1, "tag": "a", "label": "LlamaIndex", "hint": "/knowledge"},
    {"i": 2, "tag": "button", "label": "", "hint": "nav"},  # icon-only
    {"i": 3, "tag": "button", "label": "ลบทั้งหมด", "hint": ""},  # dangerous
    {"i": 4, "tag": "div", "label": "", "hint": ""},  # unaddressable → dropped
    "junk",
    {"i": "x", "label": "bad index"},
]


def _patch_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_synthesize(text: str) -> tuple[bytes, str]:
        return (f"AUDIO:{text}".encode(), "audio/mpeg")

    monkeypatch.setattr(pipe, "synthesize_speech", fake_synthesize)
    pipe._FIXED_LINE_CACHE.clear()


# ── sanitize / format / parse ───────────────────────────────────────────


def test_sanitize_inventory_keeps_addressable_items_only() -> None:
    items = ui_deep.sanitize_inventory(RAW_INVENTORY)
    assert [item["i"] for item in items] == [0, 1, 2, 3]
    assert items[1]["hint"] == "/knowledge"
    assert ui_deep.sanitize_inventory("junk") == []
    assert ui_deep.sanitize_inventory(None) == []


def test_format_inventory_numbers_the_lines() -> None:
    items = ui_deep.sanitize_inventory(RAW_INVENTORY)
    text = ui_deep.format_inventory(items)
    assert "[0] <button> ส่ง" in text
    assert "[1] <a> LlamaIndex — /knowledge" in text


def test_parse_index_reply_is_strict() -> None:
    items = ui_deep.sanitize_inventory(RAW_INVENTORY)
    assert ui_deep.parse_index_reply("1", items) == items[1]
    assert ui_deep.parse_index_reply(" [1] ", items) == items[1]
    assert ui_deep.parse_index_reply("NONE", items) is None
    assert ui_deep.parse_index_reply("", items) is None
    assert ui_deep.parse_index_reply("99", items) is None  # not in inventory
    # Destructive label → refused server-side no matter what the LLM said.
    assert ui_deep.parse_index_reply("3", items) is None


@pytest.mark.asyncio
async def test_pick_element_survives_llm_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*a: Any, **k: Any) -> str:
        raise RuntimeError("provider down")

    monkeypatch.setattr("deeptutor.services.llm.client.LLMClient.complete", boom)
    monkeypatch.setattr(
        "deeptutor.services.llm.config.get_llm_config", lambda: object(), raising=False
    )
    items = ui_deep.sanitize_inventory(RAW_INVENTORY)
    assert await ui_deep.pick_element("ส่ง", "กดส่ง", items) is None
    assert await ui_deep.pick_element("x", "x", []) is None  # empty → no LLM call


# ── pipeline rung ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_click_miss_falls_to_deep_rung_and_clicks_by_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Miss everywhere on-screen + graph → scan, LLM pick, click_index frame."""
    _patch_tts(monkeypatch)

    async def fake_pick(spoken: str, transcript: str, items: list[dict]) -> dict | None:
        assert spoken and items
        return items[1]

    monkeypatch.setattr(pipe.ui_deep, "pick_element", fake_pick)

    async def getter() -> list[dict]:
        return RAW_INVENTORY

    emitter = FakeEmitter()
    await pipe.run_text_turn(
        emitter,
        "กดลามะอินเด็ก",  # garbled; resolver + graph both miss
        [],
        session_id="voice:test",
        ui_context={"path": "/x", "summary": "x", "buttons": ["ส่งข้อความ"]},
        nav_state={},
        inventory_getter=getter,
    )

    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert actions == [
        {
            "type": "ui_action",
            "action": "navigate",
            "target": "click_index",
            "argument": "1",
            "label": "LlamaIndex",
        }
    ]


@pytest.mark.asyncio
async def test_deep_rung_miss_still_ends_honestly(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM answers NONE → the honest click-miss line, nothing dispatched."""
    _patch_tts(monkeypatch)

    async def fake_pick(*a: Any, **k: Any) -> None:
        return None

    monkeypatch.setattr(pipe.ui_deep, "pick_element", fake_pick)

    async def getter() -> list[dict]:
        return RAW_INVENTORY

    emitter = FakeEmitter()
    reply = await pipe.run_text_turn(
        emitter,
        "กดปุ่มที่ไม่มีจริง",
        [],
        session_id="voice:test",
        ui_context={"path": "/x", "summary": "x", "buttons": ["ส่ง"]},
        nav_state={},
        inventory_getter=getter,
    )

    assert "ไม่เห็นปุ่ม" in reply
    assert not [m for m in emitter.json if m.get("type") == "ui_action"]


@pytest.mark.asyncio
async def test_click_ambiguous_falls_to_deep_rung(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live regression: a fuzzy tie used to dead-end at "พูดชื่อเต็ม" — the
    deep rung's LLM (full screen in hand) now adjudicates it first."""
    _patch_tts(monkeypatch)

    async def fake_pick(spoken: str, transcript: str, items: list[dict]) -> dict | None:
        return items[1]  # LlamaIndex

    monkeypatch.setattr(pipe.ui_deep, "pick_element", fake_pick)

    async def getter() -> list[dict]:
        return RAW_INVENTORY

    emitter = FakeEmitter()
    await pipe.run_text_turn(
        emitter,
        "กดที่ index",
        [],
        session_id="voice:test",
        # Two distinct labels that both substring-match "index" → a real tie.
        ui_context={"path": "/x", "summary": "x", "buttons": ["PageIndex", "LlamaIndex"]},
        nav_state={},
        inventory_getter=getter,
    )

    actions = [m for m in emitter.json if m.get("type") == "ui_action"]
    assert [a["target"] for a in actions] == ["click_index"]


@pytest.mark.asyncio
async def test_click_ambiguous_ask_back_names_the_tie(monkeypatch: pytest.MonkeyPatch) -> None:
    """No deep rung available (or it declined) → the ask-back NAMES the tied
    candidates instead of the dead-end 'พูดชื่อเต็ม'."""
    _patch_tts(monkeypatch)

    async def fake_pick(*a: Any, **k: Any) -> None:
        return None

    monkeypatch.setattr(pipe.ui_deep, "pick_element", fake_pick)

    async def getter() -> list[dict]:
        return RAW_INVENTORY

    emitter = FakeEmitter()
    reply = await pipe.run_text_turn(
        emitter,
        "กดที่ index",
        [],
        session_id="voice:test",
        ui_context={"path": "/x", "summary": "x", "buttons": ["PageIndex", "LlamaIndex"]},
        nav_state={},
        inventory_getter=getter,
    )

    assert "PageIndex" in reply and "LlamaIndex" in reply and "หรือ" in reply


# ── session round trip ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_inventory_round_trip() -> None:
    emitter = FakeEmitter()
    session = VoiceSession(emitter)

    async def resolve_soon() -> None:
        await asyncio.sleep(0.01)
        session.resolve_ui_inventory([{"i": 0, "tag": "button", "label": "ส่ง"}])

    task = asyncio.create_task(resolve_soon())
    got = await session.request_ui_inventory()
    await task

    assert got == [{"i": 0, "tag": "button", "label": "ส่ง"}]
    assert any(m.get("type") == "ui_scan" for m in emitter.json)
    # A late/duplicate frame with no waiter is a harmless no-op.
    session.resolve_ui_inventory([])


@pytest.mark.asyncio
async def test_session_inventory_timeout_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("deeptutor.services.voice_realtime.session.INVENTORY_TIMEOUT_SECONDS", 0.01)
    emitter = FakeEmitter()
    session = VoiceSession(emitter)
    assert await session.request_ui_inventory() is None
