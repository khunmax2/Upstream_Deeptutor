"""What a learning account can actually *do*, end to end, over real HTTP.

Every previous learner bug had the same shape: a permission an administrator
grants that some other layer then refuses. `allow_upload` returned 200 and then
403 on everything that would show the upload; `/api/courses` answers 403 and the
sidebar discarded the session list with it. Unit tests missed all of them
because each layer was correct on its own.

So this walks a real `preset="learner"` account, logged in with a real token,
through the whole surface its policy opens — Immersive Reading and Chat — and
asserts that nothing on the way answers 4xx. It is a contract, not a smoke
test: a route added to the learner UI without being added to
``_learning_surface_for_path`` fails here.
"""

from __future__ import annotations

import pytest

_PASSWORD = "password1234"  # noqa: S105 - test fixture credential


@pytest.fixture
def learner_http(mu_isolated_root, monkeypatch):
    """An admin client and a learner client, both really logged in."""
    from fastapi.testclient import TestClient

    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user.identity import save_user

    # The reading extensions register through entry points, which only exist once
    # the package is installed. CI's python-tests job installs the requirements
    # files and never runs `pip install -e .`, so the registry comes up empty
    # there and the policy below is rejected with "Unknown reading extensions" —
    # green locally, red on every Python version in CI. Build the registry from
    # the classes directly so the contract under test is the policy, not how the
    # environment was provisioned.
    from deeptutor.reading import extensions as reading_extensions
    from deeptutor.reading.quiz import ReadingQuizExtension
    from deeptutor.reading.read_aloud import ReadAloudExtension
    from deeptutor.reading.study_guidance import StudyGuidanceExtension
    from deeptutor.services import auth as auth_service

    registry = reading_extensions.ReadingExtensionRegistry(
        [ReadAloudExtension(), StudyGuidanceExtension(), ReadingQuizExtension()]
    )
    monkeypatch.setattr(reading_extensions, "get_reading_extension_registry", lambda **_: registry)

    monkeypatch.setattr(auth_service, "AUTH_SECRET", "secret-for-the-learner-contract-test")
    for module in (auth_service, auth_router):
        monkeypatch.setattr(module, "AUTH_ENABLED", True)
        monkeypatch.setattr(module, "POCKETBASE_ENABLED", False)

    save_user("owner", auth_service.hash_password(_PASSWORD), role="admin")
    learner = save_user("kid", auth_service.hash_password(_PASSWORD), role="user", preset="learner")

    from deeptutor.api.main import app

    def _login(username: str) -> TestClient:
        client = TestClient(app)
        response = client.post(
            "/api/auth/login", json={"username": username, "password": _PASSWORD}
        )
        assert response.status_code == 200, response.text
        assert client.cookies.get("dt_token"), f"{username} got no session cookie"
        return client

    return _login("owner"), _login("kid"), learner


def _policy(material_ids: list[str], *, allow_upload: bool = True) -> dict:
    return {
        "enabled_tools": [],
        "mcp_tools": [],
        "cli_apps": [],
        "exec_enabled": False,
        "learning_policy": {
            "age_band": "9-12",
            "locked_persona": "teacher",
            "allowed_capabilities": ["chat", "immersive_reading"],
            "default_capability": "immersive_reading",
            "allowed_surfaces": ["chat", "reading"],
            "reading": {
                "allow_upload": allow_upload,
                "material_ids": material_ids,
                "extensions": ["read_aloud", "quiz", "guided_learning"],
            },
        },
    }


def _ok(response, label: str) -> None:
    detail = ""
    if response.status_code >= 400:
        try:
            detail = str(response.json().get("detail", ""))
        except Exception:  # noqa: BLE001 - the body may not be JSON
            detail = response.text[:200]
    assert response.status_code < 400, f"{label} -> {response.status_code} {detail}"


def test_an_assigned_material_is_readable_by_the_learner(learner_http):
    """The Learning Policy screen's "Assigned reading materials" picker."""
    admin, kid, learner = learner_http

    upload = admin.post(
        "/api/reading/materials",
        files={"file": ("lesson.txt", b"Paracetamol is a common medicine.", "text/plain")},
    )
    _ok(upload, "admin uploads the material it will assign")
    material_id = upload.json()["material_id"]

    assigned = admin.put(
        f"/api/multi-user/users/{learner['id']}/grants",
        json={"grant": _policy([material_id])},
    )
    _ok(assigned, "admin assigns the material")

    _ok(kid.get("/api/reading/materials"), "learner lists materials")
    assert material_id in [row["material_id"] for row in kid.get("/api/reading/materials").json()]
    _ok(kid.get(f"/api/reading/materials/{material_id}"), "learner opens the assigned material")
    _ok(kid.get(f"/api/reading/materials/{material_id}/units/1"), "learner reads a unit")


def test_the_whole_immersive_reading_surface_answers_the_learner(learner_http):
    admin, kid, learner = learner_http
    _ok(
        admin.put(f"/api/multi-user/users/{learner['id']}/grants", json={"grant": _policy([])}),
        "admin grants the policy",
    )

    for label, path in [
        ("supported formats", "/api/reading/supported-formats"),
        ("material list", "/api/reading/materials"),
        ("library", "/api/reading/library/materials"),
        ("collections", "/api/reading/workspaces"),
        ("collection index", "/api/reading/workspaces/index"),
        ("extensions", "/api/reading/extensions"),
        ("epub pairings", "/api/reading/epub-pairings"),
    ]:
        _ok(kid.get(path), f"reading: {label}")

    upload = kid.post(
        "/api/reading/materials",
        files={"file": ("story.txt", b"The cat sat on the mat. It was warm.", "text/plain")},
    )
    _ok(upload, "learner uploads their own material")
    own = upload.json()["material_id"]

    for label, method, path, kwargs in [
        ("open it", "GET", f"/api/reading/materials/{own}", {}),
        ("read a unit", "GET", f"/api/reading/materials/{own}/units/1", {}),
        ("list revisions", "GET", f"/api/reading/materials/{own}/revisions", {}),
        ("export", "GET", f"/api/reading/materials/{own}/export?fmt=markdown", {}),
        (
            "save position",
            "PUT",
            f"/api/reading/materials/{own}/position",
            {"json": {"locator": 1, "progress": 0.5}},
        ),
        (
            "highlight",
            "PUT",
            f"/api/reading/materials/{own}/annotations",
            {
                "json": {
                    "material_id": own,
                    "locator": 1,
                    "color": "yellow",
                    "selector": {"type": "TextQuoteSelector", "exact": "The cat"},
                }
            },
        ),
        ("list highlights", "GET", f"/api/reading/materials/{own}/annotations", {}),
        (
            "duplicate check",
            "POST",
            "/api/reading/library/duplicate-check",
            {"json": {"files": [{"filename": "story.txt"}]}},
        ),
        ("delete it again", "DELETE", f"/api/reading/materials/{own}", {}),
    ]:
        _ok(kid.request(method, path, **kwargs), f"reading: {label}")


def test_a_reading_collection_and_its_conversation_work(learner_http):
    admin, kid, learner = learner_http
    _ok(
        admin.put(f"/api/multi-user/users/{learner['id']}/grants", json={"grant": _policy([])}),
        "admin grants the policy",
    )
    upload = kid.post(
        "/api/reading/materials",
        files={"file": ("story.txt", b"The cat sat on the mat.", "text/plain")},
    )
    _ok(upload, "learner uploads")
    material_id = upload.json()["material_id"]

    created = kid.post(
        "/api/reading/workspaces",
        json={"title": "My reading", "material_ids": [material_id]},
    )
    _ok(created, "learner creates a collection")
    body = created.json()
    workspace_id = str((body.get("workspace") or body).get("workspace_id") or "")
    assert workspace_id

    for label, path in [
        ("open collection", f"/api/reading/workspaces/{workspace_id}"),
        ("its conversations", f"/api/reading/workspaces/{workspace_id}/sessions"),
        ("suggested openers", f"/api/reading/workspaces/{workspace_id}/openers"),
    ]:
        _ok(kid.get(path), f"reading: {label}")

    tabs = kid.get(f"/api/reading/workspaces/{workspace_id}").json()["workspace"]["tabs"]
    assert [tab["material"]["material_id"] for tab in tabs] == [material_id], (
        "a learner's own upload must stay visible as a tab in their own collection"
    )


def test_the_chat_surface_the_policy_allows_answers_the_learner(learner_http):
    admin, kid, learner = learner_http
    _ok(
        admin.put(f"/api/multi-user/users/{learner['id']}/grants", json={"grant": _policy([])}),
        "admin grants the policy",
    )

    for label, path in [
        ("who am I", "/api/auth/status"),
        ("my profile", "/api/auth/profile"),
        ("my learner profile", "/api/auth/profile/learner-profile"),
        ("conversation list", "/api/sessions"),
        # The model picker: grant-filtered server-side, and the one settings
        # route a learning account is meant to reach.
        ("model options", "/api/settings/llm-options"),
        ("question notebook", "/api/question-notebook/categories"),
        # Language and theme: hiding this would strand the account with no way
        # to change its own interface.
        ("interface preferences", "/api/settings/ui"),
    ]:
        _ok(kid.get(path), f"chat: {label}")
