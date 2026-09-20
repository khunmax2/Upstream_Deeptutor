"""Fork: the roster's summary rows, alerts and class totals (Phase 3b).

Alerts are plain rules over the evidence record, tested at their edges;
the roster route serves a teacher of the classroom and an admin, refuses
everyone else, drops a student whose link was revoked by hand, and writes
one audit line per read.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def _evidence(**overrides):
    base = {
        "student": {"id": "u_1", "username": "s1", "preset": "student"},
        "activity": {
            "available": True,
            "last_active_at": _iso(1),
            "active_days_30": 5,
            "turns_30": 20,
        },
        "question_bank": {
            "available": True,
            "unresolved": 2,
            "recent": {"days": 30, "total": 20, "correct": 15},
            "categories": [{"name": "Limits", "total": 6, "wrong": 4}],
        },
        "mastery": {
            "available": True,
            "paths": [{"due_reviews": 1, "counts": {"mastered": 3, "total": 8}}],
        },
        "reading": {
            "available": True,
            "materials": [{"progress": 0.4, "finished": False, "last_read_at": _iso(2)}],
        },
        "summary": {"available": True, "generated_at": _iso(0.5)},
    }
    base.update(overrides)
    return base


def test_a_healthy_record_raises_no_alert():
    from deeptutor.multi_user.school_alerts import alerts_for, summary_row

    assert alerts_for(_evidence(), now=NOW) == []
    row = summary_row(_evidence(), now=NOW)
    assert row["accuracy_30"] == 0.75
    assert (row["mastered"], row["objectives"], row["reviews_due"]) == (3, 8, 1)
    assert (row["reading_started"], row["reading_finished"]) == (1, 0)
    assert row["summary_at"] == _iso(0.5)
    assert row["alerts"] == []


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"activity": {"available": True, "last_active_at": _iso(7)}}, ["inactive"]),
        ({"activity": {"available": False}}, ["inactive"]),
        ({"activity": {"available": True, "last_active_at": _iso(6.9)}}, []),
        (
            {"question_bank": {"available": True, "recent": {"total": 10, "correct": 4}}},
            ["struggling"],
        ),
        ({"question_bank": {"available": True, "recent": {"total": 9, "correct": 0}}}, []),
        ({"question_bank": {"available": True, "recent": {"total": 10, "correct": 5}}}, []),
        ({"question_bank": {"available": True, "unresolved": 10}}, ["backlog"]),
        (
            {"mastery": {"available": True, "paths": [{"due_reviews": 3}, {"due_reviews": 2}]}},
            ["reviews_due"],
        ),
        (
            {
                "reading": {
                    "available": True,
                    "materials": [{"progress": 0.2, "finished": False, "last_read_at": _iso(14)}],
                }
            },
            ["reading_stalled"],
        ),
        (
            {
                "reading": {
                    "available": True,
                    "materials": [{"progress": 0.0, "finished": False, "last_read_at": _iso(40)}],
                }
            },
            [],
        ),
        (
            {
                "reading": {
                    "available": True,
                    "materials": [{"progress": 1.0, "finished": True, "last_read_at": _iso(40)}],
                }
            },
            [],
        ),
    ],
)
def test_each_alert_fires_at_its_threshold(overrides, expected):
    from deeptutor.multi_user.school_alerts import alerts_for

    assert alerts_for(_evidence(**overrides), now=NOW) == expected


def test_class_totals_roll_the_rows_up():
    from deeptutor.multi_user.school_alerts import class_totals, summary_row

    records = [
        _evidence(),
        _evidence(
            student={"id": "u_2", "username": "s2", "preset": "student"},
            activity={"available": True, "last_active_at": _iso(10)},
            question_bank={
                "available": True,
                "recent": {"total": 12, "correct": 3},
                "categories": [
                    {"name": "Limits", "total": 5, "wrong": 5},
                    {"name": "Vectors", "wrong": 1},
                ],
            },
        ),
        _evidence(
            student={"id": "u_3", "username": "s3", "preset": "student"},
            question_bank={"available": True, "recent": {"total": 0, "correct": 0}},
        ),
    ]
    rows = [summary_row(r, now=NOW) for r in records]
    totals = class_totals(rows, records, now=NOW)
    assert totals["students"] == 3
    assert totals["active_7"] == 2 and totals["active_30"] == 3
    assert totals["median_accuracy_30"] == 0.5  # median of 0.75 and 0.25
    assert totals["below_half"] == 1
    assert totals["alerts"]["inactive"] == 1 and totals["alerts"]["struggling"] == 1
    assert totals["top_wrong_categories"] == [
        {"name": "Limits", "wrong": 9},
        {"name": "Vectors", "wrong": 1},
    ]


# ── the route ───────────────────────────────────────────────────────────────


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def school(mu_isolated_root, seed_user, monkeypatch):
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import multi_user as multi_user_router
    from deeptutor.api.routers import school as school_router
    from deeptutor.multi_user import classrooms as c
    from deeptutor.multi_user.identity import set_preset
    from deeptutor.services.auth import TokenPayload

    people = {"root": seed_user("root", role="admin")}
    for name in ("t1", "t2"):
        people[name] = seed_user(name)
        set_preset(name, "teacher")
    for name in ("s1", "s2"):
        people[name] = seed_user(name)
        set_preset(name, "student")
    people["plain"] = seed_user("plain")
    room = c.create_classroom(
        "ม.4/1",
        teacher_ids=[people["t1"]["id"]],
        student_ids=[people["s1"]["id"], people["s2"]["id"]],
    )
    tokens = {
        f"{name}-token": TokenPayload(username=name, role=record["role"], user_id=record["id"])
        for name, record in people.items()
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    monkeypatch.setattr(multi_user_router, "POCKETBASE_ENABLED", False)
    app = FastAPI()
    app.include_router(multi_user_router.router, prefix="/api/multi-user")
    app.include_router(school_router.router, prefix="/api/multi-user")
    return TestClient(app), people, room


def test_roster_is_for_the_classrooms_teachers_and_admins(mu_isolated_root, school):
    client, people, room = school
    url = f"/api/multi-user/school/classrooms/{room['id']}/roster"

    assert client.get(url, headers=_auth("plain-token")).status_code == 403
    assert client.get(url, headers=_auth("t2-token")).status_code == 403
    assert client.get(url, headers=_auth("s1-token")).status_code == 403
    assert (
        client.get(
            "/api/multi-user/school/classrooms/cls_nope/roster", headers=_auth("t1-token")
        ).status_code
        == 404
    )

    response = client.get(url, headers=_auth("t1-token"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["classroom"]["id"] == room["id"]
    assert sorted(row["student"]["username"] for row in body["rows"]) == ["s1", "s2"]
    # Fresh accounts: never active, so every row is inactive and nothing else.
    assert all(row["alerts"] == ["inactive"] for row in body["rows"])
    assert body["totals"]["students"] == 2 and body["totals"]["alerts"]["inactive"] == 2
    assert body["totals"]["median_accuracy_30"] is None

    assert client.get(url, headers=_auth("root-token")).status_code == 200

    audit = (mu_isolated_root / "data" / "system" / "audit" / "usage.jsonl").read_text(
        encoding="utf-8"
    )
    views = [json.loads(line) for line in audit.splitlines() if '"classroom_roster_view"' in line]
    assert len(views) == 2
    assert views[0]["guardian_user_id"] == people["t1"]["id"]
    assert sorted(views[0]["summary"]["student_ids"]) == sorted(
        [people["s1"]["id"], people["s2"]["id"]]
    )
    assert views[1]["actor_role"] == "admin" and views[1]["summary"]["students"] == 2


def test_a_link_revoked_by_hand_keeps_the_student_off_the_teachers_roster(school):
    from deeptutor.multi_user.guardians import list_relationships, revoke_guardian

    client, people, room = school
    link = next(
        r
        for r in list_relationships(
            guardian_user_id=people["t1"]["id"], learner_user_id=people["s2"]["id"]
        )
    )
    revoke_guardian(link["id"], revoked_by=people["root"]["id"], reason="by hand")
    body = client.get(
        f"/api/multi-user/school/classrooms/{room['id']}/roster", headers=_auth("t1-token")
    ).json()
    assert [row["student"]["username"] for row in body["rows"]] == ["s1"]
    # The admin still sees the whole class.
    body = client.get(
        f"/api/multi-user/school/classrooms/{room['id']}/roster", headers=_auth("root-token")
    ).json()
    assert len(body["rows"]) == 2
