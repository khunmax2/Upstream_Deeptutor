# Removing the OpenMAIC brand from the embedded classroom — 2026-09-07

**Branch:** `feat/openmaic-subtree` · local only, not pushed
**Scope:** `integration/maic` (the vendored OpenMAIC subtree) + the pin it is verified against
**Files touched:** 64 — 62 modified, 2 added, 4 deleted

---

## What the app looked like before

Six surfaces named the product, and a seventh spelled the name out:

| Where | What it showed |
|---|---|
| Browser tab | `OpenMAIC` |
| Home hero | OpenMAIC wordmark, 1232×269 |
| Home hero, under the logo | *Generative Learning in **M**ulti-**A**gent **I**nteractive **C**lassroom* |
| Home footer | "OpenMAIC Open Source Project" |
| Classroom sidebar | the wordmark again |
| PBL v2 workspace header | the square mark |
| Access-code gate | the word `OpenMAIC` under the shield |

`lib/brand/brand-config.ts` already existed as the single place a brand is
declared, and three surfaces read it. The seven above did not — they hardcoded
`/logo-horizontal.png` and the literal string beside it. The config was a source
of truth that most of the app ignored.

---

## 1 · Logos and the product name

**The config is now the only place the brand is written**, and it reads the
environment first:

```ts
// lib/brand/brand-config.ts
productName: process.env.NEXT_PUBLIC_BRAND_NAME       || 'DeepWitya',
logoSrc:     process.env.NEXT_PUBLIC_BRAND_LOGO       || '/brand-wordmark.png',
markSrc:     process.env.NEXT_PUBLIC_BRAND_MARK       || '/brand-mark.png',
themeColor:  process.env.NEXT_PUBLIC_BRAND_THEME_COLOR|| '#b0501e',
tagline:     process.env.NEXT_PUBLIC_BRAND_TAGLINE    || 'Agent-Native Learning',
```

`NEXT_PUBLIC_*` is inlined by Next at build time, so changing any of these needs
a **rebuild**, not a restart.

The default is the host product, taken from what DeepTutor already calls itself
(`web/app/layout.tsx:26` and the login footer): **DeepWitya · Agent-Native
Learning**. Nothing was invented.

### Assets

| Action | File |
|---|---|
| deleted | `integration/maic/public/logo-horizontal.png` (148 KB) |
| deleted | `integration/maic/public/openmaic-mark.png` (15 KB) |
| added | `integration/maic/public/brand-wordmark.png` — 1035×269, from `web/public/banner.png` |
| added | `integration/maic/public/brand-mark.png` — 128×128, from `web/public/logo.png` |
| replaced | `integration/maic/app/favicon.ico` — 16/32/48/64 from the host mark |
| replaced | `integration/maic/app/apple-icon.png` — 180×180 from the host mark |

### Code rewired to read the config

| File | Was |
|---|---|
| `app/layout.tsx:40` | `title: 'OpenMAIC'` + a product description |
| `app/page.tsx:840` | `src="/logo-horizontal.png" alt="OpenMAIC"` |
| `app/page.tsx:869` | `{t('home.slogan')}` — the MAIC backronym |
| `app/page.tsx:1352` | the "OpenMAIC Open Source Project" footer — **removed outright** |
| `components/stage/scene-sidebar.tsx:134` | `src="/logo-horizontal.png" alt="OpenMAIC"` |
| `components/scene-renderers/pbl/v2/workspace.tsx:445` | `src="/openmaic-mark.png" alt="OpenMAIC"` |
| `components/access-code-modal.tsx:121` | the literal `OpenMAIC` |
| `components/workbench/workspace/WorkspaceHome.tsx:161` | `{t('home.slogan')}` |

---

## 2 · The brand leaving the machine

Three places carried it outward, where deleting a logo would never have reached.

| File | Was | Now |
|---|---|---|
| `lib/web-search/searxng.ts:17` | `User-Agent: Mozilla/5.0 (compatible; OpenMAIC/1.0; +https://github.com/THU-MAIC/OpenMAIC)` — sent to every SearXNG instance | `Mozilla/5.0 (compatible)` |
| `lib/web-search/minimax.ts:76` | `MM-API-Source: OpenMAIC` — sent to MiniMax | header removed |
| `lib/video-export-app/cover-config.ts:17` | `open.maic.chat` printed on the cover of **every exported video**, as the default | no default; a CTA appears only when `NEXT_PUBLIC_VIDEO_EXPORT_CTA_DESTINATION` is set |

### And on every file a user saves

`CLASSROOM_ZIP_EXTENSION` was `.maic.zip`, so every exported course was named
`<name>.maic.zip`. It is now `.classroom.zip`.

**Old exports still import.** The picker accepts `.zip` and the import path never
compared a filename against that constant — it is used in exactly one place, to
build the download name (`lib/export/use-export-classroom.ts:252`).

---

## 3 · Clickable links out

| File | What it was | Action |
|---|---|---|
| `components/ai-elements/open-in-chat.tsx` | six `target="_blank"` links to ChatGPT, Claude, T3, Scira, v0, Cursor | **file deleted** — nothing imported it |
| `components/ai-elements/sources.tsx` | one external source link | **file deleted** — nothing imported it |
| `components/settings/web-search-settings.tsx:203-212` | "API Docs ↗" anchors on the three Baidu sub-source rows | anchors removed; the descriptions stay |
| `lib/web-search/constants.ts` | `docsUrl` for `cloud.baidu.com` ×2 and `ai.baidu.com` | field and all three values removed |

Verified on the running container: the home page and `/workspace` return **zero**
`href="http…"` in their HTML.

### What was deliberately left clickable

- **Internal navigation** — `/`, `/workspace`, the skill-download route. Not links out.
- **Links inside model output** (`components/workbench/chat/text-block.tsx`) —
  these are citations in an answer the user asked for. Stripping them would break
  web-search grounding, which is content, not chrome. Say the word and they can
  go too.

---

## 4 · Translations — all thirteen languages

**80 translated strings changed.** The brand was in the copy, not just the pixels:

| Key | Was (en-US) | Now |
|---|---|---|
| `home.slogan` | "Generative Learning in Multi-Agent Interactive Classroom" | **key removed** — the hero reads `brand.tagline` |
| `settings.viewDocs` | "API Docs" | **key removed** — its only link is gone |
| `…builtinDetailNote` | "This skill ships with OpenMAIC." | "This skill is built in." |
| `…emptyHint` | "…or let **MAIC Agent** generate narration." | "…or let the AI agent generate narration." |
| `settings.officialDownload` | "OpenMAIC official skill" | "Built-in skill" |
| `import.error.invalidZip` | "…a valid **.maic.zip** file." | "…a valid .classroom.zip file." |

Each was rewritten in the target language, not left in English:
`الوكيل` · `KI-Agenten` · `agente de IA` · `l'agent IA` · `AI エージェント` ·
`AI 에이전트` · `ИИ-агенту` · `เอเจนต์ AI` · `tác nhân AI` · `AI 智能体` · `AI 智能體`.

Files: `lib/i18n/locales/*.json` (13), `lib/i18n/workbench-locales/*.json` (10),
`lib/i18n/workbench.ts` (the en / zh-CN table), and
`deploy/openmaic-patches/th-TH.partial.json` — the last one so
`build_th_locale.py` cannot put the brand back on the next rebuild.

**Key count: 1800 → 1798.** That is why `openmaic-pin.json` moved; the contract
check fails loudly on an unexplained key-count change, which is what it is for.

---

## 5 · Two wire identifiers

Visible only with devtools open, but shipped on every request and every rendered
slide. 38 occurrences across 14 files.

| Was | Now |
|---|---|
| `data-maic-element-id` (DOM attribute on every slide element) | `data-element-id` |
| `X-OpenMAIC-Element-Reference-Accepted` (HTTP response header) | `X-Element-Reference-Accepted` |

Neither is persisted in a saved document, and no CSS selector matched either, so
there is nothing to migrate.

---

## 6 · What was deliberately **not** changed

| Left as-is | Why |
|---|---|
| `@openmaic/*` workspace package names | Internal module ids, invisible to a reader. Renaming touches hundreds of files, the lockfile and every build script — and makes every future `git subtree pull` a conflict, for no user-visible gain. |
| `OPENMAIC_*`, `NEXT_PUBLIC_MAIC_*` env vars | Operator-facing config, never rendered. Renaming breaks every existing deployment's compose file and the runbook. |
| `maic-connector`, `maic-director-compaction` | Internal provider/model ids, cross-matched by string across six files in the agent runtime. Never shown. |
| Source comments naming OpenMAIC | Not shipped to anyone; rewriting them is pure upstream-conflict surface. |
| `integration/maic/LICENSE`, `README*.md` | MIT requires the notice **in the distribution**, not in the UI. Removing the UI footer is fine; removing the licence file would not be. |

---

## Verification

Everything below was run, not assumed.

| Check | Result |
|---|---|
| `tsc --noEmit -p tsconfig.json` | **clean** |
| `eslint` on all changed files | **0 errors** (1 pre-existing `exhaustive-deps` warning at `app/page.tsx:356`) |
| `prettier --check` | clean after formatting two files |
| upstream `scripts/check-i18n-keys.mjs` | **passed — 13 locale files** |
| `build_th_locale.py --check` | 1687/1798 (93.8%) |
| `check_openmaic_contract.py` | **all checks passed** after the pin bump |
| `check_openmaic_i18n_gaps.py` | 152 NEW / 7 known — **byte-identical to HEAD**, so this work added none |
| `docker compose build openmaic` | **exit 0** |
| Live container, `/` | `title: DeepWitya`, `description: Agent-Native Learning`, **0** case-insensitive `maic` matches in the HTML, **0** external links |
| Live container, `/workspace` | same — 0 and 0 |
| Live container, assets | `/brand-wordmark.png` 200, `/brand-mark.png` 200, `/logo-horizontal.png` **404**, `/openmaic-mark.png` **404** |

### Tests, and an honest account of the red

Targeted run over every area touched: **286 passed**, and the failures needed
separating from pre-existing damage rather than being reported as a number.

- **One failure was mine and is fixed** — `tests/web-search/minimax.test.ts`
  asserted the `MM-API-Source: OpenMAIC` header I removed.
- **`tests/lib/chat/pi/element-reference-route-l2.test.ts`** fails **5/5 on a
  pristine `git worktree` at HEAD** and 4/5 with these changes. Pre-existing; if
  anything, one more passes now.
- **`tests/lib/chat/pi/route-model-thinking.test.ts` and
  `tests/web-search/route.test.ts`** — identical command, same container:
  **31 failures at HEAD, 8 with these changes**. Every one of the 8 is
  `Test timed out in 5000ms`; **not one is an assertion failure**. These are heavy
  integration tests timing out in a Docker container on Windows.

`tests/video-export/cover-config.test.ts` also gained the `th-TH` fixture row it
had been missing since Thai joined the `Locale` union. That fixture is typed
`Record<Locale, …>`, so `tsc` had been failing on it before any of this work —
worth knowing separately, because `next build` does not typecheck the test tree
and so never surfaced it.

---

## Follow-ups this does not cover

1. **Rotate the exposed API keys** (Gemini, Tavily, OpenRouter) — still the
   oldest open item.
2. The 152 pre-existing `i18n-gaps` findings — mostly Chinese literals in server
   prompt routes, which steer the model's output language. Separate problem,
   separate fix.
3. If the brand should be something other than DeepWitya, it is five
   `NEXT_PUBLIC_BRAND_*` values and a rebuild — no code change.
