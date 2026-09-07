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

## 2. There is no step 2

OpenMAIC is at `integration/maic`, vendored as a squashed git subtree, so the
clone in step 1 already contains it — patched, translated, with its lockfile
reconciled. Nothing to fetch, nothing to assemble, no pinned commit to resolve.

This used to be the longest step in the document: a script that cloned upstream,
applied nine patches, generated the Thai locale and reconciled a lockfile in a
throwaway container, with its own failure mode for a `node_modules` built by the
wrong pnpm. All of that is now somebody else's problem exactly once, when they
run `git subtree pull` — see `OPENMAIC_SYNC.md`.

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
sleep 8
curl -sS -D headers.txt -o /dev/null http://127.0.0.1:3399/
grep -iE "content-security|x-frame" headers.txt || cat headers.txt
docker rm -f csp-check && rm -f headers.txt
```

Written to a file first, and with a single `-E` pattern, on purpose. `curl -sI |
grep -i -e A -e B` — the obvious form — dies on Git Bash with curl exit 23 and
grep aborting on 134, producing **no output at all**, which is indistinguishable
from "the header is missing". The `|| cat` is there for the same reason: a
failed match should show you the headers, not silence.

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
[ -f data/user/settings/openmaic.json ] &&   cp data/user/settings/openmaic.json data/user/settings/openmaic.json.bak
cat > data/user/settings/openmaic.json <<'EOF'
{ "embed_url": "https://203.185.144.41:10330" }
EOF
```

The backup line matters on any machine that has trialled this before: the file
may already exist and point somewhere else, and `cat >` replaces it without a
word.

`DEEPTUTOR_OPENMAIC_URL` overrides it if you prefer an environment variable. The
page reads this per request — `force-dynamic` — so no rebuild or restart of
DeepTutor is needed.

## 4b. Hand OpenMAIC the providers DeepTutor already has

```bash
python3 deploy/openmaic-patches/build_server_providers.py --dry-run   # keys masked
python3 deploy/openmaic-patches/build_server_providers.py
```

Without this, an operator configures every API key twice — once in DeepTutor and
again inside the embedded app — which is the seam a customer notices before any
other. It needs no patch: OpenMAIC already reads a server-side
`server-providers.yml` covering LLM, TTS, ASR, PDF, image, video and web search,
and its own compose file carries the mount line commented out. What was missing
was something to write the file, which is what this does, from
`data/user/settings/model_catalog.json`.

The compose overlay mounts it read-only. It contains credentials and lives under
`data/`, which is gitignored.

**You only need this command for a first bring-up.** After that DeepTutor
rewrites the file itself, on every save of provider settings, and OpenMAIC
re-reads it when its mtime changes — so a rotated key takes effect with no
script and no restart. That matters more than convenience: the person whose key
expires is a user with a settings page, not an operator with a shell, and the
old arrangement left them with a dead course studio and no way to fix it.

Set `DEEPTUTOR_OPENMAIC_BRIDGE=0` to turn the automatic refresh off (a
deployment with no course studio), or `DEEPTUTOR_OPENMAIC_HOST_ALIAS` to change
what a container should call the host. The refresh never raises: a provider
that maps to nothing, or a read-only data directory, is logged and skipped
rather than costing the user the settings they just saved.

Confirm OpenMAIC agrees, rather than assuming the mount was enough:

```bash
docker exec deeptutor-openmaic node -e "fetch('http://127.0.0.1:3000/api/server-providers').then(r=>r.json()).then(d=>console.log(Object.keys(d.providers),Object.keys(d.tts),Object.keys(d.asr)))"
```

Anything missing there was skipped, and the script says why on the line above.
A provider id OpenMAIC does not recognise is ignored **in silence** — the same
vendor is `openai` for LLM, `openai-tts` for speech and `openai-whisper` for
recognition, and getting that wrong looks exactly like success.

## 5. Start it

```bash
DEEPTUTOR_PUBLIC_ORIGIN=https://203.185.144.41 \
DEEPTUTOR_AUTH_URL=https://203.185.144.41/deepwitya2/api/auth/status \
DEEPTUTOR_LOGIN_URL=https://203.185.144.41/deepwitya2/login \
  docker compose -f docker-compose.yml -f deploy/docker-compose.openmaic.yml \
  up -d openmaic gatekeeper
```

**`DEEPTUTOR_AUTH_URL` is empty by default, on purpose** — never the production
URL. Left empty, the gatekeeper refuses every request with
`gatekeeper_misconfigured`, so an unconfigured stack serves nothing and calls
nothing. It used to fall back to the production URL, which meant a
`docker compose up` from a laptop, a CI runner or anyone else's checkout quietly
began sending whatever cookies arrived to the live server, with nobody having
chosen that. It is not a dangerous endpoint — `/api/auth/status` is a public
read — but the destination of a request should be a decision, not a leftover.

Two things about that URL:

- it is resolved **from inside the container**, so `localhost` there is the
  gatekeeper itself, not your machine. Use `host.docker.internal` (mapped for
  you) or the host's LAN address.
- the gatekeeper prints which URL it is verifying against on startup. When the
  gate behaves oddly, `docker logs deeptutor-openmaic-gatekeeper | head -3`
  settles it faster than anything else.

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

**Read the `code` in the body, not the status.** Two unrelated conditions both
answer `503`, and telling them apart by status is impossible:

```bash
curl -s http://127.0.0.1:10331/ | python3 -c "import json,sys; print(json.load(sys.stdin)['error']['code'])"
```

| code | what it means | what to do |
|---|---|---|
| `not_signed_in` | no cookie; auth is on and reachable | expected — sign in through DeepTutor |
| `session_invalid` | cookie present, session rejected | expected |
| `auth_unavailable` | **the gate could not reach DeepTutor at all** | fix `DEEPTUTOR_AUTH_URL` — see below |
| `auth_disabled_upstream` | DeepTutor has auth switched off | turn auth on, or `GATEKEEPER_ALLOW_ANONYMOUS=1` to serve it openly on purpose |

`auth_unavailable` is the one that misleads, because on a machine whose
`data/user/settings/auth.json` says `"enabled": false` you will be *expecting*
`auth_disabled_upstream` and get a `503` that looks like it. It is not. It means
the URL is wrong or unreachable, and the most common reason is the next
paragraph.

**`DEEPTUTOR_AUTH_URL` is resolved from inside the container.** `localhost` there
is the gatekeeper itself, not your machine. Use `http://host.docker.internal:PORT/...`
(mapped for you in the compose file) or the host's real LAN address. The
gatekeeper prints which URL it is verifying against on startup —
`docker logs deeptutor-openmaic-gatekeeper | head -3` — and that line is the
fastest way to settle it.

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

A local run with auth off and the gate on is not a broken deployment — it is the
gate doing its job. But the table above is a comparison, not instructions, and
the local path has more traps than the deployed one, so here it is as commands.

Substitute your machine's LAN address for `192.168.1.10`; `host.docker.internal`
also works now that the compose file maps it.

**Step 3** — the origin is the DeepTutor you will browse from:

```bash
DEEPTUTOR_PUBLIC_ORIGIN=http://localhost:3782   docker compose -f docker-compose.yml -f deploy/docker-compose.openmaic.yml   build openmaic
```

**Step 4** — locally there is no nginx, so point at the **gatekeeper** on
`10331`, not at nginx's `10330`:

```bash
echo '{ "embed_url": "http://localhost:10331" }' > data/user/settings/openmaic.json
```

**Step 5** — no `/deepwitya2` subpath locally, and the auth URL must resolve
*from inside the container*:

```bash
DEEPTUTOR_PUBLIC_ORIGIN=http://localhost:3782 DEEPTUTOR_AUTH_URL=http://host.docker.internal:3782/api/auth/status DEEPTUTOR_LOGIN_URL=http://localhost:3782/login   docker compose -f docker-compose.yml -f deploy/docker-compose.openmaic.yml   up -d openmaic gatekeeper
```

**Step 8 without a login.** If DeepTutor's auth is off, the gate refuses
everything — correctly. To see the embed anyway, say so out loud:

```bash
GATEKEEPER_ALLOW_ANONYMOUS=1   docker compose -f docker-compose.yml -f deploy/docker-compose.openmaic.yml   up -d gatekeeper
```

Confirm it took, rather than assuming: `curl -s http://127.0.0.1:10331/__gatekeeper/health`
reports `"gated": false` when the gate is off.

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
