"""Fork: the roster's summary row and its alerts (school roles design, Phase 3b).

A teacher's roster shows one line per student, not the whole evidence
record, so :func:`summary_row` reduces a record from
:mod:`learning_evidence` to the columns of design §2.2, and
:func:`alerts_for` adds the plain-rule nudges of §2.4. No model, no
weights: five thresholds in one place, so the pilot can tune them.

An alert is a reason to look, never a grade. The roster sorts by how many
a student has; nothing is sent anywhere.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# The thresholds (design §2.4). Days are calendar days; counts are as the
# evidence record reports them.
INACTIVE_DAYS = 7
STRUGGLING_MIN_QUESTIONS = 10
STRUGGLING_ACCURACY = 0.5
BACKLOG_UNRESOLVED = 10
REVIEWS_DUE = 5
READING_STALLED_DAYS = 14

ALERTS: tuple[str, ...] = ("inactive", "struggling", "backlog", "reviews_due", "reading_stalled")


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _days_since(value: Any, now: datetime) -> int | None:
    parsed = _parse(value)
    if parsed is None:
        return None
    return max(0, (now - parsed).days)


def alerts_for(evidence: dict[str, Any], *, now: datetime | None = None) -> list[str]:
    """The alerts a record raises, in :data:`ALERTS` order."""
    now = now or datetime.now(tz=timezone.utc)
    out: list[str] = []
    activity = evidence.get("activity") or {}
    bank = evidence.get("question_bank") or {}
    recent = bank.get("recent") or {}
    mastery = evidence.get("mastery") or {}
    reading = evidence.get("reading") or {}

    since_active = _days_since(activity.get("last_active_at"), now)
    if since_active is None or since_active >= INACTIVE_DAYS:
        out.append("inactive")

    recent_total = int(recent.get("total") or 0)
    if recent_total >= STRUGGLING_MIN_QUESTIONS:
        accuracy = int(recent.get("correct") or 0) / recent_total
        if accuracy < STRUGGLING_ACCURACY:
            out.append("struggling")

    if int(bank.get("unresolved") or 0) >= BACKLOG_UNRESOLVED:
        out.append("backlog")

    if sum(int(p.get("due_reviews") or 0) for p in mastery.get("paths") or []) >= REVIEWS_DUE:
        out.append("reviews_due")

    for material in reading.get("materials") or []:
        progress = float(material.get("progress") or 0.0)
        if progress <= 0.0 or material.get("finished"):
            continue
        since_read = _days_since(material.get("last_read_at"), now)
        if since_read is not None and since_read >= READING_STALLED_DAYS:
            out.append("reading_stalled")
            break
    return out


# ── the good news ───────────────────────────────────────────────────────────

SPOTLIGHTS: tuple[str, ...] = (
    "mastered_recently",
    "reading_finished",
    "accuracy_up",
    "steady",
    "back",
)
STEADY_DAYS = 4  # active on at least this many of the last 7 days
ACCURACY_UP_MIN_QUESTIONS = 5
ACCURACY_UP_POINTS = 0.10


def spotlights_for(evidence: dict[str, Any], *, now: datetime | None = None) -> list[str]:
    """The positive counterparts of :func:`alerts_for`, from the same record.

    A roster that only lists problems teaches a teacher to open it only when
    something is wrong (Teams' green spotlights, IXL's "celebrate"). Rules,
    in :data:`SPOTLIGHTS` order: an objective mastered this week; a material
    finished this week; accuracy this week at least 10 points over the four
    weeks before (with at least 5 questions); active on 4 of the last 7
    days; back after a week or more away."""
    now = now or datetime.now(tz=timezone.utc)
    out: list[str] = []
    mastery = evidence.get("mastery") or {}
    reading = evidence.get("reading") or {}
    activity = evidence.get("activity") or {}
    trend = activity.get("trend") or []

    if any(p.get("mastered_recently") for p in mastery.get("paths") or []):
        out.append("mastered_recently")

    for material in reading.get("materials") or []:
        since = _days_since(material.get("last_read_at"), now)
        if material.get("finished") and since is not None and since < 7:
            out.append("reading_finished")
            break

    if len(trend) >= 2:
        this_week = trend[-1]
        before = trend[-5:-1]
        q_now = int(this_week.get("questions") or 0)
        q_before = sum(int(w.get("questions") or 0) for w in before)
        if q_now >= ACCURACY_UP_MIN_QUESTIONS and q_before >= ACCURACY_UP_MIN_QUESTIONS:
            acc_now = int(this_week.get("correct") or 0) / q_now
            acc_before = sum(int(w.get("correct") or 0) for w in before) / q_before
            if acc_now - acc_before >= ACCURACY_UP_POINTS:
                out.append("accuracy_up")

    if int(activity.get("active_days_7") or 0) >= STEADY_DAYS:
        out.append("steady")

    if len(trend) >= 3:
        this_week, last_week, week_before = trend[-1], trend[-2], trend[-3]
        if (
            int(this_week.get("turns") or 0) > 0
            and int(last_week.get("turns") or 0) == 0
            and int(week_before.get("turns") or 0) == 0
        ):
            out.append("back")
    return out


def summary_row(evidence: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """One roster line: the columns of design §2.2 plus the alerts."""
    activity = evidence.get("activity") or {}
    bank = evidence.get("question_bank") or {}
    recent = bank.get("recent") or {}
    mastery = evidence.get("mastery") or {}
    reading = evidence.get("reading") or {}
    summary = evidence.get("summary") or {}
    paths = mastery.get("paths") or []
    materials = reading.get("materials") or []
    recent_total = int(recent.get("total") or 0)
    recent_correct = int(recent.get("correct") or 0)
    mastered = sum(int((p.get("counts") or {}).get("mastered") or 0) for p in paths)
    objectives = sum(int((p.get("counts") or {}).get("total") or 0) for p in paths)
    return {
        "student": dict(evidence.get("student") or {}),
        "last_active_at": activity.get("last_active_at"),
        "active_days_30": int(activity.get("active_days_30") or 0),
        "turns_30": int(activity.get("turns_30") or 0),
        "minutes_30": float(activity.get("minutes_30") or 0.0),
        "questions_30": recent_total,
        "correct_30": recent_correct,
        "accuracy_30": round(recent_correct / recent_total, 3) if recent_total else None,
        "unresolved": int(bank.get("unresolved") or 0),
        "mastered": mastered,
        "objectives": objectives,
        "paths": len(paths),
        "reviews_due": sum(int(p.get("due_reviews") or 0) for p in paths),
        "reading_started": sum(1 for m in materials if float(m.get("progress") or 0) > 0),
        "reading_finished": sum(1 for m in materials if m.get("finished")),
        "summary_at": summary.get("generated_at") if summary.get("available") else None,
        "alerts": alerts_for(evidence, now=now),
        "spotlights": spotlights_for(evidence, now=now),
    }


def _median(values: list[float]) -> float | None:
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else round((values[mid - 1] + values[mid]) / 2, 3)


def class_comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """What a student's page shows beside their own numbers: the class median
    of accuracy, active days and minutes over 30 days, from the roster's rows."""
    return {
        "students": len(rows),
        "accuracy_30": _median([r["accuracy_30"] for r in rows if r["accuracy_30"] is not None]),
        "active_days_30": _median([float(r["active_days_30"]) for r in rows]),
        "minutes_30": _median([float(r.get("minutes_30") or 0.0) for r in rows]),
    }


def class_totals(
    rows: list[dict[str, Any]],
    records: list[dict[str, Any]] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The class in numbers (design §3), from the rows already computed.

    *records* are the full evidence records behind the rows; they add the
    three wrong-answer categories most shared across the class."""
    now = now or datetime.now(tz=timezone.utc)
    wrong_by_category: dict[str, int] = {}
    for record in records or []:
        for category in (record.get("question_bank") or {}).get("categories") or []:
            name = str(category.get("name") or "")
            if name:
                wrong_by_category[name] = wrong_by_category.get(name, 0) + int(
                    category.get("wrong") or 0
                )
    top_wrong = sorted(
        ((name, wrong) for name, wrong in wrong_by_category.items() if wrong > 0),
        key=lambda item: (-item[1], item[0]),
    )[:3]
    week = now - timedelta(days=7)
    month = now - timedelta(days=30)
    median = _median([r["accuracy_30"] for r in rows if r["accuracy_30"] is not None])
    alert_counts = {name: 0 for name in ALERTS}
    spotlight_counts = {name: 0 for name in SPOTLIGHTS}
    for row in rows:
        for name in row["alerts"]:
            alert_counts[name] += 1
        for name in row.get("spotlights") or []:
            spotlight_counts[name] += 1
    return {
        "students": len(rows),
        "active_7": sum(1 for r in rows if (_parse(r["last_active_at"]) or week) > week),
        "active_30": sum(1 for r in rows if (_parse(r["last_active_at"]) or month) > month),
        "median_accuracy_30": median,
        "below_half": sum(
            1
            for r in rows
            if r["accuracy_30"] is not None and r["accuracy_30"] < STRUGGLING_ACCURACY
        ),
        "reviews_due": sum(r["reviews_due"] for r in rows),
        "reading_finished": sum(r["reading_finished"] for r in rows),
        "minutes_30": round(sum(float(r.get("minutes_30") or 0.0) for r in rows), 1),
        "alerts": alert_counts,
        "spotlights": spotlight_counts,
        "top_wrong_categories": [{"name": name, "wrong": wrong} for name, wrong in top_wrong],
    }


__all__ = [
    "ALERTS",
    "SPOTLIGHTS",
    "alerts_for",
    "class_comparison",
    "class_totals",
    "spotlights_for",
    "summary_row",
]
