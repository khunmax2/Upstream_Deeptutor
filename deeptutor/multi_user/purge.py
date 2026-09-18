"""Fork: what DeepWitya keeps for one account, and how a purge removes it.

Admin design §4, Phase 2 (2026-09-18). An account leaves in two steps: the
bin (``identity.set_deleted``; the record stays, the name stays taken,
everything it owns stays) and, from the bin only, the purge. This module is
the purge's data half. The account record itself, its guardian links and its
avatar go through ``identity.delete_user`` as before; what this adds is the
rest, which the shallow delete used to strand:

- the workspace ``data/users/<id>/`` (chats, notebooks, knowledge bases,
  settings)
- the grant ``data/system/grants/<id>.json``
- the secrets ``data/system/user-secrets/<id>/``
- the MCP file ``data/system/user-mcp/<id>.json``
- the device-credential records

Every location is named here so :func:`account_footprint` can show what a
purge will remove, and :func:`orphan_ids` can find ids that still have data
but no account -- the two the host stranded before the bin existed.

The deployment tree ``data/`` itself, its sentinel owners (``local-admin``,
``env-admin``) and the primary admin are never purgeable: a purge that could
reach them would be the most expensive typo the users page can make.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
from pathlib import Path
import re
import shutil
from typing import Any

from . import paths

logger = logging.getLogger(__name__)

# The ids ``identity.new_user_id`` mints: ``u_`` + 32 hex characters. Nothing
# else is a purgeable account id, whatever else the record store may hold.
_ACCOUNT_ID_RE = re.compile(r"^u_[0-9a-f]{32}$")


@dataclass
class AccountFootprint:
    """What a purge of *user_id* would remove on this side."""

    user_id: str
    workspace_files: int = 0
    workspace_bytes: int = 0
    grant: bool = False
    secrets_files: int = 0
    mcp_config: bool = False
    device_credentials: int = 0
    guardian_links: int = 0
    avatar: bool = False
    locations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_purgeable_account_id(user_id: str) -> bool:
    """Whether *user_id* is an id a purge may act on at all."""
    from .primary_admin import SENTINEL_ADMIN_IDS, is_primary_admin_account

    if not user_id or user_id in SENTINEL_ADMIN_IDS or not _ACCOUNT_ID_RE.match(user_id):
        return False
    return not is_primary_admin_account(user_id)


# The roots are read from ``paths`` per call, not bound at import: the test
# fixture and DEEPTUTOR_HOME both re-point them after this module loads.
def _workspace_dir(user_id: str) -> Path:
    return paths.USERS_ROOT / user_id


def _grant_file(user_id: str) -> Path:
    return paths.SYSTEM_ROOT / "grants" / f"{user_id}.json"


def _secrets_dir(user_id: str) -> Path:
    return paths.SYSTEM_ROOT / paths.USER_SECRETS_DIRNAME / user_id


def _mcp_file(user_id: str) -> Path:
    return paths.SYSTEM_ROOT / "user-mcp" / f"{user_id}.json"


def _tree_size(root: Path) -> tuple[int, int]:
    files = 0
    size = 0
    if not root.is_dir():
        return files, size
    for path in root.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                files += 1
                size += path.stat().st_size
        except OSError:
            continue
    return files, size


def _device_credential_count(user_id: str) -> int:
    from .device_credentials import _load_records

    return sum(1 for record in _load_records() if record.get("user_id") == user_id)


def _guardian_link_count(user_id: str) -> int:
    from .guardians import list_relationships

    return len(list_relationships(guardian_user_id=user_id)) + len(
        list_relationships(learner_user_id=user_id)
    )


def account_footprint(user_id: str) -> AccountFootprint:
    """The sizes a purge would report, without removing anything."""
    from .identity import get_avatar_file

    footprint = AccountFootprint(user_id=user_id)
    workspace = _workspace_dir(user_id)
    footprint.workspace_files, footprint.workspace_bytes = _tree_size(workspace)
    if workspace.is_dir():
        footprint.locations.append(str(workspace))
    if _grant_file(user_id).is_file():
        footprint.grant = True
        footprint.locations.append(str(_grant_file(user_id)))
    secrets = _secrets_dir(user_id)
    if secrets.is_dir():
        footprint.secrets_files, _ = _tree_size(secrets)
        footprint.locations.append(str(secrets))
    if _mcp_file(user_id).is_file():
        footprint.mcp_config = True
        footprint.locations.append(str(_mcp_file(user_id)))
    footprint.device_credentials = _device_credential_count(user_id)
    footprint.guardian_links = _guardian_link_count(user_id)
    footprint.avatar = get_avatar_file(user_id) is not None
    return footprint


def _remove_tree(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def purge_account_data(user_id: str) -> AccountFootprint:
    """Remove everything :func:`account_footprint` lists, and say what went.

    Refuses (``ValueError``) an id that :func:`is_purgeable_account_id` does
    not accept, so no caller can reach ``data/`` through it. The record,
    guardian links and avatar are the caller's (``identity.delete_user`` and
    ``delete_avatar_file``), because an orphan has none of those.
    """
    if not is_purgeable_account_id(user_id):
        raise ValueError(f"not a purgeable account id: {user_id!r}")
    from .device_credentials import remove_device_credentials_for_user

    removed = account_footprint(user_id)
    removed.device_credentials = remove_device_credentials_for_user(user_id)
    for path in (_grant_file(user_id), _secrets_dir(user_id), _mcp_file(user_id)):
        _remove_tree(path)
    _remove_tree(_workspace_dir(user_id))
    logger.warning(
        "Purged account data of %s: workspace files=%d bytes=%d grant=%s secrets files=%d "
        "mcp=%s device credentials=%d",
        user_id,
        removed.workspace_files,
        removed.workspace_bytes,
        removed.grant,
        removed.secrets_files,
        removed.mcp_config,
        removed.device_credentials,
    )
    return removed


def orphan_ids() -> list[str]:
    """Ids that hold a workspace, a grant, a secrets folder or an MCP file but
    have no account record -- neither live nor in the bin. Sentinels, the
    primary admin and anything that is not an account id are left out."""
    from .identity import load_users

    known = {str(record.get("id") or "") for record in load_users().values()}
    found: set[str] = set()
    for root in (paths.USERS_ROOT, paths.SYSTEM_ROOT / paths.USER_SECRETS_DIRNAME):
        if root.is_dir():
            found.update(child.name for child in root.iterdir() if child.is_dir())
    for root in (paths.SYSTEM_ROOT / "grants", paths.SYSTEM_ROOT / "user-mcp"):
        if root.is_dir():
            found.update(child.stem for child in root.iterdir() if child.suffix == ".json")
    return sorted(
        user_id for user_id in found if user_id not in known and is_purgeable_account_id(user_id)
    )


__all__ = [
    "AccountFootprint",
    "account_footprint",
    "is_purgeable_account_id",
    "orphan_ids",
    "purge_account_data",
]
