# Following OpenMAIC upstream

OpenMAIC lives at `integration/maic` as a **squashed git subtree**. A clone of
this repository is the whole thing: no sibling checkout, no fetch step, nothing
to assemble before a build.

That has one consequence worth stating before anything else. **`git subtree pull`
is the only command that should ever write to `integration/maic`.** A DeepTutor
upstream sync must leave it alone — it comes from THU-MAIC, not HKUDS — and
`CLAUDE.md` §2 says so where every agent will read it.

---

## Why a subtree and not patches

It was a patch queue first: nine `.patch` files applied to a sibling checkout to
build and reversed afterwards, which kept that checkout a pristine mirror and
kept every change independently sendable upstream. That was the right shape while
every change was one upstream might accept.

It stopped being the right shape when the work turned to things upstream never
will: removing OpenMAIC's branding, laying the classroom out for an iframe,
reading configuration from DeepTutor. A patch nobody upstream will take is a
patch you carry for ever, and carrying a growing stack of those against a moving
target costs more than merging does.

What the subtree gives up is that the patches were *self-evidently* ours — a
directory of files, each one a change. `export_upstream_patches.py` gives that
back on demand, so the commits stay the single source of truth.

## Updating to a newer OpenMAIC

### 1. See what is coming

```bash
git fetch https://github.com/THU-MAIC/OpenMAIC main
git log --oneline HEAD..FETCH_HEAD | head -40
git diff --stat HEAD FETCH_HEAD -- lib/i18n lib/audio app/page.tsx Dockerfile
```

The third command is the whole risk assessment. Ours touch i18n registration, the
audio provider paths, the embed hooks, `app/page.tsx` and the Dockerfile; upstream
churn anywhere else merges without a thought.

### 2. Pull

```bash
git subtree pull --prefix=integration/maic \
    https://github.com/THU-MAIC/OpenMAIC main --squash
```

Conflicts here are ordinary merge conflicts in the files both sides touched, and
they are resolved in `integration/maic` like any other merge. This is the step the
patch queue used to make loud and now makes normal — which is the trade: less
ceremony, and less of a guarantee that a change of ours cannot be quietly lost.
Read the resolutions rather than accepting them.

### 3. Re-check what upstream cannot know it broke

```bash
python3 deploy/openmaic-patches/check_openmaic_contract.py --openmaic integration/maic
python3 deploy/openmaic-patches/build_th_locale.py --openmaic integration/maic --check
python3 deploy/openmaic-patches/check_openmaic_i18n_gaps.py --openmaic integration/maic
```

- **contract** — the runtime assumptions the embed depends on, plus whether the
  subtree is still at the commit these were verified against. It fails on the pin
  straight after a pull; that is the cue to re-verify, not a defect.
- **th locale** — coverage, and any key we translated that upstream removed. New
  keys need no action to keep the app working: they render in English through the
  fill, never in Chinese.
- **i18n gaps** — the Thai problems no translation file can fix: UI text hardcoded
  in source, Chinese literals in components, language lists with no `th`. Every one
  found so far was found by *using the app*, which is why this exists.

### 4. Top up the translation

```bash
python3 deploy/openmaic-patches/build_th_locale.py \
    --openmaic integration/maic \
    --out integration/maic/lib/i18n/locales/th-TH.json
```

`th-TH.partial.json` in this directory is the translation itself; the builder
merges it over `en-US.json` so untranslated keys fall back to English rather than
to the project default, which is `zh-CN`. The result is **committed** — in this
layout it is a locale file like the other twelve.

Upstream's own gate should then pass:

```bash
docker run --rm -v "$PWD/integration/maic:/w" -w /w node:22-alpine \
    node scripts/check-i18n-keys.mjs      # expect: 13 locale files
```

### 5. Reconcile the lockfile, and build

The Thai font change adds a dependency, so `pnpm-lock.yaml` has to be updated
whenever `package.json` changes — and the Dockerfile runs
`pnpm install --frozen-lockfile`, which fails on a mismatch.

```bash
docker run --rm -e HOME=/tmp -e CI=true \
    -v "$PWD/integration/maic:/w" -w /w node:22-alpine \
    sh -c 'corepack enable && pnpm install --no-frozen-lockfile'
git add integration/maic/pnpm-lock.yaml
git commit -m "chore(maic): reconcile the lockfile"

docker compose -f docker-compose.yml -f deploy/docker-compose.openmaic.yml build openmaic
```

`CI=true` is load-bearing: without a TTY pnpm refuses to replace a `node_modules`
built elsewhere and stops with `ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`.

> After a containerised install, `node_modules` holds POSIX symlinks and no `.cmd`
> shims, so host-side `npx` cannot use it. Run the test suite in a container too.

### 6. Bump the pin

`openmaic-pin.json` records the upstream commit the checks were last verified
against. Update `commit`, `commit_date`, `commit_subject`, `verified` and
`locale_keys_en_us`, then confirm:

```bash
python3 deploy/openmaic-patches/check_openmaic_contract.py --openmaic integration/maic
```

It compares that pin against the commit `git subtree` recorded in its squash
message, so it answers the question that matters: did somebody pull a newer
OpenMAIC and not re-verify?

Close with a `CHANGES.md` entry, as every change to this fork needs.

## Sending our changes upstream

Every commit of ours in `integration/maic` can be offered to THU-MAIC, and
several should be — the raw-PCM audio fix and the Thai ASR language entry are
plain bugs for anyone, not integration work.

```bash
python3 deploy/openmaic-patches/export_upstream_patches.py            # list
python3 deploy/openmaic-patches/export_upstream_patches.py --out /tmp/pr
```

Paths inside are rewritten relative to the OpenMAIC root, so they apply to a plain
THU-MAIC checkout with `git am`. Read one before sending it: a commit message
written for this repository is not the message an upstream reviewer should get.

If upstream takes one, drop our commit on the next pull rather than carrying it —
that is the whole reason for keeping them separable.

## Two things not to do

**Do not edit `integration/maic` from a DeepTutor upstream sync.** Exclude it:

```bash
git diff <hkuds-release> -- . ':(exclude)integration/maic'
```

**Do not `git checkout --` or `git reset --hard` to tidy it.** To restore one file
to its committed state, write it back instead:

```bash
git show HEAD:integration/maic/pnpm-lock.yaml > integration/maic/pnpm-lock.yaml
```

That is how the lockfile was recovered after a `pnpm install` rewrote 1,934 lines
of it during the font work.
