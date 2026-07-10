"""OpenAI-compatible LLM proxy for the in-page agent (page-agent evaluation).

page-agent runs entirely in the browser and needs an OpenAI-compatible
`/chat/completions` endpoint. Pointing it straight at the provider would ship
our API key into the bundle, so instead the browser talks to *this* endpoint —
authenticated by the app's own session cookie — and the server forwards the
request upstream with a server-side key.

Two guarantees the browser cannot bypass, in either mode below:

* the provider key never leaves the server;
* the model is pinned server-side, so a page in the browser cannot spend our
  key on an arbitrary (expensive) model.

**Two upstream modes.**

1. *Standalone* (preferred for evaluation) — set all three of
   ``LLM_PROXY_BASE_URL`` / ``LLM_PROXY_API_KEY`` / ``LLM_PROXY_MODEL`` and the
   proxy talks to that OpenAI-compatible endpoint directly, with **no coupling
   to DeepTutor's LLM catalog at all**. This exists because the in-page agent's
   loop is far heavier than a chat turn (it feeds an indexed DOM tree into the
   prompt and tool-calls for up to 40 steps), so it often needs a different —
   usually stronger — model than the app's configured chat model. The reference
   integration (the suanrao project) runs page-agent on `gemini-2.5-flash`,
   while this app's chat model is a `-lite` tier; that difference is the leading
   suspect for page-agent behaving erratically here.

2. *Catalog fallback* — with no standalone vars set, the proxy uses the active
   LLM catalog profile (``LLM_PROXY_MODEL`` alone may still override its model).

Either way this is a **pure pass-through**: no ``ChatOrchestrator``, no agent
loop, no capabilities, no RAG. The request body is forwarded as-is apart from
the pinned ``model``. Upstream status codes are passed through unchanged —
page-agent inspects them to decide on retries (429 / 5xx).

Fork-additive: a new router file, registered in ``main.py`` behind the same auth
dependency as the rest of the API.
"""

from __future__ import annotations

import logging
import os
from typing import Any, NamedTuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import httpx

from deeptutor.services.llm import get_llm_config

logger = logging.getLogger(__name__)

router = APIRouter()

# page-agent's steps are single non-streaming completions, but a big DOM
# inventory + a slow model can still run long.
_UPSTREAM_TIMEOUT_S = 120.0

_BASE_URL_ENV = "LLM_PROXY_BASE_URL"
_API_KEY_ENV = "LLM_PROXY_API_KEY"
_MODEL_ENV = "LLM_PROXY_MODEL"


class _Upstream(NamedTuple):
    base_url: str
    api_key: str
    model: str
    extra_headers: dict[str, str]
    source: str


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _resolve_upstream() -> _Upstream | str:
    """The upstream to forward to, or an error message explaining what's missing."""
    base_url, api_key, model = _env(_BASE_URL_ENV), _env(_API_KEY_ENV), _env(_MODEL_ENV)

    # Standalone mode: any of the two connection vars present means the operator
    # intends to bypass the catalog — then all three are required, so a
    # half-configured proxy fails loudly instead of silently using the chat model.
    if base_url or api_key:
        missing = [
            name
            for name, value in (
                (_BASE_URL_ENV, base_url),
                (_API_KEY_ENV, api_key),
                (_MODEL_ENV, model),
            )
            if not value
        ]
        if missing:
            return f"LLM proxy is half-configured; set {', '.join(missing)}."
        return _Upstream(base_url.rstrip("/"), api_key, model, {}, "env")

    config = get_llm_config()
    catalog_url = (config.effective_url or config.base_url or "").rstrip("/")
    if not catalog_url or not config.api_key:
        return "LLM provider is not configured (base_url / api_key)."
    return _Upstream(
        catalog_url,
        config.api_key,
        model or config.model,  # LLM_PROXY_MODEL may override the catalog's model
        dict(config.extra_headers or {}),
        "catalog",
    )


@router.post("/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    """Forward an OpenAI-compatible completion to the resolved upstream."""
    try:
        body: dict[str, Any] = await request.json()
    except Exception:  # noqa: BLE001 — a malformed body is a client error
        return JSONResponse({"error": {"message": "Invalid JSON body."}}, status_code=400)

    upstream = _resolve_upstream()
    if isinstance(upstream, str):
        return JSONResponse({"error": {"message": upstream}}, status_code=503)

    # Pin the model server-side — the browser must not choose it.
    payload = {**body, "model": upstream.model}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {upstream.api_key}",
        **upstream.extra_headers,
    }

    try:
        async with httpx.AsyncClient(timeout=_UPSTREAM_TIMEOUT_S) as client:
            response = await client.post(
                f"{upstream.base_url}/chat/completions", json=payload, headers=headers
            )
    except httpx.HTTPError as exc:
        logger.error("llm-proxy: upstream request failed: %s", exc)
        return JSONResponse({"error": {"message": f"LLM upstream failed: {exc}"}}, status_code=502)

    if response.status_code >= 400:
        logger.warning(
            "llm-proxy: upstream returned %s (source=%s model=%s)",
            response.status_code,
            upstream.source,
            upstream.model,
        )
    try:
        data = response.json()
    except ValueError:
        data = {"error": {"message": f"LLM upstream returned {response.status_code}"}}
    # Pass the status through — page-agent retries on 429/5xx.
    return JSONResponse(data, status_code=response.status_code)


__all__ = ["router"]
