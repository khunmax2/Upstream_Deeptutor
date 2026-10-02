# Diagnostic probes

Three scripts that each caught a real bug, salvaged on 2026-10-02 from an
uncommitted 2026-09-13 handoff folder before it was deleted. They are kept
because none of them is reproducible from the committed runbooks: the other
probes beside them (`../e2e_turn_check.py`, `../ocr_check.py`,
`../nginx_upload_ceiling.py`) answer different questions.

None of them mints a token for you to paste anywhere. Where one is needed,
write it to a file and pass the path — a token in a chat log is a live
session.

| script | the question it answers | how to run |
|---|---|---|
| `ws_turn_probe_in_container.py` | is a stalled turn stuck in the server or in the UI? Replays `start_turn` over `/ws` from inside the container and prints every event with a timestamp | `docker cp` it to `deeptutor2:/tmp/`, then `docker exec -w /app -e PYTHONPATH=/app deeptutor2 python3 /tmp/ws_turn_probe_in_container.py [chat\|reading]`. It mints its own token for the first admin; set `reading_material_id` to a real one |
| `ws_turn_probe_via_proxy.py` | the same turn, but through nginx from outside, so the payload can be compared with the browser's. `browser` mode sends exactly what the UI sends | `PROBE_URL=wss://…/deepwitya/ws python ws_turn_probe_via_proxy.py browser <token-file>` |
| `studio_f1_probe.py` | does the studio's private-unless-published rule hold end to end? Alice creates a course, Bob tries every read path, then publish/unpublish | a sidecar on the studio network: `docker run --rm --network upstream_deeptutor_studio-net -v $PWD/deploy/probes:/t python:3.12-slim python -u /t/studio_f1_probe.py http://openmaic:3000/deepwitya/studio`. `freshness` is a long poll — a timeout there is the normal answer |

Also worth keeping from the same folder:

* **A reading-assistant hang was guessed wrong twice** (CPU in embedding, then
  an image URL on 127.0.0.1) before a WS frame from the browser, compared with
  the server's validator, showed what it was: `ReadingViewport` is
  `extra="forbid"` and the UI was sending `time_seconds`. Read the events
  before concluding anything.
* **`docker exec … python3 - <<PY` prints nothing** — a heredoc needs
  `docker exec -i`.
* **py-spy** gives a thread dump of a wedged backend from a sidecar:
  `--pid=container:deeptutor2 --cap-add SYS_PTRACE`.
