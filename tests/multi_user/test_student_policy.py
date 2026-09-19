"""Fork: what a `student` account cannot do (school roles design, Phase 1 step 2).

Three groups are closed -- own settings writes, partners/MCP/exec, the admin
sections -- and nothing else: a student reads every settings page, uses
Memory, Reading uploads and its own knowledge bases like any user. The rule
is one table (`student_policy.CLOSED`) applied through the app's shared
`_auth` dependency list, so it is exercised here through the real app.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

from deeptutor.multi_user.student_policy import closed_reason

PASSWORD = "pw-student-policy"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    ("method", "path", "closed"),
    [
        ("PUT", "/api/settings/catalog", True),
        ("POST", "/api/settings/apply", True),
        ("POST", "/api/settings/providers/openai-codex/oauth/start", True),
        ("GET", "/api/settings", False),
        ("GET", "/api/settings/catalog", False),
        ("PUT", "/api/settings/ui", False),
        ("PUT", "/api/settings/workspace/x", False),
        ("PUT", "/api/capabilities/chat", True),
        ("GET", "/api/capabilities", False),
        ("POST", "/api/tools/x/enable", True),
        ("GET", "/api/tools", False),
        ("PUT", "/api/agent-config/claude", True),
        ("GET", "/api/space/mcp", True),
        ("GET", "/api/space/cli-apps/apps", True),
        ("POST", "/api/partners", True),
        ("GET", "/api/partners", False),
        ("DELETE", "/api/partner-groups/g1", True),
        ("POST", "/api/memory/runs", False),
        ("POST", "/api/reading/materials", False),
        ("POST", "/api/knowledge-bases", False),
        ("PUT", "/api/auth/profile", False),
        ("PUT", "/api/auth/profile/learner-profile", False),
    ],
)
def test_the_table_says_what_is_closed(method, path, closed):
    assert (closed_reason(path, method) is not None) is closed


@pytest.fixture
def world(mu_isolated_root, monkeypatch):
    from deeptutor.api.main import app
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user.identity import save_user, set_preset
    from deeptutor.services import auth as auth_service
    from deeptutor.services.auth import create_token, hash_password

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "test-secret-for-student-policy")
    monkeypatch.setattr(auth_service, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)

    save_user("owner", hash_password(PASSWORD), role="admin")
    student = save_user("student", hash_password(PASSWORD))
    set_preset("student", "student")
    plain = save_user("plain", hash_password(PASSWORD))
    tokens = {
        "student": create_token("student", "user", student["id"]),
        "plain": create_token("plain", "user", plain["id"]),
    }
    return TestClient(app), tokens, student["id"]


def _audit(mu_isolated_root) -> list[dict]:
    path = mu_isolated_root / "data" / "system" / "audit" / "usage.jsonl"
    if not path.exists():
        return []
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [line for line in lines if line.get("action") == "student_write_refused"]


def test_a_student_is_refused_on_closed_routes_and_served_on_open_ones(world, mu_isolated_root):
    client, tokens, student_id = world
    student = _auth(tokens["student"])

    refused = client.put("/api/settings/catalog", json={"services": {}}, headers=student)
    assert refused.status_code == 403
    assert refused.json()["detail"].startswith("This is a student account:")
    assert client.post("/api/partners", json={}, headers=student).status_code == 403
    assert client.get("/api/space/mcp/servers", headers=student).status_code == 403
    assert client.get("/api/space/cli-apps/apps", headers=student).status_code == 403

    # Reads and the student's own things are not the policy's business: any
    # status but the policy's 403 is fine here (other guards may say 404/422).
    for method, path in (
        ("GET", "/api/settings/catalog"),
        ("GET", "/api/partners"),
        ("GET", "/api/memory/overview"),
        ("PUT", "/api/settings/ui"),
    ):
        response = client.request(method, path, headers=student, json={})
        assert not (
            response.status_code == 403
            and str(response.json().get("detail", "")).startswith("This is a student account")
        ), (method, path, response.text)

    lines = _audit(mu_isolated_root)
    assert [line["target_user_id"] for line in lines] == [student_id] * 4
    assert lines[0]["summary"] == {"method": "PUT", "path": "/api/settings/catalog"}


def test_an_ordinary_user_is_not_touched(world, mu_isolated_root):
    client, tokens, _ = world
    plain = _auth(tokens["plain"])
    for method, path in (
        ("PUT", "/api/settings/catalog"),
        ("POST", "/api/partners"),
        ("GET", "/api/space/mcp/servers"),
    ):
        response = client.request(method, path, headers=plain, json={})
        assert not (
            response.status_code == 403
            and str(response.json().get("detail", "")).startswith("This is a student account")
        ), (method, path, response.text)
    assert _audit(mu_isolated_root) == []
