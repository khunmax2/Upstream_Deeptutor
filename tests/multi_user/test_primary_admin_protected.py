"""No other admin can demote or delete the primary administrator.

Fork. The first admin owns the deployment workspace (``primary_admin.py``), and
the user asked for it to be the deployment's superadmin (report 2026-09-15: a
promoted DeepWitya admin could demote the first admin from Settings > Users,
and delete it). The role and delete routes refused only an admin acting on its
own account. Demoting the first admin also opened the learner routes to it --
a password reset among them -- because those refuse only admin targets.

Every admin keeps managing every other account, other admins included.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def world(mu_isolated_root, monkeypatch):
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import multi_user as multi_user_router
    from deeptutor.multi_user.identity import save_user, set_role
    from deeptutor.multi_user.primary_admin import primary_admin_id
    from deeptutor.services.auth import TokenPayload, hash_password

    owner = save_user("owner", hash_password("owner-password"), role="admin")
    # Elected now, while the owner is the only admin: the record is sticky.
    assert primary_admin_id() == owner["id"]
    demo = save_user("demo", hash_password("demo-password"))
    set_role("demo", "admin")
    helper = save_user("helper", hash_password("helper-password"))
    set_role("helper", "admin")
    save_user("student", hash_password("student-password"))
    tokens = {
        "owner-token": TokenPayload(username="owner", role="admin", user_id=owner["id"]),
        "demo-token": TokenPayload(username="demo", role="admin", user_id=demo["id"]),
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    monkeypatch.setattr(multi_user_router, "POCKETBASE_ENABLED", False)

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    app.include_router(multi_user_router.router, prefix="/api/multi-user")
    return TestClient(app), {"owner": owner, "demo": demo, "helper": helper}


def _role_of(username: str) -> str | None:
    from deeptutor.multi_user.identity import get_user

    record = get_user(username)
    return None if record is None else str(record.get("role") or "user")


def test_a_promoted_admin_cannot_demote_the_primary_admin(world):
    client, _ = world
    res = client.put(
        "/api/auth/users/owner/role", json={"role": "user"}, headers=_auth("demo-token")
    )
    assert res.status_code == 403
    assert _role_of("owner") == "admin"


def test_a_promoted_admin_cannot_delete_the_primary_admin(world):
    client, _ = world
    res = client.delete("/api/auth/users/owner", headers=_auth("demo-token"))
    assert res.status_code == 403
    assert _role_of("owner") == "admin"


def test_the_primary_admins_password_stays_out_of_reach(world):
    """The reset route refuses admin targets; a refused demotion keeps it so."""
    client, accounts = world
    client.put("/api/auth/users/owner/role", json={"role": "user"}, headers=_auth("demo-token"))
    res = client.post(
        f"/api/multi-user/learners/{accounts['owner']['id']}/credentials/reset",
        json={"new_password": "taken-over-1234"},
        headers=_auth("demo-token"),
    )
    assert res.status_code == 403


def test_the_primary_admin_manages_every_other_account(world):
    """Since Phase 1 step 2 (test_admin_management.py) roles and deletions are
    the primary admin's alone; this checks the primary side of the rule."""
    client, _ = world
    demote_helper = client.put(
        "/api/auth/users/helper/role", json={"role": "user"}, headers=_auth("owner-token")
    )
    assert demote_helper.status_code == 200
    assert _role_of("helper") == "user"
    assert client.delete("/api/auth/users/student", headers=_auth("owner-token")).status_code == 200
    assert _role_of("student") is None
    demote_demo = client.put(
        "/api/auth/users/demo/role", json={"role": "user"}, headers=_auth("owner-token")
    )
    assert demote_demo.status_code == 200


def test_an_unknown_account_is_still_not_found(world):
    client, _ = world
    assert client.delete("/api/auth/users/ghost", headers=_auth("demo-token")).status_code == 404
    res = client.put(
        "/api/auth/users/ghost/role", json={"role": "user"}, headers=_auth("demo-token")
    )
    assert res.status_code == 404


def test_the_user_list_marks_the_primary_admin(world):
    client, _ = world
    users = client.get("/api/auth/users", headers=_auth("demo-token")).json()
    assert [user["username"] for user in users if user.get("is_primary")] == ["owner"]
