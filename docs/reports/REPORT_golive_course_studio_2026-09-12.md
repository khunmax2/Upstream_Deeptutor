# REPORT — Course Studio go-live, 2026-09-11 → 2026-09-12

Closes the go-live phase of the Course Studio integration (ADR-0005). The
running record is in `CHANGES.md` (entries dated 2026-09-11 and 2026-09-12);
the operational procedure, with what this run taught it, is
`deploy/GO-LIVE.md`. This report is the phase summary.

## Outcome

| | |
|---|---|
| cutover | 2026-09-12 00:10 host time, `apply-nginx-golive.sh --cutover 10310 10320`, ~5 s |
| DeepWitya | built on the host from tag `golive-2026-09-11` = `main` `b119ee12c`, base path `/deepwitya`, frontend 10320 |
| Course Studio | `ghcr.io/khunmax2/deepwitya-studio@sha256:4f54b507257fdd8453495ac2bd7206ed8a1e59f79b473c67489b05765f4dee6d`, built by `studio-image.yml` from fork `d5585dd3`, pulled by digest |
| path | `https://203.185.144.41/deepwitya` (app), `/deepwitya/studio` (gatekeeper 10330 → studio), `http://` → 301 |
| verified from outside | new code answers (`learning_policy` in `/api/auth/status`), studio refused without a session (`not_signed_in` → `/deepwitya/login`), assets under the base path, neighbouring applications unchanged |
| removed | `/deepwitya2` locations, the loopback preview server |
| rollback | v1 still running on 10310; `--revert` restores `:443` and `:80` byte-for-byte; kept until 2026-09-19 |
| data | DeepWitya `data/` continued from the validated `/deepwitya2` stack (deploy config is what mattered; user data was test data); studio database created fresh |
| watch | 8/8 healthy, `RestartCount` 0 on all eight through the browser checklist and the first 30 minutes |

## How it was run

Two Claude Code sessions: one on the host, in the checkout, measuring and
diagnosing; one on the dev machine, holding the repository. Attapon relayed
reports between them and typed every `sudo` step himself — the host session
has no TTY and cannot enter a password, which the runbook's §9 now states.

The rule was: when the host disagrees with the runbook, fix the runbook, not
the host. It was exercised four times in one evening, each as a PR to
`main`, a merge, and a moved tag, after which the host ran
`git fetch origin --force --tags && git checkout golive-2026-09-11`:

| PR | what the host showed | fix |
|---|---|---|
| #71 | — | first image digest recorded in the pin (`built: true`) |
| #72 | `:80 /deepwitya` is a `proxy_pass` to v1, not a redirect; a port swap would have sent plain-HTTP visitors to a stack whose `Secure` cookie never sticks | cutover adds one `return 301` line on `:80`; revert removes it; both shared files round-trip byte-identical |
| #73 | `deeptutor-openmaic-postgres` in a restart loop, `exec docker-entrypoint.sh: operation not permitted`; the studio and gatekeeper never started behind `depends_on` | the host's known `no-new-privileges` quirk (kernel 6.8 + Docker 29 + AppArmor, REDEPLOY §6) — unset for the studio's three services in the production overlay, marked this-host-only, accepted as a deliberate relaxation |
| #74 | preview on `127.0.0.1:8443` "succeeded" (`nginx -t` ok, reload returned 0) but the browser got `Server: kong/3.9.1` — port 8443 belongs to a supabase-kong container on `0.0.0.0`; nginx logged `bind() failed` and kept the old config, and the stale file would have failed the cutover's reload the same way | preview port is an argument; refused if anything listens; listener verified after reload; `--cutover` refuses while a stale preview exists |

Before anything on `:443` changed, the whole stack was exercised at its real
path through an SSH tunnel to the loopback preview: admin login, a chat
turn, no missing assets, the studio framed, a server-side key surviving a
reload as a mask, a Thai course whose simulation buttons are Thai, and a
`learner` account refused with the friendly page.

## What the host taught the runbook

Folded into `deploy/GO-LIVE.md` (lessons table at the end): filter
`docker ps` by compose project label, v1 shares the name prefix; §3.3 must
be repeated after any container restart, because the app resets directory
modes to 700; the gatekeeper writes no per-request log, so status codes come
from the nginx access log under `sudo`; the dev machine's own 8443 was taken
by an IDE, so the tunnel's local side is 18443; a stale `ssh -L` from the
previous attempt kept answering on 18443 until its process was stopped.

## Left open

- The studio's `custom-image` provider (`qwen-image-2512`) points at an
  endpoint the host cannot reach — image generation fails in ~200 ms while
  TTS on the same kind of provider works. A URL to correct in the studio's
  Settings; not part of the cutover.
- The gatekeeper could log one line per request (method, path, status,
  owner id); today it logs only a boot banner.
- §8 on 2026-09-19: `docker compose down` v1 (no `-v`), no `system prune -a`.
- Threat-model backlog unchanged (T12 headers, orphaned studio data after
  an account is deleted, `studio_credential` at rest).
