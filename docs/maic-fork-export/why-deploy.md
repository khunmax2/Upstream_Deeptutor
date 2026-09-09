
════════════════════════════════════════
28cb1760d  2026-09-04  Pond500
feat(deploy): serve v1.6.4 under nginx subpath /deepwitya2 over HTTPS

Second deployment of this fork on the ai4thai host, run side by side with the
existing v1.4.15 stack. Every hook is a no-op when NEXT_PUBLIC_BASE_PATH is
empty, so serving at the domain root is unaffected.

Two upstream call sites escaped the subpath and were only found by testing the
running app:

- TurnRuntimeClient defaulted to a hardcoded url: "/ws", so the browser opened
  wss://<host>/ws outside the subpath. Every chat turn died as "connection lost"
  without ever reaching FastAPI.
- features/runtime-status hands a raw path to requestJson, bypassing apiUrl, so
  the turn-runtime health card always failed to load.

The second one is the reason apiFetch now applies withBasePath centrally rather
than relying on callers to remember apiUrl: the same mistake is easy to repeat
and impossible to catch by inspection. withBasePath is idempotent, so paths that
did go through apiUrl are left alone.

Verified end to end on the live deployment: HTTPS page, assets and _next chunks,
per-path HTTP->HTTPS redirect, multi-user auth gating, and a full streaming turn
over wss://.../deepwitya2/ws returning a model answer.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>


════════════════════════════════════════
dc87319ee  2026-09-04  Pond500
fix(web): keep the signed-out login redirect inside the basePath

A signed-out visitor to /deepwitya2 was sent to a bare /login, outside the
subpath, where the reverse proxy answers 404. It looked browser-specific —
Safari was fine, Chrome was not — but the real variable was the session cookie:
whoever still held one never hit the redirect at all.

loginHref() is assigned to window.location.href, which does not apply basePath
the way the Next router does, so the prefix has to be added explicitly.
browserReturnPath() needed the opposite treatment: window.location.pathname
carries basePath, but `next` is consumed by router.replace(), which adds it
again — /deepwitya2 as `next` would land on /deepwitya2/deepwitya2 after
signing in. The middleware already emits a stripped `next`; both sides now
produce the same shape.

Verified by running the deployed bundle's own compiled helpers, and against the
live URLs: /deepwitya2/login?next=%2Fdashboard now 200s and matches what the
middleware redirects to.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>


════════════════════════════════════════
e0dfe6888  2026-09-07  Pond500
docs(deploy): note that saving settings in the UI re-locks system.json

The perms note covered the container restart path only. A second, separate
trigger surfaced during the 2026-09-07 update: the app writes system.json
atomically (temp file + rename), so the replacement takes its mode from umask
rather than inheriting the 644 we set. Anyone saving a setting in the web UI
therefore re-locks the file, and the next --build dies before it starts.

docker.env escapes this because the wrapper writes it, not the app.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>


════════════════════════════════════════
42d171981  2026-09-07  Pond500
fix(deploy): raise the nginx upload ceiling to match the app's 200 MB

Immersive reading rejected anything over ~1 MB with a bare "Request failed:
413". The app allows 200 MB, but the location block never set
client_max_body_size, so nginx's 1 MB default cut the request off before the app
saw it — which is also why the app's own "exceeds the 200 MB limit" message
never appeared.

The Next middleware was the other suspect, since /api/reading/materials is not
excluded from its matcher the way the knowledge-base upload routes are, and the
matcher comment warns that entering the proxy caps a multipart body. Posting
straight to the frontend port ruled it out: 58 MB streamed through untouched.

Re-running deploy/apply-nginx-deepwitya2.sh applies this — step 2 rewrites the
snippet unconditionally and step 3 no-ops once the include is in place.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>


════════════════════════════════════════
1c4791ab0  2026-09-07  Pond500
feat(deploy): install Tesseract so the OCR fallback can actually run

deeptutor/reading/ocr.py shipped with the 2026-09-07 update but had nothing to
call: the image carries no tesseract binary, so every scanned PDF and
picture-only deck still failed the way it did before the feature existed.

Three things had to be true, and only the first is obvious:

- the tesseract binary;
- traineddata for BOTH languages — ocr.py always appends English to the
  interface language, so a Thai deployment asks for "tha+eng";
- TESSDATA_PREFIX, because pymupdf.get_tessdata() reads it and otherwise raises
  "No tessdata specified and Tesseract is not installed" — the same message you
  get with nothing installed, so the missing variable looks like a missing
  package.

The tessdata path is version-numbered, so it was read out of a throwaway
container built from the same base rather than guessed.

Pinned DEEPTUTOR_READING_OCR_LANGUAGE=tha+eng in the host override: main.yaml
still says language: en, so Thai scans would otherwise be OCR'd as English.

deploy/ocr_check.py proves the path end to end by rasterising a page and
rebuilding a PDF from the raster alone, which is what makes it genuinely
text-layer-free. English round-trips exactly.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>


════════════════════════════════════════
2b95d2f0b  2026-09-07  khunmax2
fix(bridge): a rotated key reaches the course studio without a shell

The provider bridge was a script under deploy/ plus a container restart. Both
are things a user cannot do, and the person whose key expires is a user with a
settings page, not an operator with SSH. Their key runs out, they paste a new
one into DeepTutor, and the embedded studio keeps using the dead one — alive and
broken at the same time.

The mapping moves out of build_server_providers.py into
deeptutor/services/config/openmaic_bridge.py, which ships inside the image
(deploy/ does not), and ModelCatalogService.save() calls it. save() is the one
place every settings path funnels through, so the settings page, the connection
tester and the partner flows are covered by hooking it once. Best-effort by
construction: an unmappable provider or a read-only data directory is logged and
skipped rather than costing the user the settings they just saved.
DEEPTUTOR_OPENMAIC_BRIDGE=0 disables it.

OpenMAIC's getConfig() cached the parsed YAML for the life of the process, which
is the wrong shape for a read-only mount another process rewrites. It is now
keyed on mtime + size; a statSync per call is nothing beside the LLM round trip
that follows.

The script stays as a thin CLI over the same module — one implementation, two
entry points — for a first bring-up and for --dry-run.

Also: the bridge's image and video binding tables were empty, so a configured
image provider was skipped entirely. Filled in, including openrouter, which
answers the same /images/generations contract openai-image calls and returns
data[0].b64_json as that adapter expects — verified against the real endpoint at
1024x576, the 16:9 size slides ask for.

Verified with no restart: change the model, save, and /api/server-providers in
the studio returns it, while docker inspect reports restarts: 0 and the log
shows three "Loaded (server-providers.yml)" lines in one process.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>


════════════════════════════════════════
acfc22e3e  2026-09-07  khunmax2
feat(maic): say when a media capability is ready but switched off

Configuring an image provider and switching image generation on are two
controls in two places — the settings page owns the first, the popover beside
the compose box owns the second — and nothing connected them. A credit key, a
working provider and a bridge that carried it through still produced courses
with no pictures, because imageGenerationEnabled defaults to false and the
prompt never asks for an image while it is.

The default is right; images cost money per call. The silence was not:

- an enabled tab carried a violet dot, and a tab whose provider is configured
  but switched off looked identical to one with no provider at all. It now
  carries a hollow dot.
- the image tab says so when off with a usable provider.
- the settings page, where the provider was configured, names the state and
  where the switch actually lives.

Four keys, 13 languages, two files — both small UI insertions rather than
changes to existing logic, and none of it is DeepTutor-specific, so it is an
upstream candidate rather than something to carry.

Found in passing: the popover's tab labels (Image/Video/TTS/ASR) were hardcoded
English in every language, in the file being edited. Now media.tab*.

Verified in the browser: hollow dot on the image tab, the hint under its switch,
and "การสร้างภาพยังปิดอยู่ เปิดได้ที่ปุ่มสื่อ ข้างช่องพิมพ์ในหน้าแรก" on the
settings tab. tsc clean, eslint clean, i18n gate 13 locales, contract green
after the pin bump (1798 -> 1862 keys).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

