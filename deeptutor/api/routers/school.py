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
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends
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
    current: object = Depends(require_auth),
) -> dict[str, Any]:
    learner_username, learner_record, actor_user_id, is_admin = _require_guardian_access(
        current, learner_user_id, "view_reports"
    )
    from deeptutor.multi_user.learning_evidence import learning_evidence

    evidence = await asyncio.to_thread(learning_evidence, learner_user_id, learner_record)
    evidence["student"]["username"] = learner_username
    _log_supervisor_action(
        "guardian_evidence_view",
        actor_user_id=actor_user_id,
        learner_user_id=learner_user_id,
        is_admin=is_admin,
        summary={"available": _available(evidence)},
    )
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
