"""OpenAI-compatible LLM proxy for the in-page agent (page-agent evaluation).

page-agent runs entirely in the browser and needs an OpenAI-compatible
`/chat/completions` endpoint. Pointing it straight at the provider would ship
our API key into the bundle, so instead the browser talks to *this* endpoint —
authenticated by the app's own session cookie — and the server forwards the
request using the key from the active LLM catalog profile.

Two guarantees the browser cannot bypass:

* the provider key never leaves the server;
* the model is pinned server-side, so a page in the browser cannot spend our
  key on an arbitrary (expensive) model.

Upstream status codes are passed through unchanged: page-agent inspects them to
decide on retries (429 / 5xx). Fork-additive: a new router file, registered in
``main.py`` behind the same auth dependency as the rest of the API.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import httpx

from deeptutor.services.llm import get_llm_config

logger = logging.getLogger(__name__)

router = APIRouter()

# page-agent's steps are single non-streaming completions, but a big DOM
# inventory + a slow model can still run long.
_UPSTREAM_TIMEOUT_S = 120.0

# The in-page agent's loop is far heavier than a chat turn: it feeds an indexed
# DOM tree into the prompt and tool-calls for up to 40 steps. The chat model the
# app is configured with may be a "lite" tier that cannot hold that up, so allow
# an operator-set override — still server-side, so the browser can never pick a
# model to spend our key on. Unset ⇒ use the app's configured model.
_MODEL_OVERRIDE_ENV = "LLM_PROXY_MODEL"


@router.post("/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    """Forward an OpenAI-compatible completion to the active LLM provider."""
    try:
        body: dict[str, Any] = await request.json()
    except Exception:  # noqa: BLE001 — a malformed body is a client error
        return JSONResponse({"error": {"message": "Invalid JSON body."}}, status_code=400)

    config = get_llm_config()
    base_url = (config.effective_url or config.base_url or "").rstrip("/")
    if not base_url or not config.api_key:
        return JSONResponse(
            {"error": {"message": "LLM provider is not configured (base_url / api_key)."}},
            status_code=503,
        )

    # Pin the model server-side — the browser must not choose it. An operator
    # may override which one via LLM_PROXY_MODEL (see the note above).
    model = (os.getenv(_MODEL_OVERRIDE_ENV) or "").strip() or config.model
    payload = {**body, "model": model}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.api_key}",
        **(config.extra_headers or {}),
    }

    try:
        async with httpx.AsyncClient(timeout=_UPSTREAM_TIMEOUT_S) as client:
            upstream = await client.post(
                f"{base_url}/chat/completions", json=payload, headers=headers
            )
    except httpx.HTTPError as exc:
        logger.error("llm-proxy: upstream request failed: %s", exc)
        return JSONResponse({"error": {"message": f"LLM upstream failed: {exc}"}}, status_code=502)

    if upstream.status_code >= 400:
        logger.warning("llm-proxy: upstream returned %s", upstream.status_code)
    try:
        data = upstream.json()
    except ValueError:
        data = {"error": {"message": f"LLM upstream returned {upstream.status_code}"}}
    # Pass the status through — page-agent retries on 429/5xx.
    return JSONResponse(data, status_code=upstream.status_code)


__all__ = ["router"]
