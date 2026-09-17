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
one account keeps ``data/``: the *primary* admin, recorded here. It is also the
deployment's superadmin: no other admin may demote or delete it (decided
2026-09-15, see docs/planning/admin-roles/).

The record is deliberately sticky. It is elected once and then written down; it
is not re-derived on later reads. The election prefers the ``auth.json``
bootstrap account when that account is usable (a username *and* a password
hash), because that account is the deployment's first admin; otherwise it takes
the earliest-created admin in the account store. Re-deriving would mean that
deleting or demoting the primary admin — or adding a bootstrap password later —
silently moves another admin's workspace out from under them, the failure this
module exists to prevent. If the marker ever names an account that is gone, the
tree at ``data/`` simply keeps waiting for it rather than being handed to
whoever happens to sort first.

The owner changes only through an explicit, audited handover run on the server::

    python -m deeptutor.multi_user.primary_admin show
    python -m deeptutor.multi_user.primary_admin handover <username | env-admin>

``data/`` stays where it is and belongs to the new owner from then on; the
previous owner works in ``data/users/<id>/`` and what it made inside ``data/``
stays there. Migrating content between the two trees is a separate,
operator-driven job and is not done here.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
import threading
from typing import Any

from .models import LOCAL_ADMIN_ID

logger = logging.getLogger(__name__)

# The in-memory id of the ``auth.json`` bootstrap account (identity.py builds
# its record with this id; it is never a row in the account store).
ENV_ADMIN_ID = "env-admin"

# Identities that are not rows in the account store: the AUTH_ENABLED=false
# local admin and the env-configured bootstrap admin. Only ``local-admin``
# always owns ``data/``; the bootstrap admin owns it when it is the recorded
# owner, like any other admin.
SENTINEL_ADMIN_IDS = frozenset({LOCAL_ADMIN_ID, ENV_ADMIN_ID})

_MARKER_FILENAME = "primary_admin.json"

_lock = threading.Lock()
# Keyed by marker path so a monkey-patched SYSTEM_ROOT (tests, and any
# re-rooted runtime) never reads another root's answer out of the cache.
_cache: dict[str, str] = {}
# Marker paths for which the "bootstrap admin is not the owner" warning has
# been logged, so a busy server says it once.
_warned: set[str] = set()


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


def _write_marker(path: Path, user_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"user_id": user_id}, indent=2), encoding="utf-8")
    tmp.replace(path)


def bootstrap_admin() -> tuple[str, str]:
    """``(username, password_hash)`` of a *usable* bootstrap admin, else ``("", "")``."""
    from .identity import _env_bootstrap_admin

    return _env_bootstrap_admin()


def _elect() -> str:
    """The account to record when nothing is recorded yet, or "" if there is none.

    A usable bootstrap admin is the deployment's first admin, so it wins.
    Otherwise the earliest-created admin in the account store.
    """
    if bootstrap_admin()[0]:
        return ENV_ADMIN_ID
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


def _warn_if_bootstrap_is_not_the_owner(key: str, recorded: str) -> None:
    if recorded == ENV_ADMIN_ID or key in _warned:
        return
    username = bootstrap_admin()[0]
    if not username:
        return
    _warned.add(key)
    logger.warning(
        "The bootstrap admin '%s' does not own data/ (the recorded primary admin is %s). "
        "If it should, run: python -m deeptutor.multi_user.primary_admin handover %s",
        username,
        recorded,
        username,
    )


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
                    _write_marker(path, recorded)
                except OSError:
                    # Not fatal: the election is deterministic, so an unwritable
                    # marker only means it is recomputed next process.
                    logger.warning("could not record the primary admin at %s", path, exc_info=True)
        if not recorded:
            # No admin in the store yet (a fresh deployment, or auth disabled).
            # Do not cache: the answer changes the moment one is created.
            return LOCAL_ADMIN_ID
        _cache[key] = recorded
        _warn_if_bootstrap_is_not_the_owner(key, recorded)
        return recorded


def is_primary_admin(user_id: str) -> bool:
    """Whether *user_id* is the admin whose workspace is the deployment tree."""
    candidate = str(user_id or "")
    if not candidate or candidate == LOCAL_ADMIN_ID:
        return True
    return candidate == primary_admin_id()


def is_primary_admin_account(user_id: str) -> bool:
    """Whether *user_id* names the account no other admin may demote or delete.

    The primary admin is the deployment's superadmin (decided 2026-09-15).
    Unlike :func:`is_primary_admin`, an empty id answers False: a route that
    finds no account must say "not found", not "protected".
    """
    return bool(user_id) and is_primary_admin(user_id)


def owns_deployment_workspace(user: Any) -> bool:
    """Whether *user*'s workspace is the deployment tree (``data/``).

    Upstream asks ``user.is_admin`` wherever it means this, because there every
    admin *is* the deployment tree. With this module only the primary admin (and
    the local sentinel) is; an admin promoted later has a workspace of its own,
    and anything it owns — knowledge bases included — lives there.
    """
    scope = getattr(user, "scope", None)
    return getattr(scope, "kind", "") == "admin"


def reads_deployment_presets(user: Any) -> bool:
    """Whether *user* reads the deployment's shared presets instead of owning them.

    Upstream asks ``not user.is_admin`` here, because there every admin *is* the
    deployment tree. With this module only the primary admin is; every other
    account — ordinary users and admins promoted later alike — works in its own
    workspace and gets the deployment's presets (personas) read-only. Anything
    such an account writes still lands in its own workspace.
    """
    return not owns_deployment_workspace(user)


def reset_primary_admin_cache() -> None:
    """Drop the in-process cache. For tests and for re-rooted runtimes."""
    with _lock:
        _cache.clear()
        _warned.clear()


# ---------------------------------------------------------------------------
# The handover: the one way the owner changes
# ---------------------------------------------------------------------------


def _describe(user_id: str) -> str:
    """``<id> (<username>)`` for a message, from the store or the bootstrap config."""
    if user_id == ENV_ADMIN_ID:
        username = bootstrap_admin()[0]
        return f"{user_id} ({username or 'bootstrap admin, not usable'})"
    if user_id == LOCAL_ADMIN_ID:
        return f"{user_id} (auth disabled)"
    from .identity import get_user_by_id

    found = get_user_by_id(user_id)
    return f"{user_id} ({found[0]})" if found else f"{user_id} (no such account)"


def _resolve_handover_target(target: str) -> str:
    """The account id *target* names, or raise ``ValueError`` saying why not."""
    from .identity import get_user_by_id, load_users

    wanted = str(target or "").strip()
    if not wanted:
        raise ValueError("no account given")
    bootstrap_username = bootstrap_admin()[0]
    if wanted == ENV_ADMIN_ID or (bootstrap_username and wanted == bootstrap_username):
        if not bootstrap_username:
            raise ValueError(
                "the bootstrap admin in auth.json has no password hash, so nobody can sign in as it"
            )
        return ENV_ADMIN_ID
    record = load_users().get(wanted)
    if record is None:
        by_id = get_user_by_id(wanted)
        record = by_id[1] if by_id else None
    if record is None:
        raise ValueError(f"no account named {wanted!r}")
    if str(record.get("role") or "user") != "admin":
        raise ValueError(f"{wanted!r} is not an admin; promote it first")
    user_id = str(record.get("id") or "")
    if not user_id:
        raise ValueError(f"{wanted!r} has no account id")
    return user_id


def handover(target: str) -> tuple[str, str]:
    """Make *target* the owner of ``data/``. Returns ``(previous, new)``.

    Raises ``ValueError`` when *target* is not an admin or not usable. A
    handover to the current owner changes nothing and records nothing.
    """
    new_owner = _resolve_handover_target(target)
    previous = primary_admin_id()
    if new_owner == previous:
        return previous, previous
    path = _marker_path()
    with _lock:
        _write_marker(path, new_owner)
        _cache[str(path)] = new_owner
        _warned.discard(str(path))
    from .audit import log_operator_action

    log_operator_action(
        "primary_handover",
        target_user_id=new_owner,
        summary={"from": previous, "to": new_owner},
    )
    logger.warning("The primary admin changed from %s to %s (handover)", previous, new_owner)
    return previous, new_owner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m deeptutor.multi_user.primary_admin",
        description="Show or hand over the account that owns the deployment workspace (data/).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("show", help="print the current owner")
    move = commands.add_parser("handover", help="make another admin the owner")
    move.add_argument("account", help="a username, an account id, or env-admin")
    args = parser.parse_args(argv)

    if args.command == "show":
        owner = primary_admin_id()
        print(f"primary admin: {_describe(owner)}")
        username = bootstrap_admin()[0]
        print(
            f"bootstrap admin (auth.json): {username!r} usable"
            if username
            else "bootstrap admin (auth.json): none usable"
        )
        return 0

    try:
        previous, new_owner = handover(args.account)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if previous == new_owner:
        print(f"unchanged: {_describe(new_owner)} already owns data/")
        return 0
    print(f"primary admin: {_describe(previous)} -> {_describe(new_owner)}")
    print("data/ now belongs to the new owner; what the previous owner made there stays there.")
    print(f"The previous owner works in data/users/{previous}/ from now on.")
    print("Restart the server so every worker reads the new owner.")
    return 0


__all__ = [
    "ENV_ADMIN_ID",
    "SENTINEL_ADMIN_IDS",
    "bootstrap_admin",
    "handover",
    "is_primary_admin",
    "is_primary_admin_account",
    "main",
    "owns_deployment_workspace",
    "primary_admin_id",
    "reads_deployment_presets",
    "reset_primary_admin_cache",
]


if __name__ == "__main__":  # pragma: no cover - the entry point
    raise SystemExit(main())
