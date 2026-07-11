# REPORT — LINE Integration Implementation

**Date:** 2026-06-20
**Branch:** `feature/LINE_Integration`
**Baseline:** v1.4.8 (`deeptutor/__version__.py = "1.4.8"`)
**Commit(s):** `feat(partners): add LINE Messaging channel (DM MVP)` (this round)
**Companion:** `REPORT_line_integration_feasibility.md` (the code-traced plan this
executes).

---

## 1. สรุปสิ่งที่ทำ

Implemented the LINE Official Account channel (Messaging API) as a single new
backend adapter, plus a unit-test suite — **backend-only, fully additive**.

**Scope shipped (DM MVP):**
- 1:1 **text** inbound/outbound.
- Webhook with **HMAC-SHA256 `x-line-signature` verification** over the raw body.
- **Reply-first / Push-fallback** delivery (Reply is free + single-use; Push uses
  `userId` and counts against quota).
- **Allowlist** (`allow_from`) — enforced by the base contract.
- **`displayName` resolution** via Get profile, cached in-memory (so the partner
  session list shows a real name, not the opaque `userId`).

**Deferred to phase 2:** rich content / images / audio / stickers / group chat;
optional Web UI (LINE brand icon, locale keys) — LINE falls back to the generic
`Radio` icon for now.

## 2. Touchpoint ที่แตะจริง

| File | Type | Matches feasibility report? |
|---|---|---|
| `deeptutor/partners/channels/line.py` | **new** | ✅ as predicted |
| `tests/services/partners/test_line_channel.py` | **new** | ✅ (mirrors `test_msteams_channel.py`) |
| `FORK_TOUCHPOINTS.txt` (append `line.py`) | edit | ✅ fork policy |
| `CHANGES.md` | edit | ✅ fork policy |
| `REPORT_line_implementation.md` | **new** | ✅ closeout |
| `registry.py` / `schema.py` / `manager.py` / `_partners_channel_schema.py` / `pyproject.toml` | — | ✅ **untouched, as predicted** |

The feasibility prediction held exactly: **zero edits** to the framework. Verified
at runtime (see §4) that auto-discovery, config resolution, and secret masking all
work off the naming convention alone.

> Note on the touchpoints manifest format: `FORK_TOUCHPOINTS.txt` is a plain
> path list with no `[tag]` convention in the actual file, so the path was added
> without the `[line]` tag the feasibility report sketched. The test file was not
> added to the manifest (the manifest tracks source touchpoints; test files other
> than the pre-existing `web/tests/...` entry are not listed).

## 3. ดีไซน์ที่ตัดสินใจตอนเขียน

- **Default port `3979`** (off msteams' 3978 so both webhook channels coexist);
  `path = /line/webhook`. Configurable.
- **Reply-token margin = `50s`** (`reply_token_ttl_s`, configurable). LINE tokens
  are usable ~60s but the docs warn the exact limit may change and to allow for
  network delay; 50s is the safe live window before falling through to Push.
- **Token popped on first `send()`** — the manager retries `send()` up to 3×, and
  a reply token is single-use, so any retry must fall through to Push rather than
  reuse a dead token. Implemented with `self._reply_tokens.pop(chat_id, None)`.
- **In-memory reply-token map only** — confirmed the feasibility finding (§4.1):
  the runtime does **not** forward inbound metadata to `send()`, and Push only
  needs `userId` (= `chat_id` for a DM), so no disk persistence / file-lock /
  pruning is needed. This is the ~400-line simplification vs `msteams.py`.
- **No JWT/OAuth** — LINE uses a static channel access token (`Authorization:
  Bearer …` on every REST call), dropping the entire msteams token-exchange path.
- **Verify-event handling** — `events: []` (the console "Verify" button) loops
  zero times → plain 200. An all-zero placeholder `replyToken` (redelivery /
  verify) is detected by `_is_placeholder_token()` and **not stored** as a live
  token.
- **Profile cache policy** — only **successful** lookups are cached, so a transient
  Get-profile failure self-heals on the next message. A permanently-unavailable
  profile (rare: PC-only, non-consented user) costs one GET per message — an
  accepted trade-off for MVP, noted in §5.
- **No `send_delta` override** — LINE cannot edit a sent message, so there is no
  live streaming; `supports_streaming` is `False` (unit-tested).
- **Empty content guard** — outbound text defaults to `" "` because LINE rejects
  empty text messages.

What the feasibility report got right: every framework claim (§3 auto-discovery,
config `extra="allow"`, schema introspection, secret masking, manager retry,
metadata-not-forwarded) held verbatim. Nothing was found to be wrong.

## 4. ผลการทดสอบ

**Unit — `tests/services/partners/test_line_channel.py`: 32 passed.**
Coverage: config defaults + camelCase aliases; `default_config()`; `is_allowed`
(wildcard / empty / exact); **signature verify** (valid / tampered body / missing
header / wrong secret); event parsing (text dispatched + token stored; non-message
skipped; non-text skipped; missing userId skipped; empty text skipped; placeholder
token not stored; denied sender not dispatched); webhook batch (multi-event each
dispatched; empty events; one bad event doesn't block others); **`send()`** (no
HTTP client raises; reply path payload + token popped; push fallback when no token
/ expired / reply-error; one-time token → push on 2nd send; push failure raises for
manager retry); `displayName` resolve + cache + fallback; `supports_streaming` is
False; `stop()` without `start()` is safe.

**Framework integration (runtime, no real LINE account):**
- `discover_channel_names()` includes `line`; `load_channel_class("line")` →
  `LineChannel` / display `LINE`. ✅
- `resolve_config_model(LineChannel)` → `LineConfig`. ✅
- `channel_schema_payload(LineChannel)` exposes all 10 fields; `secret_fields ==
  ["channel_secret", "channel_access_token"]` (masked in the Web UI). ✅
- **Zero edits** to registry/schema/manager/endpoint to achieve the above. ✅

**Regression:**
- `ruff check .` → All checks passed. `ruff format --check` on both new files →
  clean.
- Partner test selection: **107 passed**. The 9 failures observed are all
  **pre-existing environment issues** in this `.venv` (optional deps not
  installed: `telegram`, `slack_sdk`, `jwt`/`cryptography`); none reference
  `line`. The `test_channel_registry_discovers_builtin_channels` failure is a
  `{"telegram","slack",…} <= set(channels)` subset assertion failing because those
  optional channels are skipped — unaffected by adding `line`. CI (which installs
  `.[all]`) should be green.

**Integration (ngrok, real LINE OA) — NOT YET RUN.** Requires a LINE Developers
Console OA + channel secret/token + ngrok. Checklist to run (from feasibility §4.2):
- [ ] Set webhook URL (ngrok + `/line/webhook`) in console → **Verify** goes green.
- [ ] Add the OA on a phone → message it → bot replies in-chat.
- [ ] Read own `userId` from logs → set `allow_from` → outsider is silently ignored.
- [ ] Session list shows real `displayName`, not the hash.
- [ ] Fast question → Reply path; slow (>~1 min) answer → Push fallback succeeds.
- [ ] 2–3 users concurrently → answers not cross-wired, histories isolated.

## 5. ปัญหา / ข้อจำกัด / สิ่งที่ค้าง

- **Integration test pending** (needs real OA + ngrok) — see §4 checklist.
- **`allow_from` must be set** or the manager exits (`SystemExit` on `[]`). For
  testing: developer's own `userId`; for go-live: `["*"]` + abuse/quota guarding
  (open decision, §6).
- **Profile cache is per-process / in-memory** — lost on restart (re-fetched on
  next message). Acceptable; no persistence by design.
- **Profile failure trade-off** — a permanently non-consented user triggers a
  Get-profile GET on every message (rare; PC-only accounts, disabled since 2020).
- **Push counts against monthly quota** — Reply-first conserves it, but a chatty
  bot whose answers routinely exceed the reply-token window will consume Push
  quota. Watch the OA plan (Thailand figures differ from LINE's general docs).
- **Single text message per turn** — multi-bubble / >5-object batching not used.

## 6. คำถาม/ประเด็นที่อยากเอากลับไปคุยใน Cowork

1. **Go-live allowlist policy** — `["*"]` public vs curated. What abuse/rate
   guarding do we want around a public OA (per-`userId` throttle, Push-quota
   ceiling)?
2. **Quota / plan** — which LINE OA plan, and do we need Push-quota telemetry
   before going public?
3. **Phase 2 scope & priority** — images/stickers inbound, rich messages
   (buttons/quick-replies) outbound, group chat. Which first?
4. **UI** — land the LINE brand icon (`#06C755`) + locale keys now, or keep the
   `Radio` fallback until phase 2?
5. **Profile persistence** — worth caching `displayName` to the session record so
   it survives restarts, or leave in-memory?

---

## 7. Post-review fixes (2026-06-20, before integration test)

Cowork review of the full file flagged four items (2 quota/abuse, 2 robustness for
a public OA). All four are in-file; no framework files touched.

### FIX 1 — quota-safe delivery defaults
`LineConfig` now overrides `send_progress = False` and `send_tool_hints = False`
(was inheriting `True` from `DeliveryOverrides`). LINE cannot edit a sent message,
so progress/tool-hint narration has no UX value, and each one is a *separate*
`OutboundMessage` — only the first can use the free Reply, the rest become
quota-counted Push. Users can still opt back in per channel.

> **Mechanism nuance (for Cowork):** the effective runtime flag is resolved by
> `ChannelManager._init_channels` via `_resolve_bool_override(section,
> "send_progress", default=True)` — it reads the **persisted config section**, not
> the Pydantic model, and *defaults to `True` when the key is absent*. So FIX 1
> bites through the **seeding path**: `default_config()` now emits
> `sendProgress: False` / `sendToolHints: False`, so a channel enabled the normal
> way persists `False` and the manager reads `False`. Verified end-to-end
> (`EFFECTIVE send_progress: False`). Caveat: a hand-edited `config.yaml` that
> *omits* the key would still default to `True` — a pre-existing framework quirk,
> not LINE-specific.

### FIX 2 — allowlist pre-gate before network work
`_handle_event` now calls `is_allowed(user_id)` **before** storing a reply token
or calling Get profile, dropping unauthorized senders early (mirrors how
`msteams.py` checks before persisting). The base `_handle_message` still re-checks
`is_allowed` as the single source of truth — this just stops an out-of-allowlist
spammer from burning the Get-profile rate limit / filling caches.

### FIX 3 — fast ack (processing off the ack path)
The webhook `do_POST` previously blocked the 200 ack on `fut.result(timeout=15)`,
which includes a first-sighting Get profile. It now schedules `_handle_webhook`
fire-and-forget via `run_coroutine_threadsafe` + `add_done_callback`
(`_log_webhook_task_result` logs any top-level failure) and acks 200 immediately.
Signature verify + JSON parse stay on the ack path (so a bad request still gets a
4xx). Per-event exceptions are already swallowed inside `_handle_webhook`.

### FIX 4 — bounded in-memory caches
`_reply_tokens` and `_profile_cache` are now `OrderedDict`, capped at
`LINE_MAX_CACHE_ENTRIES = 10_000` via the `_bounded_set` helper (LRU: evict oldest
over cap). `_store_reply_token` additionally prunes expired tokens on insert
(a turn with no outbound never pops its token, so without this an idle/abusive
public OA would leak dead tokens). `_bounded_set` reads the cap from the module
global at call time so it stays test-overridable.

### Test results
`tests/services/partners/test_line_channel.py`: **39 passed** (was 32; +7 for the
fixes — delivery-flag defaults + re-enable, pre-gate-blocks-network, `_bounded_set`
eviction + key-refresh, profile/token cap, expired-token prune, ack-path no-block
source guard). `ruff check .` clean; `ruff format --check` clean on both files.
Manager smoke re-confirmed: `LineChannel` still wired with **zero** framework
edits, and effective delivery flags resolve to `False` via the seeding path.
