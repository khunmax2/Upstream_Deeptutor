"""End-to-end turn check over the real public URL.

Runs INSIDE the deeptutor container (it needs `jose` to mint a session and
`websockets` to speak the turn protocol), but connects out to the public
https/wss origin so the whole path is exercised:

    wss://<host>/deepwitya2/ws
      -> nginx  (location /deepwitya2, Upgrade headers)
      -> Next.js (strips basePath, proxy.ts rewrites /ws to the backend)
      -> FastAPI unified_ws

That is exactly the path the browser takes, so a pass here means the basePath
work holds for the chat transport, not just for plain HTTP GETs.

Usage:  docker exec deeptutor2 python3 /app/deploy/e2e_turn_check.py <origin> <username>
"""

from __future__ import annotations

import asyncio
import json
import ssl
import sys

PROTOCOL_VERSION = "2.0"
# Verified against the live stream: a turn ends with "done".
TERMINAL = {"done", "error", "protocol_error", "turn_failed"}


async def main(origin: str, username: str) -> int:
    from deeptutor.services.auth import create_token

    token = create_token(username, "admin")
    ws_origin = origin.replace("https://", "wss://").replace("http://", "ws://")
    url = f"{ws_origin}/ws"

    import websockets

    ctx = ssl.create_default_context() if ws_origin.startswith("wss") else None

    print(f"→ connecting {url}")
    async with websockets.connect(
        url,
        additional_headers={"Cookie": f"dt_token={token}"},
        ssl=ctx,
        open_timeout=30,
    ) as ws:
        print("✓ WebSocket upgraded (101) — nginx + basePath + proxy rewrite all OK")

        await ws.send(
            json.dumps(
                {
                    "type": "message",
                    "protocol_version": PROTOCOL_VERSION,
                    "content": "ตอบสั้น ๆ ว่า 2+2 เท่ากับเท่าไร",
                    "capability": "chat",
                }
            )
        )
        print("→ turn sent, waiting for stream…")

        text = []
        seen = []
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=180)
            except asyncio.TimeoutError:
                print("✗ TIMEOUT — no terminal event within 180s")
                print("  events seen:", seen)
                return 1

            event = json.loads(raw)
            etype = event.get("type", "?")
            if etype not in seen:
                seen.append(etype)

            if etype == "content":
                for key in ("delta", "content", "text"):
                    chunk = event.get(key)
                    if isinstance(chunk, str) and chunk:
                        text.append(chunk)
                        break

            if etype in TERMINAL:
                print(f"\n— terminal event: {etype}")
                if etype in {"error", "protocol_error", "turn_failed"}:
                    print("✗ FAILED:", json.dumps(event, ensure_ascii=False)[:600])
                    return 1
                answer = "".join(text).strip()
                print("✓ event types seen:", seen)
                print("✓ answer:", (answer[:300] or "<ว่าง>"))
                return 0 if answer else 1


if __name__ == "__main__":
    origin = sys.argv[1] if len(sys.argv) > 1 else "https://203.185.144.41/deepwitya2"
    username = sys.argv[2] if len(sys.argv) > 2 else "admin@example.com"
    raise SystemExit(asyncio.run(main(origin, username)))
