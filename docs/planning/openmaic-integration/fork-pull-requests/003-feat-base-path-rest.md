# #3 — fix(base-path): cover the shapes `fetch(` never matched

- **State**: MERGED (merged 2026-09-10T13:44:08Z)
- **Branch**: `feat/base-path-rest` → `main`
- **Opened**: 2026-09-10T13:28:18Z
- **Was at**: https://github.com/khunmax2/OpenMAIC/pull/3

---

The first pass converted `fetch('<literal>')` and reported a clean tree. **Running the stack showed the tree was not clean.**

`lib/persistence/bootstrap.ts` hands `baseUrl: '/api/persistence'` to `HttpDocumentStore` and `HttpRuntimeStore` and never reaches a `fetch(` in this repo — so the entire persistence layer was still addressing the origin root while a guard said everything was covered.

## Three shapes

| shape | where | fix |
|---|---|---|
| URL as configuration | `bootstrap.ts` — the two stores | wrapped |
| URL to an injected factory | `owner-session-client.ts` `createEventSource`, `stage-meta-client.ts` `fetchImpl` | wrapped |
| URL through a variable | pbl/v2 `endpoint`, a union of 16 path literals | wrapped once at its single `fetch` — wrapping each would retype the union |

The guard now matches the first two. The third cannot be matched by any static rule, so those two files are exempt **and the exemption is paired with an assertion that `fetch(apiPath(endpoint)` is still there** — remove the wrap and the suite fails.

## Mutation-tested

| mutation | result |
|---|---|
| `baseUrl: apiPath(...)` → bare | CAUGHT, named `bootstrap.ts:49` and `:57` |
| `fetch(apiPath(endpoint))` → `fetch(endpoint)` | CAUGHT by the exemption's own guard |

The config rule is narrowed to `/api/` deliberately: `endpoint: '/v1/audio/speech'` in `lib/audio/voxcpm.ts` is a path on a *provider's* base URL, and prefixing it would send the request here instead.

`tsc --noEmit` clean, eslint clean, 118 passed across `tests/base-path`, `tests/persistence` and the identity suite.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
