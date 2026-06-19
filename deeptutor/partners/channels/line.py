"""LINE Official Account channel via the Messaging API.

Scope (DM MVP):
- 1:1 text inbound/outbound
- HMAC-SHA256 webhook signature verification (``x-line-signature``)
- Reply API (free, single-use reply token, valid ~1 min) with Push API fallback
- sender allowlist (``allow_from``)
- ``displayName`` resolution via Get profile (cached in-memory)

Deferred to phase 2: rich content / images / audio / stickers / group chat.

Structural template: ``msteams.py`` (a tiny built-in ``ThreadingHTTPServer``
that bridges inbound POSTs onto the asyncio loop via
``run_coroutine_threadsafe``). Two simplifications vs. that template:

- **No ConversationRef persistence.** A LINE Push only needs the ``userId``,
  which equals ``chat_id`` for a 1:1 chat, so the only state we keep is an
  in-memory reply-token map. No disk store / file lock / pruning is required.
- **No JWT/OAuth token exchange.** LINE authenticates outbound calls with a
  static channel access token, so there is no token-fetch dance.
"""

from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from typing import Any

import httpx
from loguru import logger
from pydantic import Field

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.base import BaseChannel
from deeptutor.partners.config.schema import DeliveryOverrides

LINE_API_BASE = "https://api.line.me/v2/bot"
# LINE reply tokens are usable for ~1 minute (LINE notes the exact limit may
# change and to account for network delay), so we treat them as live only well
# inside that window and otherwise fall straight through to Push.
LINE_REPLY_TOKEN_TTL_S = 50.0
# Hard ceiling on the in-memory token / profile caches so a public OA
# (allow_from=["*"]) with many senders cannot grow them without bound.
LINE_MAX_CACHE_ENTRIES = 10_000


def _is_placeholder_token(token: str) -> bool:
    """True for LINE's all-zero reply token used by webhook verify / redelivery.

    The console "Verify" button and redelivered events can carry a dummy
    ``replyToken`` (all ``0``); it must never be stored as a live token.
    """
    return bool(token) and set(token) == {"0"}


def _bounded_set(
    cache: OrderedDict[str, Any], key: str, value: Any, max_entries: int | None = None
) -> None:
    """Insert into an LRU-bounded cache, evicting the oldest entry over the cap.

    ``max_entries`` defaults to the module-level ``LINE_MAX_CACHE_ENTRIES`` read
    at call time (not bound as a default arg, so it stays overridable).
    """
    if max_entries is None:
        max_entries = LINE_MAX_CACHE_ENTRIES
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > max_entries:
        cache.popitem(last=False)


def _log_webhook_task_result(future: Any) -> None:
    """Done-callback: log a top-level webhook-task failure (ack is already sent)."""
    try:
        exc = future.exception()
    except Exception:  # pragma: no cover - cancelled / not-done guard
        return
    if exc is not None:
        logger.warning("LINE webhook task failed: {}", exc)


class LineConfig(DeliveryOverrides):
    """LINE channel configuration.

    ``channel_secret`` and ``channel_access_token`` are masked automatically by
    the partner manager's secret-field detection (names contain "secret"/"token").
    """

    enabled: bool = False
    channel_secret: str = ""
    channel_access_token: str = ""
    host: str = "0.0.0.0"
    # Default off msteams' 3978 so both webhook channels can run side by side.
    port: int = 3979
    path: str = "/line/webhook"
    allow_from: list[str] = Field(default_factory=list)
    reply_token_ttl_s: float = Field(default=LINE_REPLY_TOKEN_TTL_S, ge=0)
    # LINE cannot edit a message in place (no streaming) so progress/tool-hint
    # narration adds no UX value, and each one is a separate OutboundMessage —
    # only the first can use the free Reply, the rest become quota-counted Push.
    # Default both off; a user can still opt back in per channel.
    send_progress: bool = False
    send_tool_hints: bool = False


class LineChannel(BaseChannel):
    """LINE Official Account channel (DM-first MVP)."""

    name = "line"
    display_name = "LINE"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return LineConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = LineConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: LineConfig = config
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._http: httpx.AsyncClient | None = None
        # userId -> (replyToken, issued_at). In-memory: a Push fallback only
        # needs the userId, so nothing here needs to survive a restart. Bounded
        # (LINE_MAX_CACHE_ENTRIES) so a public OA cannot grow it without limit.
        self._reply_tokens: OrderedDict[str, tuple[str, float]] = OrderedDict()
        # userId -> displayName, resolved lazily via Get profile. Also bounded.
        self._profile_cache: OrderedDict[str, str] = OrderedDict()

    async def start(self) -> None:
        """Start the LINE webhook listener."""
        if not self.config.channel_secret or not self.config.channel_access_token:
            logger.error("LINE channel_secret/channel_access_token not configured")
            return

        self._loop = asyncio.get_running_loop()
        self._http = httpx.AsyncClient(timeout=30.0)
        self._running = True

        channel = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                if self.path != channel.config.path:
                    self.send_response(404)
                    self.end_headers()
                    return

                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    raw = self.rfile.read(length) if length > 0 else b""
                except Exception as e:
                    logger.warning("LINE invalid request body: {}", e)
                    self.send_response(400)
                    self.end_headers()
                    return

                # Verify the signature against the RAW body before parsing JSON.
                signature = self.headers.get("x-line-signature", "")
                if not channel._verify_signature(raw, signature):
                    logger.warning("LINE signature verification failed")
                    self.send_response(401)
                    self.end_headers()
                    return

                try:
                    payload = json.loads(raw.decode("utf-8")) if raw else {}
                except Exception as e:
                    logger.warning("LINE invalid JSON body: {}", e)
                    self.send_response(400)
                    self.end_headers()
                    return

                # Schedule processing fire-and-forget and ack immediately: do
                # NOT block on the result. _handle_webhook may call Get profile
                # for a new user, and a slow/failing ack makes LINE disable the
                # webhook. Per-event errors are already swallowed inside
                # _handle_webhook; a done-callback logs any top-level failure.
                future = asyncio.run_coroutine_threadsafe(
                    channel._handle_webhook(payload),
                    channel._loop,
                )
                future.add_done_callback(_log_webhook_task_result)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, format: str, *args: Any) -> None:
                return

        self._server = ThreadingHTTPServer((self.config.host, self.config.port), Handler)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            name="deeptutor-line",
            daemon=True,
        )
        self._server_thread.start()

        logger.info(
            "LINE webhook listening on http://{}:{}{}",
            self.config.host,
            self.config.port,
            self.config.path,
        )

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the channel and clean up resources."""
        self._running = False
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=2)
        self._server_thread = None
        if self._http:
            await self._http.aclose()
            self._http = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a plain-text message, Reply-first with a Push fallback.

        Raises on delivery failure so the channel manager's retry policy applies.
        The reply token is popped on the first attempt: it is single-use, so any
        manager retry must fall through to Push rather than reuse a dead token.
        """
        if not self._http:
            raise RuntimeError("LINE HTTP client not initialized")

        chat_id = str(msg.chat_id)
        text = msg.content or " "  # LINE rejects empty text messages
        messages = [{"type": "text", "text": text}]
        headers = {
            "Authorization": f"Bearer {self.config.channel_access_token}",
            "Content-Type": "application/json",
        }

        token_entry = self._reply_tokens.pop(chat_id, None)
        if token_entry is not None:
            reply_token, issued_at = token_entry
            if time.time() - issued_at <= self.config.reply_token_ttl_s:
                try:
                    resp = await self._http.post(
                        f"{LINE_API_BASE}/message/reply",
                        headers=headers,
                        json={"replyToken": reply_token, "messages": messages},
                    )
                    resp.raise_for_status()
                    logger.info("LINE reply sent to {}", chat_id)
                    return
                except Exception as e:
                    logger.warning("LINE reply failed for {}, falling back to push: {}", chat_id, e)

        # Push fallback: no token / expired / reply failed. Counts against the
        # monthly quota, hence Reply-first above.
        try:
            resp = await self._http.post(
                f"{LINE_API_BASE}/message/push",
                headers=headers,
                json={"to": chat_id, "messages": messages},
            )
            resp.raise_for_status()
            logger.info("LINE push sent to {}", chat_id)
        except Exception:
            logger.exception("LINE push failed for {}", chat_id)
            raise

    def _verify_signature(self, raw: bytes, signature: str) -> bool:
        """Verify ``x-line-signature`` = base64(HMAC-SHA256(channel_secret, raw))."""
        if not signature:
            return False
        digest = hmac.new(self.config.channel_secret.encode("utf-8"), raw, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode("utf-8")
        return hmac.compare_digest(expected, signature)

    async def _handle_webhook(self, payload: dict[str, Any]) -> None:
        """Dispatch each event in a webhook batch (one POST may carry many)."""
        for event in payload.get("events") or []:
            try:
                await self._handle_event(event)
            except Exception:
                logger.exception("LINE event handling failed")

    async def _handle_event(self, event: dict[str, Any]) -> None:
        """Handle a single inbound LINE event (text messages only for the MVP)."""
        if event.get("type") != "message":
            return
        message = event.get("message") or {}
        if message.get("type") != "text":
            return

        source = event.get("source") or {}
        user_id = str(source.get("userId") or "").strip()
        text = str(message.get("text") or "").strip()
        if not user_id or not text:
            return

        # Pre-gate before doing any network work or storing a token: an
        # unauthorized sender must not be able to burn the Get-profile rate
        # limit or fill the token cache. The base _handle_message re-checks
        # is_allowed as the single source of truth.
        if not self.is_allowed(user_id):
            logger.warning("LINE: access denied for {}, ignoring", user_id)
            return

        reply_token = str(event.get("replyToken") or "").strip()
        if reply_token and not _is_placeholder_token(reply_token):
            self._store_reply_token(user_id, reply_token)

        display_name = await self._resolve_display_name(user_id)
        await self._handle_message(
            sender_id=user_id,
            chat_id=user_id,
            content=text,
            metadata={"line": {"user_id": user_id, "display_name": display_name}},
        )

    async def _resolve_display_name(self, user_id: str) -> str:
        """Resolve a human display name via Get profile; cache and fall back to userId.

        The LINE ``userId`` is an opaque per-OA hash, so we call Get profile on
        first sighting to surface a real name in the session list. Only
        successful lookups are cached, so a transient failure self-heals on the
        next message (a permanently unavailable profile — e.g. a PC-only,
        non-consented user — costs one GET per message, which is rare).
        """
        cached = self._profile_cache.get(user_id)
        if cached is not None:
            return cached
        if not self._http:
            return user_id
        try:
            resp = await self._http.get(
                f"{LINE_API_BASE}/profile/{user_id}",
                headers={"Authorization": f"Bearer {self.config.channel_access_token}"},
            )
            resp.raise_for_status()
            name = str(resp.json().get("displayName") or "").strip() or user_id
            _bounded_set(self._profile_cache, user_id, name)
            return name
        except Exception as e:
            logger.debug("LINE get-profile failed for {}: {}", user_id, e)
            return user_id

    def _store_reply_token(self, user_id: str, token: str) -> None:
        """Store a reply token in the bounded cache, pruning expired ones first.

        Pruning is opportunistic (on insert): a turn that yields no outbound
        message never pops its token, so without this an idle/abusive public OA
        would leak dead tokens until the LRU cap evicts them.
        """
        now = time.time()
        ttl = self.config.reply_token_ttl_s
        expired = [uid for uid, (_, ts) in self._reply_tokens.items() if now - ts > ttl]
        for uid in expired:
            self._reply_tokens.pop(uid, None)
        _bounded_set(self._reply_tokens, user_id, (token, now))
