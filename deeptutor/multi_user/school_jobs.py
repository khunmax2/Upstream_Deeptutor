"""Fork: the nightly ``teacher.md`` run for student accounts (Phase 2).

L2 and L3 do not refresh by themselves: consolidation is a run the user
starts from Settings > Memory. A teacher's summary that waited for the
student to press that button would be stale for most students, so this job
writes every ``student`` account's ``teacher.md`` once a day, from whatever
the allowed memory sections hold at that time. It skips a student whose
sources have not changed since the last run, so a quiet account costs
nothing.

Switches live in the deployment's ``settings/school.json``
(``summaries_enabled``, ``summaries_hour`` in the server's local time) and
are edited through the admin routes in :mod:`deeptutor.api.routers.school`.
The job runs on the elected background leader beside the cron service and
the partners bus (``api/main.py``), and the model it calls is the deployment
default: the school pays for its teachers' summaries.

The run itself is :func:`run_summaries_once`, which the admin route also
calls; the loop only decides *when*.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SETTINGS_NAME = "school.json"
DEFAULT_SETTINGS: dict[str, Any] = {"summaries_enabled": False, "summaries_hour": 2}
_CHECK_SECONDS = 15 * 60


# ── settings ────────────────────────────────────────────────────────────────


def _settings_path() -> Path:
    from deeptutor.multi_user.paths import get_admin_path_service

    return get_admin_path_service().get_settings_dir() / SETTINGS_NAME


def load_school_settings() -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    try:
        raw = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if isinstance(raw, dict):
        if isinstance(raw.get("summaries_enabled"), bool):
            settings["summaries_enabled"] = raw["summaries_enabled"]
        hour = raw.get("summaries_hour")
        if isinstance(hour, int) and not isinstance(hour, bool) and 0 <= hour <= 23:
            settings["summaries_hour"] = hour
    last_run = raw.get("last_run") if isinstance(raw, dict) else None
    settings["last_run"] = last_run if isinstance(last_run, dict) else None
    return settings


def save_school_settings(changes: dict[str, Any]) -> dict[str, Any]:
    from deeptutor.services.file_io import atomic_write_text

    current = load_school_settings()
    if "summaries_enabled" in changes:
        current["summaries_enabled"] = bool(changes["summaries_enabled"])
    if "summaries_hour" in changes:
        current["summaries_hour"] = max(0, min(23, int(changes["summaries_hour"])))
    if "last_run" in changes:
        current["last_run"] = changes["last_run"]
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(current, ensure_ascii=False, indent=2))
    return current


# ── the run ─────────────────────────────────────────────────────────────────


def student_accounts() -> list[tuple[str, dict[str, Any]]]:
    """``(username, record)`` of every enabled ``student`` account."""
    from deeptutor.multi_user.identity import load_users
    from deeptutor.multi_user.student_policy import STUDENT_PRESET

    return [
        (username, record)
        for username, record in load_users().items()
        if str(record.get("preset") or "") == STUDENT_PRESET
        and str(record.get("id") or "")
        and not record.get("disabled")
        and not record.get("deleted_at")
    ]


async def run_summaries_once(*, force: bool = False) -> dict[str, Any]:
    """Write ``teacher.md`` for every student whose sources changed.

    Returns a report the audit line and the admin route carry:
    ``{"students": N, "written": [...], "unchanged": N, "no_input": N,
    "failed": [...]}``; usernames only, never content.
    """
    from deeptutor.multi_user.paths import scope_for_user
    from deeptutor.multi_user.teacher_summary import generate_summary
    from deeptutor.services.i18n import current_language

    language = current_language()
    report: dict[str, Any] = {
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "students": 0,
        "written": [],
        "unchanged": 0,
        "no_input": 0,
        "failed": [],
    }
    for username, record in student_accounts():
        report["students"] += 1
        scope = scope_for_user(str(record["id"]), is_admin=False)
        try:
            result = await generate_summary(
                scope, language=language, user_label=username, force=force
            )
        except Exception:  # noqa: BLE001 - one student must not stop the run
            logger.exception("school summaries: %s failed", username)
            report["failed"].append(username)
            continue
        status = result["status"]
        if status == "written":
            report["written"].append(username)
        elif status == "failed":
            report["failed"].append(username)
        else:
            report[status] += 1
    report["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    save_school_settings({"last_run": report})
    logger.info(
        "school summaries: %d students, %d written, %d unchanged, %d without input, %d failed",
        report["students"],
        len(report["written"]),
        report["unchanged"],
        report["no_input"],
        len(report["failed"]),
    )
    return report


# ── the loop ────────────────────────────────────────────────────────────────


def due(settings: dict[str, Any], now: datetime) -> bool:
    """Whether today's run is due: enabled, past the hour, not yet run today."""
    if not settings.get("summaries_enabled"):
        return False
    if now.hour < int(settings.get("summaries_hour", 2)):
        return False
    last = settings.get("last_run") or {}
    started = str(last.get("started_at") or "")
    return started[:10] != now.date().isoformat()


class SchoolSummaryService:
    """Background loop: check every 15 minutes, run once a day when due."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._loop(), name="school-summaries")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        self._stop.set()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if due(load_school_settings(), datetime.now()):
                    await run_summaries_once()
            except Exception:  # noqa: BLE001
                logger.exception("school summaries: run failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=_CHECK_SECONDS)
            except asyncio.TimeoutError:
                continue


_service: SchoolSummaryService | None = None


def get_school_summary_service() -> SchoolSummaryService:
    global _service
    if _service is None:
        _service = SchoolSummaryService()
    return _service


__all__ = [
    "DEFAULT_SETTINGS",
    "SchoolSummaryService",
    "due",
    "get_school_summary_service",
    "load_school_settings",
    "run_summaries_once",
    "save_school_settings",
    "student_accounts",
]
