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


async def main() -> None:
    transcript = sys.argv[1] if len(sys.argv) > 1 else "สร้างหนังสือใหม่ให้หน่อย"

    # No real TTS in a headless run.
    async def fake_tts(text: str) -> tuple[bytes, str]:
        return (b"AUDIO", "audio/mpeg")

    pipe.synthesize_speech = fake_tts  # type: ignore[assignment]

    async with httpx.AsyncClient() as client:
        await client.post(f"{HOST}/goto", json={"url": "/home"}, timeout=40)
        await client.post(f"{HOST}/reset", timeout=20)

        async def agent_runner(task: str) -> str:
            # The REAL loop (think() reads DEEPTUTOR_AGENT_* from env) on the live page.
            loop = InPageAgentLoop(HttpActuator(client), step_delay_s=0.4, max_steps=12)
            result = await loop.execute(task)
            return result.text

        print(f"\n>>> transcript: {transcript!r}", flush=True)
        reply = await pipe.run_text_turn(
            Emitter(),
            transcript,
            [],
            session_id="live",
            ui_context={"path": "/home", "summary": "หน้าหลัก"},
            agent_runner=agent_runner,
        )
        print(f">>> reply: {reply!r}", flush=True)

        info = (await client.get(f"{HOST}/probe", timeout=20)).json()
        print(f">>> final url: {info.get('url')}", flush=True)
        print(f">>> dialog open: {info.get('hasDialog')}", flush=True)
        body = info.get("bodyText", "")
        for kw in ("หนังสือ", "book", "New book", "สร้าง", "Create"):
            if kw in body:
                print(f">>> page mentions: {kw!r}")
                break


if __name__ == "__main__":
    asyncio.run(main())
