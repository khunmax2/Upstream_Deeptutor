# REPORT — LINE Integration Feasibility (code-verified, baseline v1.4.8)

**Date:** 2026-06-20
**Baseline:** v1.4.8 (`deeptutor/__version__.py = "1.4.8"`, release `88c25653`)
**Branch:** `feature/LINE_Integration`
**Scope of this report:** verify the LINE-channel plan against the *actual* v1.4.8
code, not assumptions. Companion planning doc:
`/Users/attapon/Project/antigravity/LINE_Integration_KICKOFF_handoff.md`.

> This report re-does the earlier (lost-on-re-branch) feasibility note from
> scratch against v1.4.8, with every claim traced to a file:line.

---

## 1. Verdict

The plan holds and is, if anything, **more additive than the original handoff
hedged**. Adding LINE is a single new file
(`deeptutor/partners/channels/line.py`) plus one required manifest append
(`FORK_TOUCHPOINTS.txt`). No edits are needed to the channel registry, config
schema, schema-introspection endpoint, partner runtime, channel manager, or
`pyproject.toml`. The only upstream-file touches are cosmetic and optional
(a brand icon, two marketing strings, Thai locale keys).

The real engineering risk is **not** upstream-merge conflict (near zero) — it is
**LINE-specific reply-token lifecycle and allowlist policy**, both of which live
entirely inside the new file.

## 2. What changed v1.4.6 → v1.4.8 (and why the channel plan is unaffected)

- Channel framework dir `deeptutor/partners/channels/` had only a `prepare 1.4.7`
  touch between v1.4.6 and HEAD — **no contract change**.
- v1.4.8's `fix:partners & improve my agents` (`7871955a`) touched
  `api/routers/partners.py` (10 lines) and `services/partners/runtime.py`
  (22 lines) but is about **subagents / partner_memory**, not the channel
  adapter layer. The `BaseChannel` contract, registry, manager, and bus are
  intact.

## 3. Framework verification (file:line)

### 3.1 Contract — `deeptutor/partners/channels/base.py` (184 lines)
LINE must implement the three abstract methods `start()`, `stop()`,
`send(msg: OutboundMessage)` (`base.py:60-88`). The base already provides
`_handle_message(...)` (`base.py:126-174`), which enforces `is_allowed()` then
publishes an `InboundMessage` to the bus — the adapter just calls it from the
webhook. `is_allowed()` reads `self.config.allow_from`; **empty list denies all,
`"*"` allows all** (`base.py:116-124`).

### 3.2 Auto-discovery — `deeptutor/partners/channels/registry.py` (85 lines)
`discover_channel_names()` scans the package with `pkgutil.iter_modules`;
`load_channel_class("line")` imports the module and returns the first
`BaseChannel` subclass. **Adding `line.py` requires zero registry edits.**
External plugins via entry-point group `deeptutor.partners.channels` are also
supported but unnecessary here.

### 3.3 Config — `deeptutor/partners/config/schema.py`
`ChannelsConfig` uses `model_config = ConfigDict(extra="allow")` (`schema.py:47`)
and stores each channel's config as an extra dict; each channel parses its own
in `__init__`. **No schema edit.** Base config classes available to subclass:
`DeliveryOverrides` (send_progress / send_tool_hints) and `StreamingSupport`.

### 3.4 Schema introspection — `deeptutor/api/routers/_partners_channel_schema.py`
`resolve_config_model()` finds `LineConfig` by the `XxxChannel ↔ XxxConfig`
naming convention automatically (`:22-47`); `channel_schema_payload()` emits the
JSON Schema the Web UI renders into a generic form (`:120-146`).
`collect_secret_fields()` + `_is_secret_field()` mask any field whose name
contains `token` / `secret` / `password` (`services/partners/manager.py:51-64`)
— so `channel_secret` and `channel_access_token` are **masked automatically**.
**No endpoint edit, no manual secret wiring.**

### 3.5 Manager — `deeptutor/partners/channels/manager.py`
`_init_channels()` iterates `discover_all()` and reads `config.line.enabled`
(`:57-86`) — works with the new channel immediately. Two operational facts the
adapter must respect:
- **`_validate_allow_from()` raises `SystemExit` if `allow_from == []`**
  (`:108-114`).
- **`_send_with_retry()` retries `channel.send()` up to `send_max_retries`
  (default 3) with 1s/2s/4s backoff** (`:296-327`). Because a LINE `replyToken`
  is single-use, `send()` must consume the token on the first attempt so retries
  fall through to Push.

### 3.6 Bus — `deeptutor/partners/bus/{queue,events}.py`
Plain `asyncio.Queue` in/out. `InboundMessage.session_key` defaults to
`f"{channel}:{chat_id}"` (`events.py:21-24`). `OutboundMessage` carries only
`channel`, `chat_id`, `content`, `reply_to`, `media`, `metadata`.

## 4. Two non-obvious findings that shape the adapter

### 4.1 The runtime does NOT propagate inbound metadata to `send()`
`runtime.py:110-127` builds the outbound as
`OutboundMessage(channel, chat_id, content, metadata=delivery_meta)` where
`delivery_meta` is a **fresh dict** holding only internal flags (`_streamed`).
The inbound message's metadata (where a LINE `replyToken` would ride) is **not
forwarded**. Therefore LINE must mirror the msteams pattern: stash the token in
an **in-memory** map keyed by `chat_id` at webhook time, and look it up in
`send()`. No disk persistence is needed because Push only needs `userId`
(= `chat_id` for DM), so the fallback always works. This is exactly why LINE can
drop msteams's ~400 lines of `ConversationRef` persistence / file-locking /
pruning.

### 4.2 Concurrency is already solved, for free
`PartnerRunner.run()` spawns one `asyncio.create_task` per inbound message
(`runtime.py:99`) and serialises same-session turns via
`_session_locks: dict[str, asyncio.Lock]` (`runtime.py:89,152`). Model:
**concurrent across senders, serialised within a sender.** The adapter only has
to set `chat_id`/`session_key = userId`; the runtime fans out and isolates per
user (one user flooding backs up only their own lane).

## 5. Template decision: `msteams.py`, not `slack.py`

`slack.py` uses socket mode (persistent WebSocket); LINE needs webhook + HMAC +
REST. `msteams.py` (836 lines) is the right shape: `ThreadingHTTPServer` accepts
the POST, validates, bridges to the event loop via
`asyncio.run_coroutine_threadsafe`, and sends with `httpx`
(`msteams.py:169-234`, `250-290`). LINE simplifies it by removing conversation-
ref persistence and the JWT/OAuth token exchange (LINE uses a static channel
access token), landing around 300-400 lines.

## 6. LINE protocol notes (verify against current LINE docs at build time)

- Product: **LINE Official Account via the Messaging API** (not LINE Login /
  Notify / personal accounts). Needs Channel secret + Channel access token +
  webhook URL; OA set to Bot/Webhook mode.
- Verify `x-line-signature` = base64(HMAC-SHA256(channelSecret, **raw body**)) —
  read raw bytes before JSON-parsing.
- One webhook POST may batch multiple events in `events[]` — loop and enqueue each.
- Ack 200 fast; process async (LINE disables a slow/failing webhook).
- Reply API: `replyToken`, usable ~1 min (LINE: *limit may change without notice
  + network delay — do not rely on exact timing*), single-use, ≤5 message objects,
  **free / not counted against quota**. Push API: `userId`, always available,
  **counts against monthly quota**. Reply-first, Push-fallback conserves quota.
- LINE cannot edit a sent message → **no live streaming**; do not override
  `send_delta`; default `send_progress=False`.

## 6A. What LINE lets you retrieve — and not (official docs, Jun 2026)

**Why this matters:** DeepTutor stores the LINE `userId` as `sender_id`, which is
an **opaque hash** (e.g. `U4af4980629...`), not a human name. To show a real name
in the partner session list, the adapter must call **Get profile** and cache it.

**Get profile** — `GET https://api.line.me/v2/bot/profile/{userId}` (Bearer channel
access token). Returns: `displayName`, `userId`, `pictureUrl`, `statusMessage`,
`language`. Recommended: call on first sighting of a new `userId`, cache it
(in the session record / metadata); fall back to the raw `userId` if unavailable.

**Conditions to get a profile / `userId` at all:** the user must (1) have added the
OA as a friend, (2) not be blocking it, and (3) have **consented** to profile
access. LINE iOS/Android users consent automatically on first app use;
**PC-only users cannot consent → the webhook carries no `userId` and profile is
unavailable** (rare — PC account creation has been disabled since Apr 2020).

**NOT obtainable via the Messaging API** (do not design features that need these):
real name, email, phone, gender, birthday, address (require **LINE Login**, and
mostly the corporate **LINE Profile+** application; email needs a separate Login
permission), the searchable **LINE ID**, the user's friend list, or messages the
user sends to anyone else.

**`userId` semantics:** opaque, unique, **per-OA** — the same person yields a
different `userId` under a different OA (no cross-OA correlation), and it differs
from both the display name and the LINE ID.

**Quota / cost:** Reply is **free and uncounted**; Push counts **one per
recipient** (number of message objects in a request is irrelevant); messages to
blocked / nonexistent users aren't counted. Free monthly quota depends on the
**OA plan and country** (LINE's general docs cite Light 5,000 / Standard 30,000
msgs/month; Thailand plans/figures differ — check the actual OA plan). Each
endpoint (push, get-profile, …) has its own rate limit; exceeding returns
**429**. → reinforces Reply-first, Push-only-on-token-expiry.

## 7. Touchpoint manifest (v1.4.8)

| File | Type | Required? |
|---|---|---|
| `deeptutor/partners/channels/line.py` | **new** | yes |
| `FORK_TOUCHPOINTS.txt` (append `[line]`) | edit | yes (fork policy) |
| `web/components/partners/ChannelIcon.tsx` (+brand #06C755) | edit | optional (falls back to `Radio` icon) |
| marketing copy ×2 ("…Telegram, Slack and more") | edit | optional |
| `web/locales/{th,en,zh}/*` LINE keys | edit | optional (consistent w/ existing channels = EN field descriptions) |
| `pyproject.toml` | — | **no** (no new dependency) |
| `registry.py` / `schema.py` / `_partners_channel_schema.py` / `partners.py` / `manager.py` | — | **no** (verified) |

## 8. Allowlist policy — decided (2026-06-20)

`LineConfig.allow_from` must be set (empty → `SystemExit`). For a public OA,
`userId`s are opaque hashes, so per-user allowlisting is impractical at scale.
**Decision:** during testing, restrict `allow_from` to the developer's own
`userId` (read it from the first webhook); at go-live, switch to `["*"]` with
abuse/quota guarding (rate-limit + Push-quota awareness). No other open
decisions remain before coding `line.py`.

## 9. Method / provenance

Files read in full: `base.py`, `msteams.py`, `services/partners/runtime.py`,
`channels/manager.py`, `bus/queue.py`, `bus/events.py`,
`partners/config/schema.py`, `_partners_channel_schema.py`,
`web/components/partners/ChannelIcon.tsx`. Greps: hardcoded channel-name
enumerations (none in non-test Python), frontend channel references (2 marketing
strings only), dependency manifests (LINE adds none). Channel framework git
history v1.4.6→HEAD confirmed contract-stable.

LINE protocol facts (§6, §6A) verified against official `developers.line.biz`
docs, Jun 2026: Get profile / user-profile types table, user-consent conditions,
sending-messages (reply vs push, ≤5 objects, quota counting), reply-token
validity note, pricing/quota. Sources listed below.

## 10. Sources

- [Get user profile information | LINE Developers](https://developers.line.biz/en/docs/basics/user-profile/)
- [Consent on getting user profile information | LINE Developers](https://developers.line.biz/en/docs/messaging-api/user-consent/)
- [Get user IDs | LINE Developers](https://developers.line.biz/en/docs/messaging-api/getting-user-ids/)
- [Send messages | LINE Developers](https://developers.line.biz/en/docs/messaging-api/sending-messages/)
- [Messaging API pricing | LINE Developers](https://developers.line.biz/en/docs/messaging-api/pricing/)
- [Messaging API reference | LINE Developers](https://developers.line.biz/en/reference/messaging-api/)
