# REPORT — deploy rounds `deploy-2026-09-13d` … `deploy-2026-09-17b` (2026-09-13 → 2026-09-18)

Seventeen tags in six days, fourteen of them deployed. The round record after
`deploy-2026-09-13c` (`REPORT_uat_fixes_2026-09-13.md`) stopped there; this
report closes the gap. Every round followed `deploy/GO-LIVE.md` §11 as an
explicit numbered host prompt, the user typed every sudo step, and each host
result was reported back step by step. The per-change detail is in
`CHANGES.md` under the dates named below; this file is the round-level view.

Two workstreams ran side by side:

- **DeepWitya** (`deeptutor2` rebuilds): UAT fixes from the host, then the
  multi-admin faults that the fork's primary/promoted-admin split had left, and
  finally Phase 1 of the admin design.
- **Course Studio** (studio image recreates): first "the studio stops living in
  one browser", then the record of who shared a key, then the organisation's
  model catalog and its one-button setup.

## Rounds

| tag | main | half | what | host result |
|---|---|---|---|---|
| `13d` | `29c6238a5` | deeptutor2 | #92 quiz after a thinking turn, #93 GeoGebra command repairs + non-blocking refusals, #94 Task models Run test, #91 13c record | 2026-09-13 23:31 — 11/11; image `d09e856b0150` |
| `14` | `970db9364` | deeptutor2 | #95 settings menu / version badge / reading session keep `/deepwitya` | 2026-09-14 01:43 — 11/11; `df1e6a51e719` |
| `14b` | `7a86bbb54` | deeptutor2 | #96 STT converts browser WebM/Ogg/MP4 to WAV (`ptm-asr-1` 422) | 2026-09-14 02:16 — 11/11; `ad642d51ecc4`; backend-only build ~1 min |
| `14c` | `02eb9f305` | deeptutor2 | #97 Settings Run test acts as the caller, never saves a masked key | 2026-09-14 ~05:44 — passed; `00e9545d573a`; step-12 scan: primary catalog intact |
| `14d` | `7dbb0ee1b` | deeptutor2 | #98 promoted admins see the system personas (`reads_deployment_presets`) | 2026-09-14 06:33 — passed; `8c56154333b7` |
| `14e` | `29a628c34` | — | #99 Ask Questions card no longer hangs (`waiting_input` subscribes) | pushed, superseded by 14f |
| `14f` | `cba4bb935` | deeptutor2 | #99 + #100 a promoted admin opens its own KBs (`owns_deployment_workspace`) | 2026-09-14 08:55 — passed; `dadad5770b2f` |
| `14g` | `ddf9bad9a` | studio | pin fork `099b09cf` (#24 custom ASR sent WAV, #25 shared custom provider carries its profile) | 2026-09-14 ~11:55 — 11/11; studio `eca9d2b3…185c03d`; `profile` column created on first use |
| `15` | `320839860` | — | pin fork `1e88d4ce` (#26–#31) | pushed, superseded: the owner's new browser regenerated served images |
| `15b` | `7935f499c` | studio | pin fork `370b1665` (#26–#34: owner-only resume, media on the server, settings/profile per account in `studio_account_kv`, concurrency, served copies) | 2026-09-15 ~04:35 — 11/11; studio `0e25f9d4…8e3113`; **save bug found minutes later** |
| `15c` | `3d64adfea` | studio | pin fork `dc6f05f6` (#35 settings writes send JSON values) | 2026-09-15 ~05:26 — passed; studio `cf1a5809…3a9022`; saves verified on the host at 05:50 |
| `15d` | `0e3938df6` | studio | pin fork `3daa7d00` (#36 `studio_credential.updated_by`, replace/stop confirmations, `[Credentials]` log) | 2026-09-15 ~11:25 — 11/11; studio `869d43c8…5f2c59`; 7 default rows, all pre-record |
| `15e` | `a0627fa1d` | nginx only | #106 `--upload-ceiling`: production `/deepwitya` had no `client_max_body_size` | 2026-09-15 ~14:33 — user typed the sudo step; +2 lines; 2 MB POST → app, was nginx 413 |
| `15f` | `ca864e446` | — | pin fork `3a187aea` (#37 tab keeps to its account, #38 organisation model catalog) | pushed, superseded by 15g |
| `15g` | `063b5688e` | both | 15f's studio + #108 a promoted admin cannot demote/delete the primary admin | 2026-09-16 ~11:11 — 15/15; deeptutor2 `f975515d037b`, studio `7a388c94…e528d1` |
| `17` | `028297b76` | studio | pin fork `8c19f351` (#39–#43: star only after publishing, un-star, one "use for every account" button, TTS tab in the home popover, image quality + `Image took` log) | 2026-09-17 ~10:38 — 11/11; studio `a5962e05…3e82461`; `studio_org_setting` 2 rows |
| `17b` | `13845d818` | deeptutor2 | admin design Phase 1: #111 one recorded owner + `primary_admin show|handover`, #112 only the primary manages admins + audit, #113 disable instead of delete | 2026-09-18 ~11:47 — 10/10; `9507ef935c63`; `show` = `u_8d809b7e`, bootstrap not usable, handover not run |

Host state after 17b: `deeptutor2` `9507ef935c63` (rollback tag
`pre-deploy-20260917b` = `f975515d037b`), studio
`ghcr.io/khunmax2/deepwitya-studio@sha256:a5962e05…3e82461` (rollback value
in `../_deeptutor_backup/pre-deploy-20260917-studio-image.txt` = 15g
`7a388c94…e528d1`), 8/8 healthy, restarts 0, OCR `tha+eng`, gatekeeper 401.
Nightly studio backups run at 03:30; each studio round took one by hand first
(21 → 23 tables over the period: `studio_account_kv`, `studio_org_setting`).
Nineteen `pre-deploy-*` image tags are kept on the host. v1 still runs on
10310 as the §8 rollback until 2026-09-19.

## What shipped, by area

**DeepWitya fixes found in UAT on the host** (CHANGES 2026-09-13/14): a
thinking round ending the request on the model's turn (#92); GeoGebra
commands the model writes repaired before `evalCommand`, dialogs off, refusals
listed under the applet (#93); the Task models page's Run test (#94); the
settings menu dropping the base path (#95); STT recordings normalised to WAV
for libsndfile-backed servers (#96); the Ask Questions card stuck on "Sending
your answers…" (#99).

**The fork's admin split, patched where it misbehaved** (CHANGES 2026-09-14):
upstream gives every admin the one deployment tree; this fork gives it to the
primary admin only, and three places still assumed `is_admin` meant "owns
`data/`": the Settings Run test saving the tester's catalog into the primary
admin's file and then sending `Bearer ***` (#97, plus `secret_guard.py` so no
route saves a mask); system personas withheld from promoted admins (#98,
`reads_deployment_presets`); a promoted admin's own knowledge bases resolved
in the primary admin's tree (#100, `owns_deployment_workspace`). `CLAUDE.md`
records the split as a fork decision that may be reversed.

**Production upload ceiling** (CHANGES 2026-09-15, #106): the go-live cutover
only swapped the port inside the shared `location /deepwitya` block, so nginx's
1 MiB default had refused every DeepWitya upload over 1 MB since go-live. The
fix is a runbook mode, `apply-nginx-golive.sh --upload-ceiling`, proven against
real nginx before the host ran it; `--cutover` and `--revert` carry it now.

**Course Studio, in fork order:**

- `099b09cf` (#24, #25): custom ASR gets WAV; a shared custom provider carries
  its definition (`profile` column), so other accounts can build it.
- `370b1665` (#26–#34): the studio stops living in one browser — owner-only
  generation resume, generated media on the `/app/data` volume, settings and
  profile per account (`studio_account_kv`, upstream's KV contract served by
  the fork), served images not regenerated, thumbnails/exports/timeline read
  the served copies, image concurrency, settings hardening after the user's
  second review. Eighteen new fork test files.
- `dc6f05f6` (#35): the hotfix for 15b — zustand persist handed actions and
  `undefined` fields to the server KV, which refused every write.
- `3daa7d00` (#36): who shared a key is recorded and shown to admins;
  replacing or stopping a share asks first; `[Credentials]` log lines.
- `3a187aea` (#37, #38): a tab keeps to the account it loaded
  (`x-studio-kv-owner`, 409 `OWNER_CHANGED`), deleted built-in models stay
  deleted, an admin publishes the organisation's model list and default
  (`studio_org_setting`). Two bugs were caught by local browser UAT before the
  merge: a stale tab's save beating a fresh tab's newer catalog (`servedAt`),
  and an organisation entry swallowing the account's own copy (`ownCopy`).
- `8c19f351` (#39–#43): the star only after publishing and on every published
  row, un-star, one button "ใช้กับทุกบัญชี" that shares the key and publishes
  the list together (withdrawal cascades), a TTS tab in the home popover, and
  an image quality level with `Image took N ms` in the studio log.

**Admin design, Phase 1** (CHANGES 2026-09-15/17; design in
`docs/planning/admin-roles/`): #108 closed the immediate hole — a promoted
admin could demote and then reset the password of the first admin. The check
that followed found two owners of `data/`, an election that could not pick a
bootstrap account, no audit of account changes, a `disabled` flag nobody read,
and a delete that strands data. The user decided the model on 2026-09-15
(PR #109), and Phase 1 shipped as one PR per step, each tested locally on a
rebuilt image first: #111 exactly one recorded owner and a logged handover
command; #112 only the primary admin promotes, demotes or deletes, with audit
lines and WARNING logs that reach `docker logs`; #113 disable instead of
delete, enforced in `decode_token` so the WebSocket, every route and the
studio gatekeeper refuse a disabled account.

## Evidence

- Every code change carries a test that was red before it (the CHANGES entries
  name them). Studio images were checked by string markers inside the pulled
  image before and after each recreate — the counts in the host prompts were
  measured on the pulled digest, never guessed, and the host reported the same
  numbers every time.
- **Local UAT before the host**, adopted after 15b: the pulled studio digest or
  a `deeptutor` image built from the exact tag is run locally and the changed
  flows are driven with headless-browser scripts or in-container API probes
  (15f/15g/17/17b: `uat-org-catalog`, `uat-org-stale-tab`, `uat-one-button`,
  `uat-tts-popover`, `uat-image-quality`, `uat_primary_owner_probe`,
  `uat_admin_management_probe`, `uat_account_disable_probe` — kept in the
  session scratchpad, not the repo). Three real bugs never reached the host
  because of it (the 15 image regeneration, `servedAt`, `ownCopy`).
- Host read-only re-checks after the user's web tests: 15c saves confirmed at
  05:50 and audit F02 ruled out; 15d's `updated_by` column appeared on the
  first credential request; 17's `studio_org_setting` held 2 rows, 6 shared
  keys, 4 KV rows; 17b's `primary_admin show` named `admin@example.com`.

## Process notes

- **Local UAT is a gate, not an option.** 15b's save bug passed unit tests, CI
  and the in-image marker greps; only a real browser against the real KV route
  showed it. Since then every round runs the new image locally first.
- **`ruff format --check .` before every push.** #113 went red on CI's format
  gate after `precheck.sh` had flagged it; one format-only commit fixed it.
- **A PR can get no CI.** GitHub delivered no `pull_request` events for #110;
  close/reopen and an empty push changed nothing. Evidence came from
  `workflow_dispatch` of `tests.yml` on the branch (all green). If it happens
  again, dispatch first, do not wait.
- **The step-2 "quiet host" criterion was wrong.** A finished agent chat left
  69 gen-log lines and the criterion flagged it; the round was judged safe and
  continued. The criterion now reads the age of the last line and the
  gatekeeper's in-flight connections.
- **Probes can write the real `data/`.** Worker-thread code falls back to
  `./data`; a local probe of the Run test path overwrote the local catalog on
  2026-09-14 (restored from a backup). Isolate with `DEEPTUTOR_HOME` or back up
  first.
- **Docker Desktop must be up before a build** — two builds failed early with
  a missing `OPENMAIC_IMAGE` after a machine restart; the recipe reads the
  image from the running container.
- Backslashes through the Bash tool corrupt regex edits; files with them are
  written with the Write/Edit tools. A cp1252 console needs
  `PYTHONIOENCODING=utf-8` for Thai output.
- Two Claude accounts share this session's memory; branches and PRs are named
  in chat so they do not collide (fork #39–#43, DeepWitya #109/#110 and
  `deploy-2026-09-17` were done by the second account).

## Open after 17b

- The user's web checks of 17b: admin2 cannot promote/demote/delete; the
  disable button; a disabled account locked out of DeepWitya and the studio;
  the audit and `docker logs` lines.
- **Phase 2** (PR #114, agreed 2026-09-18): delete goes through a bin with a
  30-day restore, then a typed primary-only purge on both sides behind a new
  `x-deeptutor-primary` gatekeeper header; published courses survive a purge.
  Sequence: studio PR → DeepWitya PR-A (status flag, header, pin, contract)
  → PR-B (bin, restore, purge, users page) → one host round with a backup.
  Then the two stranded host ids (`u_909cf324…`, `u_afc706c2…`) are purged
  from the leftovers panel.
- Settings exposure audit (2026-09-18): no secrets reach ordinary users; six
  low/medium items parked by the user (MCP env/headers shown to every admin,
  `/api/system/test/*` open to any signed-in user, raw provider errors in Run
  test, studio shared base URLs visible to all accounts, `/api/system/update`
  open, minor `str(e)` leaks). Fix the first before any non-user admin exists.
- Studio audit items F02–F20 await the user's triage; disk use on the
  `/app/data` volume only grows (no GC of replaced media).
- `web/contracts/schema/openapi.json` drifts from the code and no CI job
  checks it.
- Host: remove v1 on 2026-09-19 (§8); the local `deeptutor` container cannot
  resolve `host.docker.internal` (only the studio service has `extra_hosts`).
