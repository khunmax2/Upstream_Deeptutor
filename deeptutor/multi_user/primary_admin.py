"""Which admin account owns the deployment workspace at ``data/``.

``admin_scope()`` is a *place*, not a role: the deployment tree that holds the
shared model catalog, personas, skills, knowledge bases, partners and cron, plus
the original operator's own chats. Every admin used to resolve there, with their
user id rewritten to ``local-admin`` — so promoting a second account to admin
handed it the first admin's entire workspace, session history included, and
demoting an admin pointed it at an empty tree instead (HKUDS/DeepTutor#1230 is
the same defect seen from the demotion side).

Privileges have never come from the workspace — they come from ``role`` — so an
admin can own a private workspace and still administer the deployment. Exactly
one account keeps ``data/``: the *primary* admin, recorded here.

The record is deliberately sticky. It is elected once, from the earliest-created
admin in the account store, and then written down; it is not re-derived on later
reads. Re-deriving would mean that deleting or demoting the primary admin
silently moves another admin's workspace out from under them — the failure this
module exists to prevent. If the marker ever names an account that is gone, the
tree at ``data/`` simply keeps waiting for it rather than being handed to
whoever happens to sort first.

Migrating an existing workspace between accounts is a separate, operator-driven
job and is not done here.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import threading
from typing import Any

from .models import LOCAL_ADMIN_ID

logger = logging.getLogger(__name__)

# Identities that are not rows in the account store: the AUTH_ENABLED=false
# local admin and the env-configured bootstrap admin. Both *are* the
# deployment, so both always resolve to ``data/``.
SENTINEL_ADMIN_IDS = frozenset({LOCAL_ADMIN_ID, "env-admin"})

_MARKER_FILENAME = "primary_admin.json"

_lock = threading.Lock()
# Keyed by marker path so a monkey-patched SYSTEM_ROOT (tests, and any
# re-rooted runtime) never reads another root's answer out of the cache.
_cache: dict[str, str] = {}


def _marker_path() -> Path:
    # SYSTEM_ROOT is read per call, not imported once, so a re-rooted deployment
    # and the test fixtures both land on their own file.
    from .paths import SYSTEM_ROOT

    return SYSTEM_ROOT / "auth" / _MARKER_FILENAME


def _read_marker(path: Path) -> str:
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ""
    except (OSError, ValueError):
        logger.warning("unreadable primary-admin marker at %s", path, exc_info=True)
        return ""
    if isinstance(raw, dict):
        return str(raw.get("user_id") or "")
    return ""


def _elect() -> str:
    """The earliest-created admin in the account store, or "" if there is none."""
    from .identity import load_users

    try:
        users = load_users()
    except Exception:  # pragma: no cover - a broken store must not break routing
        logger.warning("could not read the account store to elect a primary admin", exc_info=True)
        return ""
    candidates = [
        (str(record.get("created_at") or ""), str(record.get("id") or ""))
        for record in users.values()
        if isinstance(record, dict) and str(record.get("role") or "user") == "admin"
    ]
    candidates = [item for item in candidates if item[1]]
    if not candidates:
        return ""
    # created_at is an ISO-8601 UTC string, so lexical order is chronological.
    # The id breaks ties so two admins written in the same instant still elect
    # the same one on every host.
    return min(candidates)[1]


def primary_admin_id() -> str:
    """The account id that owns ``data/``. Falls back to the local-admin sentinel."""
    path = _marker_path()
    key = str(path)
    cached = _cache.get(key)
    if cached:
        return cached
    with _lock:
        cached = _cache.get(key)
        if cached:
            return cached
        recorded = _read_marker(path)
        if not recorded:
            recorded = _elect()
            if recorded:
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_suffix(".json.tmp")
                    tmp.write_text(json.dumps({"user_id": recorded}, indent=2), encoding="utf-8")
                    tmp.replace(path)
                except OSError:
                    # Not fatal: the election is deterministic, so an unwritable
                    # marker only means it is recomputed next process.
                    logger.warning("could not record the primary admin at %s", path, exc_info=True)
        if not recorded:
            # No admin in the store yet (a fresh deployment, or auth disabled).
            # Do not cache: the answer changes the moment one is created.
            return LOCAL_ADMIN_ID
        _cache[key] = recorded
        return recorded


def is_primary_admin(user_id: str) -> bool:
    """Whether *user_id* is the admin whose workspace is the deployment tree."""
    candidate = str(user_id or "")
    if not candidate or candidate in SENTINEL_ADMIN_IDS:
        return True
    return candidate == primary_admin_id()


def reset_primary_admin_cache() -> None:
    """Drop the in-process cache. For tests and for re-rooted runtimes."""
    with _lock:
        _cache.clear()


__all__ = [
    "SENTINEL_ADMIN_IDS",
    "is_primary_admin",
    "primary_admin_id",
    "reset_primary_admin_cache",
]
