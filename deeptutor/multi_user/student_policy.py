"""Fork: what a `student` account cannot do (school roles design, Phase 1).

A student is the full product -- every learning surface, Memory, Co-Writer,
own knowledge bases, persona choice -- with **no learning policy**, so
upstream treats it as an ordinary user everywhere. Only three groups are
closed, and not because a student should not have them but because they
are not the student's to hold (design decision 4):

1. **own settings writes** -- personal providers and keys, tools, MCP,
   capabilities, agent configuration: the school's models and cost, and the
   dashboard compares students only when they use the same ones;
2. **partners, MCP connections and code execution** -- channels out of the
   deployment and processes on its host;
3. the admin sections, which `require_admin` already closes.

The rule lives here, in one table, and is applied once: `refuse_closed`
rides beside `require_learning_surface` in the app's shared `_auth`
dependency list, so every router that carries it is covered without a
change of its own. Reads stay open, so the pages render read-only; a
refused write answers 403 with a sentence that says why, and is audited.

Everything that is not in the table is untouched. That is the point of
the design: the tutor's personalisation works exactly as for any user.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

STUDENT_PRESET = "student"

WRITES = frozenset({"POST", "PUT", "PATCH", "DELETE"})
ALL = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"})

# (path prefix, methods closed, what the refusal says)
CLOSED: tuple[tuple[str, frozenset[str], str], ...] = (
    ("/api/settings", WRITES, "settings are managed by the school"),
    ("/api/capabilities", WRITES, "capabilities are managed by the school"),
    ("/api/tools", WRITES, "tools are managed by the school"),
    ("/api/agent-config", WRITES, "agent configuration is managed by the school"),
    ("/api/space/mcp", ALL, "MCP connections are not available to a student account"),
    ("/api/space/cli-apps", ALL, "code execution is not available to a student account"),
    ("/api/partners", WRITES, "partners are managed by the school"),
    ("/api/partner-groups", WRITES, "partners are managed by the school"),
)

# Under a closed prefix, the student's own account still works: the profile,
# the UI preferences and the learner profile are theirs.
OPEN_UNDER_CLOSED: tuple[str, ...] = (
    "/api/settings/ui",
    "/api/settings/workspace",
)


def closed_reason(path: str, method: str) -> str | None:
    """Why *method* *path* is closed to a student, or None when it is open."""
    normalized = "/" + str(path or "").lstrip("/")
    verb = str(method or "GET").upper()
    for prefix in OPEN_UNDER_CLOSED:
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return None
    for prefix, methods, reason in CLOSED:
        if verb in methods and (normalized == prefix or normalized.startswith(prefix + "/")):
            return reason
    return None


def is_student(user: Any) -> bool:
    """Whether the current account is a student, read from the store.

    ``CurrentUser.preset`` is not filled on the request path -- upstream builds
    the object from the token, which carries no preset -- so the answer comes
    from the account record. Callers check the path first, so this read
    happens only for a request that would be refused anyway.
    """
    if user is None or str(getattr(user, "role", "") or "") != "user":
        return False
    from .identity import get_user_by_id

    found = get_user_by_id(str(getattr(user, "id", "") or ""))
    return bool(found) and str(found[1].get("preset") or "") == STUDENT_PRESET


async def refuse_closed(request: Request) -> None:
    """FastAPI dependency: 403 when a student account calls a closed route.

    Runs after ``require_auth`` has set the current user (it is listed after
    ``require_learning_surface`` in ``_auth``). The path is checked before
    the account is, so every open request costs one string comparison.
    """
    reason = closed_reason(request.url.path, request.method)
    if reason is None:
        return
    from .context import get_current_user

    user = get_current_user()
    if not is_student(user):
        return
    from .audit import log_admin_action

    log_admin_action(
        "student_write_refused",
        target_user_id=str(user.id),
        summary={"method": request.method, "path": request.url.path},
    )
    logger.warning(
        "Student account '%s' called %s %s; refused: %s",
        user.username,
        request.method,
        request.url.path,
        reason,
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"This is a student account: {reason}",
    )


__all__ = ["CLOSED", "STUDENT_PRESET", "closed_reason", "is_student", "refuse_closed"]
