"""Live end-to-end for the form/commit policy (grounding issue 03).

``run_voice_live.py`` builds the loop BARE, so ``ask_user``/``pre_act`` are
absent from the action catalog — it cannot exercise the ask-once / stop-before-
expensive-commit policy at all (the model's ``ask_user`` is rejected as an
Unknown action and the run crashes). This variant wires the loop the way the
REAL voice pipeline (``agent/voice_bridge.py``) does:

* ``ask_user`` → a SCRIPTED answer (records the question, returns a canned
  learning intent) so the flow can proceed past the one un-inferable field.
* ``pre_act`` → a ``DangerGate`` whose confirm callback DENIES every request and
  records it. Denying is the safety valve: the expensive "ยืนยันข้อเสนอและสร้าง
  โครงร่าง / build spine" commit (full book compilation, large LLM spend) is
  NEVER actually clicked, so the test cannot burn a book-compile — while still
  proving the gate FIRES on it (issue 03 + the new ``is_expensive_commit`` rung).

New file under eval/ (fork policy §3); nothing shared is modified.

Prereqs identical to ``run_voice_live.py``: app + ``browser_host`` up, and a
full-tier ``DEEPTUTOR_AGENT_MODEL`` loaded (see eval/README.md).
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import httpx

HOST = "http://127.0.0.1:8899"

from deeptutor.services.voice_realtime import pipeline as pipe  # noqa: E402
from deeptutor.services.voice_realtime.agent.danger import DangerGate  # noqa: E402
from deeptutor.services.voice_realtime.agent.loop import InPageAgentLoop  # noqa: E402
from deeptutor.services.voice_realtime.agent.types import ActResult, BrowserState  # noqa: E402

# The one un-inferable required field the policy is allowed to ask for.
SCRIPTED_INTENT = "อยากได้หนังสือแคลคูลัสเบื้องต้นสำหรับผู้เริ่มต้น เน้นเข้าใจง่าย"


class RecordingActuator:
    """HttpActuator that also records every act for the trace."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._c = client
        self.acts: list[tuple[str, dict[str, Any]]] = []

    async def observe(self) -> BrowserState:
        d = (await self._c.get(f"{HOST}/observe", timeout=30)).json()
        return BrowserState(
            url=d.get("url", ""),
            title=d.get("title", ""),
            header=d.get("header", ""),
            content=d.get("content", ""),
            footer=d.get("footer", ""),
        )

    async def act(self, name: str, args: dict[str, Any]) -> ActResult:
        self.acts.append((name, dict(args)))
        d = (
            await self._c.post(f"{HOST}/act", json={"name": name, "args": args}, timeout=40)
        ).json()
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

    actuator = RecordingActuator(client)
    ask_questions: list[str] = []
    confirm_questions: list[str] = []

    async def scripted_ask(question: str) -> str:
        ask_questions.append(question)
        return SCRIPTED_INTENT

    async def deny_confirm(question: str) -> bool:
        # SAFETY: always decline, so the expensive commit is never clicked.
        confirm_questions.append(question)
        return False

    async def agent_runner(task: str) -> str:
        loop = InPageAgentLoop(
            actuator,
            ask_user=scripted_ask,
            pre_act=DangerGate(deny_confirm),
            step_delay_s=0.4,
            max_steps=18,
        )
        return (await loop.execute(task)).text

    print(f"\n=== {transcript!r}", flush=True)
    reply = await pipe.run_text_turn(
        Emitter(),
        transcript,
        [],
        session_id="live",
        ui_context={"path": "/home", "summary": "หน้าหลัก"},
        agent_runner=agent_runner,
    )
    after = (await client.get(f"{HOST}/probe", timeout=20)).json()

    print(f"  landed: {after.get('url', '?')}", flush=True)
    print(f"  acts ({len(actuator.acts)}):", flush=True)
    for name, args in actuator.acts:
        print(f"    - {name} {args}", flush=True)
    print(f"  ask_user asked {len(ask_questions)}x:", flush=True)
    for q in ask_questions:
        print(f"    ? {q}", flush=True)
    print(f"  danger-gate confirms {len(confirm_questions)}x:", flush=True)
    for q in confirm_questions:
        print(f"    ! {q}", flush=True)
    gate_hit_commit = any("ทรัพยากร" in q for q in confirm_questions)
    print(f"  >>> expensive-commit gate fired: {gate_hit_commit}", flush=True)
    print(f"  reply: {reply[:160]!r}", flush=True)


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
                print(f"  ERROR: {type(exc).__name__}: {str(exc)[:200]}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
