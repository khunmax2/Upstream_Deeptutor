"""Tests for the in-page-agent LLM proxy.

The proxy's whole reason to exist is that the browser must never hold the
provider key, and must never be able to spend it on a model of its choosing.
Both of those are pinned here, plus honest upstream status pass-through
(page-agent retries on 429/5xx).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from deeptutor.api.routers import llm_proxy


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(llm_proxy.router, prefix="/api/v1/llm-proxy")
    return TestClient(app)


class _Config:
    def __init__(self, **kw: Any) -> None:
        self.model = kw.get("model", "gemini-3.1-flash-lite")
        self.api_key = kw.get("api_key", "server-side-secret")
        self.base_url = kw.get("base_url", "https://provider.example/v1")
        self.effective_url = kw.get("effective_url")
        self.extra_headers: dict[str, str] = kw.get("extra_headers", {})


def _patch_config(monkeypatch: pytest.MonkeyPatch, config: _Config) -> None:
    monkeypatch.setattr(llm_proxy, "get_llm_config", lambda: config)


def _patch_upstream(
    monkeypatch: pytest.MonkeyPatch, *, status: int = 200, payload: Any = None
) -> dict[str, Any]:
    """Capture what we send upstream; reply with *status*/*payload*."""
    seen: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def post(self, url: str, json: Any, headers: dict[str, str]) -> httpx.Response:
            seen["url"] = url
            seen["json"] = json
            seen["headers"] = headers
            return httpx.Response(
                status,
                json=payload if payload is not None else {"choices": []},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(llm_proxy.httpx, "AsyncClient", _FakeClient)
    return seen


def test_key_stays_server_side_and_model_is_pinned(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_config(monkeypatch, _Config())
    seen = _patch_upstream(monkeypatch)

    # The browser asks for an expensive model it must not get.
    res = client.post(
        "/api/v1/llm-proxy/chat/completions",
        json={"model": "some-huge-model", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert res.status_code == 200
    assert seen["url"] == "https://provider.example/v1/chat/completions"
    assert seen["json"]["model"] == "gemini-3.1-flash-lite"  # pinned server-side
    assert seen["json"]["messages"][0]["content"] == "hi"  # body otherwise forwarded
    assert seen["headers"]["Authorization"] == "Bearer server-side-secret"


def test_upstream_status_passes_through(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """page-agent decides retries from the status — never flatten it to 200."""
    _patch_config(monkeypatch, _Config())
    _patch_upstream(monkeypatch, status=429, payload={"error": {"message": "rate limited"}})

    res = client.post("/api/v1/llm-proxy/chat/completions", json={"messages": []})

    assert res.status_code == 429
    assert res.json()["error"]["message"] == "rate limited"


def test_unconfigured_provider_is_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_config(monkeypatch, _Config(api_key="", base_url=""))
    res = client.post("/api/v1/llm-proxy/chat/completions", json={"messages": []})
    assert res.status_code == 503


def test_upstream_failure_is_502(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_config(monkeypatch, _Config())

    class _Boom:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> "_Boom":
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def post(self, *a: Any, **kw: Any) -> httpx.Response:
            raise httpx.ConnectError("no route")

    monkeypatch.setattr(llm_proxy.httpx, "AsyncClient", _Boom)
    res = client.post("/api/v1/llm-proxy/chat/completions", json={"messages": []})
    assert res.status_code == 502


def test_malformed_body_is_400(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_config(monkeypatch, _Config())
    res = client.post(
        "/api/v1/llm-proxy/chat/completions",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 400
