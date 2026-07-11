"""Tests for the realtime voice WebSocket router's receive-loop routing.

These exercise the router's dispatch logic (binary → utterance, barge → cancel,
oversize → error, disconnect → clean teardown) against a scripted fake socket,
without standing up the full app / auth / model catalog.
"""

from __future__ import annotations

from typing import Any

import pytest

import deeptutor.api.routers.voice_realtime as vr


class FakeWebSocket:
    """A scripted WebSocket: yields queued frames, records sent text."""

    def __init__(self, incoming: list[dict[str, Any]]) -> None:
        self._incoming = list(incoming)
        self.accepted = False
        self.sent_text: list[str] = []

    async def accept(self) -> None:
        self.accepted = True

    async def receive(self) -> dict[str, Any]:
        if self._incoming:
            return self._incoming.pop(0)
        return {"type": "websocket.disconnect"}

    async def send_text(self, data: str) -> None:
        self.sent_text.append(data)


class FakeSession:
    last: "FakeSession | None" = None

    def __init__(self, emitter: Any, *, language: str = "th") -> None:
        self.utterances: list[bytes] = []
        self.texts: list[str] = []
        self.cancels = 0
        self.greeted = False
        self.closed = False
        self.ui_manifest: Any = None
        self.ui_context: Any = None
        self.nav_state: dict[str, Any] = {}
        self.inventories: list[Any] = []
        FakeSession.last = self

    def resolve_ui_inventory(self, items: Any) -> None:
        self.inventories.append(items)

    async def greet(self) -> None:
        self.greeted = True

    async def handle_utterance(self, audio: bytes) -> None:
        self.utterances.append(audio)

    async def handle_text(self, text: str) -> None:
        self.texts.append(text)

    async def cancel_current_turn(self) -> None:
        self.cancels += 1

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _patch_auth_and_session(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_auth(ws: Any) -> str:
        return "user-token"

    monkeypatch.setattr("deeptutor.api.routers.auth.ws_require_auth", fake_auth)
    monkeypatch.setattr("deeptutor.multi_user.context.reset_current_user", lambda token: None)
    monkeypatch.setattr(vr, "VoiceSession", FakeSession)
    FakeSession.last = None


@pytest.mark.asyncio
async def test_binary_frame_starts_a_turn() -> None:
    ws = FakeWebSocket([{"type": "websocket.receive", "bytes": b"utterance-webm"}])
    await vr.voice_websocket(ws)

    assert ws.accepted
    assert FakeSession.last is not None
    assert FakeSession.last.utterances == [b"utterance-webm"]
    assert FakeSession.last.closed  # torn down in finally


@pytest.mark.asyncio
async def test_barge_control_frame_cancels_turn() -> None:
    ws = FakeWebSocket(
        [
            {"type": "websocket.receive", "bytes": b"u1"},
            {"type": "websocket.receive", "text": '{"type": "barge"}'},
        ]
    )
    await vr.voice_websocket(ws)

    assert FakeSession.last.utterances == [b"u1"]
    assert FakeSession.last.cancels >= 1


@pytest.mark.asyncio
async def test_user_text_frame_starts_text_turn() -> None:
    ws = FakeWebSocket(
        [{"type": "websocket.receive", "text": '{"type": "user_text", "text": "สวัสดี"}'}]
    )
    await vr.voice_websocket(ws)

    assert FakeSession.last.texts == ["สวัสดี"]
    assert not FakeSession.last.utterances


@pytest.mark.asyncio
async def test_ui_frames_land_on_the_session() -> None:
    """ui_manifest and ui_context control frames update session state."""
    ws = FakeWebSocket(
        [
            {
                "type": "websocket.receive",
                "text": '{"type": "ui_manifest", "manifest": '
                '{"pages": [{"id": "settings", "label": "หน้าตั้งค่า"}]}}',
            },
            {
                "type": "websocket.receive",
                "text": '{"type": "ui_context", "context": '
                '{"path": "/settings", "summary": "ปุ่ม: บันทึก"}}',
            },
        ]
    )
    await vr.voice_websocket(ws)

    sess = FakeSession.last
    assert sess is not None and sess.greeted
    assert sess.ui_manifest == {"pages": [{"id": "settings", "label": "หน้าตั้งค่า"}]}
    assert sess.ui_context == {"path": "/settings", "summary": "ปุ่ม: บันทึก"}
    assert any("ui_manifest_ok" in t for t in ws.sent_text)


@pytest.mark.asyncio
async def test_ui_action_result_lands_on_nav_state() -> None:
    """Post-action verify verdicts are remembered (silently) on nav_state."""
    ws = FakeWebSocket(
        [
            {
                "type": "websocket.receive",
                "text": '{"type": "ui_action_result", "result": '
                '{"target": "fill_field", "field": "ค้นหา", "ok": false, '
                '"detail": "value_is:กดหมาย"}}',
            },
        ]
    )
    await vr.voice_websocket(ws)

    sess = FakeSession.last
    assert sess is not None
    assert sess.nav_state["last_action_result"] == {
        "target": "fill_field",
        "field": "ค้นหา",
        "ok": False,
        "detail": "value_is:กดหมาย",
    }
    # Silent frame: no ack goes back.
    assert not any("ui_action_result" in t for t in ws.sent_text)


@pytest.mark.asyncio
async def test_verified_navigation_releases_the_parked_graph_step() -> None:
    """Website Graph: the parked follow-up fires when (and only when) the
    client's post-action verify confirms the planned page landed."""
    import time as _time

    ws = FakeWebSocket(
        [
            {
                "type": "websocket.receive",
                "text": '{"type": "ui_action_result", "result": '
                '{"target": "open_path", "argument": "/settings/appearance", '
                '"ok": true, "detail": "route_changed"}}',
            },
        ]
    )

    # Park a step before the frames run: FakeSession is created inside
    # voice_websocket, so plant via a wrapper.
    orig_init = FakeSession.__init__

    def init_with_pending(self: FakeSession, emitter: Any, *, language: str = "th") -> None:
        orig_init(self, emitter, language=language)
        self.nav_state["pending_graph_step"] = {
            "page_path": "/settings/appearance",
            "action": {
                "type": "ui_action",
                "action": "navigate",
                "target": "click_element",
                "argument": "Dark",
            },
            "expires_at": _time.time() + 15,
        }

    FakeSession.__init__ = init_with_pending  # type: ignore[method-assign]
    try:
        await vr.voice_websocket(ws)
    finally:
        FakeSession.__init__ = orig_init  # type: ignore[method-assign]

    sess = FakeSession.last
    assert sess is not None
    assert "pending_graph_step" not in sess.nav_state  # consumed
    assert any('"click_element"' in t and '"Dark"' in t for t in ws.sent_text)


@pytest.mark.asyncio
async def test_ui_inventory_frame_reaches_the_session() -> None:
    """A ui_inventory reply is delivered to the awaiting turn, silently."""
    ws = FakeWebSocket(
        [
            {
                "type": "websocket.receive",
                "text": '{"type": "ui_inventory", "inventory": '
                '[{"i": 0, "tag": "button", "label": "ส่ง", "hint": ""}]}',
            },
        ]
    )
    await vr.voice_websocket(ws)

    sess = FakeSession.last
    assert sess is not None
    assert sess.inventories == [[{"i": 0, "tag": "button", "label": "ส่ง", "hint": ""}]]
    assert not any("ui_inventory" in t for t in ws.sent_text)  # no ack


@pytest.mark.asyncio
async def test_ui_action_result_malformed_is_dropped() -> None:
    ws = FakeWebSocket(
        [
            {
                "type": "websocket.receive",
                "text": '{"type": "ui_action_result", "result": {"ok": true}}',  # no target
            },
        ]
    )
    await vr.voice_websocket(ws)

    assert FakeSession.last is not None
    assert "last_action_result" not in FakeSession.last.nav_state


@pytest.mark.asyncio
async def test_oversize_utterance_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vr, "is_utterance_too_large", lambda n: True)
    ws = FakeWebSocket([{"type": "websocket.receive", "bytes": b"way-too-big"}])
    await vr.voice_websocket(ws)

    assert not FakeSession.last.utterances  # never started
    assert any("error" in t for t in ws.sent_text)


@pytest.mark.asyncio
async def test_auth_failure_returns_without_accepting(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.api.routers.auth import ws_auth_failed

    async def fail_auth(ws: Any) -> Any:
        return ws_auth_failed

    monkeypatch.setattr("deeptutor.api.routers.auth.ws_require_auth", fail_auth)
    ws = FakeWebSocket([{"type": "websocket.receive", "bytes": b"u1"}])
    await vr.voice_websocket(ws)

    assert not ws.accepted
    assert FakeSession.last is None  # no session created


@pytest.mark.asyncio
async def test_agent_ready_flash_sent_on_connect_when_loop_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Call pickup with the loop on → one agent_ready frame (the client's cue
    to flash the neon vision sweep) BEFORE any turn happens."""
    monkeypatch.setenv("DEEPTUTOR_AGENT_LOOP", "1")
    monkeypatch.setenv("DEEPTUTOR_AGENT_MODEL", "gemini-2.5-flash")
    ws = FakeWebSocket([])

    await vr.voice_websocket(ws)

    assert any('"agent_ready"' in t for t in ws.sent_text)


@pytest.mark.asyncio
async def test_no_agent_ready_when_loop_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPTUTOR_AGENT_LOOP", raising=False)
    ws = FakeWebSocket([])

    await vr.voice_websocket(ws)

    assert not any('"agent_ready"' in t for t in ws.sent_text)
