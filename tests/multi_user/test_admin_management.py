"""Only the primary admin manages admins, and every account change is audited.

Fork, Phase 1 step 2 of docs/planning/admin-roles/DESIGN_primary_admin_and_account_lifecycle.md
(§2 and §5, decided 2026-09-15). Before this, any admin could promote, demote
and delete any account but the primary admin (PR #108), and none of it left a
line in ``data/system/audit/usage.jsonl``: two admin accounts were deleted on
the host on 2026-09-15 and nothing said by whom.

Now: promoting, demoting and deleting are the primary admin's alone; other
admins keep creating accounts (as ``user``) and managing ordinary users; and
``account_create``, ``account_role_set`` and ``account_delete`` are recorded
with the actor, the target and what changed.
"""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _audit(mu_isolated_root, action: str) -> list[dict]:
    path = mu_isolated_root / "data" / "system" / "audit" / "usage.jsonl"
    if not path.exists():
        return []
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [line for line in lines if line.get("action") == action]


def _role_of(username: str) -> str | None:
    from deeptutor.multi_user.identity import get_user

    record = get_user(username)
    return None if record is None else str(record.get("role") or "user")


@pytest.fixture
def world(mu_isolated_root, monkeypatch):
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user.identity import save_user, set_role
    from deeptutor.multi_user.primary_admin import primary_admin_id
    from deeptutor.services.auth import TokenPayload, hash_password

    owner = save_user("owner", hash_password("owner-password"), role="admin")
    assert primary_admin_id() == owner["id"]
    demo = save_user("demo", hash_password("demo-password"))
    set_role("demo", "admin")
    helper = save_user("helper", hash_password("helper-password"))
    set_role("helper", "admin")
    student = save_user("student", hash_password("student-password"))
    tokens = {
        "owner-token": TokenPayload(username="owner", role="admin", user_id=owner["id"]),
        "demo-token": TokenPayload(username="demo", role="admin", user_id=demo["id"]),
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    return TestClient(app), {"owner": owner, "demo": demo, "helper": helper, "student": student}


def test_only_the_primary_admin_promotes(world):
    client, accounts = world
    refused = client.put(
        "/api/auth/users/student/role", json={"role": "admin"}, headers=_auth("demo-token")
    )
    assert refused.status_code == 403
    assert _role_of("student") == "user"

    allowed = client.put(
        "/api/auth/users/student/role", json={"role": "admin"}, headers=_auth("owner-token")
    )
    assert allowed.status_code == 200
    assert _role_of("student") == "admin"


def test_only_the_primary_admin_demotes_an_admin(world):
    client, _ = world
    refused = client.put(
        "/api/auth/users/helper/role", json={"role": "user"}, headers=_auth("demo-token")
    )
    assert refused.status_code == 403
    assert _role_of("helper") == "admin"

    allowed = client.put(
        "/api/auth/users/helper/role", json={"role": "user"}, headers=_auth("owner-token")
    )
    assert allowed.status_code == 200
    assert _role_of("helper") == "user"


def test_only_the_primary_admin_deletes(world):
    client, _ = world
    assert client.delete("/api/auth/users/student", headers=_auth("demo-token")).status_code == 403
    assert _role_of("student") == "user"
    assert client.delete("/api/auth/users/student", headers=_auth("owner-token")).status_code == 200
    assert _role_of("student") is None


def test_the_primary_admin_still_cannot_touch_itself(world):
    client, _ = world
    assert client.delete("/api/auth/users/owner", headers=_auth("owner-token")).status_code == 400
    res = client.put(
        "/api/auth/users/owner/role", json={"role": "user"}, headers=_auth("owner-token")
    )
    assert res.status_code == 400


def test_other_admins_still_create_accounts(world):
    client, _ = world
    res = client.post(
        "/api/auth/users",
        json={"username": "newbie", "password": "newbie-password", "preset": "standard"},
        headers=_auth("demo-token"),
    )
    assert res.status_code == 201
    assert res.json()["role"] == "user"
    assert _role_of("newbie") == "user"


def test_the_bootstrap_admin_manages_admins_when_it_owns_the_deployment(
    mu_isolated_root, monkeypatch
):
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user.identity import save_user
    from deeptutor.multi_user.primary_admin import (
        ENV_ADMIN_ID,
        primary_admin_id,
        reset_primary_admin_cache,
    )
    from deeptutor.services import auth as auth_service
    from deeptutor.services.auth import TokenPayload, hash_password

    monkeypatch.setattr(auth_service, "AUTH_USERNAME", "operator")
    monkeypatch.setattr(auth_service, "AUTH_PASSWORD_HASH", hash_password("operator-password"))
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    reset_primary_admin_cache()
    save_user("student", hash_password("student-password"))
    assert primary_admin_id() == ENV_ADMIN_ID
    tokens = {"op-token": TokenPayload(username="operator", role="admin", user_id=ENV_ADMIN_ID)}
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    client = TestClient(app)

    res = client.put(
        "/api/auth/users/student/role", json={"role": "admin"}, headers=_auth("op-token")
    )
    assert res.status_code == 200
    assert _role_of("student") == "admin"


def test_every_account_change_is_audited(world, mu_isolated_root):
    client, accounts = world

    client.post(
        "/api/auth/users",
        json={"username": "newbie", "password": "newbie-password", "preset": "learner"},
        headers=_auth("demo-token"),
    )
    client.put("/api/auth/users/student/role", json={"role": "admin"}, headers=_auth("owner-token"))
    client.delete("/api/auth/users/helper", headers=_auth("owner-token"))

    created = _audit(mu_isolated_root, "account_create")
    assert len(created) == 1
    assert created[0]["actor_id"] == accounts["demo"]["id"]
    assert created[0]["summary"] == {"username": "newbie", "role": "user", "preset": "learner"}
    assert created[0]["target_user_id"] == _user_id("newbie")

    role_set = _audit(mu_isolated_root, "account_role_set")
    assert len(role_set) == 1
    assert role_set[0]["actor_id"] == accounts["owner"]["id"]
    assert role_set[0]["target_user_id"] == accounts["student"]["id"]
    assert role_set[0]["summary"] == {"username": "student", "from": "user", "to": "admin"}

    deleted = _audit(mu_isolated_root, "account_delete")
    assert len(deleted) == 1
    assert deleted[0]["actor_id"] == accounts["owner"]["id"]
    assert deleted[0]["target_user_id"] == accounts["helper"]["id"]
    assert deleted[0]["summary"] == {"username": "helper", "role": "admin"}


def test_a_refusal_is_audited_and_logged(world, mu_isolated_root, caplog):
    client, accounts = world
    with caplog.at_level(logging.WARNING, logger="deeptutor.api.routers.auth"):
        client.put(
            "/api/auth/users/student/role", json={"role": "admin"}, headers=_auth("demo-token")
        )
    refused = _audit(mu_isolated_root, "account_change_refused")
    assert len(refused) == 1
    assert refused[0]["actor_id"] == accounts["demo"]["id"]
    assert refused[0]["target_user_id"] == accounts["student"]["id"]
    assert "refused" in caplog.text.lower()
    assert not _audit(mu_isolated_root, "account_role_set")


def _user_id(username: str) -> str:
    from deeptutor.multi_user.identity import get_user

    return str((get_user(username) or {}).get("id") or "")
