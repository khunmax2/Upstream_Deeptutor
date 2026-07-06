"""Static host for the DeepTutor voice-call page (`call.html`).

The call page talks directly to DeepTutor's own realtime socket
(``ws://localhost:8001/api/v1/voice/ws`` → the real ChatOrchestrator, with STT/TTS
resolved from the Settings > Voice catalog). This tiny server exists only to
serve the page from an ``http://localhost`` origin, which browsers require to
grant microphone access (a ``file://`` page cannot use the mic).

The earlier standalone demos (`/` audio pipeline, `/mvp` browser-speech) and
their prototype-local STT→LLM→TTS handlers were removed once the focus moved to
the DeepTutor-backed call page; the provider seam they exercised still lives in
``providers.py`` / ``pipeline.py`` and is covered by ``selftest.py`` + ``tests/``.
"""

from __future__ import annotations

from pathlib import Path

from config import CONFIG
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="DeepTutor Voice Call")
STATIC = Path(__file__).parent / "static"


@app.get("/")
@app.get("/call")
async def call() -> FileResponse:
    return FileResponse(STATIC / "call.html")


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


# Serve any extra static assets (e.g. future images) alongside the page.
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=CONFIG.host, port=CONFIG.port)
