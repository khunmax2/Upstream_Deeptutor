# REPORT — admin lifecycle Phase 2 on the host (`deploy-2026-09-19`), and v1 retired (2026-09-19)

Closes the admin design agreed on 2026-09-15 and 2026-09-18
(`docs/planning/admin-roles/DESIGN_primary_admin_and_account_lifecycle.md`,
decisions 1–10). Phase 1 went live in `deploy-2026-09-17b`
(`REPORT_rounds_2026-09-13d_to_17b.md`); this report covers Phase 2's four
PRs, its one host round, and the retirement of the go-live rollback stack
the same evening.

## What shipped

| piece | where | what |
|---|---|---|
| studio purge routes | fork PR [#44](https://github.com/khunmax2/Ups_openMAIC/pull/44) → `e75ef948` | `readStudioPrimary()` reads a third gateway header, `x-deeptutor-primary`, true only beside role `admin`. `/api/studio/admin/accounts`: `GET` lists owner ids with rows, `GET /{id}/footprint` counts, `DELETE /{id}` purges rows in one transaction then media directories and material bytes. Published courses are kept under `deleted:<uid>` (learners keep them); drafts and soft-deleted courses go; shared keys and the organisation's list stay with `updated_by` re-attributed; orphaned asset blobs are marked for the collector. Idempotent; self-purge refused; every purge and refusal logged at WARN. |
| the header | DeepWitya #116 | `/api/auth/status` answers `is_primary`; the gatekeeper sets `x-deeptutor-primary: 1` from it (only beside `admin`, cached with the verdict, stripped from the client on HTTP and websocket); compose passes `STUDIO_PRIMARY_HEADER` to both services; the contract check asserts all three sides; pin → `e75ef948`, image `sha256:8e0a86cd…d248e`. |
| the bin | DeepWitya #117 | Delete sets `deleted_at`: the name stays taken (409 "belongs to a deleted account"), everything stays, the account is locked out everywhere (login says "This account has been deleted"; the studio gatekeeper refuses it through `/status`), device credentials revoked. Restore clears the stamp only. Purge (`?confirm=<name>`, from the bin only, primary only) removes workspace, grant, secrets, MCP file, device-credential records, avatar, guardian links and the record; a file it cannot remove is reported, not raised. Footprint and orphans routes. Users page: Accounts / Bin tabs, days left, restore, a purge dialog that measures both sides and keeps its button off until the exact name is typed, a Leftovers panel. Audit `account_delete` / `account_restore` / `account_purge`. |
| the store guard | DeepWitya #118 | `identity._read_json` raises `UsersStoreUnreadableError` instead of answering `{}` when `users.json` exists but cannot be read or parsed, so no writer can replace the store; the background recovery pass tolerates it for one round instead of dropping leadership. |

Every piece carried a test that was red before it (PGlite on the studio side
with the real schemas; `tests/multi_user/test_account_bin.py`,
`test_status_is_primary.py`, `test_users_store_readable_or_refuse.py`, the
gatekeeper's own suite +7, `web/tests/admin-account-bin.test.ts`).

## Local UAT before the round

Each PR was run locally through the UAT nginx and the **real** gatekeeper
before merge, with the studio on the pulled digest and `deeptutor` built from
the exact branch: PR-A's probe (30 checks: the header reaches the studio for
the primary and not for a promoted admin, a client-sent header is stripped, a
throwaway account's row is listed, measured and purged), PR-B's probe (45
checks: delete → locked out on both sides → name taken → restore → purge on
both sides → orphan purge → refusals → audit) and a Playwright pass on the
users page (19 checks). The local `deeptutor` was rebuilt once more from the
final tag after #118 was folded in, and both passes were repeated.

**The incident.** The first PR-B probe ran `docker exec … python` as root and
wrote `users.json` root-owned 0600. The app, running as `deeptutor`, could not
read it; the old `_read_json` swallowed the error into "no users"; the app's
next write replaced the file with one account, and the four local UAT
accounts lost their records (their workspaces and grants were intact). They
were restored by the user from a script that writes as the app user (same
ids, a temporary password). Two things came out of it: probes now run in the
container only as the app user and create accounts only through the API, and
#118 closes the hazard in the app itself. Nothing on the host was affected.

## Round `deploy-2026-09-19` (= `main` `0737638ce`)

Three halves in one round, two gates ("build", "studio"), 13 steps; the host
reported each and every expected value matched.

- Backups first: `backup-studio.sh` (23 tables) and, because the round
  carries a real purge, a tar of `data/users`, `system/auth`, `grants`,
  `user-secrets` and `user-mcp` taken **from inside the container** (the
  secrets folders are 0700 of the container user and unreadable from the
  host): `users-pre-deploy-20260919.tgz`, 21.99 MB, 2,269 entries.
- `deeptutor2` rebuilt in ~5 min → image `03ce974ec252` (rollback tag
  `pre-deploy-20260919` = `9507ef935c63`, 20 pre-deploy tags kept); markers
  `1 4 4 9 8 2 8` as measured locally; `/api/auth/status` carries
  `is_primary`.
- gatekeeper and studio recreated in one `up --force-recreate`; compose
  brought the studio healthy before starting the gatekeeper. Studio
  `sha256:8e0a86cd…d248e` (rollback value file = `a5962e05…3e82461`),
  markers `35 1`; gatekeeper `PRIMARY_HEADER` ×5 and the env on both
  services; `/deepwitya/studio/api/studio/admin/accounts` without a cookie →
  401 from the gatekeeper. 8/8 healthy, restarts 0.
- After: `studio_account_kv` 5 / shared keys 6 / `studio_org_setting` 2,
  unchanged; OCR `tha+eng`; `users.json` still `deeptutor:deeptutor` 0600.
- `orphan_ids()` (run as `-u deeptutor`) answered **four** ids, not the two
  expected: `u_5b2633ebda` and `u_8d8a93c325` were test accounts deleted
  with the shallow delete before 2026-09-13, invisible until this tool
  existed, beside the known `u_909cf3245b` (old demoadmin) and
  `u_afc706c274` (admin3). The Leftovers panel shows all four; the user
  purges them from the browser.

The user's web checks: delete → bin → restore → delete → typed purge with
both footprints, and the Leftovers panel — passed.

## v1 retired (GO-LIVE §8)

Seven days after go-live, the same evening. Read-only checks first: v1 =
`/home/search/Thoughtmind/Upstream_Deeptutor` (project `upstream_deeptutor`),
four containers up 7 weeks, **zero** labelled volumes (v1 was all bind
mounts). The host Claude stopped at the "down" gate with a real finding: the
v1 directory holds a `compose.yaml` beside `docker-compose.yml`, and a bare
`docker compose down` picks `compose.yaml`, which knows only two services —
`deeptutor-ollama` and `deeptutor-sandbox-runner` would have been left
behind and the network kept. The stack's own `config_files` label named
`docker-compose.yml` + `deploy/docker-compose.localhost.yml`, so the agreed
command was `docker compose -f docker-compose.yml -f
deploy/docker-compose.localhost.yml down`. Before it ran, one more read-only
check: v2 does not use anything of v1 (v1's ollama network holds only v1's
containers; `deeptutor2` has no ollama env or settings; v2 runs its own
`deeptutor2-ollama`).

Result: four containers and the network removed, no volume touched; port
10310 has no listener; v2 8/8 healthy, auth 200 / studio 401; `docker image
prune -f` reclaimed 3.887 GB with every `pre-deploy-*` tag intact; the
`--revert` state file removed by the user with sudo. Kept until about
2026-10-19 per §8: v1's `data/` (1.2 GB) and its image `b1646c428e6c`.
`--revert` to v1 is no longer possible; the rollback of a round is its
previous image, as every round since go-live has recorded.

§8 in `deploy/GO-LIVE.md` now says to read the compose files from the
`config_files` label and to check that v2 does not depend on v1 first.

## Process notes

- **A gate is worth its wait.** The v1 `compose.yaml` trap would have left
  half the stack running with no error worth noticing; the host's rule to
  stop when runbook and host disagree is what caught it.
- **In-container Python runs as the app user, always.** `docker exec` is
  root by default; a root-owned `users.json` is unreadable to the app. Every
  host prompt now says `-u deeptutor` for `python`, and every probe does.
- **Backups of `data/` are taken from inside the container**, for the same
  ownership reason, and verified by listing the archive.
- **A tag can move before it is deployed.** #118 was folded into the round by
  re-pointing `deploy-2026-09-19` at the new merge, rebuilding the local
  image from it and repeating both UAT passes; the prompt's markers were
  re-measured against that image.

## Open after this round

- The user purges the four leftover ids from the panel (or keeps the two
  unknown ones until sure).
- Parked, unchanged: the settings exposure backlog (6 items), studio audit
  F02–F20, `openapi.json` drift, disk growth on the studio volume.
- Possible Phase 3 topics, none started: promoted admins reaching the
  primary admin's knowledge bases and skills; per-admin model catalogs and
  keys across embedding changes; making studio sharing primary-only with the
  header that now exists; returning to upstream's shared admin workspace.
