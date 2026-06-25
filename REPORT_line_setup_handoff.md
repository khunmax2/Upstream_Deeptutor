# REPORT — LINE channel: bringing it live (local dev) + handoff

**Date:** 2026-06-20
**Scope:** Connecting the already-implemented LINE channel adapter
(`deeptutor/partners/channels/line.py`) to a real LINE Official Account and
getting inbound + outbound working on a local machine. Plus one **open item**
(language behavior) intentionally left unstarted for the next task.

---

## Account / target

- LINE OA: **DeepWitya** (`@149bktca`), Messaging API **channel ID 2010458287**.
- DeepTutor partner: **`lineme`** (`data/partners/lineme/config.yaml`).
- Soul: `companion` (library), persona file under the partner workspace.

## What was done (all verified working end-to-end)

1. **Public tunnel.** `ngrok` was unusable (now requires a verified account +
   authtoken — `ERR_NGROK_4018`). Switched to **cloudflared quick tunnel**, which
   needs no account:
   ```bash
   cloudflared tunnel --url http://localhost:3979
   ```
   > ⚠️ A quick tunnel URL **changes every restart** and dies when that terminal
   > closes. For anything beyond ad-hoc testing, use a named cloudflared tunnel or
   > deploy behind a real domain/reverse-proxy.

2. **Webhook URL** entered in LINE (OA Manager → Messaging API → "ลิงก์ Webhook",
   or Developers Console → Webhook settings):
   ```
   https://<tunnel-host>/line/webhook
   ```
   Path `/line/webhook` and default **port 3979** come from `LineConfig` in
   `line.py`. LINE requires **HTTPS** and a publicly reachable host (no localhost).

3. **Enabled the LINE channel** in `data/partners/lineme/config.yaml`
   (`channels.line`): `enabled: true`, plus `host`, `port`, `path`, `allow_from`.
   The channel will not start unless `enabled` is ticked AND both secrets are set
   (`line.py` `start()` logs an error and returns otherwise).

4. **Root-cause bug — secret/token were in the wrong fields.** This caused two
   distinct 401s; the fix is to keep the two values straight:

   | Value | Where to get it | Used for | Shape |
   |-------|-----------------|----------|-------|
   | **Channel secret** | Basic settings tab ("ความลับแชนแนล") | **Inbound** — HMAC-SHA256 signature verify of `x-line-signature` | 32-char hex |
   | **Channel access token** | Messaging API tab → "Channel access token (long-lived)" → **Issue** | **Outbound** — Reply/Push API calls | long (~170+ chars), often ends `=` |

   - Wrong **secret** ⇒ `LINE signature verification failed` + **401 on Verify**.
   - Wrong/missing **access token** ⇒ inbound OK, but **401 on
     `…/message/reply`** then push fallback also fails.
   - In this session both were initially swapped/mismatched; once each value went
     into its correct field and DeepTutor was restarted, Verify passed and the bot
     replied successfully.
   - **Restart DeepTutor after any config change** — channel config is read at
     start. Watch for log line:
     `LINE webhook listening on http://0.0.0.0:3979/line/webhook`.

5. **OA Manager hygiene.** Auto-reply messages and Greeting messages were
   **Enabled** by default — recommend disabling both so LINE's canned replies
   don't talk over the bot.

> 🔐 Actual secret/token values are **not** recorded here. They live in
> `data/partners/lineme/config.yaml` only.

## Verification status

- ✅ cloudflared tunnel reachable → listener on 3979 → path correct (401 not 404).
- ✅ Webhook **Verify** passes.
- ✅ Inbound message creates a `line_<userId>` session; bot **replies** in LINE.

---

## OPEN ITEM (not started — next task should pick this up)

**Symptom:** the bot's reply language is inconsistent — same OA replied in
Chinese, then English, then Thai across three short greetings.

**Root cause:** partner `language` was empty → `_language()` falls back to `"en"`
(`deeptutor/services/partners/runtime.py`). The chat pipeline always injects a
**single-fixed-language** directive via `language_directive()` in
`deeptutor/services/prompt/language.py`, appended at
`deeptutor/agents/chat/prompt_blocks.py:47` (`append_language_directive`). There is
currently **no "respond in the user's language" mode** — only `zh` / `th` / `en`.

**Interim state in the repo right now:** `config.yaml` was set to `language: th`
(locks Thai). This was a stopgap, **not** the desired behavior.

**Desired behavior:** mirror the user — Thai→Thai, English→English, per turn.

**Proposed fix (NOT yet applied — paused at user's request):**

1. `deeptutor/services/prompt/language.py`
   - `normalize_agent_language`: return `"auto"` for inputs `"auto"`/`"mirror"`.
   - `language_directive`: add an `"auto"` branch that instructs the model to
     detect the user's most recent message language and reply in that same
     language (keep proper nouns; don't announce the switch).
2. Set `data/partners/lineme/config.yaml` → `language: auto`.
3. Caveat: a few UI-label lookups compare `self.language == "th"`/`"zh"`; under
   `"auto"` they fall to English defaults (minor, cosmetic).
4. **Fork policy (CLAUDE.md §1):** log in `CHANGES.md`, Conventional-Commit, and
   update `NOTICE`; `language.py` is already a fork-touched file (Thai support).

**Alternative considered & rejected:** putting "mirror the user" only in the
SOUL/persona — the strict `language_directive` is appended *after* the persona and
says "Do NOT switch languages", so it would override the soul. A code-level `auto`
mode is the robust path.

---

## Quick restart checklist (local)

1. Terminal A: `cloudflared tunnel --url http://localhost:3979` (keep open).
2. Update LINE Webhook URL with the new tunnel host + `/line/webhook`; **Verify**.
3. Terminal B: start DeepTutor; confirm the "LINE webhook listening…" log.
4. Message the OA from a phone; confirm a reply.
