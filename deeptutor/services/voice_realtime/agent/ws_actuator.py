"""WsPageActuator — the server end of the browser's page-actuator bridge.

Implements the loop's :class:`~.types.Actuator` protocol over the voice
WebSocket: ``observe()`` asks the page for its serialized state, ``act()``
executes one action, both as request/response with correlation ids and
timeouts (a silent client degrades the run honestly instead of hanging a
phone line).

``agent_state`` arrives CHUNKED (``agent_state_chunk`` frames with seq/total)
because control frames are size-capped server-side — the browser JSON-encodes
the payload first and splits it; this class reassembles by (id, seq) and
parses once. Frame protocol lives in ``web/lib/page-actuator/wsBridge.ts``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
import logging
from typing import Any
import uuid

from deeptutor.services.voice_realtime.agent.types import ActResult, BrowserState

logger = logging.getLogger(__name__)

# A full-page scan + chunked transfer on localhost is ~instant; these bounds
# only exist so a dead tab can't freeze the loop.
OBSERVE_TIMEOUT_S = 8.0
# Clicks/inputs include settle sleeps browser-side (~0.5s) plus page reactions.
ACT_TIMEOUT_S = 20.0

SendJson = Callable[[dict[str, Any]], Awaitable[None]]


class ActuatorTimeout(RuntimeError):
    """The page never answered — surfaced to the run as an honest failure."""


class WsPageActuator:
    """One per agent task run, bound to one connection's ``send_json``."""

    def __init__(
        self,
        send_json: SendJson,
        *,
        observe_timeout_s: float = OBSERVE_TIMEOUT_S,
        act_timeout_s: float = ACT_TIMEOUT_S,
    ) -> None:
        self._send = send_json
        self._observe_timeout_s = observe_timeout_s
        self._act_timeout_s = act_timeout_s
        # request id → future; chunks buffer per observe id
        self._state_futures: dict[str, asyncio.Future[BrowserState]] = {}
        self._chunks: dict[str, dict[int, str]] = {}
        self._chunk_totals: dict[str, int] = {}
        self._act_futures: dict[str, asyncio.Future[ActResult]] = {}

    async def start_run(self) -> None:
        """Mask up + fresh `*[new]` baseline on the browser side."""
        await self._send({"type": "agent_run", "running": True})

    async def end_run(self) -> None:
        await self._send({"type": "agent_run", "running": False})

    async def observe(self) -> BrowserState:
        request_id = uuid.uuid4().hex
        future: asyncio.Future[BrowserState] = asyncio.get_running_loop().create_future()
        self._state_futures[request_id] = future
        try:
            await self._send({"type": "agent_observe", "id": request_id})
            return await asyncio.wait_for(future, timeout=self._observe_timeout_s)
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise ActuatorTimeout("The page did not answer an observe request.") from exc
        finally:
            self._state_futures.pop(request_id, None)
            self._chunks.pop(request_id, None)
            self._chunk_totals.pop(request_id, None)

    async def act(self, name: str, args: dict[str, Any]) -> ActResult:
        request_id = uuid.uuid4().hex
        future: asyncio.Future[ActResult] = asyncio.get_running_loop().create_future()
        self._act_futures[request_id] = future
        try:
            await self._send({"type": "agent_act", "id": request_id, "action": name, "args": args})
            return await asyncio.wait_for(future, timeout=self._act_timeout_s)
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise ActuatorTimeout(f"The page did not answer the {name} action.") from exc
        finally:
            self._act_futures.pop(request_id, None)

    def handle_frame(self, msg: dict[str, Any]) -> bool:
        """Route a client frame here; True when it was ours."""
        kind = msg.get("type")
        if kind == "agent_state_chunk":
            self._on_state_chunk(msg)
            return True
        if kind == "agent_acted":
            future = self._act_futures.get(str(msg.get("id")))
            if future is not None and not future.done():
                future.set_result(
                    ActResult(ok=bool(msg.get("ok")), message=str(msg.get("message") or ""))
                )
            return True
        return False

    def _on_state_chunk(self, msg: dict[str, Any]) -> None:
        request_id = str(msg.get("id"))
        future = self._state_futures.get(request_id)
        if future is None or future.done():
            return  # stale (timed-out or aborted request) — drop silently

        try:
            seq = int(msg.get("seq", 0))
            total = int(msg.get("total", 1))
        except (TypeError, ValueError):
            return
        parts = self._chunks.setdefault(request_id, {})
        parts[seq] = str(msg.get("part") or "")
        self._chunk_totals[request_id] = total

        if len(parts) < total:
            return
        payload = "".join(parts[i] for i in sorted(parts))
        try:
            data = json.loads(payload)
            state = BrowserState(
                url=str(data.get("url") or ""),
                title=str(data.get("title") or ""),
                header=str(data.get("header") or ""),
                content=str(data.get("content") or ""),
                footer=str(data.get("footer") or ""),
            )
        except (json.JSONDecodeError, AttributeError) as exc:
            future.set_exception(RuntimeError(f"Malformed agent_state payload: {exc}"))
            return
        future.set_result(state)
