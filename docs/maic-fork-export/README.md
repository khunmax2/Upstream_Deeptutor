# What this fork changed in `integration/maic`, and why

A reference for rebuilding the OpenMAIC integration from a clean import. It
answers three questions the diff alone does not: what each change was for, what
it cost, and what bit us while making it.

**Reference point:** `8475f82c6` — the commit that imported OpenMAIC as a
squashed subtree (upstream `fb0a9f22`). Everything after it that touches
`integration/maic` is ours: **22 commits, 127 files, +4,557 / −2,990**.

Regenerate any of this at any time:

```bash
git log  --oneline --no-merges 8475f82c6..main -- integration/maic
git diff  8475f82c6..main -- integration/maic
git format-patch <sha> -1 --stdout -- integration/maic
```

## What is in this folder

| | |
|---|---|
| `why.md` | Every commit message in order. **The reasoning lives here** — these were written long on purpose, and they explain decisions the code cannot. |
| `patches/` | One patch per commit, numbered in apply order. Binary assets and `pnpm-lock.yaml` are excluded: they are regenerable and unreadable as guidance. |
| `code-only.patch` | Everything except the locale JSON — the approach, without the bulk. |
| `thai-i18n.patch` | The localisation work on its own. |

`full.patch` is deliberately absent: it is the sum of `patches/`.

## The work in six groups

### 1. Thai localisation — the cleanest group to lift

`th-TH.json` is a **new file** (+2,104), so it cannot conflict. The other twelve
locales each gained `+79/−9` — the identical shape, because they are the same
new keys, created when hardcoded strings were routed through `t()`.

Commits 1, 2, 9, 10, 11, 12.

**Redoing it:** start here. New file plus additive keys is the only group that
merges without thought.

### 2. De-branding — the group with deletions

Three files were removed outright, `open-in-chat.tsx` (−335) among them: it was
an outbound link to OpenMAIC's own product.

**Two traps, both of which caught us:**

- **Labels built from ternaries survive a literal grep.** `Play`/`Mute` were
  "fixed", then found again still in English, because the string never appears
  as a literal. It happened twice in one day (`组合`, `直线` too).
- **Token substitution leaves spaces behind.** Replacing a product name inside
  ja/th/zh strings left `หรือให้ เอเจนต์ AI` — those languages do not put spaces
  between words. Only found because someone asked what the replacement text was.

Commits 13, 14, 15, 16.

### 3. Host integration — `?lang=`, `?theme=`, `?embed=1`

Lets DeepTutor tell the studio which language and theme to use and hide the
chrome that belongs to the host. `lib/hooks/use-embed.ts` is a new file.

Commits 4, 5.

### 4. Serving under a subpath — three new files, nothing to conflict

`lib/base-path.ts`, `components/base-path-bridge.tsx` and their test are **new
files** (+306 total).

**The part that is not obvious:** Next's `basePath` prefixes `<Link>`, the
router and `/_next/` assets. It does **not** touch a URL the app writes itself,
and this app writes 74 `fetch('/api/...')` calls across 44 files plus three
`EventSource` streams. Patching the two globals they funnel through is one file;
patching the call sites is 44.

The first symptom when this is wrong is not a network error — it is the studio
showing **an access-code login box nobody configured**, because
`/api/access-code/status` fails and the guard treats an error as locked.

Static files under `/public` are the other half: `AvatarImage`, `DEFAULT_BRAND`
and `PROVIDERS` cover most of it; the rest needed a sweep of 52 `src=` sites.

Commits 3, 20, 22.

### 5. Provider bridge — TTS voices, capability state, key rotation

`lib/server/provider-config.ts` (+68) and `lib/audio/tts-providers.ts` (+162)
are the two biggest edits in the fork.

`loadEnvSection` copied four named fields, so a new `voices` field was **silently
dropped** until it was added in both that function and the `${PREFIX}_VOICES`
env path. A field that exists in the type and never arrives is the failure mode
to watch for here.

Commits 7, 17, 18, 19.

### 6. Build and container

`Dockerfile` (+17), `next.config.ts` (+10), `.dockerignore` (+8),
`package.json` (+3/−2), and `pnpm-lock.yaml` (+93/−1,934).

Commits 6, 8, 11.

## What a rebuild should expect to fight

| Risk | Where |
|---|---|
| **Conflicts every time** | `pnpm-lock.yaml` — the moment upstream touches a dependency |
| **Twelve files at once** | the locale JSONs, if upstream adds keys in the same region |
| **Read every line** | the 8 files edited by more than 30 lines |
| **Git will ask** | the 3 files we deleted, if upstream modifies them |
| **Low risk each, 61 of them** | the one-line `asset()` + import edits from the image sweep |

## Two decisions worth keeping

**Wrap at the render site, not at the constants.** Prefixing
`AVATAR_OPTIONS`/`AGENT_DEFAULT_AVATARS` where they are declared is wrong twice:
they are `as const`, so widening them breaks types other code depends on, and
the user profile's avatar is **persisted** — a prefixed value would be written
into saved state and break whenever the prefix changes.

**Idempotence is load-bearing, not tidiness.** `asset()` is applied by more than
one layer — `brand-config.ts` prefixes the logo and the sweep prefixes it again.
Without the "already prefixed → return unchanged" guard that is
`/prefix/prefix/brand-wordmark.png`.

---

# Beyond the subtree

The integration is not only `integration/maic`. Three other groups carry it, and
a rebuild that restores the subtree alone will find the studio unreachable, or
reachable and unable to generate anything.

## The tooling — `deploy/openmaic-patches/`

Seven files, already tracked in the repository. Not copied here on purpose: a
second copy is a second thing to keep in step, and it will drift.

| | |
|---|---|
| `build_th_locale.py` | Builds a complete `th-TH.json` from `th-TH.partial.json`, and checks coverage, interpolation parity, and keys that no longer exist upstream. |
| `th-TH.partial.json` | 150 KB. **The Thai translation source.** `th-TH.json` in the subtree is generated from it — edit this, not the output. |
| `check_openmaic_i18n_gaps.py` | Finds the Thai gaps a translation file *cannot* close — strings that are not routed through `t()` at all. |
| `check_openmaic_contract.py` | Checks the handful of runtime assumptions this fork makes about OpenMAIC. Nothing here imports anything there; the dependency is a contract, not code. |
| `export_upstream_patches.py` | Turns our OpenMAIC commits into patches an upstream maintainer can apply. |
| `build_server_providers.py` | Writes `server-providers.yml` from DeepTutor's provider settings, for a first bring-up. |
| `openmaic-pin.json` | The upstream commit this fork's work was verified against — `d4ef5faa`, 2026-09-01. Updating OpenMAIC is meant to be a decision, not a surprise. |

**Correction worth carrying forward:** `build_th_locale.py`'s docstring says
OpenMAIC falls back to **`zh-CN`** for a missing key, which is why coverage
mattered so much. That was true when it was written. `lib/i18n/types.ts` now
sets `defaultLocale = 'en-US'` — this fork changed it — and `th-TH.json` is at
**1,862 of 1,862 keys, zero missing**. Read that docstring as history, not as
the current state.

## The deploy side — `patches-deploy/` and `why-deploy.md`

Seven commits outside the subtree, without which the integration does not run:

| | |
|---|---|
| `28cb1760d` | Serve v1.6.4 under the nginx subpath `/deepwitya2` over HTTPS |
| `dc87319ee` | Keep the signed-out login redirect inside the basePath |
| `e0dfe6888` | Saving settings in the UI re-locks `system.json` |
| `42d171981` | Raise the nginx upload ceiling to the app's 200 MB — below it, a large document died as a bare nginx 413 and the app never saw the request, so its own friendly message could never fire |
| `1c4791ab0` | **Tesseract**, so the OCR fallback can actually run |
| `2b95d2f0b` | A rotated API key reaches the course studio without anyone opening a shell |
| `acfc22e3e` | Say when a media capability is ready but switched off |

### Tesseract, specifically

Three things must all be true, and the third is the one that looks optional:

1. the `tesseract` binary → `tesseract-ocr`
2. the traineddata per language → `tesseract-ocr-{eng,tha}`
3. `TESSDATA_PREFIX` pointing at them

Without (3), `pymupdf.get_tessdata()` raises *"No tessdata specified and
Tesseract is not installed"* — **the same message you get when nothing is
installed at all**, so a missing variable reads as a missing package.

`tha` is not optional either: `ocr.py` maps the interface language to a
traineddata name and always appends English, so a Thai deployment asks for
`tha+eng` and fails if either half is absent.

The path is version-numbered (`/usr/share/tesseract-ocr/5/tessdata`, verified
against debian trixie / tesseract 5.5.0). Re-check it whenever the base image's
tesseract major version moves.

## What is still not here

`deeptutor/services/config/openmaic_bridge.py`, the gatekeeper
(`deploy/openmaic-gatekeeper/`) and the compose overlay
(`deploy/docker-compose.openmaic.yml`) are live code in the repository, not
exported. They are found through `deploy/OPENMAIC_RUNBOOK.md` and
`deploy/OPENMAIC_EMBED.md`, which is where the reasoning for those lives.
