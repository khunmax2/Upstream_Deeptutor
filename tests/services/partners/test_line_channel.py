"""Unit tests for the LINE channel implementation."""

from __future__ import annotations

import base64
from collections import OrderedDict
import hashlib
import hmac
import inspect
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels import line as line_mod
from deeptutor.partners.channels.line import LineChannel, LineConfig, _bounded_set

SECRET = "test-channel-secret"
TOKEN = "test-access-token"


def _make_channel(**overrides) -> LineChannel:
    defaults = {
        "enabled": True,
        "channel_secret": SECRET,
        "channel_access_token": TOKEN,
        "allow_from": ["*"],
    }
    defaults.update(overrides)
    config = LineConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return LineChannel(config, bus)


def _sign(raw: bytes, secret: str = SECRET) -> str:
    return base64.b64encode(hmac.new(secret.encode(), raw, hashlib.sha256).digest()).decode()


def _text_event(user_id: str = "U123", text: str = "Hello", reply_token: str = "rt-1") -> dict:
    return {
        "type": "message",
        "replyToken": reply_token,
        "source": {"type": "user", "userId": user_id},
        "message": {"type": "text", "text": text},
    }


def _ok_response() -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    return resp


class TestLineConfig:
    def test_default_values(self):
        cfg = LineConfig()
        assert cfg.enabled is False
        assert cfg.channel_secret == ""
        assert cfg.channel_access_token == ""
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 3979
        assert cfg.path == "/line/webhook"
        assert cfg.allow_from == []
        assert cfg.reply_token_ttl_s == 50.0
        # LINE overrides DeliveryOverrides: no in-place edit + Push counts quota,
        # so progress/tool-hint narration is off by default.
        assert cfg.send_progress is False
        assert cfg.send_tool_hints is False

    def test_delivery_flags_can_be_re_enabled(self):
        cfg = LineConfig(send_progress=True, send_tool_hints=True)
        assert cfg.send_progress is True
        assert cfg.send_tool_hints is True

    def test_camel_case_alias(self):
        cfg = LineConfig(channel_secret="s", channel_access_token="t")
        d = cfg.model_dump(by_alias=True)
        assert "channelSecret" in d
        assert "channelAccessToken" in d
        assert "allowFrom" in d
        assert "replyTokenTtlS" in d

    def test_from_camel_case_dict(self):
        cfg = LineConfig.model_validate(
            {
                "enabled": True,
                "channelSecret": "s1",
                "channelAccessToken": "t1",
                "allowFrom": ["*"],
                "port": 4000,
            }
        )
        assert cfg.channel_secret == "s1"
        assert cfg.channel_access_token == "t1"
        assert cfg.allow_from == ["*"]
        assert cfg.port == 4000


class TestDefaultConfig:
    def test_default_config_returns_dict(self):
        cfg = LineChannel.default_config()
        assert isinstance(cfg, dict)
        assert cfg["enabled"] is False
        assert "channelSecret" in cfg
        assert "channelAccessToken" in cfg


class TestIsAllowed:
    def test_wildcard_allows_all(self):
        ch = _make_channel(allow_from=["*"])
        assert ch.is_allowed("U123") is True

    def test_empty_list_denies_all(self):
        ch = _make_channel(allow_from=[])
        assert ch.is_allowed("U123") is False

    def test_sender_id_match(self):
        ch = _make_channel(allow_from=["U123"])
        assert ch.is_allowed("U123") is True
        assert ch.is_allowed("U999") is False


class TestVerifySignature:
    def test_valid_signature_passes(self):
        ch = _make_channel()
        raw = b'{"events":[]}'
        assert ch._verify_signature(raw, _sign(raw)) is True

    def test_tampered_body_rejected(self):
        ch = _make_channel()
        raw = b'{"events":[]}'
        sig = _sign(raw)
        assert ch._verify_signature(b'{"events":[1]}', sig) is False

    def test_missing_signature_rejected(self):
        ch = _make_channel()
        assert ch._verify_signature(b"{}", "") is False

    def test_wrong_secret_rejected(self):
        ch = _make_channel()
        raw = b'{"events":[]}'
        assert ch._verify_signature(raw, _sign(raw, "other-secret")) is False


class TestHandleEvent:
    @pytest.mark.asyncio
    async def test_text_event_dispatched(self):
        ch = _make_channel()
        await ch._handle_event(_text_event())

        ch.bus.publish_inbound.assert_awaited_once()
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.channel == "line"
        assert msg.sender_id == "U123"
        assert msg.chat_id == "U123"
        assert msg.content == "Hello"
        assert msg.metadata["line"]["user_id"] == "U123"
        # No HTTP client in unit context → displayName falls back to the userId.
        assert msg.metadata["line"]["display_name"] == "U123"
        assert ch._reply_tokens["U123"][0] == "rt-1"

    @pytest.mark.asyncio
    async def test_non_message_event_ignored(self):
        ch = _make_channel()
        await ch._handle_event({"type": "follow", "source": {"userId": "U123"}})
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_text_message_ignored(self):
        ch = _make_channel()
        await ch._handle_event(
            {
                "type": "message",
                "replyToken": "rt-1",
                "source": {"userId": "U123"},
                "message": {"type": "image", "id": "1"},
            }
        )
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_user_id_ignored(self):
        ch = _make_channel()
        await ch._handle_event(_text_event(user_id=""))
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_text_ignored(self):
        ch = _make_channel()
        await ch._handle_event(_text_event(text="   "))
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_placeholder_reply_token_not_stored(self):
        ch = _make_channel()
        await ch._handle_event(_text_event(reply_token="0" * 32))
        ch.bus.publish_inbound.assert_awaited_once()
        assert "U123" not in ch._reply_tokens

    @pytest.mark.asyncio
    async def test_denied_sender_pre_gated_no_network_no_token(self):
        # FIX 2: an unauthorized sender must be dropped before any Get-profile
        # call or token storage — not just before the bus publish.
        ch = _make_channel(allow_from=[])
        ch._http = AsyncMock()
        await ch._handle_event(_text_event())
        ch.bus.publish_inbound.assert_not_awaited()
        ch._http.get.assert_not_awaited()  # no Get profile
        assert "U123" not in ch._reply_tokens  # no token stored


class TestHandleWebhook:
    @pytest.mark.asyncio
    async def test_multiple_events_each_dispatched(self):
        ch = _make_channel()
        payload = {
            "events": [
                _text_event(user_id="U1", reply_token="r1"),
                _text_event(user_id="U2", reply_token="r2"),
            ]
        }
        await ch._handle_webhook(payload)
        assert ch.bus.publish_inbound.await_count == 2

    @pytest.mark.asyncio
    async def test_empty_events_no_dispatch(self):
        ch = _make_channel()
        await ch._handle_webhook({"events": []})
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_one_bad_event_does_not_block_others(self):
        ch = _make_channel()
        await ch._handle_webhook({"events": [{"type": "message"}, _text_event()]})
        ch.bus.publish_inbound.assert_awaited_once()


class TestSend:
    @pytest.mark.asyncio
    async def test_send_without_http_client_raises(self):
        ch = _make_channel()
        msg = OutboundMessage(channel="line", chat_id="U123", content="hi")
        with pytest.raises(RuntimeError, match="not initialized"):
            await ch.send(msg)

    @pytest.mark.asyncio
    async def test_reply_path_used_for_fresh_token(self):
        ch = _make_channel()
        ch._http = AsyncMock()
        ch._http.post.return_value = _ok_response()
        ch._reply_tokens["U123"] = ("rt-1", time.time())

        await ch.send(OutboundMessage(channel="line", chat_id="U123", content="Hi"))

        ch._http.post.assert_awaited_once()
        call = ch._http.post.call_args
        assert call.args[0].endswith("/message/reply")
        assert call.kwargs["json"]["replyToken"] == "rt-1"
        assert call.kwargs["json"]["messages"][0]["text"] == "Hi"
        assert call.kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"
        # Single-use: token is consumed.
        assert "U123" not in ch._reply_tokens

    @pytest.mark.asyncio
    async def test_push_fallback_when_no_token(self):
        ch = _make_channel()
        ch._http = AsyncMock()
        ch._http.post.return_value = _ok_response()

        await ch.send(OutboundMessage(channel="line", chat_id="U999", content="Hi"))

        call = ch._http.post.call_args
        assert call.args[0].endswith("/message/push")
        assert call.kwargs["json"]["to"] == "U999"

    @pytest.mark.asyncio
    async def test_push_fallback_when_token_expired(self):
        ch = _make_channel()
        ch._http = AsyncMock()
        ch._http.post.return_value = _ok_response()
        ch._reply_tokens["U123"] = ("rt-1", time.time() - 999)

        await ch.send(OutboundMessage(channel="line", chat_id="U123", content="Hi"))

        call = ch._http.post.call_args
        assert call.args[0].endswith("/message/push")
        assert call.kwargs["json"]["to"] == "U123"

    @pytest.mark.asyncio
    async def test_reply_failure_falls_back_to_push(self):
        ch = _make_channel()
        ch._http = AsyncMock()
        ok = _ok_response()

        def post_side_effect(url, **kwargs):
            if url.endswith("/message/reply"):
                raise RuntimeError("reply boom")
            return ok

        ch._http.post.side_effect = post_side_effect
        ch._reply_tokens["U123"] = ("rt-1", time.time())

        await ch.send(OutboundMessage(channel="line", chat_id="U123", content="Hi"))

        assert ch._http.post.await_count == 2
        assert ch._http.post.await_args.args[0].endswith("/message/push")

    @pytest.mark.asyncio
    async def test_token_one_time_then_push(self):
        ch = _make_channel()
        ch._http = AsyncMock()
        ch._http.post.return_value = _ok_response()
        ch._reply_tokens["U123"] = ("rt-1", time.time())

        await ch.send(OutboundMessage(channel="line", chat_id="U123", content="first"))
        assert "U123" not in ch._reply_tokens

        ch._http.post.reset_mock()
        await ch.send(OutboundMessage(channel="line", chat_id="U123", content="second"))
        assert ch._http.post.await_args.args[0].endswith("/message/push")

    @pytest.mark.asyncio
    async def test_push_failure_raises_for_manager_retry(self):
        ch = _make_channel()
        ch._http = AsyncMock()
        ch._http.post.side_effect = RuntimeError("boom")

        msg = OutboundMessage(channel="line", chat_id="U999", content="Hi")
        with pytest.raises(RuntimeError, match="boom"):
            await ch.send(msg)


class TestResolveDisplayName:
    @pytest.mark.asyncio
    async def test_resolves_and_caches_display_name(self):
        ch = _make_channel()
        ch._http = AsyncMock()
        resp = _ok_response()
        resp.json = MagicMock(return_value={"displayName": "Alice", "userId": "U123"})
        ch._http.post.return_value = resp
        ch._http.get.return_value = resp

        name = await ch._resolve_display_name("U123")
        assert name == "Alice"
        assert ch._profile_cache["U123"] == "Alice"

        # Second call is served from cache (no extra GET).
        ch._http.get.reset_mock()
        assert await ch._resolve_display_name("U123") == "Alice"
        ch._http.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failure_falls_back_to_user_id_uncached(self):
        ch = _make_channel()
        ch._http = AsyncMock()
        ch._http.get.side_effect = RuntimeError("404")

        assert await ch._resolve_display_name("U123") == "U123"
        # Not cached → next message retries.
        assert "U123" not in ch._profile_cache


class TestBoundedCaches:
    def test_bounded_set_evicts_oldest_over_cap(self):
        cache: OrderedDict[str, int] = OrderedDict()
        for i in range(5):
            _bounded_set(cache, f"k{i}", i, max_entries=3)
        assert len(cache) == 3
        # Oldest two evicted; newest three retained in insertion order.
        assert list(cache.keys()) == ["k2", "k3", "k4"]

    def test_bounded_set_refreshes_existing_key_to_newest(self):
        cache: OrderedDict[str, int] = OrderedDict()
        _bounded_set(cache, "a", 1, max_entries=2)
        _bounded_set(cache, "b", 2, max_entries=2)
        _bounded_set(cache, "a", 3, max_entries=2)  # touch "a" → now newest
        _bounded_set(cache, "c", 4, max_entries=2)  # evicts the oldest ("b")
        assert "b" not in cache
        assert cache["a"] == 3
        assert cache["c"] == 4

    def test_profile_cache_capped(self, monkeypatch):
        monkeypatch.setattr(line_mod, "LINE_MAX_CACHE_ENTRIES", 3)
        ch = _make_channel()
        for i in range(10):
            _bounded_set(ch._profile_cache, f"U{i}", f"name{i}")
        assert len(ch._profile_cache) <= 3

    def test_store_reply_token_caps_and_prunes_expired(self):
        ch = _make_channel(reply_token_ttl_s=50)
        # An expired token already parked in the cache.
        ch._reply_tokens["old"] = ("rt-old", time.time() - 999)
        ch._store_reply_token("fresh", "rt-fresh")
        # Expired entry pruned opportunistically on insert; fresh one stored.
        assert "old" not in ch._reply_tokens
        assert ch._reply_tokens["fresh"][0] == "rt-fresh"

    def test_reply_tokens_capped(self, monkeypatch):
        monkeypatch.setattr(line_mod, "LINE_MAX_CACHE_ENTRIES", 3)
        ch = _make_channel(reply_token_ttl_s=999)
        for i in range(10):
            ch._store_reply_token(f"U{i}", f"rt{i}")
        assert len(ch._reply_tokens) <= 3


class TestFastAck:
    def test_ack_path_does_not_block_on_result(self):
        # FIX 3: the webhook handler must schedule processing fire-and-forget,
        # never blocking the 200 ack on the task result.
        src = inspect.getsource(LineChannel.start)
        assert "fut.result" not in src
        assert "add_done_callback" in src


class TestSupportsStreaming:
    def test_streaming_not_supported(self):
        # LINE cannot edit a sent message, so send_delta is not overridden.
        ch = _make_channel()
        assert ch.supports_streaming is False


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self):
        ch = _make_channel()
        ch._running = True
        await ch.stop()
        assert ch._running is False
        assert ch._server is None
        assert ch._http is None
