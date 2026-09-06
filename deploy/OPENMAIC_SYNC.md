# Following OpenMAIC upstream

How to take a new OpenMAIC release. This is deliberately short: unlike the
HKUDS sync, there is nothing to merge, because our checkout of OpenMAIC is a
**pristine mirror of upstream** and everything of ours lives in this repository.

If that stops being true, this document stops working — so the first step is a
check, not a pull.

---

## What we own

Everything in `deploy/openmaic-patches/`:

| | |
|---|---|
| `th-TH.partial.json` | the Thai translation, 1,689 keys |
| `build_th_locale.py` | merges it over `en-US.json` into a complete locale file |
| `0001-register-th-TH-locale.patch` | 3 lines: registers the locale |
| `0002-thai-script-support.patch` | the Thai font, UI and video export |
| `check_openmaic_tree.py` | guard — nothing foreign may ride along |
| `check_openmaic_contract.py` | the five runtime assumptions, plus drift |
| `openmaic-pin.json` | the commit all of the above was verified against |

Nothing of ours is committed inside the OpenMAIC checkout. A patch is applied
long enough to build or test, then reversed with `git apply -R`.

## Getting the checkout in the first place

On a machine that has never had one — a deploy host, a new laptop — there is no
`../OpenMAIC` to update, and no repository of ours to clone it from. One command
builds it:

```bash
./deploy/openmaic-fetch.sh
```

It clones upstream at the commit in `openmaic-pin.json`, applies every patch in
order, generates the Thai locale, and reconciles the lockfile in a throwaway
container so the host needs no Node toolchain — only git and docker. Re-running
it is safe: patches already applied are recognised, and it refuses rather than
building over a change it did not make.

The rest of this document is for **updating** an existing checkout to a newer
OpenMAIC, which is a different job with different risks.

## The procedure

Run from this repository's root, with OpenMAIC checked out as a sibling
directory (`../OpenMAIC`).

### 1. Check before you pull

```bash
python deploy/openmaic-patches/check_openmaic_tree.py --openmaic ../OpenMAIC
```

Anything in the **foreign** bucket is a local change that would otherwise be
carried into the pull — a Dockerfile experiment, a leftover `.bak`. Deal with it
first. A pull onto a dirty tree is where the "pristine mirror" property quietly
dies.

### 2. Pull

```bash
git -C ../OpenMAIC fetch origin
git -C ../OpenMAIC merge --ff-only origin/main
```

`--ff-only` is the guard, not a preference: if it refuses, something was
committed into that checkout and it is no longer a mirror. Find out what before
going further.

### 3. Measure the drift

```bash
python deploy/openmaic-patches/check_openmaic_contract.py --openmaic ../OpenMAIC
```

Two things fail here, and both are expected after a real update:

- **version pin** — HEAD moved past `openmaic-pin.json`. Expected; you bump it
  at the end.
- **locale key count** — upstream adds roughly 50-90 keys a week. The number in
  the failure line is how many strings the Thai file is now missing.

### 4. Re-check the patches

```bash
git -C ../OpenMAIC apply --check deploy/openmaic-patches/0001-register-th-TH-locale.patch
git -C ../OpenMAIC apply --check deploy/openmaic-patches/0002-thai-script-support.patch
```

`--check` changes nothing. A failure names the file and line, which is the whole
reason our changes are patches rather than commits: they break loudly instead of
merging into something subtly wrong.

Both are small and sit in stable places (the end of a locale array, an import
list, a font-face table), so a conflict usually means upstream reorganised that
file — re-generate the patch against the new source rather than hand-editing it.

### 5. Top up the translation

```bash
python deploy/openmaic-patches/build_th_locale.py --openmaic ../OpenMAIC --check
```

It prints coverage and fails on any key we translated that no longer exists
upstream. New keys need no action to keep the app working — they render in
English through the autofill, never in Chinese — so this is a backlog, not an
outage. Translate them into `th-TH.partial.json` when convenient.

### 5b. Look for gaps the translation cannot close

```bash
python deploy/openmaic-patches/check_openmaic_i18n_gaps.py --openmaic ../OpenMAIC
```

Step 5 checks the translation. This checks everything Thai needs that a
translation file cannot supply: UI text hardcoded in source, Chinese literals in
components, and language option lists with no `th` in them.

It exists because all three kinds were found by *using the app*, not by any
check — the coverage number was 93.8% and both gates were green while the screen
still showed a Chinese chip and an English toast. Judgement finds these on the
days somebody happens to click the right thing; a check finds them every time.

Findings are not automatically work. Each is a source change, so each is a
patch — and each is an upstream candidate, since none is about DeepTutor. What
matters is that a new one is seen on the update that introduced it.

### 6. Build and verify

```bash
git -C ../OpenMAIC apply deploy/openmaic-patches/0001-register-th-TH-locale.patch
git -C ../OpenMAIC apply deploy/openmaic-patches/0002-thai-script-support.patch
python deploy/openmaic-patches/build_th_locale.py \
    --openmaic ../OpenMAIC --out ../OpenMAIC/lib/i18n/locales/th-TH.json
cd ../OpenMAIC && pnpm install && pnpm run gen:video-export-noto-script-fonts
node scripts/check-i18n-keys.mjs     # their gate: expect 13 locale files
```

`pnpm install` there is not optional and not a habit. `0002` adds a dependency
while deliberately leaving `pnpm-lock.yaml` out of the patch (one package churned
2,934 lines of it, and lockfile hunks conflict on every upstream dependency
change). The Dockerfile runs `pnpm install --frozen-lockfile`, so without this
step the image build fails on a lockfile that does not match `package.json`.

To build the container image:

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.openmaic.yml build openmaic
```

Start it, then check the runtime contract against a running instance:

```bash
python deploy/openmaic-patches/check_openmaic_contract.py \
    --openmaic ../OpenMAIC \
    --url http://localhost:3100 \
    --origin http://localhost:3782
```

This is the check that earns its keep. A blank iframe has a dozen possible
causes and they all look identical; this names the one that actually happened —
a renamed `ALLOWED_FRAME_ANCESTORS`, an `X-Frame-Options` header that reappeared,
an access gate that switched on.

### 7. Put the checkout back, and bump the pin

```bash
git -C ../OpenMAIC apply -R deploy/openmaic-patches/0002-thai-script-support.patch
git -C ../OpenMAIC apply -R deploy/openmaic-patches/0001-register-th-TH-locale.patch
rm ../OpenMAIC/lib/i18n/locales/th-TH.json
rm ../OpenMAIC/public/vendor/video-export/fonts/noto-sans-thai-thai-400-normal.woff2
cd ../OpenMAIC && pnpm run gen:video-export-noto-script-fonts && pnpm install --frozen-lockfile
```

Then update `commit`, `commit_date`, `commit_subject`, `verified` and
`locale_keys_en_us` in `openmaic-pin.json`, and confirm:

```bash
python deploy/openmaic-patches/check_openmaic_tree.py --openmaic ../OpenMAIC
```

Clean means the mirror survived the round trip.

## Two things not to do

**Do not commit inside `../OpenMAIC`.** That is the single decision that turns a
`git pull` into a merge with conflicts, which is exactly the position this fork
is already in with HKUDS — see the note under §5 in `CLAUDE.md`.

**Do not use `git checkout --` or `git reset --hard` to tidy that checkout.** To
restore one file to its committed state, write it back instead:

```bash
git -C ../OpenMAIC show HEAD:pnpm-lock.yaml > ../OpenMAIC/pnpm-lock.yaml
```

That is how the lockfile was recovered after `pnpm install` rewrote 1,934 lines
of it during the font work.

## If upstream merges our work

The Thai locale is offered to THU-MAIC rather than kept here — see
`docs/planning/PLAN_openmaic_thai_i18n.md` for why, and for the evidence that
outside language PRs do get merged there. If `th-TH` lands upstream, delete
`0001-register-th-TH-locale.patch` and `th-TH.partial.json`: every later release
then carries Thai for us, because their own `check-i18n-keys` gate forces new
keys to be filled in for every locale.
