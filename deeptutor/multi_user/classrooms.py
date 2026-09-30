"""Fork: classrooms (school roles design, Phase 3a).

A classroom is a named group of `teacher` accounts and `student` accounts,
with a home-room teacher and a set of class defaults. It is **not** an
authorization path: the guardian record stays the only thing the evidence
routes check. A classroom is a bulk editor of those records --

* after every membership change, :func:`sync_links` makes sure a guardian
  link (``view_reports``, ``assign_materials``) exists for every
  teacher x student pair of every active classroom, and revokes the links
  *this module created* whose pair no classroom justifies any more;
* a link an admin made by hand on the users page is never created or
  revoked here: the module knows its own links by id (``derived_links`` in
  the store), so nothing in ``guardians.py`` changes.

Class defaults (parent design, decision 9) are a grant fragment -- models,
knowledge bases, skills -- **merged into** a student's grant when they join
the class. A starting point, not a lock: the student's grant stays editable
on the users page, and leaving the class takes nothing away.

The store is ``data/system/school/classrooms.json``, one JSON document
with a write lock and atomic writes, like ``guardians.json`` beside it.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4

from deeptutor.services.file_io import atomic_write_text

from . import paths
from .guardians import authorize_guardian, list_relationships, revoke_guardian
from .identity import get_user_by_id

DERIVED_PERMISSIONS = ("assign_materials", "view_reports")
DEFAULT_GRANT_KEYS = ("models", "knowledge_bases", "skills")
TEACHER_PRESET = "teacher"
STUDENT_PRESET = "student"
_MAX_NAME = 80

_WRITE_LOCK = threading.RLock()


class ClassroomError(ValueError):
    """A classroom write that the rules refuse; the message is for the admin."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── the store ───────────────────────────────────────────────────────────────


def _canonical_defaults(value: Any) -> dict[str, Any]:
    """Keep only the grant keys a class may set, in the grant's own shape."""
    if not isinstance(value, dict):
        return {}
    grant = value.get("grant") if isinstance(value.get("grant"), dict) else {}
    out: dict[str, Any] = {}
    models = grant.get("models") if isinstance(grant.get("models"), dict) else {}
    llm = models.get("llm") if isinstance(models, dict) else None
    if isinstance(llm, list):
        items = [dict(item) for item in llm if isinstance(item, dict)]
        if items:
            out["models"] = {"llm": items}
    for key in ("knowledge_bases", "skills"):
        raw = grant.get(key)
        if isinstance(raw, list):
            items = [dict(item) for item in raw if isinstance(item, dict)]
            if items:
                out[key] = items
    return {"grant": out} if out else {}


def _canonical_classroom(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    classroom_id = str(value.get("id") or "")
    name = str(value.get("name") or "").strip()
    if not classroom_id or not name:
        return None

    def ids(key: str) -> list[str]:
        raw = value.get(key)
        seen: list[str] = []
        for item in raw if isinstance(raw, list) else []:
            text = str(item or "")
            if text and text not in seen:
                seen.append(text)
        return seen

    archived_at = value.get("archived_at")
    return {
        "id": classroom_id,
        "name": name[:_MAX_NAME],
        "term": str(value.get("term") or "").strip()[:_MAX_NAME],
        "home_room_teacher_id": str(value.get("home_room_teacher_id") or ""),
        "teacher_ids": ids("teacher_ids"),
        "student_ids": ids("student_ids"),
        "defaults": _canonical_defaults(value.get("defaults")),
        "created_at": str(value.get("created_at") or _utc_now()),
        "updated_at": str(value.get("updated_at") or value.get("created_at") or _utc_now()),
        "archived_at": str(archived_at) if archived_at else None,
    }


def classrooms_file() -> Path:
    # Resolved on every call, like the guardian store's path is patched per
    # test: the system root is a module attribute tests redirect under tmp.
    return paths.SYSTEM_ROOT / "school" / "classrooms.json"


def _load() -> dict[str, Any]:
    try:
        loaded = json.loads(classrooms_file().read_text(encoding="utf-8"))
    except Exception:
        loaded = {}
    if not isinstance(loaded, dict):
        loaded = {}
    classrooms: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in loaded.get("classrooms") or []:
        record = _canonical_classroom(value)
        if record is None or record["id"] in seen:
            continue
        seen.add(record["id"])
        classrooms.append(record)
    raw_links = loaded.get("derived_links")
    derived = (
        {str(k): str(v) for k, v in raw_links.items() if k and v}
        if isinstance(raw_links, dict)
        else {}
    )
    return {"classrooms": classrooms, "derived_links": derived}


def _write(store: dict[str, Any]) -> None:
    path = classrooms_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(store, indent=2, ensure_ascii=False))


# ── validation ──────────────────────────────────────────────────────────────


def _require_preset(user_id: str, preset: str, label: str) -> dict[str, Any]:
    found = get_user_by_id(user_id)
    if found is None:
        raise ClassroomError(f"Unknown {label} user id: {user_id}")
    _username, record = found
    if str(record.get("role") or "user") == "admin":
        raise ClassroomError(f"Admin accounts cannot be classroom {label}s.")
    if str(record.get("preset") or "standard") != preset:
        raise ClassroomError(f"A classroom {label} must be a {preset} account: {user_id}")
    if record.get("deleted_at"):
        raise ClassroomError(f"This {label} account is in the bin: {user_id}")
    return record


def _validate_members(teacher_ids: list[str], student_ids: list[str], home_room: str) -> None:
    for teacher_id in teacher_ids:
        _require_preset(teacher_id, TEACHER_PRESET, "teacher")
    for student_id in student_ids:
        _require_preset(student_id, STUDENT_PRESET, "student")
    if home_room and home_room not in teacher_ids:
        raise ClassroomError("The home-room teacher must be one of the classroom's teachers.")


def _dedupe(values: Any) -> list[str]:
    out: list[str] = []
    for item in values or []:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _name_taken(store: dict[str, Any], name: str, *, excluding: str | None = None) -> bool:
    lowered = name.strip().lower()
    return any(
        record["name"].lower() == lowered
        and record["archived_at"] is None
        and record["id"] != excluding
        for record in store["classrooms"]
    )


# ── reads ───────────────────────────────────────────────────────────────────


def list_classrooms(
    *, include_archived: bool = False, teacher_user_id: str | None = None
) -> list[dict[str, Any]]:
    return [
        deepcopy(record)
        for record in _load()["classrooms"]
        if (include_archived or record["archived_at"] is None)
        and (teacher_user_id is None or teacher_user_id in record["teacher_ids"])
    ]


def get_classroom(classroom_id: str) -> dict[str, Any] | None:
    for record in _load()["classrooms"]:
        if record["id"] == classroom_id:
            return deepcopy(record)
    return None


def classroom_by_name(name: str) -> dict[str, Any] | None:
    lowered = name.strip().lower()
    for record in _load()["classrooms"]:
        if record["archived_at"] is None and record["name"].lower() == lowered:
            return deepcopy(record)
    return None


def classrooms_for_student(student_id: str) -> list[dict[str, Any]]:
    return [
        deepcopy(record)
        for record in _load()["classrooms"]
        if record["archived_at"] is None and student_id in record["student_ids"]
    ]


# ── writes ──────────────────────────────────────────────────────────────────


def create_classroom(
    name: str,
    *,
    term: str = "",
    home_room_teacher_id: str = "",
    teacher_ids: list[str] | None = None,
    student_ids: list[str] | None = None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    name = str(name or "").strip()
    if not name or len(name) > _MAX_NAME:
        raise ClassroomError(f"A classroom name is 1-{_MAX_NAME} characters.")
    teachers = _dedupe(teacher_ids)
    students = _dedupe(student_ids)
    home_room = str(home_room_teacher_id or "").strip()
    _validate_members(teachers, students, home_room)
    with _WRITE_LOCK:
        store = _load()
        if _name_taken(store, name):
            raise ClassroomError("A classroom with this name already exists.")
        now = _utc_now()
        record = {
            "id": f"cls_{uuid4().hex}",
            "name": name,
            "term": str(term or "").strip()[:_MAX_NAME],
            "home_room_teacher_id": home_room,
            "teacher_ids": teachers,
            "student_ids": students,
            "defaults": _canonical_defaults(defaults),
            "created_at": now,
            "updated_at": now,
            "archived_at": None,
        }
        store["classrooms"].append(record)
        _write(store)
        for student_id in students:
            apply_defaults(record, student_id)
        sync_links(store)
    return deepcopy(record)


def update_classroom(
    classroom_id: str,
    *,
    name: str | None = None,
    term: str | None = None,
    home_room_teacher_id: str | None = None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _WRITE_LOCK:
        store = _load()
        record = _find(store, classroom_id)
        if name is not None:
            text = str(name).strip()
            if not text or len(text) > _MAX_NAME:
                raise ClassroomError(f"A classroom name is 1-{_MAX_NAME} characters.")
            if _name_taken(store, text, excluding=classroom_id):
                raise ClassroomError("A classroom with this name already exists.")
            record["name"] = text
        if term is not None:
            record["term"] = str(term).strip()[:_MAX_NAME]
        if home_room_teacher_id is not None:
            home_room = str(home_room_teacher_id).strip()
            if home_room and home_room not in record["teacher_ids"]:
                raise ClassroomError(
                    "The home-room teacher must be one of the classroom's teachers."
                )
            record["home_room_teacher_id"] = home_room
        if defaults is not None:
            record["defaults"] = _canonical_defaults(defaults)
        record["updated_at"] = _utc_now()
        _write(store)
        return deepcopy(record)


def set_teachers(
    classroom_id: str, teacher_ids: list[str]
) -> tuple[dict[str, Any], dict[str, int]]:
    teachers = _dedupe(teacher_ids)
    for teacher_id in teachers:
        _require_preset(teacher_id, TEACHER_PRESET, "teacher")
    with _WRITE_LOCK:
        store = _load()
        record = _find(store, classroom_id)
        before = set(record["teacher_ids"])
        record["teacher_ids"] = teachers
        if record["home_room_teacher_id"] not in teachers:
            record["home_room_teacher_id"] = ""
        record["updated_at"] = _utc_now()
        _write(store)
        links = sync_links(store)
        after = set(teachers)
        return deepcopy(record), {
            "added": len(after - before),
            "removed": len(before - after),
            **links,
        }


def set_students(
    classroom_id: str, student_ids: list[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    students = _dedupe(student_ids)
    for student_id in students:
        _require_preset(student_id, STUDENT_PRESET, "student")
    with _WRITE_LOCK:
        store = _load()
        record = _find(store, classroom_id)
        before = set(record["student_ids"])
        record["student_ids"] = students
        record["updated_at"] = _utc_now()
        _write(store)
        added = [student_id for student_id in students if student_id not in before]
        for student_id in added:
            apply_defaults(record, student_id)
        links = sync_links(store)
        return deepcopy(record), {
            "added": len(added),
            "removed": len(before - set(students)),
            **links,
        }


def add_students(
    classroom_id: str, student_ids: list[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Add without removing -- what the CSV import needs."""
    current = get_classroom(classroom_id)
    if current is None:
        raise ClassroomError(f"Unknown classroom: {classroom_id}")
    return set_students(classroom_id, [*current["student_ids"], *_dedupe(student_ids)])


def archive_classroom(classroom_id: str) -> dict[str, Any]:
    with _WRITE_LOCK:
        store = _load()
        record = _find(store, classroom_id)
        if record["archived_at"] is None:
            record["archived_at"] = _utc_now()
            record["updated_at"] = record["archived_at"]
            _write(store)
            sync_links(store)
        return deepcopy(record)


def _find(store: dict[str, Any], classroom_id: str) -> dict[str, Any]:
    for record in store["classrooms"]:
        if record["id"] == classroom_id:
            return record
    raise ClassroomError(f"Unknown classroom: {classroom_id}")


# ── the derived guardian links ──────────────────────────────────────────────


def _pair(teacher_id: str, student_id: str) -> str:
    return f"{teacher_id}:{student_id}"


def desired_pairs(store: dict[str, Any] | None = None) -> set[str]:
    """Every teacher x student pair an active classroom justifies."""
    store = store if store is not None else _load()
    pairs: set[str] = set()
    for record in store["classrooms"]:
        if record["archived_at"] is not None:
            continue
        for teacher_id in record["teacher_ids"]:
            for student_id in record["student_ids"]:
                pairs.add(_pair(teacher_id, student_id))
    return pairs


def sync_links(store: dict[str, Any] | None = None) -> dict[str, int]:
    """Create the missing derived links and revoke the stale ones.

    A pair that already has an *active* link -- hand-made or derived -- gets
    nothing new. A derived link whose pair no classroom justifies is
    revoked with reason ``classroom``; a hand-made link is never touched,
    because only ids this module wrote are in ``derived_links``.
    """
    with _WRITE_LOCK:
        store = store if store is not None else _load()
        active = {
            _pair(record["guardian_user_id"], record["learner_user_id"]): record["id"]
            for record in list_relationships()
        }
        desired = desired_pairs(store)
        derived: dict[str, str] = store["derived_links"]
        created = revoked = 0
        for pair in sorted(desired):
            if pair in active:
                continue
            teacher_id, student_id = pair.split(":", 1)
            try:
                record = authorize_guardian(teacher_id, student_id, list(DERIVED_PERMISSIONS))
            except ValueError:
                # A preset changed under us (a student promoted, a teacher
                # demoted): the link is refused, and that is right.
                continue
            derived[pair] = record["id"]
            active[pair] = record["id"]
            created += 1
        for pair, link_id in list(derived.items()):
            if pair in desired and active.get(pair) == link_id:
                continue
            if pair not in desired and active.get(pair) == link_id:
                revoke_guardian(link_id, revoked_by="system", reason="classroom")
                revoked += 1
            # Either revoked now, revoked by hand, or superseded: forget it.
            derived.pop(pair, None)
        _write(store)
        return {"links_created": created, "links_revoked": revoked}


# ── class defaults ──────────────────────────────────────────────────────────


def _merge_items(
    current: list[dict[str, Any]], extra: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    seen = {json.dumps(item, sort_keys=True) for item in current}
    out = list(current)
    for item in extra:
        key = json.dumps(item, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _merge_llm(current: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Grant llm items are one per profile (``{profile_id, model_ids}``); the
    users page finds a profile by its first item, so merge by profile and
    union the model ids instead of appending a second item."""
    out = [dict(item) for item in current]
    by_profile = {str(item.get("profile_id") or ""): item for item in out}
    for item in extra:
        profile_id = str(item.get("profile_id") or "")
        if not profile_id:
            continue
        existing = by_profile.get(profile_id)
        if existing is None:
            added = dict(item)
            added.setdefault("source", "admin")
            out.append(added)
            by_profile[profile_id] = added
            continue
        wanted = [str(m) for m in item.get("model_ids") or []]
        have = [str(m) for m in existing.get("model_ids") or []]
        existing["model_ids"] = have + [m for m in wanted if m not in have]
    return out


def apply_defaults(classroom: dict[str, Any], student_id: str) -> bool:
    """Merge the class defaults into *student_id*'s grant. True when it changed."""
    from .grants import load_grant, save_grant

    defaults = (classroom.get("defaults") or {}).get("grant") or {}
    if not defaults:
        return False
    grant = load_grant(student_id)
    changed = False
    llm = (defaults.get("models") or {}).get("llm") or []
    if llm:
        merged = _merge_llm(grant["models"]["llm"], llm)
        if merged != grant["models"]["llm"]:
            grant["models"]["llm"] = merged
            changed = True
    for key in ("knowledge_bases", "skills"):
        extra = defaults.get(key) or []
        if extra:
            merged = _merge_items(grant[key], extra)
            if merged != grant[key]:
                grant[key] = merged
                changed = True
    if changed:
        save_grant(student_id, grant)
    return changed


__all__ = [
    "classrooms_file",
    "DERIVED_PERMISSIONS",
    "ClassroomError",
    "add_students",
    "apply_defaults",
    "archive_classroom",
    "classroom_by_name",
    "classrooms_for_student",
    "create_classroom",
    "desired_pairs",
    "get_classroom",
    "list_classrooms",
    "set_students",
    "set_teachers",
    "sync_links",
    "update_classroom",
]
