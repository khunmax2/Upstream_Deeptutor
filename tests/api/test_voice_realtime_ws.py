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
        self.cancels = 0
        self.closed = False
        FakeSession.last = self

    async def handle_utterance(self, audio: bytes) -> None:
        self.utterances.append(audio)

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
