# Pull requests on khunmax2/OpenMAIC

Exported so the reasoning survives the pull request pages themselves. They live
here rather than in the fork because ADR-0005 asks the fork to stay a small,
readable set of commits on top of upstream's history, and because the fork
gitignores `/docs` anyway. A PR
body is where a change was argued; the commit messages carry the same
reasoning, but the tables of measurements and the before/after numbers live
here.

- [#1 — feat(auth): derive identity from the gateway, and partition assets by owner](001-feat-deeptutor-identity.md) — `feat/deeptutor-identity`, merged
- [#2 — feat(base-path): let the app be served under a path, not only at the root](002-feat-base-path.md) — `feat/base-path`, merged
- [#3 — fix(base-path): cover the shapes `fetch(` never matched](003-feat-base-path-rest.md) — `feat/base-path-rest`, merged
- [#4 — fix(base-path): carry the base path in stored media references](004-fix-media-src-base-path.md) — `fix/media-src-base-path`, open

## Why these exist

The fork's CI has never run. GitHub disables Actions on a forked repository
until someone enables them by hand, so every one of these was merged on local
measurement — vitest against a measured baseline, `tsc`, `eslint`, and finally
a built image and a running stack — with that stated each time in the PR body.
If enabling CI turns anything red in hindsight, these are the arguments to
check it against.

Re-export with `gh pr list --repo khunmax2/OpenMAIC --state all --json ...`;
the script that produced them is in this file's history.
