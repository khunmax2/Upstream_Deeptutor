"""Fork: classrooms and the CSV import (school roles design, Phase 3a).

A classroom is a bulk editor of guardian links: membership derives them,
leaving derives them away, and a link an admin made by hand is never
touched. Class defaults land in a student's grant on join. The import
creates student accounts through the same code as the admin route, places
them, and hands the generated passwords back once.
"""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def people(mu_isolated_root, seed_user):
    """root (admin), two teachers, three students, one plain user."""
    from deeptutor.multi_user.identity import set_preset

    root = seed_user("root", role="admin")
    out = {"root": root}
    for name in ("t1", "t2"):
        out[name] = seed_user(name)
        set_preset(name, "teacher")
    for name in ("s1", "s2", "s3"):
        out[name] = seed_user(name)
        set_preset(name, "student")
    out["plain"] = seed_user("plain")
    return out


def _active_pairs() -> set[tuple[str, str]]:
    from deeptutor.multi_user.guardians import list_relationships

    return {(r["guardian_user_id"], r["learner_user_id"]) for r in list_relationships()}


def test_membership_derives_the_links_and_leaving_removes_them(people):
    from deeptutor.multi_user import classrooms as c
    from deeptutor.multi_user.guardians import guardian_can_access, list_relationships

    t1, t2, s1, s2 = (people[n]["id"] for n in ("t1", "t2", "s1", "s2"))
    room = c.create_classroom("ม.4/1", term="2569/1", teacher_ids=[t1], student_ids=[s1, s2])
    assert room["name"] == "ม.4/1" and room["home_room_teacher_id"] == ""
    assert _active_pairs() == {(t1, s1), (t1, s2)}
    assert guardian_can_access(t1, s1, "view_reports")
    assert guardian_can_access(t1, s1, "assign_materials")
    assert not guardian_can_access(t1, s1, "reset_credentials")

    # A second teacher joins: links to every student appear.
    _room, changes = c.set_teachers(room["id"], [t1, t2])
    assert changes == {"added": 1, "removed": 0, "links_created": 2, "links_revoked": 0}
    assert _active_pairs() == {(t1, s1), (t1, s2), (t2, s1), (t2, s2)}

    # A student leaves: their links go, the others stay.
    _room, changes = c.set_students(room["id"], [s1])
    assert changes["removed"] == 1 and changes["links_revoked"] == 2
    assert _active_pairs() == {(t1, s1), (t2, s1)}
    revoked = [r for r in list_relationships(include_revoked=True) if r["revoked_at"]]
    assert {r["revocation_reason"] for r in revoked} == {"classroom"}

    # Archiving the class revokes the rest.
    c.archive_classroom(room["id"])
    assert _active_pairs() == set()
    assert c.list_classrooms() == []
    assert c.list_classrooms(include_archived=True)[0]["archived_at"]


def test_a_hand_made_link_is_never_touched_and_a_shared_pair_survives(people):
    from deeptutor.multi_user import classrooms as c
    from deeptutor.multi_user.guardians import authorize_guardian, list_relationships

    t1, s1, s2 = (people[n]["id"] for n in ("t1", "s1", "s2"))
    manual = authorize_guardian(t1, s1, ["view_reports"])
    room_a = c.create_classroom("A", teacher_ids=[t1], student_ids=[s1, s2])
    # (t1, s1) existed by hand: nothing new was created for it.
    ids = {r["id"] for r in list_relationships(guardian_user_id=t1, learner_user_id=s1)}
    assert ids == {manual["id"]}
    room_b = c.create_classroom("B", teacher_ids=[t1], student_ids=[s2])

    # s2 leaves A but is still in B: the (t1, s2) link stays.
    c.set_students(room_a["id"], [s1])
    assert (t1, s2) in _active_pairs()
    # s2 leaves B too: now it goes.
    c.set_students(room_b["id"], [])
    assert (t1, s2) not in _active_pairs()

    # s1 leaves A: the hand-made link is untouched.
    c.set_students(room_a["id"], [])
    assert (t1, s1) in _active_pairs()
    assert list_relationships(guardian_user_id=t1, learner_user_id=s1)[0]["id"] == manual["id"]


def test_the_rules_refuse_the_wrong_accounts(people):
    from deeptutor.multi_user import classrooms as c

    t1, s1, plain, root = (people[n]["id"] for n in ("t1", "s1", "plain", "root"))
    with pytest.raises(c.ClassroomError, match="must be a teacher"):
        c.create_classroom("X", teacher_ids=[plain])
    with pytest.raises(c.ClassroomError, match="must be a student"):
        c.create_classroom("X", student_ids=[t1])
    with pytest.raises(c.ClassroomError, match="Admin accounts"):
        c.create_classroom("X", teacher_ids=[root])
    with pytest.raises(c.ClassroomError, match="home-room"):
        c.create_classroom("X", teacher_ids=[t1], home_room_teacher_id=s1)
    c.create_classroom("X", teacher_ids=[t1], home_room_teacher_id=t1)
    with pytest.raises(c.ClassroomError, match="already exists"):
        c.create_classroom("x ")
    with pytest.raises(c.ClassroomError, match="Unknown classroom"):
        c.set_students("cls_nope", [s1])


def test_class_defaults_land_in_the_grant_on_join_and_stay_on_leave(people):
    from deeptutor.multi_user import classrooms as c
    from deeptutor.multi_user.grants import load_grant, save_grant

    t1, s1, s2 = (people[n]["id"] for n in ("t1", "s1", "s2"))
    model = {"profile_id": "llm-profile-default", "model_ids": ["llm-model-default"]}
    kb = {"resource_id": "kb_physics", "name": "physics-m4", "access": "read", "source": "admin"}
    save_grant(
        s1,
        {"models": {"llm": [{"profile_id": "llm-profile-default", "model_ids": ["own"]}]}},
    )
    room = c.create_classroom(
        "A",
        teacher_ids=[t1],
        student_ids=[s1],
        defaults={
            "grant": {"models": {"llm": [model]}, "knowledge_bases": [kb], "exec_enabled": True}
        },
    )
    # Only models / knowledge bases / skills are kept from the defaults.
    assert room["defaults"] == {"grant": {"models": {"llm": [model]}, "knowledge_bases": [kb]}}
    grant = load_grant(s1)
    # Same profile: the model ids are unioned, not a second item appended.
    assert grant["models"]["llm"] == [
        {"profile_id": "llm-profile-default", "model_ids": ["own", "llm-model-default"]}
    ]
    assert grant["knowledge_bases"] == [kb]
    assert grant["exec_enabled"] is None

    c.set_students(room["id"], [s1, s2])
    assert load_grant(s2)["models"]["llm"] == [{**model, "source": "admin"}]
    # Joining twice does not duplicate; leaving takes nothing away.
    c.set_students(room["id"], [s2])
    c.set_students(room["id"], [s1, s2])
    assert load_grant(s1)["models"]["llm"][0]["model_ids"] == ["own", "llm-model-default"]
    assert len(load_grant(s1)["knowledge_bases"]) == 1
    c.set_students(room["id"], [])
    assert load_grant(s1)["knowledge_bases"] == [kb]


# ── CSV import ──────────────────────────────────────────────────────────────


def test_username_rule_matches_the_register_request():
    from pydantic import ValidationError

    from deeptutor.api.routers.auth import RegisterRequest
    from deeptutor.multi_user.school_import import valid_username

    for sample in (
        "somchai.k",
        "a-b_c",
        "ab",
        "with space",
        "x" * 65,
        "nong@school.ac.th",
        "bad@x",
    ):
        try:
            RegisterRequest(username=sample, password="12345678")
            expected = True
        except ValidationError:
            expected = False
        assert valid_username(sample) is expected, sample


def test_parse_csv_reports_each_bad_line_and_keeps_the_good_ones():
    from deeptutor.multi_user.school_import import parse_csv

    text = (
        "\ufeffUsername,Password,Classroom\n"
        "somchai.k,,ม.4/1\n"
        "naree.p,Temp-1234!,ม.4/1\n"
        "\n"
        "bad name,,ม.4/1\n"
        "short.pw,1234567,ม.4/1\n"
        "no.room,,\n"
        "somchai.k,,ม.4/2\n"
    )
    rows, errors = parse_csv(text)
    assert [(r.line, r.username, r.password, r.classroom) for r in rows] == [
        (2, "somchai.k", "", "ม.4/1"),
        (3, "naree.p", "Temp-1234!", "ม.4/1"),
    ]
    assert [(e["line"], e["reason"]) for e in errors] == [
        (5, "Invalid username."),
        (6, "A password is at least 8 characters."),
        (7, "The classroom is empty."),
        (8, "This username appears twice in the file."),
    ]
    assert parse_csv("name,room\nx,y\n")[1][0]["reason"].startswith("The header")


def test_import_creates_places_and_returns_passwords_once(mu_isolated_root, people, monkeypatch):
    from deeptutor.multi_user import classrooms as c
    from deeptutor.multi_user.identity import get_user
    from deeptutor.multi_user.school_import import import_students
    from deeptutor.services import auth as auth_service

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    t1 = people["t1"]["id"]
    room = c.create_classroom(
        "ม.4/1",
        teacher_ids=[t1],
        defaults={"grant": {"models": {"llm": [{"profile_id": "p", "model_ids": ["m"]}]}}},
    )
    text = (
        "username,password,classroom\n"
        "somchai.k,,ม.4/1\n"
        "naree.p,Temp-1234!,ม.4/1\n"
        "plain,,ม.4/1\n"
        "lost.kid,,ม.9/9\n"
    )
    report = import_students(text)
    assert [r["username"] for r in report.created] == ["somchai.k", "naree.p"]
    assert report.skipped == [{"line": 4, "username": "plain", "reason": "already exists"}]
    assert report.errors == [{"line": 5, "reason": "Unknown classroom: ม.9/9"}]
    assert report.public() == {"created": 2, "skipped": 1, "errors": 1, "classrooms_created": 0}

    somchai = get_user("somchai.k")
    assert somchai["preset"] == "student" and somchai["role"] == "user"
    generated = report.created[0]["password"]
    assert len(generated) == 12 and generated.isalnum()
    assert report.created[1]["password"] == "Temp-1234!"
    assert auth_service.verify_password(generated, somchai["hash"])
    csv_text = report.credentials_csv()
    assert csv_text.splitlines()[0] == "username,password,classroom"
    assert f"somchai.k,{generated},ม.4/1" in csv_text

    placed = c.get_classroom(room["id"])
    assert set(placed["student_ids"]) == {somchai["id"], get_user("naree.p")["id"]}
    assert (t1, somchai["id"]) in _active_pairs()
    from deeptutor.multi_user.grants import load_grant

    assert load_grant(somchai["id"])["models"]["llm"] == [
        {"profile_id": "p", "model_ids": ["m"], "source": "admin"}
    ]

    # Passwords never reach the audit log; the accounts are audited as created.
    audit = (mu_isolated_root / "data" / "system" / "audit" / "usage.jsonl").read_text(
        encoding="utf-8"
    )
    assert generated not in audit and "Temp-1234!" not in audit
    assert audit.count('"account_create"') == 2

    # Re-running the same file changes nothing.
    again = import_students(text)
    assert again.created == [] and len(again.skipped) == 3

    # Unknown classrooms can be created on request.
    created = import_students(
        "username,password,classroom\nnew.kid,,ม.5/1\n", create_classrooms=True
    )
    assert created.classrooms_created == ["ม.5/1"]
    assert c.classroom_by_name("ม.5/1")["student_ids"] == [get_user("new.kid")["id"]]


# ── the routes ──────────────────────────────────────────────────────────────


def _client(monkeypatch, users: dict[str, dict]) -> TestClient:
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import multi_user as multi_user_router
    from deeptutor.api.routers import school as school_router
    from deeptutor.services import auth as auth_service
    from deeptutor.services.auth import TokenPayload

    tokens = {
        f"{name}-token": TokenPayload(username=name, role=record["role"], user_id=record["id"])
        for name, record in users.items()
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    monkeypatch.setattr(multi_user_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "POCKETBASE_ENABLED", False)
    app = FastAPI()
    app.include_router(multi_user_router.router, prefix="/api/multi-user")
    app.include_router(school_router.router, prefix="/api/multi-user")
    return TestClient(app)


def test_routes_admin_writes_teacher_reads_own_and_audit(mu_isolated_root, people, monkeypatch):
    client = _client(monkeypatch, people)
    t1, t2, s1, s2 = (people[n]["id"] for n in ("t1", "t2", "s1", "s2"))
    base = "/api/multi-user/school/classrooms"

    assert client.post(base, headers=_auth("t1-token"), json={"name": "A"}).status_code == 403
    created = client.post(
        base,
        headers=_auth("root-token"),
        json={"name": "ม.4/1", "term": "2569/1", "teacher_ids": [t1], "home_room_teacher_id": t1},
    )
    assert created.status_code == 201, created.text
    room = created.json()["classroom"]
    assert room["teachers"] == [{"id": t1, "username": "t1"}]
    rid = room["id"]
    assert (
        client.post(
            base, headers=_auth("root-token"), json={"name": "X", "teacher_ids": [s1]}
        ).status_code
        == 400
    )

    put = client.put(f"{base}/{rid}/students", headers=_auth("root-token"), json={"ids": [s1, s2]})
    assert put.status_code == 200
    assert put.json()["changes"]["links_created"] == 2
    assert [s["username"] for s in put.json()["classroom"]["students"]] == ["s1", "s2"]
    assert (
        client.put(
            f"{base}/{rid}/students", headers=_auth("t1-token"), json={"ids": []}
        ).status_code
        == 403
    )

    # A teacher lists only their own classrooms; the other teacher sees none.
    mine = client.get(base, headers=_auth("t1-token")).json()["classrooms"]
    assert [r["id"] for r in mine] == [rid]
    assert client.get(base, headers=_auth("t2-token")).json()["classrooms"] == []
    # And the teacher can now read a student's evidence through the derived link.
    assert (
        client.get(f"/api/multi-user/learners/{s1}/evidence", headers=_auth("t1-token")).status_code
        == 200
    )
    assert (
        client.get(f"/api/multi-user/learners/{s1}/evidence", headers=_auth("t2-token")).status_code
        == 403
    )

    renamed = client.put(
        f"{base}/{rid}", headers=_auth("root-token"), json={"name": "ม.4/1 (ใหม่)", "term": "2569/2"}
    )
    assert renamed.status_code == 200 and renamed.json()["classroom"]["term"] == "2569/2"
    assert (
        client.put(
            f"{base}/{rid}", headers=_auth("root-token"), json={"home_room_teacher_id": t2}
        ).status_code
        == 400
    )
    assert (
        client.put(f"{base}/cls_nope", headers=_auth("root-token"), json={"name": "x"}).status_code
        == 404
    )

    archived = client.delete(f"{base}/{rid}", headers=_auth("root-token"))
    assert archived.status_code == 200 and archived.json()["classroom"]["archived_at"]
    assert client.get(base, headers=_auth("root-token")).json()["classrooms"] == []
    assert (
        len(
            client.get(f"{base}?include_archived=true", headers=_auth("root-token")).json()[
                "classrooms"
            ]
        )
        == 1
    )
    assert (
        client.get(f"/api/multi-user/learners/{s1}/evidence", headers=_auth("t1-token")).status_code
        == 403
    )

    audit = (mu_isolated_root / "data" / "system" / "audit" / "usage.jsonl").read_text(
        encoding="utf-8"
    )
    events = [json.loads(line)["action"] for line in audit.splitlines()]
    for action in (
        "classroom_create",
        "classroom_members_update",
        "classroom_update",
        "classroom_archive",
    ):
        assert action in events


def test_import_route_is_admin_only_and_returns_the_credentials_once(
    mu_isolated_root, people, monkeypatch
):
    client = _client(monkeypatch, people)
    t1 = people["t1"]["id"]
    client.post(
        "/api/multi-user/school/classrooms",
        headers=_auth("root-token"),
        json={"name": "ม.4/1", "teacher_ids": [t1]},
    )
    body = {"csv": "username,password,classroom\nsomchai.k,,ม.4/1\n"}
    assert (
        client.post(
            "/api/multi-user/school/import", headers=_auth("t1-token"), json=body
        ).status_code
        == 403
    )
    response = client.post("/api/multi-user/school/import", headers=_auth("root-token"), json=body)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["created"] == [{"username": "somchai.k", "classroom": "ม.4/1"}]
    assert report["errors"] == [] and report["skipped"] == []
    assert report["credentials_csv"].startswith("username,password,classroom\nsomchai.k,")
    password = report["credentials_csv"].splitlines()[1].split(",")[1]
    assert len(password) == 12
    audit = (mu_isolated_root / "data" / "system" / "audit" / "usage.jsonl").read_text(
        encoding="utf-8"
    )
    assert password not in audit
    line = next(json.loads(row) for row in audit.splitlines() if '"school_import"' in row)
    assert line["summary"] == {"created": 1, "skipped": 0, "errors": 0, "classrooms_created": 0}
