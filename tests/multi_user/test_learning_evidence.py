"""Fork: the learning-evidence record and the teacher's routes (Phase 2).

A student's workspace is built with the real stores (session store, Mastery
store, reading files, memory documents), then read back through
``learning_evidence`` and the ``/learners/{id}/evidence`` route as the
teacher. The checks are two-sided: the numbers are right, and nothing the
design keeps private -- messages, session titles, memory traces, the
disallowed memory sections -- is in the answer.
"""

from __future__ import annotations

import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

SECRET_MESSAGE = "my parents are divorcing and I feel awful"
SECRET_TITLE = "Talking about my family"
SECRET_TOPIC = "Talks about breakups and family trouble"
SECRET_IDENTITY = "Lives in Chiang Mai with a younger brother"
SECRET_PREFERENCE = "Prefers the tutor to call them Nong"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _fill_workspace(store, mastery_store, reading_root, memory_root):
    """A student who chatted, answered questions, read, and has memory docs."""
    from deeptutor.learning.models import (
        KnowledgePoint,
        KnowledgeType,
        LearnerProfile,
        LearningModule,
        LearningProgress,
        QuizAttempt,
    )

    session = await store.create_session(title=SECRET_TITLE)
    sid = session["id"]
    await store.add_message(sid, "user", SECRET_MESSAGE, capability="chat")
    await store.add_message(sid, "assistant", "I am sorry to hear that.", capability="chat")
    await store.add_message(sid, "user", "what is a derivative", capability="chat")
    await store.upsert_notebook_entries(
        sid,
        [
            {
                "question_id": "q1",
                "question": "d/dx x^2 = ?",
                "is_correct": True,
                "source": "mastery_path",
                "material_id": "m1",
                "material_title": "Calculus 1",
            },
            {
                "question_id": "q2",
                "question": "limit of sin x / x",
                "is_correct": False,
                "source": "immersive_reading",
                "material_id": "m1",
                "material_title": "Calculus 1",
            },
            {"question_id": "q3", "question": "2+2", "is_correct": True, "source": "deep_question"},
        ],
    )
    category = await store.create_category("Calculus")
    await store.link_entries_to_category([1, 2], category["id"])

    kp = KnowledgePoint(
        id="kp1", name="Derivatives", type=KnowledgeType.PROCEDURE, module_id="mod1"
    )
    kp2 = KnowledgePoint(id="kp2", name="Limits", type=KnowledgeType.CONCEPT, module_id="mod1")
    progress = LearningProgress(
        book_id="path1",
        name="Calculus basics",
        modules=[LearningModule(id="mod1", name="Module 1", order=0, knowledge_points=[kp, kp2])],
        mastery_levels={"kp1": 0.9},
        quiz_attempts=[
            QuizAttempt(question_id="q1", knowledge_point_id="kp1", is_correct=True),
            QuizAttempt(question_id="q2", knowledge_point_id="kp2", is_correct=False),
        ],
    )
    progress.learner_profile = LearnerProfile(
        prior_knowledge="algebra", target_level="pass the exam", notes=SECRET_IDENTITY
    )
    mastery_store.save(progress)

    material = reading_root / "abc123"
    (material / "positions").mkdir(parents=True)
    (material / "annotations").mkdir()
    (material / "manifest.json").write_text(
        json.dumps(
            {
                "material_id": "abc123",
                "filename": "calculus.pdf",
                "title": "Calculus book",
                "unit": "page",
                "unit_count": 10,
                "created_at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    (material / "positions" / "abc123.json").write_text(
        json.dumps({"locator": 4, "percentage": 0.4, "updated_at": time.time()}),
        encoding="utf-8",
    )
    (material / "annotations" / "abc123.json").write_text(
        json.dumps([{"annotation_id": "a1", "text": SECRET_MESSAGE, "locator": 2}]),
        encoding="utf-8",
    )

    (memory_root / "L2").mkdir(parents=True)
    (memory_root / "L3").mkdir()
    (memory_root / "L2" / "chat.md").write_text(
        "# chat\n\n## Misconceptions\n\n- Confuses derivative and integral <!--m_01HZK4ABCDEFGHJKMNPQRSTVW1-->\n\n"
        "## Mastery\n\n- Applies the power rule <!--m_01HZK4ABCDEFGHJKMNPQRSTVW2-->\n\n"
        f"## Topics\n\n- {SECRET_TOPIC} <!--m_01HZK4ABCDEFGHJKMNPQRSTVW3-->\n",
        encoding="utf-8",
    )
    (memory_root / "L2" / "quiz.md").write_text(
        "# quiz\n\n## Error patterns\n\n- Sign errors in limits <!--m_01HZK4ABCDEFGHJKMNPQRSTVW4-->\n",
        encoding="utf-8",
    )
    (memory_root / "L3" / "profile.md").write_text(
        f"# profile\n\n## Identity\n\n- {SECRET_IDENTITY} <!--m_01HZK4ABCDEFGHJKMNPQRSTVW5-->\n\n"
        "## Learning style\n\n- Works best from worked examples <!--m_01HZK4ABCDEFGHJKMNPQRSTVW6-->\n",
        encoding="utf-8",
    )
    (memory_root / "L3" / "preferences.md").write_text(
        f"# preferences\n\n## Address\n\n- {SECRET_PREFERENCE} <!--m_01HZK4ABCDEFGHJKMNPQRSTVW7-->\n",
        encoding="utf-8",
    )
    (memory_root / "L3" / "scope.md").write_text(
        "# scope\n\n## Practicing\n\n- Limits <!--m_01HZK4ABCDEFGHJKMNPQRSTVW8-->\n",
        encoding="utf-8",
    )


@pytest.fixture
def student(mu_isolated_root, as_user, seed_user):
    """A student account with a filled workspace; returns (record, scope).

    An admin is seeded first: the first account created becomes the admin,
    and the student must be an ordinary user."""
    import asyncio

    from deeptutor.learning.storage import LearningStore
    from deeptutor.multi_user.identity import set_preset
    from deeptutor.multi_user.paths import get_path_service_for_scope, scope_for_user
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    seed_user("root", role="admin")
    record = seed_user("student")
    set_preset("student", "student")
    scope = scope_for_user(record["id"], is_admin=False)
    service = get_path_service_for_scope(scope)
    with as_user(record["id"]):
        store = SQLiteSessionStore(db_path=service.get_chat_history_db())
        mastery_root = service.get_workspace_dir() / "learning" / "mastery_v2"
        mastery_store = LearningStore(root=mastery_root)
        asyncio.run(
            _fill_workspace(
                store,
                mastery_store,
                service.get_workspace_feature_dir("reading"),
                service.get_memory_dir(),
            )
        )
    return record, scope


def _flat(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def test_the_record_carries_the_numbers_and_none_of_the_words(student):
    from deeptutor.multi_user.learning_evidence import learning_evidence

    record, _scope = student
    evidence = learning_evidence(record["id"], record)

    mastery = evidence["mastery"]
    assert mastery["available"] is True
    path = mastery["paths"][0]
    assert path["name"] == "Calculus basics"
    assert path["counts"]["total"] == 2
    assert path["counts"]["mastered"] == 1
    assert path["quiz_attempts"] == 2 and path["quiz_correct"] == 1
    assert [kp["name"] for kp in path["modules"][0]["knowledge_points"]] == [
        "Derivatives",
        "Limits",
    ]

    bank = evidence["question_bank"]
    assert bank["available"] is True
    assert (bank["total"], bank["correct"], bank["wrong"]) == (3, 2, 1)
    assert bank["by_source"]["mastery_path"] == {"total": 1, "correct": 1}
    assert bank["by_source"]["immersive_reading"] == {"total": 1, "correct": 0}
    assert bank["materials"] == [
        {"material_id": "m1", "title": "Calculus 1", "total": 2, "correct": 1}
    ]
    assert bank["categories"] == [{"name": "Calculus", "total": 2, "wrong": 1}]
    assert bank["recent"]["total"] == 3

    reading = evidence["reading"]["materials"][0]
    assert reading["title"] == "Calculus book"
    assert reading["progress"] == 0.4 and reading["finished"] is False
    assert reading["annotations"] == 1

    activity = evidence["activity"]
    assert activity["sessions_total"] == 1
    assert activity["turns_30"] == 2
    assert activity["active_days_7"] == 1
    assert activity["by_capability_30"] == {"chat": 2}

    assert evidence["profile"]["goals"] == [
        {"path": "Calculus basics", "prior_knowledge": "algebra", "target_level": "pass the exam"}
    ]
    assert evidence["summary"]["available"] is False

    text = _flat(evidence)
    for secret in (SECRET_MESSAGE, SECRET_TITLE, SECRET_TOPIC, SECRET_IDENTITY, SECRET_PREFERENCE):
        assert secret not in text
    assert "I am sorry" not in text


def test_an_empty_workspace_reports_every_source_unavailable(mu_isolated_root, seed_user):
    from deeptutor.multi_user.learning_evidence import learning_evidence

    seed_user("root", role="admin")
    record = seed_user("fresh")
    evidence = learning_evidence(record["id"], record)
    assert evidence["mastery"] == {"available": False, "paths": []}
    assert evidence["question_bank"]["available"] is False
    assert evidence["reading"] == {"available": False, "materials": []}
    assert evidence["activity"]["available"] is False
    assert evidence["summary"]["available"] is False
    assert evidence["profile"] == {"account": None, "goals": []}


def test_reading_evidence_never_writes_to_the_student_tree(student):
    """Read-only means read-only: no file appears or changes in the student's
    tree. SQLite's own ``-wal`` / ``-shm`` sidecars are the one exception --
    a WAL database cannot be read at all without them, and they hold no data."""
    from deeptutor.multi_user.learning_evidence import learning_evidence
    from deeptutor.multi_user.paths import get_path_service_for_scope

    record, scope = student
    root = get_path_service_for_scope(scope).get_workspace_dir().parent

    def files():
        return {
            str(p.relative_to(root)): p.stat().st_mtime_ns
            for p in root.rglob("*")
            if p.is_file() and not p.name.endswith(("-wal", "-shm"))
        }

    before = files()
    learning_evidence(record["id"], record)
    assert files() == before


# ── teacher.md ──────────────────────────────────────────────────────────────


def test_the_allowed_input_holds_the_allowed_sections_only(student):
    from deeptutor.multi_user.teacher_summary import allowed_input

    _record, scope = student
    text, sources = allowed_input(scope)
    assert set(sources) == {"L2/chat", "L2/quiz", "L3/profile", "L3/scope"}
    assert "Confuses derivative and integral" in text
    assert "Applies the power rule" in text
    assert "Sign errors in limits" in text
    assert "Works best from worked examples" in text
    assert "Limits" in text
    for secret in (SECRET_TOPIC, SECRET_IDENTITY, SECRET_PREFERENCE):
        assert secret not in text
    assert "<!--" not in text and "[^" not in text


def test_parse_response_keeps_the_four_sections_and_drops_the_rest():
    from deeptutor.multi_user.teacher_summary import SECTIONS, parse_response

    raw = (
        "Some preamble the model should not have written\n"
        "## Strengths\n- Applies the power rule reliably [^1]\n- Solid on 2+2\n"
        "## Working on\n- Limits: sign errors in recent quizzes\n"
        "## Personal\n- Lives in Chiang Mai\n"
        "## Learning style\n- Worked examples help; the student always loves them\n"
        "## Suggested next steps\n- Two short limit exercises this week\n"
        "[^1]: chat\n"
    )
    sections = parse_response(raw)
    assert tuple(sections) == SECTIONS
    assert sections["Strengths"] == ["Applies the power rule reliably", "Solid on 2+2"]
    assert sections["Working on"] == ["Limits: sign errors in recent quizzes"]
    # The banned-absolute guard drops the bullet with "always" / "loves".
    assert sections["Learning style"] == []
    assert sections["Suggested next steps"] == ["Two short limit exercises this week"]
    assert "Chiang Mai" not in json.dumps(sections)


@pytest.mark.asyncio
async def test_generate_summary_writes_outside_l3_and_the_record_reads_it(student, monkeypatch):
    from deeptutor.multi_user import teacher_summary
    from deeptutor.multi_user.learning_evidence import learning_evidence
    from deeptutor.multi_user.paths import get_path_service_for_scope
    from deeptutor.services.memory import paths as memory_paths

    record, scope = student
    seen: dict[str, str] = {}

    async def fake_llm(*, system_prompt, user_prompt, **_kwargs):
        seen["system"] = system_prompt
        seen["user"] = user_prompt
        return "## Strengths\n- Power rule is reliable\n## Working on\n- Limits\n"

    monkeypatch.setattr("deeptutor.services.memory.consolidator.modes._runtime.call_llm", fake_llm)
    result = await teacher_summary.generate_summary(scope, language="th", user_label="student")
    assert result["status"] == "written"
    assert SECRET_IDENTITY not in seen["user"] and SECRET_TOPIC not in seen["user"]
    assert "Sign errors in limits" in seen["user"]

    path = teacher_summary.summary_path(scope)
    memory_root = get_path_service_for_scope(scope).get_memory_dir()
    assert path == memory_root / "school" / "teacher.md"
    assert "teacher" not in memory_paths.L3_SLOTS
    assert not (memory_root / "L3" / "teacher.md").exists()
    body = path.read_text(encoding="utf-8")
    assert "Power rule is reliable" in body and "[^" not in body

    summary = learning_evidence(record["id"], record)["summary"]
    assert summary["available"] is True
    assert summary["language"] == "th"
    assert summary["sections"] == [
        {"title": "Strengths", "items": ["Power rule is reliable"]},
        {"title": "Working on", "items": ["Limits"]},
    ]

    # Nothing changed: the next run is a no-op without an LLM call.
    async def boom(**_kwargs):
        raise AssertionError("no call expected")

    monkeypatch.setattr("deeptutor.services.memory.consolidator.modes._runtime.call_llm", boom)
    again = await teacher_summary.generate_summary(scope, language="th", user_label="student")
    assert again["status"] == "unchanged"


@pytest.mark.asyncio
async def test_generate_summary_without_allowed_memory_writes_nothing(mu_isolated_root, seed_user):
    from deeptutor.multi_user import teacher_summary
    from deeptutor.multi_user.paths import scope_for_user

    seed_user("root", role="admin")
    record = seed_user("fresh")
    scope = scope_for_user(record["id"], is_admin=False)
    result = await teacher_summary.generate_summary(scope)
    assert result["status"] == "no_input"
    assert not teacher_summary.summary_path(scope).exists()


# ── the routes ──────────────────────────────────────────────────────────────


def _client(monkeypatch, users: dict[str, dict]) -> TestClient:
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import multi_user as multi_user_router
    from deeptutor.api.routers import school as school_router
    from deeptutor.services.auth import TokenPayload

    tokens = {
        f"{name}-token": TokenPayload(username=name, role=record["role"], user_id=record["id"])
        for name, record in users.items()
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    monkeypatch.setattr(multi_user_router, "POCKETBASE_ENABLED", False)
    app = FastAPI()
    app.include_router(multi_user_router.router, prefix="/api/multi-user")
    app.include_router(school_router.router, prefix="/api/multi-user")
    return TestClient(app)


@pytest.fixture
def school(student, seed_user, monkeypatch):
    from deeptutor.multi_user.identity import get_user, set_preset

    record, _scope = student
    root = get_user("root")
    teacher = seed_user("teacher")
    set_preset("teacher", "teacher")
    stranger = seed_user("stranger")
    client = _client(
        monkeypatch, {"root": root, "teacher": teacher, "stranger": stranger, "student": record}
    )
    return client, {"root": root, "teacher": teacher, "stranger": stranger, "student": record}


def test_evidence_needs_the_guardian_link_and_is_audited(mu_isolated_root, school):
    client, users = school
    student_id = users["student"]["id"]
    url = f"/api/multi-user/learners/{student_id}/evidence"

    assert client.get(url, headers=_auth("stranger-token")).status_code == 403
    assert client.get(url, headers=_auth("teacher-token")).status_code == 403
    assert client.get(url, headers=_auth("student-token")).status_code == 403

    linked = client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={
            "guardian_user_id": users["teacher"]["id"],
            "learner_user_id": student_id,
            "permissions": ["assign_materials"],
        },
    )
    assert linked.status_code == 201
    # The link exists but without view_reports: still closed.
    assert client.get(url, headers=_auth("teacher-token")).status_code == 403
    relationship_id = linked.json()["relationship"]["id"]
    assert (
        client.delete(
            f"/api/multi-user/guardians/{relationship_id}", headers=_auth("root-token")
        ).status_code
        == 200
    )

    linked = client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={
            "guardian_user_id": users["teacher"]["id"],
            "learner_user_id": student_id,
            "permissions": ["view_reports"],
        },
    )
    assert linked.status_code == 201
    response = client.get(url, headers=_auth("teacher-token"))
    assert response.status_code == 200
    body = response.json()
    assert body["student"] == {"id": student_id, "username": "student", "preset": "student"}
    assert body["question_bank"]["total"] == 3
    assert SECRET_MESSAGE not in response.text and SECRET_TITLE not in response.text

    # An admin reads without a link.
    assert client.get(url, headers=_auth("root-token")).status_code == 200

    audit_path = mu_isolated_root / "data" / "system" / "audit" / "usage.jsonl"
    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    views = [event for event in events if event["action"] == "guardian_evidence_view"]
    assert views[0]["guardian_user_id"] == users["teacher"]["id"]
    assert views[0]["learner_user_id"] == student_id
    assert views[0]["summary"]["available"]["question_bank"] is True
    assert views[1]["actor_role"] == "admin" and views[1]["target_user_id"] == student_id
    assert SECRET_MESSAGE not in audit_path.read_text(encoding="utf-8")


def test_summary_refresh_needs_the_link_and_uses_the_allowed_input(
    mu_isolated_root, school, monkeypatch
):
    client, users = school
    student_id = users["student"]["id"]
    url = f"/api/multi-user/learners/{student_id}/summary"
    seen: dict[str, str] = {}

    async def fake_llm(*, system_prompt, user_prompt, **_kwargs):
        seen["user"] = user_prompt
        return "## Strengths\n- Power rule is reliable\n"

    monkeypatch.setattr("deeptutor.services.memory.consolidator.modes._runtime.call_llm", fake_llm)

    assert client.post(url, headers=_auth("stranger-token")).status_code == 403
    client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={
            "guardian_user_id": users["teacher"]["id"],
            "learner_user_id": student_id,
            "permissions": ["view_reports"],
        },
    )
    response = client.post(url, headers=_auth("teacher-token"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "written"
    assert body["summary"]["sections"] == [
        {"title": "Strengths", "items": ["Power rule is reliable"]}
    ]
    assert SECRET_IDENTITY not in seen["user"]

    audit_path = mu_isolated_root / "data" / "system" / "audit" / "usage.jsonl"
    assert '"guardian_summary_refresh"' in audit_path.read_text(encoding="utf-8")


def test_school_settings_and_manual_run_are_admin_only(mu_isolated_root, school, monkeypatch):
    client, users = school

    assert (
        client.get("/api/multi-user/school/settings", headers=_auth("teacher-token")).status_code
        == 403
    )
    assert (
        client.post(
            "/api/multi-user/school/summaries/run", headers=_auth("teacher-token")
        ).status_code
        == 403
    )

    settings = client.get("/api/multi-user/school/settings", headers=_auth("root-token"))
    assert settings.status_code == 200
    assert settings.json()["summaries_enabled"] is False
    assert settings.json()["summaries_hour"] == 2

    saved = client.put(
        "/api/multi-user/school/settings",
        headers=_auth("root-token"),
        json={"summaries_enabled": True, "summaries_hour": 3},
    )
    assert saved.status_code == 200
    assert saved.json()["summaries_enabled"] is True and saved.json()["summaries_hour"] == 3
    assert (
        client.put(
            "/api/multi-user/school/settings",
            headers=_auth("root-token"),
            json={"summaries_hour": 24},
        ).status_code
        == 422
    )

    async def fake_llm(**_kwargs):
        return "## Working on\n- Limits\n"

    monkeypatch.setattr("deeptutor.services.memory.consolidator.modes._runtime.call_llm", fake_llm)
    run = client.post("/api/multi-user/school/summaries/run", headers=_auth("root-token"))
    assert run.status_code == 200
    report = run.json()
    assert report["students"] == 1
    assert report["written"] == ["student"]
    assert report["failed"] == []

    # The run is remembered, so the loop does not run again today.
    from datetime import datetime

    from deeptutor.multi_user.school_jobs import due, load_school_settings

    settings = load_school_settings()
    assert settings["last_run"]["written"] == ["student"]
    assert due(settings, datetime.now()) is False


def test_due_follows_the_switches():
    from datetime import datetime

    from deeptutor.multi_user.school_jobs import due

    noon = datetime(2026, 9, 21, 12, 0)
    assert due({"summaries_enabled": False, "summaries_hour": 2}, noon) is False
    assert due({"summaries_enabled": True, "summaries_hour": 13}, noon) is False
    assert due({"summaries_enabled": True, "summaries_hour": 2, "last_run": None}, noon) is True
    assert (
        due(
            {
                "summaries_enabled": True,
                "summaries_hour": 2,
                "last_run": {"started_at": "2026-09-21T02:00:00+07:00"},
            },
            noon,
        )
        is False
    )
    assert (
        due(
            {
                "summaries_enabled": True,
                "summaries_hour": 2,
                "last_run": {"started_at": "2026-09-20T02:00:00+07:00"},
            },
            noon,
        )
        is True
    )


def test_the_summary_is_written_in_the_deployment_language(mu_isolated_root, school, monkeypatch):
    """A teacher's own interface.json (absent here, so ``en``) must not decide
    the language; the deployment's does, the same for a refresh and the
    nightly run."""
    from deeptutor.multi_user.paths import get_admin_path_service
    from deeptutor.multi_user.school_jobs import deployment_language

    client, users = school
    settings_file = get_admin_path_service().get_settings_file("interface")
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps({"language": "th"}), encoding="utf-8")
    assert deployment_language() == "th"

    seen: dict[str, str] = {}

    async def fake_llm(*, language=None, **_kwargs):
        seen["language"] = language
        return "## Strengths\n- ok\n"

    monkeypatch.setattr("deeptutor.services.memory.consolidator.modes._runtime.call_llm", fake_llm)
    client.post(
        "/api/multi-user/guardians",
        headers=_auth("root-token"),
        json={
            "guardian_user_id": users["teacher"]["id"],
            "learner_user_id": users["student"]["id"],
            "permissions": ["view_reports"],
        },
    )
    response = client.post(
        f"/api/multi-user/learners/{users['student']['id']}/summary", headers=_auth("teacher-token")
    )
    assert response.status_code == 200
    assert seen["language"] == "th"
    assert response.json()["summary"]["language"] == "th"


# ── step A: minutes and the weekly trend ────────────────────────────────────


def test_minutes_are_estimated_from_message_gaps_with_a_cap():
    from deeptutor.multi_user.learning_evidence import SESSION_GAP_SECONDS, _minutes

    # One session: 0 s, 5 min, 8 min, then a 2-hour silence, then one more.
    stamps = [0.0, 300.0, 480.0, 480.0 + 7200.0]
    # 5 + 3 min of work, the long gap counts one tail minute, plus one tail
    # minute for the last message.
    assert _minutes({"s": stamps}) == 5 + 3 + 1 + 1
    assert _minutes({"s": [0.0]}) == 1.0
    assert _minutes({}) == 0.0
    assert _minutes({"a": [0.0, float(SESSION_GAP_SECONDS)]}) == SESSION_GAP_SECONDS / 60 + 1


def test_the_record_carries_minutes_and_an_eight_week_trend(student):
    from deeptutor.multi_user.learning_evidence import TREND_WEEKS, learning_evidence

    record, _scope = student
    activity = learning_evidence(record["id"], record)["activity"]
    # Three messages seconds apart: no measurable gaps, one tail minute.
    assert activity["minutes_30"] == 1.0
    trend = activity["trend"]
    assert len(trend) == TREND_WEEKS
    assert [w["week_start"] for w in trend] == sorted(w["week_start"] for w in trend)
    this_week = trend[-1]
    assert this_week["turns"] == 2 and this_week["active_days"] == 1
    assert this_week["questions"] == 3 and this_week["correct"] == 2
    assert this_week["minutes"] == 1.0
    assert all(w["turns"] == 0 for w in trend[:-1])


# ── step B: an account reads itself ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_my_evidence_is_the_same_record_minus_the_teachers_part(
    mu_isolated_root, school, monkeypatch
):
    from deeptutor.multi_user import teacher_summary

    client, users = school
    record = users["student"]
    scope_id = record["id"]
    from deeptutor.multi_user.paths import scope_for_user

    async def fake_llm(**_kwargs):
        return "## Strengths\n- Power rule is reliable\n"

    monkeypatch.setattr("deeptutor.services.memory.consolidator.modes._runtime.call_llm", fake_llm)
    written = await teacher_summary.generate_summary(scope_for_user(scope_id, is_admin=False))
    assert written["status"] == "written"

    mine = client.get("/api/multi-user/me/evidence", headers=_auth("student-token"))
    assert mine.status_code == 200, mine.text
    body = mine.json()
    assert body["student"] == {"id": scope_id, "username": "student", "preset": "student"}
    assert body["question_bank"]["total"] == 3
    assert body["activity"]["trend"]
    assert "spotlights" in body and "comparison" not in body
    # The teacher's summary is not the student's to see (decision 8).
    assert body["summary"]["available"] is False
    assert "Power rule" not in mine.text
    # Not a supervisor action: nothing in the audit.
    audit_path = mu_isolated_root / "data" / "system" / "audit" / "usage.jsonl"
    audit = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""
    assert "guardian_evidence_view" not in audit

    # An account with nothing yet still gets a record, not an error.
    fresh = client.get("/api/multi-user/me/evidence", headers=_auth("stranger-token"))
    assert fresh.status_code == 200
    assert fresh.json()["activity"]["available"] is False
