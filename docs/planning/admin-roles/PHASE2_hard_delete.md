# Phase 2: delete with a grace period, then purge on both sides

Draft for review, 2026-09-18 (revised the same day after the survey below;
agreed as decision 10). Implements §4 of
`DESIGN_primary_admin_and_account_lifecycle.md`. Built 2026-09-18/19: fork
#44 (the studio routes), DeepWitya #116 (status flag, gatekeeper header,
pin) and the bin/restore/purge PR (#117, with #118); live on the host since
`deploy-2026-09-19`. `docs/reports/REPORT_admin_lifecycle_phase2_2026-09-19.md`
records the round.

## What upstream and other systems do

Checked on 2026-09-18 so the design borrows a known shape instead of
inventing one.

**Upstream HKUDS/DeepTutor `main`.** `delete_user` removes the record,
guardian links and the avatar; the workspace, grants and secrets stay. The
`disabled` flag on a record is never read. No account change is audited, and
any admin deletes any admin. Issue #1230 (open) asks for the first admin to
be demotable. There is nothing to copy.

**Official documentation of the others:**

| system | disable | delete | restore | what the account made |
|---|---|---|---|---|
| Microsoft Entra | sign-in blocked | soft delete, kept 30 days, then permanent (can be forced earlier) | within 30 days, every property back | kept during the 30 days |
| Google Workspace | suspend (recommended over delete); archived licence | kept 20 days, then gone for good | within 20 days, super admin only, username must still be free | **transfer Drive/Calendar ownership first**, otherwise gone |
| Moodle | suspend: no login, data intact (recommended) | `deleted=1`; username and email are overwritten so the name can be reused | partial (reset the flag), enrolments and preferences are lost | **forum posts and submitted files are not deleted** |
| Slack | deactivate only, an admin reactivates | no permanent delete | — | messages and files stay; the primary owner must transfer ownership before deactivating itself |
| GitHub | — | permanent, "GitHub cannot restore" | none | comments move to the `ghost` user; the username is free again after 90 days; sole-owner orgs must be transferred first |

The shape they share, and what this draft adopts:

1. Disable is the everyday action; delete is the last resort. (Phase 1 has
   this.)
2. Delete is not immediate: a grace period with full restore, then a
   permanent purge.
3. What the account shared with others does not follow it out: transfer the
   owner or keep the content and drop the name.
4. The old username can be reused, but it is a new account.
5. The owner cannot delete itself; hand over first. (Phase 1 has this.)
6. Only the top admin purges. (Phase 1: primary-only.)

## The lifecycle after Phase 2

```
active ──disable──▶ disabled ──enable──▶ active
  │                    │
  └──────delete────────┴──▶ in the bin (30 days, restorable)
                                │              │
                             restore        purge (now, or when the
                                │            30 days are up)
                                ▼              ▼
                              active        gone on both sides
```

- **Disabled** (Phase 1): cannot sign in, everything stays, any admin does
  it for ordinary users, the primary for admins.
- **In the bin** (new): the record carries `deleted_at`. The account is out
  of the normal list and shown under a "ถังขยะ" (bin) tab, it cannot sign
  in (same enforcement as disabled: `decode_token`, login, device login,
  `/api/auth/status`), its device credentials are revoked, and every byte on
  both sides stays. The username is still taken while the account is in the
  bin, so re-creating the same name is refused until the purge.
- **Purged** (new): the account and its data are removed on DeepWitya and
  the studio. Nothing runs by itself: the primary admin presses **purge**
  on a row in the bin, and the page shows how many days are left or that
  the 30 days are up. A scheduled purge is deliberately not part of this,
  matching the handover decision that nothing changes owner by itself.

Only the primary admin deletes, restores or purges. The primary admin's own
account and the caller's own account stay refused.

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

- **published stages are kept**: every `document_stages` / `stage_meta` row
  the account owned that is published gets `owner_id = 'deleted:<id>'`, and
  its classroom media stays; the studio shows them as "from an account that
  no longer exists" (this is the Moodle / GitHub `ghost` rule: what learners
  are using does not vanish with its author);
- delete the account's **draft** stages and their rows, then the rows in the
  other tables (`agent_sessions`, `agent_owner_session_events`,
  `agent_owner_session_event_counters`, `agent_user_skill`,
  `document_folders`, `owner_material`, `studio_account_kv`,
  `studio_credential` with `scope = owner`; `asset_entries` by `principal`);
- collect the draft stage ids first, then remove `data/classrooms/<stage>/`
  for each after the transaction commits;
- rewrite `updated_by = 'user:<id>'` to `'deleted:<id>'` in
  `studio_credential` and `studio_org_setting`, so a shared key or the
  organisation's list keeps working and the page can say "shared by an
  account that no longer exists" instead of showing a dead id;
- never touch `scope = 'default'` rows.

It returns the counts per table, the stages kept and the media directories
removed, logs one `[Accounts] Purged user:<id>: …` line, and is idempotent:
purging an owner with nothing left answers 200 with zeros. That is what lets
the host's stranded ids be cleaned up.

`GET /api/studio/admin/accounts/{ownerId}/footprint` returns the same counts
without deleting, for the dialog, including how many published stages will
be kept. `GET /api/studio/admin/accounts` lists the distinct owner ids the
studio holds rows for, so DeepWitya can show studio-only leftovers.

### 3. DeepWitya: delete, restore, purge

Three routes, all primary-only (`_require_primary_admin` from #112):

- `DELETE /api/auth/users/{username}` — **moves the account to the bin**:
  sets `deleted_at`, revokes device credentials, audit `account_delete`.
  Refused for the primary admin and the caller's own account. Nothing is
  removed.
- `POST /api/auth/users/{username}/restore` — clears `deleted_at`, audit
  `account_restore`. The account comes back exactly as it was (still
  disabled if it was disabled before).
- `DELETE /api/auth/users/{username}/purge?confirm=<username>` — a missing
  or wrong `confirm` is 400; the account must be in the bin (409 otherwise,
  so a purge never skips the bin). It removes, in this order:
  1. device-credential records,
  2. `data/system/grants/<id>.json`, `data/system/user-secrets/<id>/`,
     `data/system/user-mcp/<id>.json`,
  3. `data/users/<id>/`,
  4. the account record, guardian links and the avatar (today's shallow
     delete).

  Audit `account_purge` with a summary of what was removed (files, bytes,
  grants, credentials) and the studio counts. Audit lines that mention the
  id are kept.

`load_users` keeps accounts in the bin in `users.json` (they must still block
their username), and `get_users` returns them with `deleted_at` so the page
can split the tabs. `create_user` refuses a username that is in the bin with
"This name belongs to a deleted account; purge or restore it first".

`GET /api/auth/users/{username}/footprint` (primary-only) returns the sizes
for the dialog. `GET /api/auth/orphans` (primary-only) lists ids that have a
workspace, a grant or a secrets folder but no account record.

Both routes refuse the workspace of the primary admin and `data/` itself:
the id must be a `u_…` id, never `local-admin` or `env-admin`.

### 4. The users page

For the primary admin only:

- **Delete** on an active or disabled row asks once ("The account goes to
  the bin. It can be restored for 30 days, then purged.") and moves it.
  No typing: it is reversible.
- A **"ถังขยะ" (bin) tab** lists the accounts with `deleted_at`, each with
  the days left, **Restore**, and **Purge**.
- **Purge** opens the dialog that first fetches both footprints (DeepWitya
  directly; the studio through the same-origin path
  `/deepwitya/studio/api/studio/admin/accounts/user:<id>/footprint`, which
  the gatekeeper forwards with the admin's own session cookie, so no new
  secret and no server-to-server route). It lists what will go on each
  side, what will be kept (published stages, shared keys), and requires the
  username to be typed.
- On confirm: the studio purge first, then the DeepWitya purge. Studio first
  because the studio rows are only findable while the id is known: if the
  DeepWitya purge ran first and the studio call failed, the id would vanish
  from the list and the rows would be stranded. If the studio call fails,
  nothing is deleted and the dialog says so. If the DeepWitya purge fails
  after the studio purge, the account is still in the bin and the button can
  be pressed again; the studio purge is idempotent.
- A **"ข้อมูลค้าง" (leftovers)** panel under the bin lists the ids from
  `/api/auth/orphans` and the studio's owner list that match no account, each
  with the same purge flow. This is how the two stranded host accounts
  (`u_909cf324…` the old demoadmin, `u_afc706c2…` admin3) get cleaned up,
  from the browser, with no cookie pasted anywhere.

Ordinary admins keep the Phase 1 page: disable/enable, no delete, no bin.

### 5. Decided on 2026-09-18

These close the open questions of the first draft:

1. **An admin account can be deleted without demoting it first.** The bin
   is the guard against a slip; a demote step would add nothing but clicks.
2. **Published courses stay.** The purge keeps them with `owner_id =
   'deleted:<id>'`; drafts go with the account.
3. **Three audit actions**, not one: `account_delete` (to the bin),
   `account_restore`, `account_purge`. A Phase 1 shallow delete in an old log
   is `account_delete` without a purge line after it.

What stays out: shared credentials and the organisation's model list (they
belong to the deployment); a scheduled purge; any delete path for ordinary
admins.

## Sequence

One host round at the end; every piece lands behind Phase 1's disable, so the
delete button is unchanged until the round.

1. **Studio PR** (fork): `readStudioPrimary`, the accounts routes with the
   published-stages rule, tests. Merge → `studio-image.yml` → digest.
2. **DeepWitya PR-A**: `is_primary` in `/api/auth/status`, gatekeeper header
   (+ its test), pin bump to the new fork commit with the contract fields,
   contract-check assertions. Local UAT: the header reaches the studio for
   the primary and not for a promoted admin.
3. **DeepWitya PR-B**: `deleted_at` with the bin enforcement, restore, purge
   with cleanup, footprint, orphans, the users page tabs and dialog, tests.
   Local UAT: create an account, give it data on both sides (settings row, a
   draft course, a published course, a KB), delete → it is locked out and
   its name cannot be re-registered → restore → everything is back → delete
   → purge → every location is empty except the published course, now
   "from a deleted account"; a promoted admin gets 403 on all three routes
   and on the studio; the primary's own account is refused.
4. **Host round** `deploy-2026-09-19` (or later): gatekeeper recreate + studio
   recreate + `deeptutor2` rebuild; `backup-studio.sh` and a `data/users`
   snapshot first. Then the user purges the two stranded ids from the
   leftovers panel.

Rollback: the previous images; no database restore needed for the code
change. Purges themselves are irreversible, which is why they are
primary-only, typed, preceded by a backup, and reachable only from the bin.

## Tests

- DeepWitya: `tests/multi_user/test_account_bin.py` (delete locks the account
  out and blocks the name, restore brings it back unchanged, purge refuses an
  account that is not in the bin), `tests/multi_user/test_account_purge.py`
  (every location removed, refusals, confirm, audit summary, orphans),
  `tests/api` for `/status.is_primary`, gatekeeper test for the header,
  contract-check test.
- Studio: `tests/server/accounts.test.ts` (403 without the primary header,
  counts, published stages kept and re-owned, drafts and media removed,
  shared rows untouched, `updated_by` rewrite, idempotent), the identity
  test for `readStudioPrimary`.
- Web: source assertions for the bin tab, the typed-confirm purge dialog and
  the leftovers panel.
