"""WsPageActuator — request/response over frames, chunk reassembly, timeouts."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from deeptutor.services.voice_realtime.agent.ws_actuator import ActuatorTimeout, WsPageActuator

STATE = {
    "url": "http://x/knowledge",
    "title": "DeepTutor",
    "header": "Current Page: …",
    "content": "[0]<a >ศูนย์ความรู้ />",
    "footer": "[End of page]",
}


def collector():
    sent: list[dict[str, Any]] = []

    async def send(payload: dict[str, Any]) -> None:
        sent.append(payload)

    return sent, send


@pytest.mark.asyncio
async def test_observe_reassembles_chunks_in_seq_order():
    sent, send = collector()
    actuator = WsPageActuator(send, observe_timeout_s=1)

    async def client_replies():
        while not sent:  # wait for the observe frame
            await asyncio.sleep(0)
        request_id = sent[0]["id"]
        payload = json.dumps(STATE)
        third = len(payload) // 3 + 1
        parts = [payload[i : i + third] for i in range(0, len(payload), third)]
        # Deliver OUT of order — reassembly must sort by seq.
        order = list(enumerate(parts))
        for seq, part in reversed(order):
            actuator.handle_frame(
                {
                    "type": "agent_state_chunk",
                    "id": request_id,
                    "seq": seq,
                    "total": len(parts),
                    "part": part,
                }
            )

    replies = asyncio.ensure_future(client_replies())
    state = await actuator.observe()
    await replies

    assert sent[0]["type"] == "agent_observe"
    assert state.url == "http://x/knowledge"
    assert state.content == "[0]<a >ศูนย์ความรู้ />"


@pytest.mark.asyncio
async def test_act_roundtrip_carries_ok_and_message():
    sent, send = collector()
    actuator = WsPageActuator(send, act_timeout_s=1)

    async def client_replies():
        while not sent:
            await asyncio.sleep(0)
        frame = sent[0]
        assert frame == {
            "type": "agent_act",
            "id": frame["id"],
            "action": "click_element_by_index",
            "args": {"index": 3},
        }
        actuator.handle_frame(
            {
                "type": "agent_acted",
                "id": frame["id"],
                "ok": True,
                "message": "✅ Clicked element ([3]<a >ศูนย์ความรู้ />).",
            }
        )

    replies = asyncio.ensure_future(client_replies())
    result = await actuator.act("click_element_by_index", {"index": 3})
    await replies

    assert result.ok
    assert "ศูนย์ความรู้" in result.message


@pytest.mark.asyncio
async def test_silent_page_times_out_honestly():
    _sent, send = collector()
    actuator = WsPageActuator(send, observe_timeout_s=0.01, act_timeout_s=0.01)
    with pytest.raises(ActuatorTimeout):
        await actuator.observe()
    with pytest.raises(ActuatorTimeout):
        await actuator.act("scroll", {"down": True})


@pytest.mark.asyncio
async def test_stale_and_foreign_frames_are_dropped():
    _sent, send = collector()
    actuator = WsPageActuator(send)
    # No request in flight — nothing should blow up, chunk is silently dropped.
    assert actuator.handle_frame(
        {"type": "agent_state_chunk", "id": "ghost", "seq": 0, "total": 1, "part": "{}"}
    )
    assert actuator.handle_frame({"type": "agent_acted", "id": "ghost", "ok": True, "message": ""})
    # Non-agent frames are not ours.
    assert not actuator.handle_frame({"type": "ui_context"})


@pytest.mark.asyncio
async def test_run_frames_toggle_the_mask():
    sent, send = collector()
    actuator = WsPageActuator(send)
    await actuator.start_run()
    await actuator.end_run()
    assert sent == [
        {"type": "agent_run", "running": True},
        {"type": "agent_run", "running": False},
    ]
