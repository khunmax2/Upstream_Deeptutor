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
  * ``{"type": "ui_context", "context": {"path", "page", "summary"}}`` →
    current-screen snapshot (what the page shows *now*); refreshed by the
    client per turn so "หน้านี้มีอะไรบ้าง" is answered from the real screen and
    "ตอนนี้อยู่หน้าไหน" is answered deterministically from ``page``
  * ``{"type": "ui_action_result", "result": {"target", "field", "ok",
    "detail"}}`` → post-action verify verdict: after executing a
    ``ui_action`` the client polls the DOM and reports whether the action
    actually landed (value stuck / route changed / caret placed)
  * ``{"type": "ui_inventory", "inventory": [{"i", "tag", "label",
    "hint"}]}`` → reply to a server ``ui_scan``: the full indexed list of
    interactive elements (deep rung — an LLM picks the index on a
    fast-path miss)

Server → client (all JSON except the audio payload frames):
  * ``{"type": "transcript", "text": …}``                 recognised user speech
  * ``{"type": "stage", "stage": …, "ms": …}``            per-stage latency
  * ``{"type": "audio", "seq": n, "text": …}`` + a following BINARY mp3 frame
  * ``{"type": "assistant_text", "text": …}``             full reply text
  * ``{"type": "done", "total_ms": …, "first_audio_ms": …}``
  * ``{"type": "ui_action", "action": "navigate", "target": …}``  execute on page
  * ``{"type": "ui_scan"}``  request the indexed element inventory (deep rung)
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
    sanitize_action_result,
    sanitize_manifest,
    sanitize_ui_context,
)
from deeptutor.services.voice_realtime.ui_graph import take_pending_step
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
    elif kind == "ui_context":
        # Silent refresh (no ack): the client streams this before every turn.
        session.ui_context = sanitize_ui_context(msg.get("context"))
    elif kind == "ui_action_result":
        # Post-action verify verdict (silent, client-initiated after each
        # executed ui_action). Remembered on nav_state so the next rung /
        # the future agentic loop can check the previous step landed;
        # failures are logged — that's the honest record of a spoken
        # "ได้เลยครับ" whose action did NOT stick.
        result = sanitize_action_result(msg.get("result"))
        if result is not None:
            session.nav_state["last_action_result"] = result
            if not result.get("ok"):
                logger.warning("voice ui_action verify FAILED: %s", result)
            # Website Graph: a parked cross-page step fires the moment the
            # client CONFIRMS the planned page landed — verify-gated, once,
            # TTL-bounded (ui_graph.take_pending_step owns those rules).
            step = take_pending_step(session.nav_state, result)
            if step is not None:
                logger.info("voice graph step dispatched: %s", step.get("argument"))
                await safe_send(step)
    elif kind == "ui_inventory":
        # Deep-rung reply (client answers a server ui_scan with its indexed
        # element inventory). Silent; delivered to the turn awaiting it.
        session.resolve_ui_inventory(msg.get("inventory"))


__all__ = ["router"]
