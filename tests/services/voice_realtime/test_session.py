"""Tests for VoiceSession turn serialisation and barge-in cancellation."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deeptutor.services.voice_realtime import session as session_mod
from deeptutor.services.voice_realtime.session import VoiceSession


class _NullEmitter:
    async def send_json(self, data: dict[str, Any]) -> None:  # noqa: ARG002
        return None

    async def send_bytes(self, data: bytes) -> None:  # noqa: ARG002
        return None


@pytest.mark.asyncio
async def test_completed_turn_appends_history(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_turn(emitter, audio, history, *, session_id, language, **kwargs):  # noqa: ANN001
        return "ผู้ใช้พูด", "ผู้ช่วยตอบ"

    monkeypatch.setattr(session_mod, "run_turn", fake_run_turn)
    sess = VoiceSession(_NullEmitter())

    await sess.handle_utterance(b"audio")
    await sess._current  # let the turn finish

    assert sess.history == [
        {"role": "user", "content": "ผู้ใช้พูด"},
        {"role": "assistant", "content": "ผู้ช่วยตอบ"},
    ]


@pytest.mark.asyncio
async def test_barge_in_cancels_turn_and_skips_history(monkeypatch: pytest.MonkeyPatch) -> None:
    started = asyncio.Event()

    async def slow_run_turn(emitter, audio, history, *, session_id, language, **kwargs):  # noqa: ANN001
        started.set()
        await asyncio.sleep(10)  # simulate a long turn that gets barged in on
        return "should-not", "commit"

    monkeypatch.setattr(session_mod, "run_turn", slow_run_turn)
    sess = VoiceSession(_NullEmitter())

    await sess.handle_utterance(b"audio")
    await started.wait()
    await sess.cancel_current_turn()

    assert sess._current is None
    assert sess.history == []  # nothing committed for a barged-in turn


@pytest.mark.asyncio
async def test_new_utterance_cancels_previous_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bytes] = []
    first_started = asyncio.Event()

    async def run_turn_recording(emitter, audio, history, *, session_id, language, **kwargs):  # noqa: ANN001
        calls.append(audio)
        if audio == b"first":
            first_started.set()
            await asyncio.sleep(10)
        return "u", "a"

    monkeypatch.setattr(session_mod, "run_turn", run_turn_recording)
    sess = VoiceSession(_NullEmitter())

    await sess.handle_utterance(b"first")
    await first_started.wait()
    await sess.handle_utterance(b"second")  # should cancel the first
    await sess._current

    assert calls == [b"first", b"second"]
    # Only the second (completed) turn committed.
    assert sess.history == [
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "a"},
    ]
