"""Cheap per-KB content manifest — document titles + main topics + summaries.

Built LAZILY from the text already stored in the index docstore (no re-upload,
no ingest-pipeline change), cached inside the KB's ``metadata.json``. It lets a
router answer "what does this KB contain / is this question even about it?"
WITHOUT a RAG search, and answer whole-corpus ("what documents are there?",
"summarise the KB") questions that top-k RAG handles worst.

New file — fork-additive (fork policy §3). Inert until a caller (the KB-aware
router, a later phase) asks for a manifest; nothing here runs on its own.
See docs/issues/kb-content-routing/PRD.md (Phase 1).
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from typing import Any

from deeptutor.services.rag.index_versioning import list_kb_versions
from deeptutor.services.rag.kb_paths import resolve_kb_dir

logger = logging.getLogger(__name__)

MANIFEST_KEY = "content_manifest"

# Optional dedicated model for manifest generation (same shape as the voice
# classifier's). Unset ⇒ the app's configured chat model (model=None). This is a
# one-time backend summarisation, so a lite tier is ideal but not required.
MODEL_ENV = "DEEPTUTOR_KB_MANIFEST_MODEL"
BASE_URL_ENV = "DEEPTUTOR_KB_MANIFEST_BASE_URL"
API_KEY_ENV = "DEEPTUTOR_KB_MANIFEST_API_KEY"
BINDING_ENV = "DEEPTUTOR_KB_MANIFEST_BINDING"

_PER_DOC_CHAR_BUDGET = 8000  # text sampled per document for one summary call
_SAMPLE_CHUNKS = 20  # spread this many chunks across a document
_MAX_TOPICS = 7

_DOC_PROMPT = """You summarise ONE document from a knowledge base so a router can \
tell what it is about. Reply with ONLY a JSON object:
{"title": "...", "topics": ["...", "..."], "summary": "..."}
- "title": a short human title for the document, in the document's own language.
- "topics": 3-7 short keywords/phrases naming its main subjects, same language.
- "summary": ONE sentence on what the document covers.
Base it ONLY on the excerpt; never invent. Reply with ONLY the JSON object."""

_KB_PROMPT = """Given short per-document summaries of one knowledge base, reply \
with ONLY a JSON object: {"summary": "one sentence describing the whole knowledge \
base"} — in the language the summaries use. Reply with ONLY the JSON object."""


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _default_kb_base_dir() -> str:
    from deeptutor.runtime.home import get_runtime_data_root

    return str(get_runtime_data_root() / "knowledge_bases")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _metadata_path(kb_dir: Path) -> Path:
    return kb_dir / "metadata.json"


def _active_storage_dir(kb_dir: Path) -> Path | None:
    """The newest READY index version's storage folder (holds docstore.json)."""
    for entry in list_kb_versions(kb_dir):
        if entry.get("ready") and entry.get("storage_path"):
            return Path(str(entry["storage_path"]))
    return None


def _docstore_texts(storage_dir: Path) -> dict[str, list[str]]:
    """``{file_name: [chunk text, ...]}`` from a llamaindex ``docstore.json``."""
    doc = _read_json(storage_dir / "docstore.json") or {}
    data = doc.get("docstore/data")
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for node in data.values():
        inner = node.get("__data__", node) if isinstance(node, dict) else {}
        text = str(inner.get("text") or "").strip()
        if not text:
            continue
        meta = inner.get("metadata") if isinstance(inner.get("metadata"), dict) else {}
        fname = str(meta.get("file_name") or "unknown")
        out.setdefault(fname, []).append(text)
    return out


def _sample_text(chunks: list[str], budget: int) -> str:
    """Evenly-spaced chunks up to a char budget — the gist without the whole doc."""
    if not chunks:
        return ""
    step = max(1, len(chunks) // _SAMPLE_CHUNKS)
    picked: list[str] = []
    total = 0
    for i in range(0, len(chunks), step):
        chunk = chunks[i]
        if total + len(chunk) > budget:
            picked.append(chunk[: max(0, budget - total)])
            break
        picked.append(chunk)
        total += len(chunk)
    return "\n---\n".join(picked).strip()


def _signature(metadata: dict[str, Any]) -> str:
    """Stable hash of the KB's document set — the manifest is stale when it moves."""
    file_hashes = metadata.get("file_hashes")
    payload = json.dumps(file_hashes or {}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _llm_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_retries": 1,
    }
    base_url, api_key, binding = _env(BASE_URL_ENV), _env(API_KEY_ENV), _env(BINDING_ENV)
    if base_url:
        kwargs["base_url"] = base_url
    if api_key:
        kwargs["api_key"] = api_key
    if binding:
        kwargs["binding"] = binding
    return kwargs


def _extract_json(raw: str) -> dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", raw or "")
    if match:
        try:
            value = json.loads(match.group(0))
            if isinstance(value, dict):
                return value
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _coerce_topics(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    topics = [str(t).strip() for t in value if str(t).strip()]
    return topics[:_MAX_TOPICS]


async def _summarise_document(file_name: str, text: str) -> dict[str, Any]:
    """One LLM call → ``{file, title, topics, summary}`` (never raises)."""
    fallback = {"file": file_name, "title": file_name, "topics": [], "summary": ""}
    if not text:
        return fallback
    try:
        from deeptutor.services.llm import complete

        raw = await complete(
            f"[{file_name}]\n\n{text}",
            system_prompt=_DOC_PROMPT,
            model=_env(MODEL_ENV) or None,
            **_llm_kwargs(),
        )
    except Exception:  # noqa: BLE001 — a summary failure must not break ingest/routing
        logger.warning("kb manifest: doc summary failed for %r", file_name, exc_info=True)
        return fallback
    data = _extract_json(raw)
    return {
        "file": file_name,
        "title": str(data.get("title") or file_name).strip(),
        "topics": _coerce_topics(data.get("topics")),
        "summary": str(data.get("summary") or "").strip(),
    }


async def _summarise_kb(documents: list[dict[str, Any]]) -> str:
    """One sentence over the per-doc summaries (never raises; may be empty)."""
    lines = [
        f"- {d.get('title') or d.get('file')}: {d.get('summary') or ''}".strip() for d in documents
    ]
    if not lines:
        return ""
    try:
        from deeptutor.services.llm import complete

        raw = await complete(
            "\n".join(lines),
            system_prompt=_KB_PROMPT,
            model=_env(MODEL_ENV) or None,
            **_llm_kwargs(),
        )
    except Exception:  # noqa: BLE001
        logger.warning("kb manifest: kb summary failed", exc_info=True)
        return ""
    return str(_extract_json(raw).get("summary") or "").strip()


async def build_manifest(
    kb_name: str, kb_base_dir: str | None = None, *, signature: str | None = None
) -> dict[str, Any] | None:
    """Summarise every document in ``kb_name`` from its docstore. ``None`` when
    there is no ready index or no text to read. Does NOT write to disk — see
    :func:`get_or_build_manifest`."""
    kb_dir = resolve_kb_dir(kb_base_dir or _default_kb_base_dir(), kb_name)
    storage = _active_storage_dir(kb_dir)
    if storage is None:
        logger.info("kb manifest: no ready index for %r", kb_name)
        return None
    texts = _docstore_texts(storage)
    if not texts:
        logger.info("kb manifest: no docstore text for %r", kb_name)
        return None

    documents: list[dict[str, Any]] = []
    for file_name in sorted(texts):
        documents.append(
            await _summarise_document(
                file_name, _sample_text(texts[file_name], _PER_DOC_CHAR_BUDGET)
            )
        )

    if signature is None:
        signature = _signature(_read_json(_metadata_path(kb_dir)) or {})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": _env(MODEL_ENV) or "app-default",
        "signature": signature,
        "summary": await _summarise_kb(documents),
        "documents": documents,
    }


async def get_or_build_manifest(
    kb_name: str, kb_base_dir: str | None = None, *, force: bool = False
) -> dict[str, Any] | None:
    """Return the cached manifest if fresh, else build it and cache it into the
    KB's ``metadata.json``. Freshness is keyed on the document set (``file_hashes``);
    a changed KB rebuilds. Returns the stale cache if a rebuild yields nothing."""
    kb_dir = resolve_kb_dir(kb_base_dir or _default_kb_base_dir(), kb_name)
    metadata = _read_json(_metadata_path(kb_dir)) or {}
    signature = _signature(metadata)
    cached = metadata.get(MANIFEST_KEY)
    if not force and isinstance(cached, dict) and cached.get("signature") == signature:
        return cached

    manifest = await build_manifest(kb_name, kb_base_dir, signature=signature)
    if manifest is None:
        return cached if isinstance(cached, dict) else None

    metadata[MANIFEST_KEY] = manifest
    try:
        _write_json(_metadata_path(kb_dir), metadata)
    except OSError:
        logger.warning(
            "kb manifest: could not cache to metadata.json for %r", kb_name, exc_info=True
        )
    return manifest


__all__ = ["build_manifest", "get_or_build_manifest", "MANIFEST_KEY"]
