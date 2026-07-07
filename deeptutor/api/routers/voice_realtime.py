"""Realtime voice WebSocket endpoint — ``/api/v1/voice/ws``.

One WebSocket connection is one live "call". The browser captures the mic, does
energy-VAD endpointing, and sends one finished utterance per turn as a **binary**
frame; the server runs STT → ``ChatOrchestrator`` → per-sentence TTS and streams
audio back. **Text** frames are JSON control messages.

Client → server:
  * binary frame                     → one utterance (e.g. a webm blob)
  * ``{"type": "user_text", "text"}`` → client-recognised utterance (browser STT
    such as Web Speech); skips server STT, same turn from the brain onward
  * ``{"type": "barge"}``            → barge-in: cancel the turn now (stop audio)
  * ``{"type": "ui_manifest", "manifest": {...}}`` → declare the steerable UI
    (pages/actions whitelist) so the model may drive it via ``ui_navigate``;
    the server answers ``{"type": "ui_manifest_ok", "targets": n}``

Server → client (all JSON except the audio payload frames):
  * ``{"type": "transcript", "text": …}``                 recognised user speech
  * ``{"type": "stage", "stage": …, "ms": …}``            per-stage latency
  * ``{"type": "audio", "seq": n, "text": …}`` + a following BINARY mp3 frame
  * ``{"type": "assistant_text", "text": …}``             full reply text
  * ``{"type": "done", "total_ms": …, "first_audio_ms": …}``
  * ``{"type": "ui_action", "action": "navigate", "target": …}``  execute on page
  * ``{"type": "error", "message": …}``

Like ``unified_ws`` this endpoint does its own ``ws_require_auth`` (so it is
mounted without the HTTP auth dependency) and runs in the authenticated user's
scope — rag / skills / memory resolve to that user's workspace.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from deeptutor.services.voice_realtime.session import VoiceSession
from deeptutor.services.voice_realtime.ui_control import (
    MAX_MANIFEST_BYTES,
    install_ui_control,
    sanitize_manifest,
)
from deeptutor.services.voice_realtime.vad import is_utterance_too_large

logger = logging.getLogger(__name__)

router = APIRouter()

# Mount the voice-UI tool + capability once per process (runtime registration —
# no upstream registry files are edited; inactive unless a manifest arrives).
install_ui_control()


@router.websocket("/ws")
async def voice_websocket(ws: WebSocket) -> None:
    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth
    from deeptutor.multi_user.context import reset_current_user

    user_token = await ws_require_auth(ws)
    if user_token is ws_auth_failed:
        return

    await ws.accept()
    session = VoiceSession(ws)
    await session.greet()  # answer the phone: "สวัสดีครับ มีอะไรให้ผมช่วยไหมครับ"

    async def safe_send(data: dict[str, Any]) -> None:
        try:
            await ws.send_text(json.dumps(data, ensure_ascii=False, default=str))
        except Exception:  # noqa: BLE001 — a dead socket just ends the call
            logger.debug("Voice WS send failed", exc_info=True)

    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break

            audio = message.get("bytes")
            if audio is not None:
                if is_utterance_too_large(len(audio)):
                    await safe_send({"type": "error", "message": "เสียงยาวเกินไป"})
                    continue
                await session.handle_utterance(audio)
                continue

            text = message.get("text")
            if text:
                await _handle_control(text, session, safe_send)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.error("Voice WS error: %s", exc, exc_info=True)
        await safe_send({"type": "error", "message": str(exc)})
    finally:
        await session.aclose()
        if user_token is not None:
            reset_current_user(user_token)


async def _handle_control(raw: str, session: VoiceSession, safe_send: Any) -> None:
    """Dispatch a JSON control frame (``barge`` / ``user_text`` / ``ui_manifest``)."""
    if len(raw) > MAX_MANIFEST_BYTES:
        await safe_send({"type": "error", "message": "Control frame too large."})
        return
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        await safe_send({"type": "error", "message": "Invalid JSON."})
        return
    kind = msg.get("type")
    if kind == "barge":
        await session.cancel_current_turn()
    elif kind == "user_text":
        await session.handle_text(str(msg.get("text") or ""))
    elif kind == "ui_manifest":
        manifest = sanitize_manifest(msg.get("manifest"))
        session.ui_manifest = manifest
        targets = sum(len(manifest.get(k, [])) for k in ("pages", "actions")) if manifest else 0
        await safe_send({"type": "ui_manifest_ok", "targets": targets})


__all__ = ["router"]
