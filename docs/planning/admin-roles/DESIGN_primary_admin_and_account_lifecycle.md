# Primary admin and account lifecycle: design

Decided with the user on 2026-09-15. Nothing here is built yet except what
PR #108 (`deploy-2026-09-15g`) already shipped. This document is the agreement
that Phase 1 and Phase 2 below implement.

## Why

A promoted DeepWitya admin could demote the first admin and delete it from
Settings ▸ Users. Once demoted, the first admin was also open to a password
reset through the learner routes. PR #108 closed that, but checking who "the
first admin" is turned up a design that never said it clearly:

- **Two accounts can own `data/`.** `primary_admin.py` gives the deployment
  tree to the account recorded in `data/system/auth/primary_admin.json`. It
  *also* treats the bootstrap account from `data/user/settings/auth.json`
  (id `env-admin`) as an owner. On the local UAT deployment both exist, so
  the bootstrap `admin` and the recorded `admin2` share one workspace: chats,
  notebooks, model catalog, personas and knowledge bases.
- **The recorded account was not the first admin.** The election reads
  `users.json` only, so a bootstrap account can never be chosen. Locally it
  picked `admin2`, an account the user created from `admin` and promoted.
  On the host the record names `admin@example.com`, the account first
  registered through the web when multi-user was switched on. That one is
  right. The host's `auth.json` has a username but no password hash, so it
  is not an account at all: `load_users` merges the bootstrap only when both
  are set.
- **Any admin manages any admin.** Promoted admins can promote, demote and
  delete other admins. On 2026-09-15 two admin accounts on the host were
  deleted (by the user, as it turned out). Nothing recorded who did it.
- **Deleting an account strands its data.** `delete_user` removes the record,
  guardian links and the avatar. The workspace (`data/users/<id>/`), grants,
  user secrets and every studio row keyed by `user:<id>` stay. Re-creating
  the same username gets a new id and starts empty.
- **Account changes leave no trace.** Role changes, creations and deletions
  log at INFO, which does not reach `docker logs` (checked locally), and none
  of them writes to `data/system/audit/usage.jsonl`.
- **`disabled` exists but is not enforced.** Account records carry a
  `disabled` flag, and no login or request path reads it.

## Decisions (2026-09-15)

| # | Question | Decision |
|---|---|---|
| 1 | Ship the #108 protection now? | Yes, as `deploy-2026-09-15g`. It protects the right account on the host. |
| 2 | Who is the primary admin? | The `auth.json` bootstrap account when it is usable (username **and** password hash). Otherwise the account recorded in `primary_admin.json`. Exactly one owner of `data/`. |
| 3 | Does the owner change by itself when a usable bootstrap appears later? | No. The election prefers a usable bootstrap only while no owner is recorded. Changing the owner is an explicit server command, and it is logged. |
| 4 | Who manages admins? | Only the primary admin promotes, demotes, disables or deletes an admin. |
| 5 | What does "delete" do? | By default it becomes *disable*: the account cannot sign in, its data stays, and it can be re-enabled. Hard delete is primary-only. It asks for confirmation, then removes the account's data on both DeepWitya and the studio. **Revised 2026-09-18 (decision 10):** delete first moves the account to a bin for 30 days with full restore; the purge is the separate, typed, primary-only step. |
| 6 | Who disables whom? | Any admin disables or enables ordinary users. Only the primary disables admins or hard-deletes anyone. |
| 7 | Audit? | Every create, promote, demote, disable, enable, delete and owner handover records the actor, the target and the time. |
| 8 | Course Studio: who shares, replaces or stops a shared API key? | Unchanged: any admin, with the record and the confirmations that shipped in `deploy-2026-09-15d`. |
| 9 | Course Studio: who publishes the organisation's model list and default model? | Unchanged: any admin, with the record that ships in `deploy-2026-09-15g`. |
| 10 | (2026-09-18) Is a delete immediate? | No. Delete = the account goes to a bin: locked out, name still taken, every byte kept, restorable by the primary admin for 30 days. Purge is a second, typed, primary-only action from the bin, never scheduled. Published courses survive a purge as "from a deleted account"; drafts go. An admin can be deleted without demoting first. Audit: `account_delete`, `account_restore`, `account_purge`. Shape taken from Entra / Google Workspace (soft delete + restore window) and Moodle / GitHub (shared content outlives its author); see `PHASE2_hard_delete.md`. |

## Design

### 1. One recorded owner

`primary_admin.json` becomes the only answer to "who owns `data/`".

- **Election.** It runs only when no record exists. A usable bootstrap
  account wins and is recorded as `env-admin`. Otherwise the earliest-created
  admin in `users.json` wins, as today.
- **The `env-admin` sentinel.** It no longer owns `data/` on its own. It owns
  it only when it is the recorded owner. `local-admin` (auth disabled) is
  unchanged.
- **Handover command.** The owner changes only through the command, for
  example `python -m deeptutor.multi_user.primary_admin handover <username | env-admin>`,
  run on the server.
  - It refuses a target that is not an admin, or a bootstrap account that is
    not usable.
  - It writes the record and an audit line.
  - It prints what moves: `data/` stays where it is and now belongs to the new
    owner. The previous owner works in `data/users/<id>/` from then on. What
    it made inside `data/` stays in `data/`.
- **A record that names a deleted account.** `data/` waits, as today. The
  handover command is the fix.

**Host impact:** none. The record stays `admin@example.com`, and the
bootstrap there is not usable.

**Local impact:** after Phase 1 ships, run the command once to hand `data/`
from `admin2` to `admin`.

### 2. Who manages admins

These actions answer 403 unless the actor is the primary admin:

- `PUT /api/auth/users/{u}/role` when the target is an admin or the new role
  is `admin`
- disabling an admin
- every hard delete

The primary admin can still not demote, disable or delete itself.

Other admins keep:

- creating accounts (always as `user`)
- managing ordinary users' grants, presets, book permissions and learner
  profiles
- disabling and enabling ordinary users

### 3. Disable instead of delete

- **Route.** `PUT /api/auth/users/{u}/disabled` with `{ "disabled": bool }`.
  The permissions are those in §2 and decision 6.
- **Enforcement.**
  - Login refuses a disabled account.
  - Every authenticated request refuses one too. Tokens are stateless, so the
    check looks the account up per request; `users.json` is small, so it can
    be cached by mtime.
  - Disabling revokes the account's device credentials.
  - `/api/auth/status` answers "not signed in", so the Course Studio
    gatekeeper refuses it as well.
- **Data.** Everything stays: the workspace, grants, guardian links and
  studio rows.

### 4. Hard delete (Phase 2)

The worked-out plan is `PHASE2_hard_delete.md` (draft 2026-09-18, revised
the same day with decision 10: a bin with a 30-day restore comes before the
purge, and published courses are kept).

Primary admin only. The purge dialog makes the admin type the username and
lists what will be removed and what will be kept.

**DeepWitya removes:**

- `data/users/<id>/`
- `data/system/grants/<id>.json`
- `data/system/user-secrets/<id>/`
- the account's `data/system/user-mcp` file
- device credentials, guardian links and the avatar

Audit lines that mention the id are kept.

**The studio removes** every row owned by `user:<id>`, in these tables:

- `agent_sessions`
- `agent_owner_session_events`, `agent_owner_session_event_counters`
- `agent_user_skill`
- `document_folders`, `document_stages`
- `stage_meta`
- `owner_material`
- `asset_entries` (by `principal`)
- `studio_account_kv`
- `studio_credential`

It also removes the classroom media files of the stages that account owned.
Authorship columns (`updated_by`) are kept.

Shared credentials are **not** removed. A shared row carries `scope =
'default'` and an empty `owner_id`, so it belongs to the deployment rather
than to the admin who shared it, and every account keeps working. Its record
then names an account that no longer exists, and the key row says so instead
of showing a dead id.

**Open item for Phase 2: the studio call.** The studio trusts only the
gatekeeper's `x-deeptutor-owner` and `x-deeptutor-role` headers, and it
cannot tell the primary admin from another admin. The proposal:

- The gatekeeper adds `x-deeptutor-primary: 1` for the primary admin. This is
  a contract change: `openmaic-pin.json` and `check_openmaic_contract.py`.
- The studio gains an admin route that purges an owner's rows and requires
  that header.
- DeepWitya calls it through the gatekeeper as part of the hard delete.

**Host cleanup, with the tool in place:**

- the old `demoadmin` (`u_909cf324…`): 4 credential rows, 1 settings row and
  `data/users/u_909cf…`
- `admin3@example.com` (`u_afc706c2…`)

### 5. Audit

`log_admin_action` gets these actions:

- `account_create`
- `account_role_set` (with before and after)
- `account_disable`, `account_enable`
- `account_delete`
- `primary_handover`

Each line records the actor's id. The same events also log at WARNING, so they
reach `docker logs`.

### 6. The users page

- **The primary admin's row.** Keeps the "Primary admin" label. Both
  `env-admin` and the recorded account show it today; after §1 only the
  recorded owner does.
- **Admin rows seen by other admins.** Role, disable and delete are disabled,
  with the tooltip "Only the primary admin manages admins".
- **Ordinary users.** A disable/enable toggle for every admin.
- **Delete.** Visible to the primary admin only. It opens the type-to-confirm
  dialog from §4.

### 7. Course Studio: providers and API keys

The studio keeps the rules it has. Nothing in §1–§6 changes them.

What it does today:

- Every account's keys live on the server, one row per account and provider.
- A provider has one shared row that serves every account without its own key.
  An account's own key always wins over it.
- Any admin shares their key, replaces the key another admin shared, or stops
  a share. Since `deploy-2026-09-15d` each shared row records who wrote it,
  the page shows that to admins, and replacing or stopping asks first. Every
  change is logged.
- A shared custom provider carries its definition, so the receiving account
  can use it.
- Any admin publishes the organisation's model list and default model
  (`deploy-2026-09-15g`), recorded and logged the same way.

Why the primary admin does not appear here: the studio learns only `admin` or
`user` from the gatekeeper. Making any of this primary-only would need the
`x-deeptutor-primary` header from §4, so it can be tightened later at little
cost if the user changes their mind. The decision on 2026-09-16 is to keep it
as it is.

## Phases

**Phase 1: DeepWitya only.** It needs a `deeptutor2` rebuild. It covers §1,
§2, §3, §5 and §6, without hard delete.

- Tests go red before each change.
- Local UAT includes the handover `admin2` → `admin`.

Progress (one step per PR, each tested locally first):

1. §1 one recorded owner + the handover command — PR #111, merged.
2. §2 only the primary admin manages admins, with the §5 audit lines for
   create, role change and delete — PR #112, merged.
3. §3 disable instead of delete, with the §6 users page — PR #113, merged
   (`deploy-2026-09-17b`). Enforcement lives in `decode_token`, the one gate
   every request, the WebSocket upgrade and `/api/auth/status` pass.

**Phase 2: DeepWitya, studio and gatekeeper.** It covers §4 (bin, restore,
purge) and the studio purge route, then the host cleanup of the stranded
accounts. Plan: `PHASE2_hard_delete.md`.

## Not decided here

- Whether promoted admins can reach the primary admin's knowledge bases and
  deployment skills. This stays open, as in CLAUDE.md.
- Whether to go back to upstream's single shared admin workspace. That is
  still possible later, and this design makes it smaller: one owner, one
  handover command.
