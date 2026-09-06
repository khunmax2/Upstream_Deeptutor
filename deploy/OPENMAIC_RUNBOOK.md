# Bringing up the OpenMAIC embed with Docker

What was actually run, in order, and every problem it hit. Written to be
followed from a clean machine — no containers, no images, no `../OpenMAIC` — so
that following it reproduces the same result rather than a similar one.

Companion documents: `OPENMAIC_EMBED.md` (why the design is shaped this way),
`OPENMAIC_SYNC.md` (taking a newer OpenMAIC), `openmaic-gatekeeper/README.md`
(the auth gate).

---

## What you end up with

```
browser
  │
  ├── https://HOST/deepwitya2      DeepTutor            (existing)
  │       └── /maic  ──frames──┐
  │                            │
  └── https://HOST:10330  ─────┘   nginx, TLS
          └── 127.0.0.1:10331      gatekeeper — checks the DeepTutor session,
                  └── openmaic     strips dt_token, then forwards
```

Two origins on purpose. OpenMAIC publishes **no host port at all**; the only
route in is the gatekeeper.

## Before you start

| | |
|---|---|
| `git`, `docker`, `docker compose` | required |
| Node / pnpm / python on the host | **not** required — the one step that needs Node runs in a throwaway container |
| Network access to `github.com` | required at prepare time (clones OpenMAIC) |
| Free ports | `10330` (nginx), `10331` (loopback only) |
| `sudo` | only for the nginx block, at the very end |

Disk: the OpenMAIC clone plus `node_modules` is roughly 2 GB, and the image
build needs headroom on top.

The verification snippets below call `python3`, which is right on the Linux
target. **On Windows use `python`** — `python3` there resolves to a Microsoft
Store stub that is on PATH and then refuses to run. `openmaic-fetch.sh` already
tests which one actually executes; these one-liners do not.

---

## 1. Get this repository

```bash
git clone https://github.com/khunmax2/Upstream_Deeptutor
cd Upstream_Deeptutor
```

Everything of ours is here — the Thai translation, all six patches, the
gatekeeper, the compose overlay, the nginx block.

## 2. Prepare the OpenMAIC source

```bash
./deploy/openmaic-fetch.sh
```

This is the step with no obvious alternative, so it is worth saying what it does
and why it exists. `deploy/docker-compose.openmaic.yml` builds OpenMAIC from
`context: ../OpenMAIC` — a sibling checkout that does not exist yet, and that
cannot be cloned from any repository of ours, because **OpenMAIC is deliberately
kept as a pristine mirror of upstream**. Committing our changes into it would
turn every future OpenMAIC release into a merge with conflicts. So the script
assembles it instead:

1. clones `THU-MAIC/OpenMAIC` and checks out the commit pinned in
   `deploy/openmaic-patches/openmaic-pin.json`
2. applies patches `0001`–`0006` in order
3. generates `lib/i18n/locales/th-TH.json` (1,689 translated keys, the rest
   filled from English so nothing falls back to Chinese)
4. runs `pnpm install` **inside a `node:22-alpine` container** and generates the
   Thai font asset

Expected output ends with:

```
==> Applying patches
    applied   0001-register-th-TH-locale.patch
    ... six in total
==> Ready
    ../OpenMAIC is at d4ef5faa... with 6 patch(es) applied.
```

Safe to re-run. It recognises patches it already applied, and refuses if the
checkout carries a change **it did not make** rather than building over someone
else's work.

> **Why step 4 is not optional.** Patch `0002` adds a dependency but deliberately
> leaves `pnpm-lock.yaml` out of the patch — that one package churns 2,934 lines
> of lockfile, and lockfile hunks conflict on every upstream dependency change.
> The Dockerfile then runs `pnpm install --frozen-lockfile`, which fails on a
> lockfile that does not match `package.json`. Skipping this step does not
> degrade the build; it breaks it.

## 3. Build the image

```bash
DEEPTUTOR_PUBLIC_ORIGIN=https://203.185.144.41 \
  docker compose -f docker-compose.yml -f deploy/docker-compose.openmaic.yml \
  build openmaic
```

**`DEEPTUTOR_PUBLIC_ORIGIN` is a build argument, not a runtime one.** It becomes
`ALLOWED_FRAME_ANCESTORS`, and Next bakes the `Content-Security-Policy:
frame-ancestors` header into the image at build time. Changing the public origin
later means **rebuilding**, not restarting. Get it wrong and the iframe renders
blank with one console line and no server-side error.

Verify what the image will actually send, before deploying it:

```bash
COMPOSE="-f docker-compose.yml -f deploy/docker-compose.openmaic.yml"
IMG=$(docker compose $COMPOSE config --format json \
      | python3 -c "import json,sys; print(json.load(sys.stdin)['name'] + '-openmaic')")

docker run --rm -d --name csp-check -p 3399:3000 "$IMG"
sleep 8 && curl -sI http://127.0.0.1:3399/ | grep -i -e content-security -e x-frame
docker rm -f csp-check
```

The service has no `image:` key, so compose names it `<project>-openmaic`, and
the project defaults to the **directory name**. Clone into a differently named
directory and the image is named differently — hence deriving it rather than
writing it down.

Expected — your origin present, and **no** `X-Frame-Options`:

```
Content-Security-Policy: frame-ancestors 'self' https://203.185.144.41
```

If you see `frame-ancestors 'self'` alone plus `X-Frame-Options: SAMEORIGIN`,
the build argument did not reach the build. Rebuild; do not try to fix it with a
runtime variable.

## 4. Point DeepTutor at it

Fork-owned settings file, because `integrations.json` is normalised against a
fixed schema upstream and silently drops unknown keys:

```bash
cat > data/user/settings/openmaic.json <<'EOF'
{ "embed_url": "https://203.185.144.41:10330" }
EOF
```

`DEEPTUTOR_OPENMAIC_URL` overrides it if you prefer an environment variable. The
page reads this per request — `force-dynamic` — so no rebuild or restart of
DeepTutor is needed.

## 5. Start it

```bash
DEEPTUTOR_PUBLIC_ORIGIN=https://203.185.144.41 \
DEEPTUTOR_AUTH_URL=https://203.185.144.41/deepwitya2/api/auth/status \
DEEPTUTOR_LOGIN_URL=https://203.185.144.41/deepwitya2/login \
  docker compose -f docker-compose.yml -f deploy/docker-compose.openmaic.yml \
  up -d openmaic gatekeeper
```

Add `--profile openmaic-persistence` to bring up OpenMAIC's own Postgres, which
the Pro agent workbench needs. It joins the compose network and publishes no
host port, so it cannot collide with anything already on `5432`.

Check what is exposed, from the resolved configuration rather than by reading
the file:

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.openmaic.yml \
  config --format json | python3 -c "
import json,sys
for n,s in json.load(sys.stdin)['services'].items():
    print(n, s.get('ports') or 'no host port')"
```

`openmaic` must say **no host port**. Anything else is a way around the gate for
whatever else is on that machine.

## 6. Verify the gate before exposing it

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:10331/          # 401
curl -s -H 'Cookie: dt_token=nonsense' \
     -o /dev/null -w '%{http_code}\n' http://127.0.0.1:10331/             # 401
curl -s http://127.0.0.1:10331/__gatekeeper/health                        # {"ok":true,...}
```

A `503` with `auth_disabled_upstream` means DeepTutor has authentication
switched off. The gate is refusing on purpose: with auth off, `/api/auth/status`
answers `authenticated: true` to every caller, so admitting on that basis would
mean serving OpenMAIC to anyone who sets a cookie named `dt_token`. Turn auth on
in DeepTutor, or set `ALLOW_ANONYMOUS=1` to serve it openly **on purpose**.

## 7. nginx (needs sudo)

```bash
sudo cp deploy/nginx-openmaic.locations.conf /etc/nginx/sites-available/openmaic
sudo ln -sf /etc/nginx/sites-available/openmaic /etc/nginx/sites-enabled/openmaic
sudo nginx -t && sudo systemctl reload nginx
```

The file has been syntax-checked offline against `nginx:1.24-alpine` (the
version on the target host) and `1.27-alpine`. Edit `server_name` and the
`frame-ancestors` origin if the host is not `203.185.144.41`.

## 8. End to end

Open DeepTutor → **Course Studio**. Expect OpenMAIC framed, in the same language
and light/dark theme as DeepTutor, with its own language and theme controls
hidden and only its settings gear showing.

---

# Problems this hit, and what each one actually was

Ten things went wrong getting here. They are listed because most of them look
identical to a dozen other causes from the outside.

### The compose file resolves relative paths from the repo root, not from `deploy/`

`./openmaic-gatekeeper` in a file that lives in `deploy/` resolves to
`<repo>/openmaic-gatekeeper`, which does not exist. The container restart-looped
on `MODULE_NOT_FOUND`. Correct value is `./deploy/openmaic-gatekeeper`. The same
rule is why `build.context: ../OpenMAIC` means a sibling of the **repo**.

### An edit that silently never reached the file

A script that made two changes hit an assertion on a later anchor and exited
before writing. Both edits were lost. The verification then used an `awk` range
that ended early and reported success. The commit message and `CHANGES.md`
claimed OpenMAIC published no host port while it still published `127.0.0.1:3100`.

**Check exposure with `docker compose config --format json`,** which reports what
compose resolved, not what a file appears to say.

### Two patches that did nothing at all

`0004` and `0005` give OpenMAIC `?lang=`, `?theme=` and `?embed=1`. Nothing in
DeepTutor ever sent them — `MaicWorkspace` framed the bare URL, and
`normalizeEmbedUrl` rebuilds its result as `origin + pathname`, discarding a
query string even if an operator added one. The receiving half was built and
verified; the sending half was never written.

Their own notes say "verified on a dev server with `?lang=th&theme=dark&embed=1`",
which was true and is exactly why it survived: typing the parameters by hand
tests OpenMAIC, not whether anything produces them.

### The gate admitted any forged cookie

The gatekeeper read `authenticated` from `/api/auth/status` and ignored
`enabled`. With DeepTutor's auth off — the shipped default — that endpoint
answers `authenticated: true` to every caller:

```
$ curl -H 'Cookie: dt_token=totally-made-up-garbage' .../api/auth/status
{"enabled":false,"authenticated":true,"user_id":"local-admin",...}
```

so the gate meant "present any cookie named `dt_token`". Twelve passing tests
missed it because the stub returned `{authenticated: <depends on token>}` — the
shape the code assumed. Stub and code agreed about a case neither had seen.

### The nginx block would have been rejected on the host

It used `http2 on;`, the standalone directive from nginx 1.25. The host runs
1.24, where that is an unknown directive and `nginx -t` refuses the **entire**
configuration — at the moment someone runs it with `sudo` on a live web server.
The file had never been passed through nginx at all.

### The build depended on files that were in no repository

`.dockerignore` needed `**/node_modules` and `**/dist` globs (Docker matches
patterns only at the context root, and pnpm on Windows writes nested
`node_modules` as absolute `D:/...` symlinks that are dead inside the image and
shadow the ones the deps stage built), and the `Dockerfile` needed an ARG/ENV
pair for `NEXT_PUBLIC_PRO_WORKBENCH_ENABLED`.

Both existed only as uncommitted edits in one working tree. An earlier
"the image builds" result had been measured with them present and reported as
though the repository sufficed. They are now patch `0006`.

### `pnpm install` rewrote the lockfile

It removed 1,934 lines. Recovered by writing the committed version back —
`git -C ../OpenMAIC show HEAD:pnpm-lock.yaml > ../OpenMAIC/pnpm-lock.yaml` —
**not** with `git checkout --` or `git reset --hard`, which would also have
discarded unrelated work in that tree.

### Checking that something exists is not checking that it runs

- `command -v python3` succeeds on Windows for a Microsoft Store stub that then
  refuses to execute.
- `pkill -f gatekeeper.mjs` silently killed nothing; the old process kept the
  port, the new one died on `EADDRINUSE`, and a `curl` against the survivor read
  exactly like "the fix did nothing".

Read the process's own startup line before believing its answers. A dead
gatekeeper and a permissive one are indistinguishable from `curl` alone.

### A blank iframe has a dozen causes that look identical

Without `ALLOWED_FRAME_ANCESTORS`, OpenMAIC sends `frame-ancestors 'self'` plus
`X-Frame-Options: SAMEORIGIN` and the browser refuses the frame with one console
line and no server-side error. `check_openmaic_contract.py --url ... --origin ...`
names which of those causes actually happened.

### Port 5432 was already taken, by something that answered

On the development machine a native `postgresql-x64-18` service held `5432`, so
OpenMAIC's `localhost:5432` reached **that** rather than the container, and
failed authentication once a second. The password was correct; the destination
was not.

This cannot happen in the deployment above: `openmaic-postgres` joins the compose
network, is addressed as `postgres:5432`, and publishes no host port.

---

# Trying it locally first

The differences that matter, beyond port numbers:

| | local | deployed |
|---|---|---|
| TLS | none | nginx terminates, existing IP-SAN certificate |
| `DEEPTUTOR_PUBLIC_ORIGIN` | `http://localhost:3782` | `https://203.185.144.41` |
| auth | `auth.json` ships `enabled: false`, so **the gate refuses everything** with `auth_disabled_upstream` | auth on, the gate works as designed |
| `dt_token` | never issued — no login exists | `SameSite=None; Secure`, reaches any port on the host |
| API keys | OpenMAIC's own `.env.local` | central `server-providers.yml` |
| nginx | absent; reach the gatekeeper on loopback | required, needs `sudo` |

To trial the embed locally, either enable auth in DeepTutor or run the
gatekeeper with `ALLOW_ANONYMOUS=1`. A local run with auth off and the gate on
is not a broken deployment — it is the gate doing its job.

## Removing everything

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.openmaic.yml \
  --profile openmaic-persistence down -v
docker image rm "$(docker compose $COMPOSE config --format json \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['name'] + '-openmaic')")"
```

`down -v` removes the named volumes too, including any courses OpenMAIC saved.
Drop the `-v` to keep them.

To return the OpenMAIC checkout to a pristine mirror:

```bash
for p in $(ls -r deploy/openmaic-patches/0*.patch); do
    git -C ../OpenMAIC apply -R "$p" 2>/dev/null || true
done
rm -f ../OpenMAIC/lib/i18n/locales/th-TH.json
python3 deploy/openmaic-patches/check_openmaic_tree.py --openmaic ../OpenMAIC
```

The guard reporting nothing foreign is what "still a mirror" means, and it is
the precondition for the next `git pull` there being a fast-forward.
