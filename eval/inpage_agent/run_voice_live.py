"""Live end-to-end: a spoken command through the REAL voice pipeline.

Drives ``pipeline.run_text_turn`` with the REAL intent classifier + a REAL agent
loop wired to the live app via browser_host — so a command like "สร้างหนังสือ
ใหม่" flows transcript → classifier → ui_task → loop → clicks on the live UI.
Proves the A1 seam on the running app (no audio/WS needed). New file under eval/.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import httpx

HOST = "http://127.0.0.1:8899"

from deeptutor.services.voice_realtime import pipeline as pipe  # noqa: E402
from deeptutor.services.voice_realtime.agent.loop import InPageAgentLoop  # noqa: E402
from deeptutor.services.voice_realtime.agent.types import ActResult, BrowserState  # noqa: E402


class HttpActuator:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._c = client

    async def observe(self) -> BrowserState:
        d = (await self._c.get(f"{HOST}/observe", timeout=30)).json()
        return BrowserState(
            url=d.get("url", ""), title=d.get("title", ""), header=d.get("header", ""),
            content=d.get("content", ""), footer=d.get("footer", ""),
        )

    async def act(self, name: str, args: dict[str, Any]) -> ActResult:
        d = (await self._c.post(f"{HOST}/act", json={"name": name, "args": args}, timeout=40)).json()
        return ActResult(ok=bool(d.get("ok")), message=str(d.get("message") or ""))


class Emitter:
    def __init__(self) -> None:
        self.json: list[dict[str, Any]] = []

    async def send_json(self, d: dict[str, Any]) -> None:
        self.json.append(d)

    async def send_bytes(self, b: bytes) -> None:
        return None


async def _run_one(client: httpx.AsyncClient, transcript: str) -> None:
    await client.post(f"{HOST}/settheme", json={"theme": "snow"}, timeout=40)
    await client.post(f"{HOST}/goto", json={"url": "/home"}, timeout=40)
    await client.post(f"{HOST}/reset", timeout=20)
    before = (await client.get(f"{HOST}/probe", timeout=20)).json()

    seen: dict[str, Any] = {"task": None}

    async def agent_runner(task: str) -> str:
        seen["task"] = task  # records that the classifier routed to the loop
        loop = InPageAgentLoop(HttpActuator(client), step_delay_s=0.4, max_steps=12)
        return (await loop.execute(task)).text

    print(f"\n=== {transcript!r}", flush=True)
    reply = await pipe.run_text_turn(
        Emitter(), transcript, [], session_id="live",
        ui_context={"path": "/home", "summary": "หน้าหลัก"}, agent_runner=agent_runner,
    )
    after = (await client.get(f"{HOST}/probe", timeout=20)).json()
    routed = "loop" if seen["task"] is not None else "chat (loop not used)"
    print(f"  routed -> {routed}", flush=True)
    print(f"  url {before.get('url','?').split('3000')[-1]} -> {after.get('url','?').split('3000')[-1]}", flush=True)
    if after.get("htmlClass") != before.get("htmlClass"):
        print(f"  htmlClass changed (theme?): ...{after.get('htmlClass','')[-24:]}", flush=True)
    print(f"  reply: {reply[:110]!r}", flush=True)


async def main() -> None:
    commands = sys.argv[1:] or ["สร้างหนังสือใหม่ให้หน่อย"]

    async def fake_tts(text: str) -> tuple[bytes, str]:
        return (b"AUDIO", "audio/mpeg")

    pipe.synthesize_speech = fake_tts  # type: ignore[assignment]

    async with httpx.AsyncClient() as client:
        for cmd in commands:
            try:
                await _run_one(client, cmd)
            except Exception as exc:  # noqa: BLE001 — keep the batch going
                print(f"  ERROR: {type(exc).__name__}: {str(exc)[:150]}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
