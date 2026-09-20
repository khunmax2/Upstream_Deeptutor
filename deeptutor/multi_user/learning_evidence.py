"""Fork: one learning-evidence record per student (school roles design, Phase 2).

The teacher dashboard and the guardian evidence route read a student through
this module and nothing else. It answers "how is this student learning" with
numbers and structure, never with what the student said: no session titles,
no messages, no memory traces, no annotation text. The sources, in the order
of trust the design gives them:

1. Mastery Path -- per path, the objective map (``policy.map_summary``),
   attempts and active error records;
2. the Question Bank -- every graded answer across Deep Question, Mastery
   Path and the reading quizzes, with ``is_correct``;
3. reading progress -- position, finished or not, annotation and bookmark
   *counts*;
4. activity -- sessions, active days, turns, estimated minutes and an
   eight-week trend; counts only;
5. the learner profile -- the intake fields a student fills in for a goal
   (prior knowledge, target level, time budget), and the account profile an
   admin set;
6. ``teacher.md`` -- the AI-written summary (:mod:`teacher_summary`), when
   one has been generated.

Every source is read straight from the student's workspace files, read-only:
SQLite is opened with ``mode=ro`` and no store class is constructed, so a
teacher's read never creates, migrates or changes anything in the student's
tree (SQLite's own ``-wal`` / ``-shm`` sidecars aside, which every reader of
a WAL database needs). A source that is missing or unreadable reports
``available: False`` and the rest of the record still comes back.

v1.6.6 keeps these three stores apart; when an upstream sync brings a single
assessment log, only the inside of this module changes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any

from deeptutor.multi_user.models import UserScope
from deeptutor.multi_user.paths import get_path_service_for_scope, scope_for_user

logger = logging.getLogger(__name__)

RECENT_DAYS = 30
_MASTERY_DB = "mastery.sqlite3"
_MASTERY_V2_DIR = "mastery_v2"
_READING_MANIFEST = "manifest.json"


# ── read-only file access ───────────────────────────────────────────────────


def _ro_connect(path: Path) -> sqlite3.Connection | None:
    """Open *path* read-only, or ``None`` when it does not exist / cannot open."""
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        logger.warning("learning evidence: cannot open %s read-only", path, exc_info=True)
        return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _mastery_db_path(scope: UserScope) -> Path:
    # Mirrors ``LearningStore.default_db_path`` without importing the store:
    # the app-owned location after the V1 -> V2 migration.
    workspace = get_path_service_for_scope(scope).get_workspace_dir()
    return workspace / "learning" / _MASTERY_V2_DIR / _MASTERY_DB


# ── 1. Mastery Path ─────────────────────────────────────────────────────────


def _mastery(scope: UserScope) -> dict[str, Any]:
    conn = _ro_connect(_mastery_db_path(scope))
    if conn is None:
        return {"available": False, "paths": []}
    from deeptutor.learning.models import LearningProgress
    from deeptutor.learning.policy import map_summary

    paths: list[dict[str, Any]] = []
    try:
        rows = conn.execute(
            "SELECT path_id, state_json, updated_at FROM mastery_paths ORDER BY updated_at DESC"
        ).fetchall()
    except sqlite3.Error:
        logger.warning("learning evidence: mastery db unreadable for %s", scope.user_id)
        return {"available": False, "paths": []}
    finally:
        conn.close()
    for row in rows:
        try:
            progress = LearningProgress.model_validate_json(row["state_json"])
        except Exception:  # noqa: BLE001 - one bad path must not hide the others
            logger.warning("learning evidence: skipping unparseable path %s", row["path_id"])
            continue
        summary = map_summary(progress)
        modules = [
            {
                "name": module["name"],
                "objective": module["objective"],
                "mastered": module["mastered"],
                "total": module["total"],
                "knowledge_points": [
                    {
                        "name": kp["name"],
                        "type": kp["type"],
                        "status": kp["status"],
                        "mastery": kp["mastery"],
                    }
                    for kp in module["knowledge_points"]
                ],
            }
            for module in summary["modules"]
        ]
        attempts = progress.quiz_attempts
        week_ago = datetime.now(tz=timezone.utc).timestamp() - 7 * 86400
        recent_ids = {a.knowledge_point_id for a in attempts if a.timestamp >= week_ago}
        mastered_recently = [
            kp["name"]
            for module in summary["modules"]
            for kp in module["knowledge_points"]
            if kp["status"] == "mastered" and kp["id"] in recent_ids
        ]
        paths.append(
            {
                "id": progress.book_id,
                "name": summary["name"],
                "stage": progress.current_stage.value,
                "counts": summary["counts"],
                "due_reviews": summary["due_reviews"],
                "complete": summary["complete"],
                "quiz_attempts": len(attempts),
                "quiz_correct": sum(1 for attempt in attempts if attempt.is_correct),
                "errors_active": sum(
                    1 for record in progress.error_records if record.status != "graduated"
                ),
                "mastered_recently": mastered_recently,
                "modules": modules,
                "updated_at": _iso(row["updated_at"]),
            }
        )
    return {"available": True, "paths": paths}


# ── 2. Question Bank ────────────────────────────────────────────────────────


def _question_bank(conn: sqlite3.Connection) -> dict[str, Any]:
    since = (datetime.now(tz=timezone.utc) - timedelta(days=RECENT_DAYS)).timestamp()
    totals = conn.execute(
        """
        SELECT COUNT(*) AS total,
               COALESCE(SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END), 0) AS correct,
               COALESCE(SUM(CASE WHEN is_correct = 0 AND resolved = 0 THEN 1 ELSE 0 END), 0)
                   AS unresolved,
               MAX(created_at) AS last_at
        FROM notebook_entries
        """
    ).fetchone()
    recent = conn.execute(
        """
        SELECT COUNT(*) AS total,
               COALESCE(SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END), 0) AS correct
        FROM notebook_entries WHERE created_at >= ?
        """,
        (since,),
    ).fetchone()
    by_source = {
        row["source"]: {"total": int(row["total"]), "correct": int(row["correct"])}
        for row in conn.execute(
            """
            SELECT source, COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END), 0) AS correct
            FROM notebook_entries GROUP BY source ORDER BY source
            """
        )
    }
    materials = [
        {
            "material_id": row["material_id"],
            "title": row["material_title"],
            "total": int(row["total"]),
            "correct": int(row["correct"]),
        }
        for row in conn.execute(
            """
            SELECT material_id, MAX(material_title) AS material_title, COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END), 0) AS correct
            FROM notebook_entries WHERE material_id != ''
            GROUP BY material_id ORDER BY total DESC LIMIT 50
            """
        )
    ]
    categories = [
        {"name": row["name"], "total": int(row["total"]), "wrong": int(row["wrong"])}
        for row in conn.execute(
            """
            SELECT c.name AS name, COUNT(e.id) AS total,
                   COALESCE(SUM(CASE WHEN e.is_correct = 0 THEN 1 ELSE 0 END), 0) AS wrong
            FROM notebook_categories c
            JOIN notebook_entry_categories ec ON ec.category_id = c.id
            JOIN notebook_entries e ON e.id = ec.entry_id
            GROUP BY c.id ORDER BY total DESC LIMIT 50
            """
        )
    ]
    total = int(totals["total"])
    return {
        "available": True,
        "total": total,
        "correct": int(totals["correct"]),
        "wrong": total - int(totals["correct"]),
        "unresolved": int(totals["unresolved"]),
        "last_answered_at": _iso(totals["last_at"]),
        "recent": {
            "days": RECENT_DAYS,
            "total": int(recent["total"]),
            "correct": int(recent["correct"]),
        },
        "by_source": by_source,
        "materials": materials,
        "categories": categories,
    }


# ── time on task and the weekly trend ───────────────────────────────────────

# A student's time is not logged; it is read off the message timestamps. Two
# messages of one session less than SESSION_GAP apart are one stretch of
# work; a longer silence ends the stretch, and the last message of a stretch
# is given TAIL_MINUTES for reading the answer. Khan Academy and IXL report
# minutes the same way (time between events, capped) -- an estimate a
# teacher reads as "about", never a clock.
SESSION_GAP_SECONDS = 10 * 60
TAIL_MINUTES = 1.0
TREND_WEEKS = 8


def _minutes(stamps_by_session: dict[str, list[float]]) -> float:
    total = 0.0
    for stamps in stamps_by_session.values():
        stamps = sorted(stamps)
        for earlier, later in zip(stamps, stamps[1:]):
            gap = later - earlier
            total += gap / 60 if gap <= SESSION_GAP_SECONDS else TAIL_MINUTES
        if stamps:
            total += TAIL_MINUTES
    return round(total, 1)


def _week_start(ts: float) -> datetime:
    day = datetime.fromtimestamp(ts, tz=timezone.utc).date()
    monday = day - timedelta(days=day.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)


def _trend(conn: sqlite3.Connection, now: datetime) -> list[dict[str, Any]]:
    """One row per week for the last :data:`TREND_WEEKS`, Monday to Sunday
    (the current week included, partial). Counts only: user turns, active
    days, minutes, questions answered and correct."""
    this_monday = _week_start(now.timestamp())
    first = this_monday - timedelta(weeks=TREND_WEEKS - 1)
    weeks: dict[str, dict[str, Any]] = {}
    for index in range(TREND_WEEKS):
        start = first + timedelta(weeks=index)
        weeks[start.date().isoformat()] = {
            "week_start": start.date().isoformat(),
            "turns": 0,
            "active_days": 0,
            "minutes": 0.0,
            "questions": 0,
            "correct": 0,
        }
    days: dict[str, set[str]] = {key: set() for key in weeks}
    stamps: dict[str, dict[str, list[float]]] = {key: {} for key in weeks}
    for row in conn.execute(
        "SELECT session_id, role, created_at FROM messages WHERE created_at >= ?",
        (first.timestamp(),),
    ):
        key = _week_start(row["created_at"]).date().isoformat()
        if key not in weeks:
            continue
        stamps[key].setdefault(row["session_id"], []).append(float(row["created_at"]))
        if row["role"] == "user":
            weeks[key]["turns"] += 1
            days[key].add(
                datetime.fromtimestamp(row["created_at"], tz=timezone.utc).date().isoformat()
            )
    for row in conn.execute(
        "SELECT created_at, is_correct FROM notebook_entries WHERE created_at >= ?",
        (first.timestamp(),),
    ):
        key = _week_start(row["created_at"]).date().isoformat()
        if key not in weeks:
            continue
        weeks[key]["questions"] += 1
        weeks[key]["correct"] += 1 if row["is_correct"] else 0
    for key, week in weeks.items():
        week["active_days"] = len(days[key])
        week["minutes"] = _minutes(stamps[key])
    return list(weeks.values())


# ── 4. activity ─────────────────────────────────────────────────────────────


def _activity(conn: sqlite3.Connection) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc)
    since_30 = (now - timedelta(days=30)).timestamp()
    since_7 = (now - timedelta(days=7)).timestamp()
    sessions = conn.execute(
        "SELECT COUNT(*) AS total, MIN(created_at) AS first_at, MAX(updated_at) AS last_at "
        "FROM sessions"
    ).fetchone()
    days_7 = conn.execute(
        "SELECT COUNT(DISTINCT date(created_at, 'unixepoch')) AS days FROM messages "
        "WHERE role = 'user' AND created_at >= ?",
        (since_7,),
    ).fetchone()
    days_30 = conn.execute(
        "SELECT COUNT(DISTINCT date(created_at, 'unixepoch')) AS days FROM messages "
        "WHERE role = 'user' AND created_at >= ?",
        (since_30,),
    ).fetchone()
    turns = conn.execute(
        "SELECT COUNT(*) AS turns FROM messages WHERE role = 'user' AND created_at >= ?",
        (since_30,),
    ).fetchone()
    by_capability = {
        (row["capability"] or "chat"): int(row["turns"])
        for row in conn.execute(
            "SELECT capability, COUNT(*) AS turns FROM messages "
            "WHERE role = 'user' AND created_at >= ? GROUP BY capability",
            (since_30,),
        )
    }
    stamps_30: dict[str, list[float]] = {}
    for row in conn.execute(
        "SELECT session_id, created_at FROM messages WHERE created_at >= ?", (since_30,)
    ):
        stamps_30.setdefault(row["session_id"], []).append(float(row["created_at"]))
    return {
        "available": True,
        "sessions_total": int(sessions["total"]),
        "first_active_at": _iso(sessions["first_at"]),
        "last_active_at": _iso(sessions["last_at"]),
        "active_days_7": int(days_7["days"]),
        "active_days_30": int(days_30["days"]),
        "turns_30": int(turns["turns"]),
        "minutes_30": _minutes(stamps_30),
        "by_capability_30": by_capability,
        "trend": _trend(conn, now),
    }


def _chat_history(scope: UserScope) -> tuple[dict[str, Any], dict[str, Any]]:
    db_path = get_path_service_for_scope(scope).get_chat_history_db()
    conn = _ro_connect(db_path)
    empty_bank = {"available": False, "total": 0}
    empty_activity = {"available": False, "sessions_total": 0}
    if conn is None:
        return empty_bank, empty_activity
    try:
        return _question_bank(conn), _activity(conn)
    except sqlite3.Error:
        logger.warning("learning evidence: chat history unreadable for %s", scope.user_id)
        return empty_bank, empty_activity
    finally:
        conn.close()


# ── 3. reading ──────────────────────────────────────────────────────────────


def _count_rows(path: Path) -> int:
    rows = _read_json(path)
    return len(rows) if isinstance(rows, list) else 0


def _reading(scope: UserScope) -> dict[str, Any]:
    root = get_path_service_for_scope(scope).get_workspace_feature_dir("reading")
    if not root.is_dir():
        return {"available": False, "materials": []}
    materials: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        manifest = _read_json(child / _READING_MANIFEST) if child.is_dir() else None
        if not isinstance(manifest, dict) or not manifest.get("material_id"):
            continue
        material_id = str(manifest["material_id"])
        position = _read_json(child / "positions" / f"{material_id}.json")
        if not isinstance(position, dict):
            position = _read_json(child / "position.json")
        progress = 0.0
        last_read_at = None
        if isinstance(position, dict):
            try:
                progress = min(1.0, max(0.0, float(position.get("percentage") or 0.0)))
            except (TypeError, ValueError):
                progress = 0.0
            last_read_at = _iso(position.get("updated_at"))
        annotations = _count_rows(child / "annotations" / f"{material_id}.json") or _count_rows(
            child / "annotations.json"
        )
        materials.append(
            {
                "material_id": material_id,
                "title": str(manifest.get("title") or manifest.get("filename") or ""),
                "unit_count": int(manifest.get("unit_count") or 0),
                "progress": round(progress, 3),
                "finished": progress >= 0.99,
                "last_read_at": last_read_at,
                "annotations": annotations,
                "bookmarks": _count_rows(child / "bookmarks" / f"{material_id}.json"),
                "added_at": _iso(manifest.get("created_at")),
            }
        )
    materials.sort(key=lambda item: item["last_read_at"] or "", reverse=True)
    return {"available": True, "materials": materials}


# ── 5. profile ──────────────────────────────────────────────────────────────

_ACCOUNT_PROFILE_FIELDS = (
    "grade_level",
    "curriculum",
    "language",
    "reading_level",
    "explanation_style",
)
_GOAL_PROFILE_FIELDS = ("prior_knowledge", "target_level", "time_budget")


def _profile(record: dict[str, Any], mastery: dict[str, Any], scope: UserScope) -> dict[str, Any]:
    account_raw = record.get("learner_profile")
    account = (
        {key: account_raw[key] for key in _ACCOUNT_PROFILE_FIELDS if account_raw.get(key)}
        if isinstance(account_raw, dict)
        else {}
    )
    goals: list[dict[str, Any]] = []
    if mastery.get("available"):
        conn = _ro_connect(_mastery_db_path(scope))
        if conn is not None:
            try:
                for row in conn.execute("SELECT path_id, state_json FROM mastery_paths"):
                    try:
                        state = json.loads(row["state_json"])
                    except ValueError:
                        continue
                    profile = state.get("learner_profile") if isinstance(state, dict) else None
                    if not isinstance(profile, dict):
                        continue
                    fields = {
                        key: str(profile[key]).strip()
                        for key in _GOAL_PROFILE_FIELDS
                        if str(profile.get(key) or "").strip()
                    }
                    if fields:
                        name = next(
                            (p["name"] for p in mastery["paths"] if p["id"] == row["path_id"]),
                            row["path_id"],
                        )
                        goals.append({"path": name, **fields})
            except sqlite3.Error:
                pass
            finally:
                conn.close()
    return {"account": account or None, "goals": goals}


# ── the record ──────────────────────────────────────────────────────────────


def learning_evidence(user_id: str, record: dict[str, Any]) -> dict[str, Any]:
    """The evidence record for the account *record* with id *user_id*.

    *record* is the account's canonical store record (``identity``); only its
    ``username``-free learning fields are read here. The caller has already
    checked that the reader may see this student.
    """
    from deeptutor.multi_user.teacher_summary import read_summary

    scope = scope_for_user(user_id, is_admin=False)
    mastery = _mastery(scope)
    question_bank, activity = _chat_history(scope)
    return {
        "student": {"id": user_id, "preset": str(record.get("preset") or "standard")},
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "mastery": mastery,
        "question_bank": question_bank,
        "reading": _reading(scope),
        "activity": activity,
        "profile": _profile(record, mastery, scope),
        "summary": read_summary(scope),
    }


__all__ = ["RECENT_DAYS", "SESSION_GAP_SECONDS", "TREND_WEEKS", "learning_evidence"]
