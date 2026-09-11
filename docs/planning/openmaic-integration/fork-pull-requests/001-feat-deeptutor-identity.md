# #1 — feat(auth): derive identity from the gateway, and partition assets by owner

- **State**: MERGED (merged 2026-09-10T12:04:13Z)
- **Branch**: `feat/deeptutor-identity` → `main`
- **Opened**: 2026-09-10T06:02:14Z
- **Was at**: https://github.com/khunmax2/OpenMAIC/pull/1

---

Threads DeepWitya's verified identity through the seam upstream documents for it, and replaces the development authenticator.

## What this is

`resolveRequestOwnerId(req, responseHeaders, authenticatedOwnerId?)` documents its third argument as the seam "a future auth integration must thread". This is that integration. A gatekeeper in front of this app verifies the DeepWitya session and states the result as one header; nothing here reads a client-supplied value.

- **`lib/server/studio-identity.ts`** (new) — the only reader of the header. Value is `user:<uid>`, matching the `user:`/`anon:` convention upstream's tests establish. The 64-character uid bound is DeepWitya's own (`AuthStatusResponse.user_id`), not invented.
- **Threading** — one wrapper covers most routes; three routes call the resolver directly; one Server Action reads the same header via `headers()`.
- **`lib/persistence/server-auth.ts`** — replaced. **Assets now partition per owner.** Upstream filed every asset under one `'shared'` principal; leaving that would have left isolation stopping at the first image.
- **`STUDIO_REQUIRE_GATEWAY`** — a request with no identity is a 401, not a fresh anonymous visitor that looks like the app working.

## Two things testing found, not reading

1. Removing upstream's `PERSISTENCE_DEV_TOKEN` gate meant an unauthenticated request opened a connection pool on its way to being refused. The refusal is now explicit and still ahead of the pool — the test proves it by pointing `DATABASE_URL` at something unusable, so reaching the pool would surface as a 500 rather than the asserted 401.
2. A first version refused unconditionally, which would have made this fork unrunnable the way upstream runs. The refusal now honours `STUDIO_REQUIRE_GATEWAY`, and the anonymous path stays intact underneath.

## Measurement

Same machine, same command, before and after:

| | files | tests |
|---|---|---|
| clean `29735f10` | 14 failed | **78** failed / 7504 |
| this branch | 16 failed | **77** failed / 7521 |

Every difference in either direction passes when run in isolation. `tsc --noEmit` clean; `eslint` clean on every changed file.

Design: `docs/adr/0005-course-studio-sibling-application.md` in the DeepWitya repo, summarised in `FORK.md` here.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
