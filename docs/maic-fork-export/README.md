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
