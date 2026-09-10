# #2 — feat(base-path): let the app be served under a path, not only at the root

- **State**: MERGED (merged 2026-09-10T13:11:21Z)
- **Branch**: `feat/base-path` → `main`
- **Opened**: 2026-09-10T12:07:16Z
- **Was at**: https://github.com/khunmax2/OpenMAIC/pull/2

---

> **Incomplete on purpose — read this first.** This converts the `fetch('<literal>')` call sites, which is **71 of roughly 139**. It does not break anything as it stands (with the variable unset every path here is a no-op, which is upstream's own deployment), but it is not the whole job. What remains is listed at the bottom.

Next's `basePath` rewrites the URLs **Next** generates. It does not touch a URL the application writes itself. On the deployment this fork exists for that is not a 404: seven applications share one origin and `/api` at the root belongs to another team, so `fetch('/api/stages')` is a request sent to somebody else.

- **`lib/base-path.ts`** — `apiPath()`, idempotent because two layers can apply it, and empty by default so a root deployment behaves exactly as upstream and pays nothing.
- **71 call sites converted**, in 41 files.
- **`tests/base-path/api-path.test.ts`** — the guard, so converted sites do not come back one at a time. It names the file and line; mutation-tested by putting one back, it reported `lib/storage/client.ts:27`.
- `NEXT_PUBLIC_STUDIO_BASE_PATH` is read by `next.config.ts` and `apiPath()` from one variable, because a mismatch is not a build error — it is a working page whose every request goes somewhere else. Declared as a build arg in the `Dockerfile`.

## What is NOT covered

The guard matches `fetch(` and `new EventSource(` followed by a **string literal**. Three shapes slip past it, found by trying to build and run the thing rather than by reading:

| shape | example | why the guard misses it |
|---|---|---|
| a URL passed as configuration | `lib/persistence/bootstrap.ts:48,56` — `baseUrl: '/api/persistence'` into `HttpDocumentStore` / `HttpRuntimeStore` | never reaches a `fetch(` in this repo |
| a URL passed through a variable | `components/scene-renderers/pbl/v2/use-instructor-stream.ts:312` — `fetch(endpoint)`, where `endpoint` is a literal declared elsewhere (16 sites across `pbl/v2`) | the argument is an identifier, not a literal |
| a URL the server builds for the client | `lib/server/agent-runtime/generate-video.ts:210` — `src: '/api/classroom-media/...'` | not a request at all until the browser makes it |

Counted precisely: **71 wrapped, 68 still bare across 32 files** (excluding `app/api/**`, which Next serves under `basePath` on its own). Some of those 68 are server-side path comparisons and doc comments that are correct as they are; `bootstrap.ts` — the whole persistence layer — is not.

The guard should grow to cover the config and variable shapes before the remainder is converted, or the same false confidence repeats.

## Measurement

Same machine, same command:

| tree | tests failed |
|---|---|
| clean upstream `29735f10` | 78, 74 |
| this branch, first guard | 81, 87 |
| this branch, guard excluded | 75 |
| **this branch, guard fixed** | **75** |

The first guard recursed by hand and `statSync`'d every entry; beside 680 other test files that pushed timeout-sensitive tests over the edge. One recursive `readdir` puts it back in the baseline band.

`tsc --noEmit` clean. ESLint clean — the two warnings on changed files were confirmed pre-existing against the stashed tree.

## Other things that went wrong here

- The codemod inserted its import after "the last line starting with `import`", which matched a line inside an interface body far below and broke six files. `tsc` caught it; the replacement tracks the import statement by bracket depth.
- A `\` collapsed to `\` in the guard test, so the file would not parse. It uses `path.sep` now and contains no backslash.
- The `Dockerfile` never declared the build arg, so a build would have silently served at the root.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
