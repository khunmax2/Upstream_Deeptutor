# Phase 2: hard delete, with the account's data gone on both sides

Draft for review, 2026-09-18. Implements §4 of
`DESIGN_primary_admin_and_account_lifecycle.md`. Nothing here is built yet.
Phase 1 (`deploy-2026-09-17b`) is live: only the primary admin deletes, and
"delete" is still the shallow delete that strands data, so the delete button
is the one thing on the users page that still does the wrong thing.

## What Phase 2 changes

Today `DELETE /api/auth/users/{u}` removes the account record, guardian links
and the avatar. Everything else the account owned stays:

| where | what stays today |
|---|---|
| DeepWitya | `data/users/<id>/` (chats, notebooks, knowledge bases, settings), `data/system/grants/<id>.json`, `data/system/user-secrets/<id>/`, `data/system/user-mcp/<id>.json`, device-credential records |
| Course Studio | every row with `owner_id = 'user:<id>'` in `agent_sessions`, `agent_owner_session_events`, `agent_owner_session_event_counters`, `agent_user_skill`, `document_folders`, `document_stages`, `stage_meta`, `owner_material`, `studio_account_kv`, `studio_credential (scope owner)`; `asset_entries` by `principal`; the classroom media files of that account's stages under `data/classrooms/<stage>/` |

After Phase 2 a delete removes all of it, only the primary admin can do it,
the dialog shows what will go and makes the admin type the username, and the
two stranded accounts on the host (`u_909cf324…` the old demoadmin,
`u_afc706c2…` admin3) can be cleaned up the same way.

## Design

### 1. The studio learns who the primary admin is

The studio trusts two headers the gatekeeper sets from DeepWitya's
`/api/auth/status`: `x-deeptutor-owner` and `x-deeptutor-role`. A purge must
be primary-only, and `role` cannot say that. So:

- `/api/auth/status` gains `is_primary: bool` (from `is_primary_admin_account`).
- The gatekeeper sets `x-deeptutor-primary: 1` when `is_primary` is true, and
  strips any such header a client sends, as it does for the other two.
  Env `STUDIO_PRIMARY_HEADER`, default `x-deeptutor-primary`.
- The studio reads it in `studio-identity.ts` (`readStudioPrimary(headers)`),
  true only when the role header is `admin` too.
- The contract: `openmaic-pin.json` gains `primary_header` and
  `primary_header_studio_reads`; `check_openmaic_contract.py` asserts the
  gatekeeper sets it, compose passes one name, and the fork reads it.

### 2. The studio purge route

`DELETE /api/studio/admin/accounts/{ownerId}` in a new
`lib/server/accounts/routes.ts`. Refuses without role `admin` **and** the
primary header (403). `ownerId` is `user:<id>`, validated like the identity
header.

In one transaction, for that owner:

- delete the rows in the ten tables above (`asset_entries` by `principal`);
- collect the stage ids from `stage_meta` / `document_stages` first, then
  remove `data/classrooms/<stage>/` for each after the transaction commits;
- rewrite `updated_by = 'user:<id>'` to `'deleted:<id>'` in
  `studio_credential` and `studio_org_setting`, so a shared key or the
  organisation's list keeps working and the page can say "shared by an
  account that no longer exists" instead of showing a dead id;
- never touch `scope = 'default'` rows.

It returns the counts per table and the media directories removed, logs one
`[Accounts] Purged user:<id>: …` line, and is idempotent: purging an owner
with nothing left answers 200 with zeros. That is what lets the host's
stranded ids be cleaned up.

`GET /api/studio/admin/accounts/{ownerId}/footprint` returns the same counts
without deleting, for the dialog. `GET /api/studio/admin/accounts` lists the
distinct owner ids the studio holds rows for, so DeepWitya can show studio-only
leftovers.

### 3. DeepWitya's hard delete

`DELETE /api/auth/users/{username}?confirm=<username>` (primary-only since
#112; a missing or wrong `confirm` is 400). It removes, in this order:

1. device credentials (revoke, then remove the records),
2. `data/system/grants/<id>.json`, `data/system/user-secrets/<id>/`,
   `data/system/user-mcp/<id>.json`,
3. `data/users/<id>/`,
4. the account record, guardian links and the avatar (as today).

Audit `account_delete` gains a summary of what was removed (files, bytes,
grants, credentials). The primary admin and the caller's own account stay
refused. Audit lines that mention the id are kept.

`GET /api/auth/users/{username}/footprint` (primary-only) returns the sizes
for the dialog. `GET /api/auth/orphans` (primary-only) lists ids that have a
workspace, a grant or a secrets folder but no account record.

Both routes refuse the workspace of the primary admin and `data/` itself:
the id must be a `u_…` id, never `local-admin` or `env-admin`.

### 4. The users page

For the primary admin only:

- **Delete** opens a dialog that first fetches both footprints (DeepWitya
  directly; the studio through the same-origin path
  `/deepwitya/studio/api/studio/admin/accounts/user:<id>/footprint`, which
  the gatekeeper forwards with the admin's own session cookie, so no new
  secret and no server-to-server route). It lists what will go on each side
  and requires the username to be typed.
- On confirm: the studio purge first, then the DeepWitya delete. Studio first
  because the studio rows are only findable while the id is known: if the
  DeepWitya delete ran first and the studio call failed, the id would vanish
  from the list and the rows would be stranded. If the studio call fails,
  nothing is deleted and the dialog says so. If the DeepWitya delete fails
  after the purge, the account still exists and the button can be pressed
  again; the purge is idempotent.
- A **"ข้อมูลค้าง" (leftovers)** panel at the bottom lists the ids from
  `/api/auth/orphans` and the studio's owner list that match no account, each
  with the same purge flow. This is how the two stranded host accounts get
  cleaned up, from the browser, with no cookie pasted anywhere.

Ordinary admins keep the Phase 1 page: disable/enable, no delete.

### 5. What stays out

- Published courses of the deleted account go too. A learner who had one
  open loses it. The dialog says so. (Open question below.)
- Shared credentials and the organisation's model list stay.
- No undo: the design chose disable for anything reversible.

## Sequence

One host round at the end; every piece lands behind Phase 1's disable, so the
delete button is unchanged until the round.

1. **Studio PR** (fork): `readStudioPrimary`, the accounts routes, tests.
   Merge → `studio-image.yml` → digest.
2. **DeepWitya PR-A**: `is_primary` in `/api/auth/status`, gatekeeper header
   (+ its test), pin bump to the new fork commit with the contract fields,
   contract-check assertions. Local UAT: the header reaches the studio for
   the primary and not for a promoted admin.
3. **DeepWitya PR-B**: hard delete with cleanup, footprint, orphans, the
   users page dialog and the leftovers panel, tests. Local UAT: create an
   account, give it data on both sides (settings row, a course, a KB), purge,
   verify every location is empty; a promoted admin gets 403 on both sides;
   the primary's own account is refused.
4. **Host round** `deploy-2026-09-18` (or later): gatekeeper recreate + studio
   recreate + `deeptutor2` rebuild; `backup-studio.sh` and a `data/users`
   snapshot first. Then the user purges the two stranded ids from the
   leftovers panel.

Rollback: the previous images; no database restore needed for the code
change. Purges themselves are irreversible, which is why they are
primary-only, typed, and preceded by a backup.

## Tests

- DeepWitya: `tests/multi_user/test_account_purge.py` (every location
  removed, refusals, confirm, audit summary, orphans), `tests/api` for
  `/status.is_primary`, gatekeeper test for the header, contract-check test.
- Studio: `tests/server/accounts.test.ts` (403 without the primary header,
  counts, shared rows untouched, `updated_by` rewrite, idempotent), the
  identity test for `readStudioPrimary`.
- Web: source assertions for the typed-confirm dialog and the leftovers panel.

## Open questions

1. Delete an **admin** account outright, or require demoting it first? The
   main design lets the primary delete anyone; demote-first would be one more
   guard against a slip.
2. A deleted account's **published courses**: remove with the account (this
   draft), or keep them readable and just drop the owner?
3. Keep `account_delete` as the audit action, or add `account_purge` so a
   Phase 1 shallow delete and a Phase 2 purge can be told apart in the log?
