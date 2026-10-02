"""Replay a turn over the backend WebSocket and print every event with a timestamp."""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, "/app")
import websockets

from deeptutor.services.auth import _load_users, create_token  # type: ignore

MODE = sys.argv[1] if len(sys.argv) > 1 else "chat"
users = _load_users()
admin = next(u for u, r in users.items() if (r or {}).get("role") == "admin")
token = create_token(admin, "admin")
URL = "ws://127.0.0.1:8001/ws"


def turn(content, **extra):
    base = {
        "type": "start_turn",
        "protocol_version": "2.0",
        "content": content,
        "capability": "chat",
        "session_id": None,
        "tools": None,
        "knowledge_bases": [],
        "language": "th",
        "config": {},
        "attachments": [],
        "notebook_references": [],
        "history_references": [],
        "partner_group_references": [],
        "question_notebook_references": [],
        "book_references": [],
        "reading_references": [],
        "memory_references": [],
        "skills": [],
        "persona": None,
        "llm_selection": None,
        "workspace_mode": None,
        "mastery_path_id": None,
        "mastery_session_mode": None,
        "mastery_path_lease_managed": False,
        "mastery_answer": None,
        "mastery_skip": None,
        "reading_material_id": None,
        "reading_material_revision": None,
        "reading_workspace_id": None,
        "reading_viewport": None,
        "timed_media_id": None,
        "timed_media_viewport": None,
        "course_id": None,
        "persist_user_message": True,
        "regenerate": False,
        "regenerated_from_message_id": None,
        "superseded_turn_id": None,
        "followup_question_context": None,
        "selection_tutor_context": None,
        "subagent_consult_budget": None,
        "auto_route": None,
    }
    base.update(extra)
    return base


async def main():
    t0 = time.time()
    async with websockets.connect(
        URL, additional_headers={"Cookie": f"dt_token={token}"}, max_size=None
    ) as ws:
        if MODE == "chat":
            msg = turn("ตอบสั้น ๆ: สวัสดี")
        else:
            msg = turn(
                "iPhone Duo ที่เปิดตัวในงานนี้ต่างจากรุ่นก่อนอย่างไร ตอบสั้น ๆ",
                reading_material_id="00533139eb8c63ed",
                reading_material_revision=1,
                reading_workspace_id="00533139eb8c63ed",
                timed_media_id="00533139eb8c63ed",
                timed_media_viewport={"time_seconds": 121.0},
            )
        await ws.send(json.dumps(msg))
        last = None
        try:
            while True:
                raw = await asyncio.wait_for(
                    ws.recv(), timeout=float(os.environ.get("PROBE_TIMEOUT", "60"))
                )
                ev = json.loads(raw)
                et = ev.get("type") or ev.get("event") or "?"
                summary = {
                    k: (str(v)[:80])
                    for k, v in ev.items()
                    if k
                    in (
                        "type",
                        "event",
                        "error",
                        "error_code",
                        "message",
                        "stage",
                        "status",
                        "name",
                        "tool",
                        "capability",
                        "delta",
                        "content",
                    )
                    and v not in (None, "")
                }
                print(
                    f"{time.time() - t0:6.2f}s  {et:24s} {json.dumps(summary, ensure_ascii=False)[:200]}"
                )
                last = et
                if et in (
                    "turn_completed",
                    "turn_failed",
                    "turn_cancelled",
                    "error",
                    "done",
                    "turn_done",
                ):
                    break
        except asyncio.TimeoutError:
            print(
                f"{time.time() - t0:6.2f}s  --- no event for {os.environ.get('PROBE_TIMEOUT', '60')}s (last: {last}) ---"
            )


asyncio.run(main())
