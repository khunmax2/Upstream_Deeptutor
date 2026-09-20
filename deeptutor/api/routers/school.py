"""Fork: the school routes (school roles design, Phase 2).

Mounted beside the multi-user router under ``/api/multi-user`` so a teacher's
reads sit next to the guardian routes they extend, and reuse their access
check and audit helper:

* ``GET /learners/{id}/evidence`` -- the learning-evidence record of one
  student (:mod:`deeptutor.multi_user.learning_evidence`). Needs the
  ``view_reports`` guardian permission, or admin; audited as
  ``guardian_evidence_view`` exactly like ``guardian_report_view``.
* ``POST /learners/{id}/summary`` -- write the student's ``teacher.md`` now
  (:mod:`deeptutor.multi_user.teacher_summary`) instead of waiting for the
  nightly run. Same permission, audited as ``guardian_summary_refresh``. The
  model is the deployment default, as in the nightly run: the school pays.
* ``GET`` / ``PUT /school/settings`` and ``POST /school/summaries/run`` --
  the nightly summary job's switches and a manual run, admin only.
* ``/school/classrooms`` (Phase 3a) -- classrooms as a bulk editor of
  guardian links (:mod:`deeptutor.multi_user.classrooms`), admin writes,
  teacher reads of their own; ``POST /school/import`` -- student accounts
  from a CSV (:mod:`deeptutor.multi_user.school_import`), admin only.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_admin, require_auth
from deeptutor.api.routers.multi_user import (
    _log_supervisor_action,
    _require_guardian_access,
)

router = APIRouter()


def _available(evidence: dict[str, Any]) -> dict[str, bool]:
    return {
        source: bool(evidence.get(source, {}).get("available"))
        for source in ("mastery", "question_bank", "reading", "activity", "summary")
    }


@router.get("/learners/{learner_user_id}/evidence")
async def guardian_evidence(
    learner_user_id: str,
    classroom_id: str = "",
    current: object = Depends(require_auth),
) -> dict[str, Any]:
    """One student's evidence record; with ``classroom_id``, also the class
    medians to show beside it (the caller must be a teacher of that class or
    an admin, and the student must be in it)."""
    learner_username, learner_record, actor_user_id, is_admin = _require_guardian_access(
        current, learner_user_id, "view_reports"
    )
    from deeptutor.multi_user.learning_evidence import learning_evidence
    from deeptutor.multi_user.school_alerts import class_comparison, spotlights_for

    evidence = await asyncio.to_thread(learning_evidence, learner_user_id, learner_record)
    evidence["student"]["username"] = learner_username
    evidence["spotlights"] = spotlights_for(evidence)
    if classroom_id:
        record, _admin = _require_classroom_reader(current, classroom_id)
        if learner_user_id not in record["student_ids"]:
            raise HTTPException(status_code=400, detail="The student is not in this classroom")
        rows, _records = await asyncio.to_thread(_roster_rows, record, actor_user_id, is_admin)
        evidence["comparison"] = {"classroom_id": classroom_id, **class_comparison(rows)}
    _log_supervisor_action(
        "guardian_evidence_view",
        actor_user_id=actor_user_id,
        learner_user_id=learner_user_id,
        is_admin=is_admin,
        summary={"available": _available(evidence), "classroom_id": classroom_id or None},
    )
    return evidence


@router.get("/me/evidence")
async def my_evidence(current: object = Depends(require_auth)) -> dict[str, Any]:
    """The caller's own evidence record, for the "My learning" section of
    their dashboard (step B). The same record a teacher would read -- one
    source, two views -- minus what is the teacher's business: no
    ``teacher.md``, no alerts, no class comparison. Not audited: an account
    reading itself is not a supervisor action."""
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.multi_user.identity import get_user_by_id
    from deeptutor.multi_user.learning_evidence import learning_evidence
    from deeptutor.multi_user.school_alerts import spotlights_for

    user = get_current_user()
    found = get_user_by_id(user.id)
    record = found[1] if found else {}
    evidence = await asyncio.to_thread(learning_evidence, user.id, record, scope=user.scope)
    evidence["student"]["username"] = user.username
    evidence["spotlights"] = spotlights_for(evidence)
    evidence["summary"] = {"available": False, "generated_at": None, "sections": []}
    return evidence


@router.post("/learners/{learner_user_id}/summary")
async def guardian_summary_refresh(
    learner_user_id: str,
    current: object = Depends(require_auth),
) -> dict[str, Any]:
    learner_username, _record, actor_user_id, is_admin = _require_guardian_access(
        current, learner_user_id, "view_reports"
    )
    from deeptutor.multi_user.paths import scope_for_user
    from deeptutor.multi_user.school_jobs import deployment_language
    from deeptutor.multi_user.teacher_summary import generate_summary, read_summary

    scope = scope_for_user(learner_user_id, is_admin=False)
    result = await generate_summary(
        scope, language=deployment_language(), user_label=learner_username, force=True
    )
    _log_supervisor_action(
        "guardian_summary_refresh",
        actor_user_id=actor_user_id,
        learner_user_id=learner_user_id,
        is_admin=is_admin,
        summary={"status": result["status"]},
    )
    return {"status": result["status"], "summary": read_summary(scope)}


class SchoolSettingsPayload(BaseModel):
    summaries_enabled: bool | None = None
    summaries_hour: int | None = Field(default=None, ge=0, le=23)


@router.get("/school/settings")
async def get_school_settings(_: object = Depends(require_admin)) -> dict[str, Any]:
    from deeptutor.multi_user.school_jobs import load_school_settings

    return load_school_settings()


@router.put("/school/settings")
async def put_school_settings(
    payload: SchoolSettingsPayload, _: object = Depends(require_admin)
) -> dict[str, Any]:
    from deeptutor.multi_user.audit import log_admin_action
    from deeptutor.multi_user.school_jobs import save_school_settings

    changes = payload.model_dump(exclude_none=True)
    settings = save_school_settings(changes)
    log_admin_action("school_settings_update", summary=changes)
    return settings


@router.post("/school/summaries/run")
async def run_school_summaries(_: object = Depends(require_admin)) -> dict[str, Any]:
    """Write every student's ``teacher.md`` now, as the nightly job would."""
    from deeptutor.multi_user.audit import log_admin_action
    from deeptutor.multi_user.school_jobs import run_summaries_once

    report = await run_summaries_once(force=False)
    log_admin_action("school_summaries_run", summary=report)
    return report


# ── classrooms (Phase 3a) ───────────────────────────────────────────────────


class ClassroomPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    term: str = Field(default="", max_length=80)
    home_room_teacher_id: str = ""
    teacher_ids: list[str] = Field(default_factory=list)
    student_ids: list[str] = Field(default_factory=list)
    defaults: dict[str, Any] | None = None


class ClassroomUpdatePayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    term: str | None = Field(default=None, max_length=80)
    home_room_teacher_id: str | None = None
    defaults: dict[str, Any] | None = None


class MemberIdsPayload(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=500)


class ImportPayload(BaseModel):
    csv: str = Field(min_length=1, max_length=200_000)
    create_classrooms: bool = False


def _classroom_or_404(classroom_id: str) -> dict[str, Any]:
    from deeptutor.multi_user.classrooms import get_classroom

    record = get_classroom(classroom_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Classroom not found")
    return record


def _classroom_view(record: dict[str, Any]) -> dict[str, Any]:
    """The record with usernames beside the ids, for the pages."""
    from deeptutor.multi_user.identity import list_user_info

    names = {str(u.get("id") or ""): str(u.get("username") or "") for u in list_user_info()}
    return {
        **record,
        "teachers": [{"id": tid, "username": names.get(tid, "")} for tid in record["teacher_ids"]],
        "students": [{"id": sid, "username": names.get(sid, "")} for sid in record["student_ids"]],
    }


@router.get("/school/classrooms")
async def list_school_classrooms(
    include_archived: bool = False,
    current: object = Depends(require_auth),
) -> dict[str, Any]:
    """Admins see every classroom; a teacher the ones they are in."""
    from deeptutor.multi_user.classrooms import list_classrooms

    is_admin = str(getattr(current, "role", "") or "") == "admin"
    actor_id = str(getattr(current, "user_id", "") or "")
    records = list_classrooms(
        include_archived=include_archived and is_admin,
        teacher_user_id=None if is_admin else actor_id,
    )
    return {"classrooms": [_classroom_view(record) for record in records]}


@router.post("/school/classrooms", status_code=201)
async def create_school_classroom(
    payload: ClassroomPayload, _: object = Depends(require_admin)
) -> dict[str, Any]:
    from deeptutor.multi_user.audit import log_admin_action
    from deeptutor.multi_user.classrooms import ClassroomError, create_classroom

    try:
        record = create_classroom(
            payload.name,
            term=payload.term,
            home_room_teacher_id=payload.home_room_teacher_id,
            teacher_ids=payload.teacher_ids,
            student_ids=payload.student_ids,
            defaults=payload.defaults,
        )
    except ClassroomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_admin_action(
        "classroom_create",
        summary={
            "classroom_id": record["id"],
            "name": record["name"],
            "teachers": len(record["teacher_ids"]),
            "students": len(record["student_ids"]),
        },
    )
    return {"classroom": _classroom_view(record)}


@router.put("/school/classrooms/{classroom_id}")
async def update_school_classroom(
    classroom_id: str, payload: ClassroomUpdatePayload, _: object = Depends(require_admin)
) -> dict[str, Any]:
    from deeptutor.multi_user.audit import log_admin_action
    from deeptutor.multi_user.classrooms import ClassroomError, update_classroom

    _classroom_or_404(classroom_id)
    changes = payload.model_dump(exclude_none=True)
    try:
        record = update_classroom(classroom_id, **changes)
    except ClassroomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_admin_action(
        "classroom_update",
        summary={"classroom_id": classroom_id, "fields": sorted(changes)},
    )
    return {"classroom": _classroom_view(record)}


@router.delete("/school/classrooms/{classroom_id}")
async def archive_school_classroom(
    classroom_id: str, _: object = Depends(require_admin)
) -> dict[str, Any]:
    from deeptutor.multi_user.audit import log_admin_action
    from deeptutor.multi_user.classrooms import archive_classroom

    _classroom_or_404(classroom_id)
    record = archive_classroom(classroom_id)
    log_admin_action("classroom_archive", summary={"classroom_id": classroom_id})
    return {"classroom": _classroom_view(record)}


@router.put("/school/classrooms/{classroom_id}/teachers")
async def set_school_classroom_teachers(
    classroom_id: str, payload: MemberIdsPayload, _: object = Depends(require_admin)
) -> dict[str, Any]:
    from deeptutor.multi_user.audit import log_admin_action
    from deeptutor.multi_user.classrooms import ClassroomError, set_teachers

    _classroom_or_404(classroom_id)
    try:
        record, changes = set_teachers(classroom_id, payload.ids)
    except ClassroomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_admin_action(
        "classroom_members_update",
        summary={"classroom_id": classroom_id, "kind": "teachers", **changes},
    )
    return {"classroom": _classroom_view(record), "changes": changes}


@router.put("/school/classrooms/{classroom_id}/students")
async def set_school_classroom_students(
    classroom_id: str, payload: MemberIdsPayload, _: object = Depends(require_admin)
) -> dict[str, Any]:
    from deeptutor.multi_user.audit import log_admin_action
    from deeptutor.multi_user.classrooms import ClassroomError, set_students

    _classroom_or_404(classroom_id)
    try:
        record, changes = set_students(classroom_id, payload.ids)
    except ClassroomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_admin_action(
        "classroom_members_update",
        summary={"classroom_id": classroom_id, "kind": "students", **changes},
    )
    return {"classroom": _classroom_view(record), "changes": changes}


@router.post("/school/import")
async def import_school_students(
    payload: ImportPayload, _: object = Depends(require_admin)
) -> dict[str, Any]:
    """Create student accounts from a CSV and place them in their classrooms.

    The generated passwords are in this response and nowhere else.
    """
    from deeptutor.multi_user.audit import log_admin_action
    from deeptutor.multi_user.school_import import import_students
    from deeptutor.services.auth import AUTH_ENABLED, POCKETBASE_ENABLED

    if not AUTH_ENABLED or POCKETBASE_ENABLED:
        raise HTTPException(status_code=400, detail="CSV import needs the built-in auth store.")
    report = await asyncio.to_thread(
        import_students, payload.csv, create_classrooms=payload.create_classrooms
    )
    log_admin_action("school_import", summary=report.public())
    return {
        "created": [
            {"username": row["username"], "classroom": row["classroom"]} for row in report.created
        ],
        "skipped": report.skipped,
        "errors": report.errors,
        "classrooms_created": report.classrooms_created,
        "credentials_csv": report.credentials_csv() if report.created else "",
    }


# ── the roster (Phase 3b) ──────────────────────────────────────────────────


def _require_classroom_reader(current: object, classroom_id: str) -> tuple[dict[str, Any], bool]:
    """The classroom, for an admin or a teacher who is in it."""
    record = _classroom_or_404(classroom_id)
    is_admin = str(getattr(current, "role", "") or "") == "admin"
    actor_id = str(getattr(current, "user_id", "") or "")
    if not is_admin and actor_id not in record["teacher_ids"]:
        raise HTTPException(status_code=403, detail="Not a teacher of this classroom")
    return record, is_admin


def _roster_rows(
    record: dict[str, Any], actor_id: str, is_admin: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One summary row (and the record behind it) per student the reader may see."""
    from deeptutor.multi_user.guardians import guardian_can_access
    from deeptutor.multi_user.identity import get_user_by_id
    from deeptutor.multi_user.learning_evidence import learning_evidence
    from deeptutor.multi_user.school_alerts import summary_row

    rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for student_id in record["student_ids"]:
        found = get_user_by_id(student_id)
        if found is None:
            continue
        username, account = found
        # The classroom lists the student; the guardian link is what allows
        # the read. A link revoked by hand keeps the row out.
        if not is_admin and not guardian_can_access(actor_id, student_id, "view_reports"):
            continue
        evidence = learning_evidence(student_id, account)
        evidence["student"]["username"] = username
        records.append(evidence)
        rows.append(summary_row(evidence))
    rows.sort(key=lambda row: (-len(row["alerts"]), row["student"].get("username", "")))
    return rows, records


@router.get("/school/classrooms/{classroom_id}/roster")
async def classroom_roster(
    classroom_id: str,
    current: object = Depends(require_auth),
) -> dict[str, Any]:
    """One summary row per student of the classroom, and the class in numbers.

    One audit line per read, with the class and its size -- not one per
    student, which at forty rows would bury the reads a parent asks about
    (a student's detail is audited per student, by the evidence route).
    """
    from deeptutor.multi_user.audit import log_admin_action, log_guardian_action
    from deeptutor.multi_user.school_alerts import class_totals

    record, is_admin = _require_classroom_reader(current, classroom_id)
    actor_id = str(getattr(current, "user_id", "") or "")
    rows, records = await asyncio.to_thread(_roster_rows, record, actor_id, is_admin)
    summary = {"classroom_id": classroom_id, "students": len(rows)}
    if is_admin:
        log_admin_action("classroom_roster_view", summary=summary)
    else:
        # One guardian line per read, naming every student it covered in the
        # summary rather than as forty lines: the audit stays readable and
        # still answers "who looked at my child's roster row, and when".
        log_guardian_action(
            "classroom_roster_view",
            guardian_user_id=actor_id,
            learner_user_id="",
            summary={**summary, "student_ids": [row["student"]["id"] for row in rows]},
        )
    return {
        "classroom": _classroom_view(record),
        "rows": rows,
        "totals": class_totals(rows, records),
    }
