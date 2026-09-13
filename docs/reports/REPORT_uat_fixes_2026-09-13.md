# REPORT — UAT bug fixes and deploy `deploy-2026-09-13c` (2026-09-13)

Post-go-live update round. Five bugs found in local UAT and on production were
fixed, verified in local UAT, and deployed together by `deploy/GO-LIVE.md` §11.

## What shipped

| Area | Symptom | Root cause | Fix | PR |
|---|---|---|---|---|
| Deep Research | quick "report" died after the outline: `Queue has reached maximum capacity (2)` | auto decompose modes size the outline with `auto_max_subtopics`, the pipeline read only `initial_subtopics` (None → 5); the queue cap was applied to the user-confirmed outline | read the mode's key; size the queue to the confirmed outline (mid-research appends still bounded) | #87 |
| Course Studio TTS | custom TTS provider with key only → OpenAI "Incorrect API key" | our F2 rule (stored key ⇒ stored URL) + the provider URL never stored with the key + OpenAI fallback URL | browser stores the provider's URL with the key and backfills own rows; server refuses a custom TTS without URL | fork #23, pin #85 |
| Math animator | "requires optional dependencies" | Manim not in the image; the runtime `DEEPTUTOR_EXTRAS` hook cannot build pycairo (no compiler in production) | build Manim in `python-base`; runtime cairo/pango libs named in production | #89 |
| Math animator | Thai labels drawn as boxes | the image had no Thai font | `fonts-thai-tlwg` | #89 |
| Math animator | a stray `MathTex` fails the whole request | no LaTeX | LaTeX set (`texlive-latex-*`, `-fonts-recommended`, `-science`, `cm-super`, `dvisvgm`); the smaller set fails on Manim's default template | #89 |
| Math animator | `PermissionError: '/root/.config/manim/manim.cfg'` | upstream: supervisord `user=` keeps `HOME=/root`, account has no home | `/home/deeptutor` + `HOME` in both backend programs | #89 |
| Visualize (GeoGebra) | "GeoGebra script failed to load" | intermittent `net::ERR_CONNECTION_RESET` to geogebra.org's CDN (2 of 12 fresh loads), loader gave up on the first error | `web/lib/load-script-with-retry.ts`: 3 tries, per-try timeout | #90 |

Runbook: §11 pulls the studio image as its own step before the gate (#86); the
per-round prompt checks out the tag before reading §11 (#88); host prompts are
written as explicit numbered steps copied from §11 of the tag (user preference).

## Evidence

- Every fix has a regression test that was red on the old code/Dockerfile
  before the fix (`test_confirmed_outline_capacity.py`,
  `test_dockerfile_math_animator.py`, `load-script-with-retry.test.ts`, fork
  `custom-tts-endpoint.test.ts` + `credentials/client.test.ts`).
- Local UAT: 8 Deep Research turns after the fix all `completed`; custom TTS
  key-only synthesis reaches the provider; MathTex + Thai `Text` rendered in the
  running container; backend HOME read from the real process (ptrace sidecar);
  GeoGebra loads repeatedly.
- Probes kept outside the repo: API probe for the custom TTS key-only case (old
  image → OpenAI error, new → "requires a base URL"); headless-Chrome GeoGebra
  load probe (12 fresh contexts).

## Deploy `deploy-2026-09-13c` (= `main` `fda48c0a7`)

12 steps, all passed; host reported each.
- `deeptutor2` → image `f7e595ea3b55…` (2.57 GB by `docker image inspect`, was
  1.66 GB); build ~4 min thanks to the host's layer cache.
- studio → `sha256:1862c324…4485` (fork `b1c73fd2`); pulled before the gate in
  under a minute; recreate only, gatekeeper answered 401.
- 8/8 healthy, RestartCount 0; `auth/status` enabled; OCR `tha+eng`.
- Rollback points: `upstream_deeptutor_v2-deeptutor:pre-deploy-20260913c`
  (`289082cab43f…`), studio backup `20260913-191356` (21 tables). The nightly
  studio backup cron ran by itself for the first time at 03:30 the same day.
- `settings/` was back at 700 after the build again; the chmod step before the
  studio gate kept the studio step from failing.
- Tag `deploy-2026-09-13b` was pushed and superseded without being deployed.

## Process notes

- A fix branch was once cut from an open docs branch, so PR #87 carried #86's
  commit and GitHub marked #86 merged early. Rule since: cut every branch from a
  fresh `main` and check `git log origin/main..HEAD` before opening the PR.
- `docker exec -u deeptutor` sets HOME from passwd and hid the HOME bug; verify
  "as the app" by reading the backend's real environment.
- Backslashes passed through the Bash tool can collapse; files carrying
  backslashes are written with the Write/Edit tools.

## Backlog (next round)

- GeoGebra: the model can emit `Point(i, j)` (invalid; a coordinate is
  `(i, j)`) — add a validator rule limited to numeric literals and enclosing
  `Sequence` loop variables (`Point(c, 0.5)` is valid and must stay); set
  `showErrorDialogs: false` and show a non-blocking "N commands failed" notice.
- Custom TTS errors carry the adapter's "OpenAI TTS API error" prefix even for a
  custom endpoint (cosmetic).
- Stale key-only rows `custom-tts-1789215968278` and `custom-tts-1789115180757`
  (own + shared) in local UAT; harmless.
- §8: remove v1 on 2026-09-19 — first list host-only commits in both checkouts
  (`git log --branches --not --remotes`).
