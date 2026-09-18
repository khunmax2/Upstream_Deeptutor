"""Fork: delete goes through a bin, then a typed purge (admin design §4, Phase 2).

Delete = the account goes to the bin: its record stays, the name stays
taken, everything it owns stays, it cannot sign in. Restore brings it back
as it was. Purge, from the bin only and with the username typed, removes
the workspace, grant, secrets, MCP file, device-credential records, avatar,
guardian links and the record. Only the primary admin does any of it.
"""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

PASSWORD = "pw-account-bin"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _audit(mu_isolated_root, action: str) -> list[dict]:
    path = mu_isolated_root / "data" / "system" / "audit" / "usage.jsonl"
    if not path.exists():
        return []
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [line for line in lines if line.get("action") == action]


@pytest.fixture
def world(mu_isolated_root, monkeypatch):
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user.identity import save_user, set_role
    from deeptutor.multi_user.primary_admin import primary_admin_id
    from deeptutor.services import auth as auth_service
    from deeptutor.services.auth import create_token, hash_password

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "test-secret-for-account-bin")
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
    accounts = {"owner": owner, "demo": demo, "student": student}
    return TestClient(app), tokens, accounts


def _give_data(mu_isolated_root, user_id: str) -> dict[str, object]:
    """Everything a purge must remove, planted where the app keeps it."""
    from deeptutor.multi_user import paths
    from deeptutor.multi_user.grants import empty_grant

    workspace = paths.USERS_ROOT / user_id / "sessions"
    workspace.mkdir(parents=True)
    (workspace / "chat.json").write_text('{"turns": []}', encoding="utf-8")
    grant = paths.SYSTEM_ROOT / "grants" / f"{user_id}.json"
    grant.parent.mkdir(parents=True, exist_ok=True)
    grant.write_text(json.dumps(empty_grant(user_id)), encoding="utf-8")
    secrets = paths.SYSTEM_ROOT / paths.USER_SECRETS_DIRNAME / user_id
    secrets.mkdir(parents=True)
    (secrets / "token.json").write_text("{}", encoding="utf-8")
    mcp = paths.SYSTEM_ROOT / "user-mcp"
    mcp.mkdir(parents=True, exist_ok=True)
    (mcp / f"{user_id}.json").write_text("{}", encoding="utf-8")
    return {
        "workspace": paths.USERS_ROOT / user_id,
        "grant": paths.SYSTEM_ROOT / "grants" / f"{user_id}.json",
        "secrets": secrets,
        "mcp": mcp / f"{user_id}.json",
    }


def _in_bin(username: str) -> bool:
    from deeptutor.multi_user.identity import get_user

    record = get_user(username)
    return bool(record and record.get("deleted_at"))


def test_delete_moves_the_account_to_the_bin_and_locks_it_out(world, mu_isolated_root):
    client, tokens, accounts = world
    student = accounts["student"]["id"]
    paths = _give_data(mu_isolated_root, student)

    response = client.delete("/api/auth/users/student", headers=_auth(tokens["owner"]))
    assert response.status_code == 200
    assert response.json() == {"ok": True, "deleted_at": response.json()["deleted_at"]}
    assert _in_bin("student")

    # Everything stays.
    assert all(path.exists() for path in paths.values())
    # The name stays taken, and the reason is said.
    taken = client.post(
        "/api/auth/users",
        json={"username": "student", "password": "another-pw-123", "preset": "standard"},
        headers=_auth(tokens["owner"]),
    )
    assert taken.status_code == 409
    assert "deleted account" in taken.json()["detail"]
    # Locked out on every path: login says so, the token stops working.
    login = client.post("/api/auth/login", json={"username": "student", "password": PASSWORD})
    assert login.status_code == 403
    assert login.json()["detail"] == "This account has been deleted"
    assert (
        client.get("/api/auth/status", headers=_auth(tokens["student"])).json()["authenticated"]
        is False
    )
    # Listed with the stamp, so the page can split the tabs.
    listed = {
        u["username"]: u
        for u in client.get("/api/auth/users", headers=_auth(tokens["owner"])).json()
    }
    assert listed["student"]["deleted_at"]
    assert listed["demo"]["deleted_at"] is None

    lines = _audit(mu_isolated_root, "account_delete")
    assert [line["target_user_id"] for line in lines] == [student]
    assert lines[0]["summary"] == {"username": "student", "role": "user"}


def test_restore_brings_the_account_back_unchanged(world, mu_isolated_root):
    client, tokens, accounts = world
    from deeptutor.multi_user.identity import set_disabled

    set_disabled("student", True)
    assert (
        client.delete("/api/auth/users/student", headers=_auth(tokens["owner"])).status_code == 200
    )

    restored = client.post("/api/auth/users/student/restore", headers=_auth(tokens["owner"]))
    assert restored.status_code == 200
    assert not _in_bin("student")
    # Still disabled: the bin only added its own mark and only took that away.
    listed = {
        u["username"]: u
        for u in client.get("/api/auth/users", headers=_auth(tokens["owner"])).json()
    }
    assert listed["student"]["disabled"] is True
    assert listed["student"]["id"] == accounts["student"]["id"]
    # Restoring an account that is not in the bin is a 409, not a silent 200.
    assert (
        client.post("/api/auth/users/student/restore", headers=_auth(tokens["owner"])).status_code
        == 409
    )
    assert [line["target_user_id"] for line in _audit(mu_isolated_root, "account_restore")] == [
        accounts["student"]["id"]
    ]


def test_purge_removes_every_location_and_only_from_the_bin(world, mu_isolated_root):
    client, tokens, accounts = world
    student = accounts["student"]["id"]
    paths = _give_data(mu_isolated_root, student)
    owner = _auth(tokens["owner"])

    # Not in the bin yet: refused, nothing touched.
    early = client.delete("/api/auth/users/student/purge?confirm=student", headers=owner)
    assert early.status_code == 409
    assert all(path.exists() for path in paths.values())

    assert client.delete("/api/auth/users/student", headers=owner).status_code == 200
    footprint = client.get("/api/auth/users/student/footprint", headers=owner)
    assert footprint.status_code == 200
    assert footprint.json()["footprint"]["workspace_files"] == 1
    assert footprint.json()["footprint"]["grant"] is True
    assert footprint.json()["footprint"]["secrets_files"] == 1
    assert footprint.json()["footprint"]["mcp_config"] is True

    # The typed name must match.
    assert client.delete("/api/auth/users/student/purge", headers=owner).status_code == 400
    assert (
        client.delete("/api/auth/users/student/purge?confirm=Student", headers=owner).status_code
        == 400
    )
    assert all(path.exists() for path in paths.values())

    purged = client.delete("/api/auth/users/student/purge?confirm=student", headers=owner)
    assert purged.status_code == 200
    assert purged.json()["removed"]["workspace_files"] == 1
    assert not any(path.exists() for path in paths.values())
    from deeptutor.multi_user.identity import get_user

    assert get_user("student") is None
    # The name is free again, and it is a new account.
    recreated = client.post(
        "/api/auth/users",
        json={"username": "student", "password": "another-pw-123", "preset": "standard"},
        headers=owner,
    )
    assert recreated.status_code == 201
    assert recreated.json()["user_id"] != student

    lines = _audit(mu_isolated_root, "account_purge")
    assert [line["target_user_id"] for line in lines] == [student]
    assert lines[0]["summary"]["username"] == "student"
    assert lines[0]["summary"]["workspace_files"] == 1


def test_only_the_primary_admin_and_never_itself_or_the_primary(world, mu_isolated_root):
    client, tokens, accounts = world
    demo = _auth(tokens["demo"])
    owner = _auth(tokens["owner"])
    _give_data(mu_isolated_root, accounts["student"]["id"])

    # A promoted admin: 403 on every step, audited.
    assert client.delete("/api/auth/users/student", headers=demo).status_code == 403
    assert client.post("/api/auth/users/student/restore", headers=demo).status_code == 403
    assert (
        client.delete("/api/auth/users/student/purge?confirm=student", headers=demo).status_code
        == 403
    )
    assert client.get("/api/auth/users/student/footprint", headers=demo).status_code == 403
    assert client.get("/api/auth/orphans", headers=demo).status_code == 403
    assert not _in_bin("student")
    assert len(_audit(mu_isolated_root, "account_change_refused")) >= 3

    # The primary admin cannot delete itself or be deleted; its footprint is refused.
    assert client.delete("/api/auth/users/owner", headers=owner).status_code == 400
    assert client.get("/api/auth/users/owner/footprint", headers=owner).status_code == 403
    assert (
        client.delete("/api/auth/users/owner/purge?confirm=owner", headers=owner).status_code == 403
    )

    # An admin can be deleted without demoting it first (decision 10).
    assert client.delete("/api/auth/users/demo", headers=owner).status_code == 200
    assert _in_bin("demo")
    assert client.get("/api/auth/status", headers=demo).json()["authenticated"] is False


def test_orphans_are_listed_and_purged_by_id(world, mu_isolated_root):
    client, tokens, _ = world
    owner = _auth(tokens["owner"])
    orphan = "u_" + "a" * 32
    paths = _give_data(mu_isolated_root, orphan)
    # Something that is not an account id must never appear, whatever holds it.
    (mu_isolated_root / "data" / "users" / "not-an-id").mkdir(parents=True)

    listed = client.get("/api/auth/orphans", headers=owner)
    assert listed.status_code == 200
    assert [o["user_id"] for o in listed.json()["orphans"]] == [orphan]
    assert listed.json()["orphans"][0]["footprint"]["workspace_files"] == 1

    assert client.delete(f"/api/auth/orphans/{orphan}", headers=owner).status_code == 400
    assert (
        client.delete("/api/auth/orphans/not-an-id?confirm=not-an-id", headers=owner).status_code
        == 400
    )
    purged = client.delete(f"/api/auth/orphans/{orphan}?confirm={orphan}", headers=owner)
    assert purged.status_code == 200
    assert not any(path.exists() for path in paths.values())
    assert client.get("/api/auth/orphans", headers=owner).json()["orphans"] == []
    # A live account's id is not an orphan, and cannot be purged through here.
    live = client.get("/api/auth/users", headers=owner).json()
    student_id = next(u["id"] for u in live if u["username"] == "student")
    assert (
        client.delete(
            f"/api/auth/orphans/{student_id}?confirm={student_id}", headers=owner
        ).status_code
        == 409
    )
    assert [line["target_user_id"] for line in _audit(mu_isolated_root, "account_purge")] == [
        orphan
    ]
