"""Registry of reading material a learning account uploaded for itself.

A learning policy's ``reading.material_ids`` is the *guardian's* allowlist: the
material an administrator staged into the learner workspace. It is written only
by the admin/guardian routes, and a learner must never write to its own grant —
that is the account's own permission record.

But ``reading.allow_upload`` promises the learner may bring their own material,
and an upload the learner cannot then open is not an upload. So learner-owned
uploads are tracked here instead, in a file inside the learner's own reading
workspace, and unioned into the accessible set at read time. Nothing here grants
access to anything outside that workspace: every id in this file names content
that was ingested into the caller's own scope.

The registry is deliberately a new sidecar file rather than a catalog column:
the reading catalog is upstream's schema, and a fork-local concern has no
business migrating it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_FILENAME = "self_uploads.json"


def _registry_path() -> Path:
    from deeptutor.services.path_service import get_path_service

    return get_path_service().get_workspace_feature_dir("reading") / _FILENAME


def self_uploaded_ids() -> set[str]:
    """Material ids the current account uploaded into its own workspace."""
    path = _registry_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    except (OSError, ValueError):
        logger.warning("unreadable learner upload registry at %s", path, exc_info=True)
        return set()
    if not isinstance(raw, list):
        return set()
    return {str(item) for item in raw if isinstance(item, str) and item}


def _write(ids: set[str]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sorted(ids), indent=2), encoding="utf-8")
    tmp.replace(path)


def record_self_upload(*material_ids: str) -> None:
    """Remember that this account owns *material_ids*.

    Best-effort: a registry that cannot be written must not fail the upload the
    learner just completed — it only means the material stays invisible until
    the next successful write, which is strictly better than losing the file.
    """
    wanted = {str(mid) for mid in material_ids if mid}
    if not wanted:
        return
    try:
        current = self_uploaded_ids()
        if wanted <= current:
            return
        _write(current | wanted)
    except OSError:
        logger.warning("could not record learner uploads %s", sorted(wanted), exc_info=True)


def forget_self_upload(*material_ids: str) -> None:
    """Drop *material_ids* from the registry after they are deleted."""
    unwanted = {str(mid) for mid in material_ids if mid}
    if not unwanted:
        return
    try:
        current = self_uploaded_ids()
        if not (current & unwanted):
            return
        _write(current - unwanted)
    except OSError:
        logger.warning("could not forget learner uploads %s", sorted(unwanted), exc_info=True)


__all__ = ["forget_self_upload", "record_self_upload", "self_uploaded_ids"]
