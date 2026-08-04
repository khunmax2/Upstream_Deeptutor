"""Atomic persistence for pet records.

One JSON file (``data/user/pet_state.json``) holding every pet keyed by
``path_id``. Survives a server restart during the demo; trivially resettable.
Single-user demo scope — no locking beyond atomic replace.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile

from pydantic import ValidationError

from deeptutor.pet.models import PetRecord
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


class PetStore:
    """Reads/writes the whole ``{path_id: PetRecord}`` map atomically."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (get_path_service().get_user_root() / "pet_state.json")

    def _load_all(self) -> dict[str, PetRecord]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("pet: unreadable %s; starting fresh", self._path, exc_info=True)
            return {}
        out: dict[str, PetRecord] = {}
        for k, rec in raw.items():
            try:
                out[k] = PetRecord.model_validate(rec)
            except ValidationError:
                # A record from an older schema must not break the whole pet — the
                # store is disposable state, not a correctness input. Drop it; the
                # next read re-creates a fresh pet.
                logger.warning("pet: dropping incompatible record %r", k)
        return out

    def get(self, key: str) -> PetRecord | None:
        return self._load_all().get(key)

    def put(self, record: PetRecord) -> None:
        records = self._load_all()
        records[record.key] = record
        data = {k: rec.model_dump() for k, rec in records.items()}
        _atomic_write_text(self._path, json.dumps(data, ensure_ascii=False, indent=2))

    def reset(self, key: str) -> None:
        records = self._load_all()
        if records.pop(key, None) is not None:
            data = {k: rec.model_dump() for k, rec in records.items()}
            _atomic_write_text(self._path, json.dumps(data, ensure_ascii=False, indent=2))


__all__ = ["PetStore"]
