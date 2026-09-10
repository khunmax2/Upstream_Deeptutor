# ADR-0005: Run the Course Studio as a Pinned Sibling Application

## Status

Accepted

## Context

The fork embeds OpenMAIC (MIT, THU-MAIC) as a course studio. The first attempt
imported it as a squashed git subtree at `integration/maic` — 2,832 files, with
22 commits of our own work interleaved inside upstream's files. That shape was
removed from `main` on 2026-09-09 so the integration could be designed again;
the notes are in `docs/maic-fork-export/` and the full design in
`docs/planning/openmaic-integration/OPENMAIC_INTEGRATION_V2_handoff.md`.

The two products cannot become one application. OpenMAIC ships Tailwind v4
against this app's v3, and its 69 Next API routes collide with `web/proxy.ts`,
which forwards every `/api/*` path to FastAPI. The deployment host opens only
443 and already serves five other applications under paths, so `/api` at the
root belongs to other people — the studio must live at a path, never a port, and
no proxy rule may sit at `/api`.

Isolation is a requirement, not a preference: every account reaches the studio
and no account sees another's work. OpenMAIC already partitions documents by an
`owner_id` column enforced inside every mutation transaction, and
`resolveRequestOwnerId(req, responseHeaders, authenticatedOwnerId?)` documents
that third argument as the seam "a future auth integration must thread". Against
upstream `29735f10`, 33 of 37 call sites reach it through one wrapper.

## Decision

- The studio is a separate application in its own container, built from our fork
  of `THU-MAIC/OpenMAIC` and pinned by both commit and image digest. Deploys pull
  an image; nothing is patched, applied, or resolved at deploy time.
- DeepWitya is coupled to it by exactly two things: a URL
  (`DEEPTUTOR_OPENMAIC_URL`, with `?lang`, `?theme`, `?embed=1` on open) and one
  identity header. Providers, API keys, model configuration and storage stay
  independent on both sides.
- Per-user isolation threads DeepTutor's uid into `authenticatedOwnerId` as
  `user:<uid>`, matching the `user:` / `anon:` convention already in upstream's
  tests. PostgreSQL runs as a compose service; the studio owns its schema.
- The gatekeeper verifies the DeepTutor session, injects that header, and strips
  any client-supplied copy. **Trusting the header is sound only while the studio
  container is unreachable except through the gatekeeper** — its README records
  that a direct `GET` with no cookie once answered `200`.
- The route is **`/course-studio`** and the menu is "Course Studio". OpenMAIC's
  brand is absent from the UI; its MIT notice travels as files (`NOTICE`, and
  `LICENSE` copied into the image), which is what the licence asks for.

  *Amended 2026-09-10.* This said `/studio`, on the stated ground that the first
  attempt's `/maic` leaked the vendor into the address bar. Checked while
  restoring the surface: the first attempt **had already fixed that** — the
  archive serves `/course-studio`, labels the menu "Course Studio", and carries a
  permanent redirect from `/maic`. The comparison in the handoff describes where
  that attempt *started*, not where it ended. With the stated reason already
  satisfied, renaming again would cost a second redirect hop and every reference
  that names the route, and buy a shorter path. Attapon chose to keep
  `/course-studio`.

  *Amended again 2026-09-10.* That is DeepWitya's **own** route — the page
  holding the iframe — and it is not the address the studio container answers
  on. The two were never distinguished here because until the fork gained a
  `basePath` there was only one of them. The studio serves under
  **`/deepwitya/studio`**, recorded as `contract.base_path` in
  `openmaic-pin.json` and asserted against the compose healthcheck.

  It sits under DeepWitya's own base path deliberately. nginx matches the
  longest prefix, so `location /deepwitya/studio/` wins over `location
  /deepwitya/` and no rule belonging to another team is touched — the host
  serves seven applications and opening a new location at the root would need
  their agreement, the same way opening a port did. `/deepwitya/course-studio`
  was the obvious name and is the one address that cannot be used: DeepWitya
  already answers there.
- Upstream's DDL constants are pinned in `check_openmaic_contract.py`, and
  `pg_dump` runs before every rebase.

## Consequences

### Positive

- Our changes stay a readable set on top of upstream's real history, so
  `git log`, `blame` and `bisect` all work on the studio.
- Work upstream accepts drops out of the next rebase by itself, so the fork
  shrinks over time rather than accreting.
- A clone of this repository needs nothing extra: with no URL configured the
  studio menu explains how to enable it, and nothing else is affected.
- Isolation reuses upstream's own ownership model rather than a parallel one, so
  roughly six files carry it instead of a container per user.

### Negative

- A second repository to maintain, and a PostgreSQL instance to back up.
- OpenMAIC ships no versioned migrations: every DDL statement is guarded by
  `IF NOT EXISTS`, so a drifted column type is accepted silently and first
  appears as a query succeeding against the wrong types. Each drift needs a
  hand-written `ALTER TABLE`.
- De-branding is permanently fork-private — nobody upstreams the removal of
  their own brand — and reaches past the UI into outbound headers, exported
  video covers, and the saved-course file extension.
- Deleting a DeepTutor account leaves studio rows orphaned, reconciled by an
  admin-run script rather than automatically.

### Neutral

- Switching interface language while the studio is open does not reach it until
  a reload; the parameters are passed on open only.
- Rebasing onto a new OpenMAIC happens for a reason — a security fix, a wanted
  feature — and never on a schedule, because every rebase takes the DDL-drift
  risk.

## Alternatives Considered

- **Vendored subtree, as before**: rejected because it produces a merge conflict
  on every OpenMAIC release and hides our work inside upstream's files. Its one
  advantage — a clone that builds — holds only on the Docker path, since
  `deeptutor start` never launched the studio anyway.
- **A pin plus a patch series applied at build time**: rejected because a
  rejected hunk would break the build and need a person to resolve it. Nothing
  requiring a person may sit in the deploy path.
- **Upstream's stock image with configuration only**: rejected as impossible
  today — de-branding, `basePath` and the identity threading all need code. It
  becomes reachable only once upstream accepts the generic work.
- **A provider bridge sharing keys and model configuration**: built the first
  time and cut from scope; each product configures its own providers.
- **A container per user**: rejected as unnecessary once upstream's `owner_id`
  partitioning was found, and disproportionate in memory and operations.
- **Two-way `postMessage` state binding**: rejected because it is an API between
  two systems that must stay in version step forever and breaks quietly on a
  rebase.
- **Deleting studio rows from a DeepTutor account-deletion webhook**: rejected
  as the provider bridge again in the opposite direction; a reconciliation
  script reads both sides only when a person runs it.
