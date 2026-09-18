"""``/api/auth/status`` says whether the caller is the primary admin.

The Course Studio gatekeeper reads this answer and turns it into the
``x-deeptutor-primary`` header, the only way the studio can tell the
deployment's primary administrator from a promoted one (admin design §4,
Phase 2). Every other admin, and every user, must read ``false``.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

PASSWORD = "pw-status-primary"


@pytest.fixture
def world(mu_isolated_root, monkeypatch):
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user.identity import save_user, set_role
    from deeptutor.multi_user.primary_admin import primary_admin_id
    from deeptutor.services import auth as auth_service
    from deeptutor.services.auth import create_token, hash_password

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "test-secret-for-status-primary")
    monkeypatch.setattr(auth_service, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)

    owner = save_user("owner", hash_password(PASSWORD), role="admin")
    assert primary_admin_id() == owner["id"]
    demo = save_user("demo", hash_password(PASSWORD))
    set_role("demo", "admin")
    student = save_user("student", hash_password(PASSWORD))
    tokens = {
        name: create_token(name, record["role"], record["id"])
        for name, record in (("owner", owner), ("demo", demo), ("student", student))
    }
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    return TestClient(app), tokens


def _status(client, token: str | None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = client.get("/api/auth/status", headers=headers)
    assert response.status_code == 200
    return response.json()


def test_only_the_primary_admin_reads_is_primary(world):
    client, tokens = world
    owner = _status(client, tokens["owner"])
    assert owner["is_admin"] is True
    assert owner["is_primary"] is True

    demo = _status(client, tokens["demo"])
    assert demo["is_admin"] is True
    assert demo["is_primary"] is False

    student = _status(client, tokens["student"])
    assert student["is_admin"] is False
    assert student["is_primary"] is False


def test_an_anonymous_request_is_not_primary(world):
    client, _ = world
    anonymous = _status(client, None)
    assert anonymous["authenticated"] is False
    assert anonymous["is_primary"] is False


def test_auth_disabled_means_the_local_admin_is_primary(monkeypatch):
    from deeptutor.api.routers import auth as auth_router

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", False)
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    body = TestClient(app).get("/api/auth/status").json()
    assert body["user_id"] == "local-admin"
    assert body["is_primary"] is True
