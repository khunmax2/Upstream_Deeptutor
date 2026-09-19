"""Fork: the `student` and `teacher` presets (school roles design, Phase 1).

Both are labels on an ordinary `user`, never a role. A `student` is the full
product with no learning policy (upstream treats it as any user); a
`teacher` behaves as `custom`. They are created by admins like any preset,
survive the canonical record, and come back through `/status` and `/users`.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

PASSWORD = "pw-school-presets"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def world(mu_isolated_root, monkeypatch):
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services import auth as auth_service
    from deeptutor.services.auth import create_token, hash_password

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "test-secret-for-school-presets")
    monkeypatch.setattr(auth_service, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)

    owner = save_user("owner", hash_password(PASSWORD), role="admin")
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    return TestClient(app), create_token("owner", "admin", owner["id"])


@pytest.mark.parametrize("preset", ["student", "teacher"])
def test_an_admin_creates_the_preset_and_it_survives_the_store(world, preset):
    from deeptutor.multi_user.grants import load_grant
    from deeptutor.multi_user.identity import get_user
    from deeptutor.services.auth import create_token

    client, admin = world
    created = client.post(
        "/api/auth/users",
        json={"username": f"{preset}-1", "password": PASSWORD, "preset": preset},
        headers=_auth(admin),
    )
    assert created.status_code == 201, created.text
    assert created.json()["preset"] == preset
    assert created.json()["role"] == "user"

    record = get_user(f"{preset}-1")
    assert record is not None and record["preset"] == preset
    # No learning policy: upstream's child mode is not what a student or a
    # teacher is (design decisions 4 and 5).
    assert load_grant(record["id"]).get("learning_policy") is None

    listed = {u["username"]: u for u in client.get("/api/auth/users", headers=_auth(admin)).json()}
    assert listed[f"{preset}-1"]["preset"] == preset

    token = create_token(f"{preset}-1", "user", record["id"])
    status = client.get("/api/auth/status", headers=_auth(token)).json()
    assert status["authenticated"] is True
    assert status["preset"] == preset
    assert status["learning_policy"] is None


def test_an_unknown_preset_is_still_refused(world):
    client, admin = world
    refused = client.post(
        "/api/auth/users",
        json={"username": "x", "password": PASSWORD, "preset": "principal"},
        headers=_auth(admin),
    )
    assert refused.status_code == 422


def test_a_stored_record_keeps_the_new_presets_through_canonicalisation():
    from deeptutor.multi_user.identity import _canonical_record

    for preset in ("student", "teacher"):
        record = _canonical_record("u", {"hash": "h", "preset": preset})
        assert record is not None and record["preset"] == preset
    assert _canonical_record("u", {"hash": "h", "preset": "principal"})["preset"] == "standard"
