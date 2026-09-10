# #4 — fix(base-path): carry the base path in stored media references

- **State**: OPEN
- **Branch**: `fix/media-src-base-path` → `main`
- **Opened**: 2026-09-10T14:42:00Z
- **Was at**: https://github.com/khunmax2/OpenMAIC/pull/4

---

`generate-image.ts`, `generate-video.ts` and `classroom-media-bytes.ts` write a `/api/classroom-media/...` reference into the scene document, which the browser later requests as a `src`. `lib/server/media-origin.ts` calls those references **origin-independent** — and they are, but a base path is not an origin, and a bare `/api/...` resolves against the root, which on a shared host is another team's API rather than a 404.

## Why at write, not at render

Prefixing at render lands in `@openmaic/renderer`, a package published on its own, which should not learn about this app's base path — and there is no single seam in the app between the document and that package.

## The cost, stated rather than hidden

A stored reference now carries the deployment's base path. Changing it — the `/deepwitya2` → `/deepwitya` cutover is a known one — needs one `UPDATE` over the scene documents. That belongs in the runbook, and it is free while the database is empty, which is why the decision was taken now.

## The part that would have been silent

The predicate deciding *"did we generate this, or is it the learner's own pick"* accepts **both** shapes. Failing to recognise the older one would not 404 — it would start treating our own past output as something to preserve, and generation would quietly stop replacing it. Eight tests cover both shapes, the absolute form the classic pipeline persists, another stage's media, and a learner's own URL.

Baseline checked: `tests/media` and the two media suites fail the same three tests on a clean checkout as they do here.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
