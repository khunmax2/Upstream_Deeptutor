"""Layer-2 KB router — does a CHAT turn need the knowledge base, and how?

Runs only after the intent classifier (layer 1) says ``chat`` and only when
``DEEPTUTOR_VOICE_KB_ROUTING`` is on. Given the utterance and the KB content
manifest (see :mod:`deeptutor.services.rag.content_manifest`), it decides:

- ``meta``      — a question ABOUT the collection ("what documents are there?",
                  "summarise the KB"). Answered from the manifest, no RAG.
- ``content``   — a question about something INSIDE the documents. Needs RAG.
- ``unrelated`` — not about the KB at all. Answered as plain chat, RAG suppressed.

Vanilla top-k RAG fires on every chat turn and answers ``meta``/``unrelated``
worst; this cheap manifest-based gate makes RAG run only when it helps.

New file — fork-additive (fork policy §3). Inert unless the flag is on; on
failure it returns ``None`` so the caller keeps today's behaviour (RAG on).
See docs/issues/kb-content-routing/PRD.md (Phase 3).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Literal

logger = logging.getLogger(__name__)

FLAG_ENV = "DEEPTUTOR_VOICE_KB_ROUTING"
# Reuse the manifest model config (a lite tier is plenty for this easy decision).
MODEL_ENV = "DEEPTUTOR_KB_MANIFEST_MODEL"
BASE_URL_ENV = "DEEPTUTOR_KB_MANIFEST_BASE_URL"
API_KEY_ENV = "DEEPTUTOR_KB_MANIFEST_API_KEY"
BINDING_ENV = "DEEPTUTOR_KB_MANIFEST_BINDING"

Route = Literal["meta", "content", "unrelated"]

_MAX_TOPICS_IN_CATALOGUE = 8

# NOTE: kept free of ``str.format`` — the JSON braces below would be read as
# format fields. The catalogue is appended by ``_with_catalogue`` instead.
_ROUTE_PROMPT = """A user is talking to DeepTutor. Given ONLY what the knowledge \
base(s) contain (the catalogue that follows), decide how to handle their message. \
Reply with ONLY a JSON object: {"route":"meta"} or {"route":"content"} or \
{"route":"unrelated"}.

- "meta" = they ask ABOUT the collection itself: which documents exist, what the
  knowledge base is about, an overview/summary of the whole thing.
- "content" = they ask about something INSIDE the documents — a specific fact,
  section, definition, or detail that would need a search to answer.
- "unrelated" = their message is not about this knowledge base at all (general
  chat, greetings, other topics)."""

_META_PROMPT = """Answer the user's question about their knowledge base using ONLY \
the catalogue that follows — do not invent anything. Reply in the user's language \
(Thai if they write Thai), in one or two short spoken sentences. If they ask which \
documents exist, name the document titles. If they ask what it is about, give the \
overview."""


def _with_catalogue(prompt: str, catalogue: str) -> str:
    return f"{prompt}\n\nKNOWLEDGE BASE CATALOGUE:\n{catalogue}"


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def kb_routing_enabled() -> bool:
    """On only when explicitly switched on. Off ⇒ the chat turn behaves exactly
    as today (RAG auto-mounts and the model decides)."""
    return _env(FLAG_ENV).lower() in {"1", "true", "yes"}


async def load_manifests(
    kb_names: list[str], kb_base_dir: str | None = None
) -> list[dict[str, Any]]:
    """Get-or-build each KB's manifest and tag it with ``kb_name``. Lazy: a KB
    without a cached manifest is built here (a one-time cost). Never raises."""
    from deeptutor.services.rag import content_manifest

    out: list[dict[str, Any]] = []
    for name in kb_names:
        try:
            manifest = await content_manifest.get_or_build_manifest(name, kb_base_dir)
        except Exception:  # noqa: BLE001 — a bad KB must not break the turn
            logger.warning("voice kb-route: manifest load failed for %r", name, exc_info=True)
            manifest = None
        if isinstance(manifest, dict):
            out.append({**manifest, "kb_name": name})
    return out


def _catalogue(manifests: list[dict[str, Any]]) -> str:
    """Compact, router-readable summary of the manifests (small — fed per turn)."""
    blocks: list[str] = []
    for manifest in manifests:
        if not isinstance(manifest, dict):
            continue
        name = str(manifest.get("kb_name") or "").strip()
        header = f"KB '{name}':" if name else "KB:"
        summary = str(manifest.get("summary") or "").strip()
        lines = [f"{header} {summary}".rstrip()]
        for doc in manifest.get("documents") or []:
            if not isinstance(doc, dict):
                continue
            title = str(doc.get("title") or doc.get("file") or "").strip()
            topics = [str(t).strip() for t in (doc.get("topics") or []) if str(t).strip()]
            topics = topics[:_MAX_TOPICS_IN_CATALOGUE]
            detail = f" — {', '.join(topics)}" if topics else ""
            lines.append(f"  • {title}{detail}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks).strip()


def has_content(manifests: list[dict[str, Any]]) -> bool:
    """True when at least one manifest carries a document — else there is nothing
    to route against and the caller should keep today's behaviour."""
    return any(isinstance(m, dict) and (m.get("documents") or m.get("summary")) for m in manifests)


def _llm_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {"temperature": 0, "max_retries": 1}
    base_url, api_key, binding = _env(BASE_URL_ENV), _env(API_KEY_ENV), _env(BINDING_ENV)
    if base_url:
        kwargs["base_url"] = base_url
    if api_key:
        kwargs["api_key"] = api_key
    if binding:
        kwargs["binding"] = binding
    return kwargs


def _parse_route(raw: str) -> Route:
    """Explicit ``meta``/``unrelated`` are honoured; anything else biases to
    ``content`` — running RAG and letting it find nothing beats a manifest-only
    answer to a real content question."""
    value = ""
    match = re.search(r"\{[\s\S]*\}", raw or "")
    if match:
        try:
            value = str(json.loads(match.group(0)).get("route", "")).lower().strip()
        except (json.JSONDecodeError, ValueError, AttributeError):
            value = ""
    if not value:
        value = (raw or "").strip().lower()
    if value == "meta":
        return "meta"
    if value == "unrelated":
        return "unrelated"
    return "content"


async def route(transcript: str, manifests: list[dict[str, Any]]) -> Route | None:
    """Return ``meta`` / ``content`` / ``unrelated``, or ``None`` when routing is
    off, there is nothing to route against, or the call failed (caller keeps
    today's RAG-on behaviour). Never raises."""
    if not kb_routing_enabled() or not transcript.strip() or not has_content(manifests):
        return None
    catalogue = _catalogue(manifests)
    if not catalogue:
        return None
    try:
        from deeptutor.services.llm import complete

        raw = await complete(
            transcript,
            system_prompt=_with_catalogue(_ROUTE_PROMPT, catalogue),
            model=_env(MODEL_ENV) or None,
            response_format={"type": "json_object"},
            **_llm_kwargs(),
        )
    except Exception:  # noqa: BLE001 — a routing failure must not break the turn
        logger.warning("voice kb-route failed; keeping RAG-on default", exc_info=True)
        return None
    result = _parse_route(raw)
    logger.info("voice kb-route=%s %r", result, transcript[:60])
    return result


async def compose_meta_answer(transcript: str, manifests: list[dict[str, Any]]) -> str | None:
    """Answer a ``meta`` question straight from the manifest (no RAG). ``None`` on
    failure so the caller can fall back to a normal content turn."""
    catalogue = _catalogue(manifests)
    if not catalogue:
        return None
    try:
        from deeptutor.services.llm import complete

        raw = await complete(
            transcript,
            system_prompt=_with_catalogue(_META_PROMPT, catalogue),
            model=_env(MODEL_ENV) or None,
            **_llm_kwargs(),
        )
    except Exception:  # noqa: BLE001
        logger.warning("voice kb-route: meta answer failed", exc_info=True)
        return None
    answer = (raw or "").strip()
    return answer or None


__all__ = [
    "kb_routing_enabled",
    "load_manifests",
    "route",
    "compose_meta_answer",
    "has_content",
    "Route",
]
