"""An account is disabled instead of deleted, and a disabled account is out.

Fork, Phase 1 step 3 of docs/planning/admin-roles/DESIGN_primary_admin_and_account_lifecycle.md
(§3 and §6, decided 2026-09-15). Account records always carried a ``disabled``
flag, and nothing read it: a disabled account could sign in and its tokens
kept working. Deleting was the only way to shut an account, and deleting
strands its data (Phase 2 makes that the primary admin's deliberate act).

Now ``PUT /api/auth/users/{username}/disabled`` flips the flag: any admin for
an ordinary user, the primary admin alone for an admin, nobody for the primary
admin or themselves. A disabled account cannot sign in, its tokens stop
working on every request (``decode_token`` is the one gate), ``/api/auth/status``
says it is not signed in -- so the Course Studio gatekeeper refuses it too --
and its device credentials are revoked. Enabling puts it back. Both are audited.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

PASSWORD = "correct-horse-battery"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _audit(mu_isolated_root, action: str) -> list[dict]:
    path = mu_isolated_root / "data" / "system" / "audit" / "usage.jsonl"
    if not path.exists():
        return []
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [line for line in lines if line.get("action") == action]


def _disabled(username: str) -> bool | None:
    from deeptutor.multi_user.identity import get_user

    record = get_user(username)
    return None if record is None else bool(record.get("disabled"))


@pytest.fixture
def world(mu_isolated_root, monkeypatch):
    """Real tokens through the real ``decode_token``, so enforcement is exercised."""
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user.identity import save_user, set_role
    from deeptutor.multi_user.primary_admin import primary_admin_id
    from deeptutor.services import auth as auth_service
    from deeptutor.services.auth import create_token, hash_password

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "test-secret-for-account-disable")
    monkeypatch.setattr(auth_service, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)

    owner = save_user("owner", hash_password(PASSWORD), role="admin")
    assert primary_admin_id() == owner["id"]
    demo = save_user("demo", hash_password(PASSWORD))
    set_role("demo", "admin")
    helper = save_user("helper", hash_password(PASSWORD))
    set_role("helper", "admin")
    student = save_user("student", hash_password(PASSWORD))
    tokens = {
        name: create_token(name, record["role"], record["id"])
        for name, record in (
            ("owner", owner),
            ("demo", demo),
            ("helper", helper),
            ("student", student),
        )
    }

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    accounts = {"owner": owner, "demo": demo, "helper": helper, "student": student}
    return TestClient(app), tokens, accounts


def _set_disabled(client, token: str, username: str, disabled: bool):
    return client.put(
        f"/api/auth/users/{username}/disabled",
        json={"disabled": disabled},
        headers=_auth(token),
    )


def test_any_admin_disables_and_enables_an_ordinary_user(world, mu_isolated_root):
    client, tokens, accounts = world
    assert _set_disabled(client, tokens["demo"], "student", True).status_code == 200
    assert _disabled("student") is True
    assert _set_disabled(client, tokens["demo"], "student", False).status_code == 200
    assert _disabled("student") is False

    disabled = _audit(mu_isolated_root, "account_disable")
    enabled = _audit(mu_isolated_root, "account_enable")
    assert [line["target_user_id"] for line in disabled] == [accounts["student"]["id"]]
    assert [line["target_user_id"] for line in enabled] == [accounts["student"]["id"]]
    assert disabled[0]["actor_id"] == accounts["demo"]["id"]
    assert disabled[0]["summary"] == {"username": "student", "role": "user"}


def test_only_the_primary_admin_disables_an_admin(world):
    client, tokens, _ = world
    assert _set_disabled(client, tokens["demo"], "helper", True).status_code == 403
    assert _disabled("helper") is False
    assert _set_disabled(client, tokens["owner"], "helper", True).status_code == 200
    assert _disabled("helper") is True


def test_nobody_disables_the_primary_admin_or_themselves(world):
    client, tokens, _ = world
    assert _set_disabled(client, tokens["demo"], "owner", True).status_code == 403
    assert _set_disabled(client, tokens["owner"], "owner", True).status_code == 400
    assert _set_disabled(client, tokens["demo"], "demo", True).status_code == 400
    assert _set_disabled(client, tokens["owner"], "ghost", True).status_code == 404
    assert _disabled("owner") is False


def test_a_disabled_account_cannot_sign_in_and_its_tokens_stop_working(world):
    client, tokens, _ = world
    # Before: the token works and the account can sign in.
    assert client.get("/api/auth/profile", headers=_auth(tokens["student"])).status_code == 200
    assert client.get("/api/auth/status", headers=_auth(tokens["student"])).json()["authenticated"]

    assert _set_disabled(client, tokens["owner"], "student", True).status_code == 200

    assert client.get("/api/auth/profile", headers=_auth(tokens["student"])).status_code == 401
    status = client.get("/api/auth/status", headers=_auth(tokens["student"])).json()
    assert status["authenticated"] is False
    login = client.post("/api/auth/login", json={"username": "student", "password": PASSWORD})
    assert login.status_code == 403
    assert "disabled" in login.json()["detail"].lower()

    assert _set_disabled(client, tokens["owner"], "student", False).status_code == 200
    assert client.get("/api/auth/profile", headers=_auth(tokens["student"])).status_code == 200
    assert (
        client.post(
            "/api/auth/login", json={"username": "student", "password": PASSWORD}
        ).status_code
        == 200
    )


def test_disabling_revokes_the_accounts_device_credentials(world):
    from deeptutor.multi_user.device_credentials import (
        issue_device_credential,
        list_device_credentials,
    )
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services.auth import hash_password

    client, tokens, _ = world
    # Device credentials are a learner-preset feature.
    kid = save_user("kid", hash_password(PASSWORD), preset="learner")
    issue_device_credential(
        user_id=kid["id"],
        device_name="tablet",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        daily_limit_minutes=60,
    )
    assert len(list_device_credentials(user_id=kid["id"])) == 1

    assert _set_disabled(client, tokens["owner"], "kid", True).status_code == 200

    assert list_device_credentials(user_id=kid["id"]) == []


def test_the_user_list_reports_the_flag(world):
    client, tokens, _ = world
    _set_disabled(client, tokens["owner"], "student", True)
    users = client.get("/api/auth/users", headers=_auth(tokens["owner"])).json()
    assert {u["username"]: u["disabled"] for u in users}["student"] is True
