"""Fork: ``teacher.md`` -- the one memory document a teacher may read.

School roles design, Phase 2, section 5. A student's Memory has three layers
and a teacher may see none of them directly: L1 is the transcript, L2 and L3
mix learning evidence with the student's identity, preferences and the
things they talked about. This module writes a fifth document, from the
allowed sections only, with a prompt that forbids personal facts and
produces no footnotes:

* L2, allowed sections: all of ``quiz``; ``chat`` Mastery and
  Misconceptions; ``book`` Pacing and Sticking points. Not ``chat`` Topics,
  not ``kb``, ``notebook``, ``cowriter`` or ``partner``.
* L3, allowed: ``scope`` whole; ``profile`` Learning style and Knowledge
  level. Not Identity, not ``preferences``, not ``recent``.

The document lives at ``memory/school/teacher.md`` -- outside ``L2/`` and
``L3/`` on purpose. It is not an :data:`~deeptutor.services.memory.paths.L3_SLOTS`
entry, so the student's Memory page does not list it, the ``read_memory``
tool does not inject it, the owner-only memory API does not serve it and a
memory backup does not carry it. The only reader is the guardian evidence
route (:mod:`learning_evidence`), which requires ``view_reports`` and writes
an audit line.

The input to the model is the *allowed text only*; the model never sees the
rest of a document, so nothing it is told not to repeat is there to repeat.
Section names are matched in both prompt languages (en / zh), because the
consolidator forces every entry into one of the names in its ``_meta.yaml``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any

from deeptutor.multi_user.models import UserScope
from deeptutor.multi_user.paths import get_path_service_for_scope

logger = logging.getLogger(__name__)

SCHOOL_DIR = "school"
SUMMARY_NAME = "teacher.md"
META_NAME = "teacher.meta.json"
_TITLE = "Learning summary for the teacher"
_MAX_ITEM_CHARS = 240
_MAX_ITEMS_PER_SECTION = 8

# What the summary is allowed to draw from, by document and section. Names
# in both prompt languages; the consolidator writes exactly these.
ALLOWED_L2: dict[str, frozenset[str]] = {
    "quiz": frozenset(
        {"Error patterns", "Strong topics", "Struggling topics", "错误模式", "强项", "弱项"}
    ),
    "chat": frozenset({"Mastery", "Misconceptions", "掌握", "误解"}),
    "book": frozenset({"Pacing", "Sticking points", "节奏", "卡点"}),
}
ALLOWED_L3: dict[str, frozenset[str] | None] = {
    "scope": None,  # whole document
    "profile": frozenset({"Learning style", "Knowledge level", "学习风格", "知识水平"}),
}

# The summary's own sections, fixed so the dashboard can rely on them.
SECTIONS: tuple[str, ...] = (
    "Strengths",
    "Working on",
    "Learning style",
    "Suggested next steps",
)

SYSTEM_PROMPT = """You write a short learning summary of one student for their teacher.

You are given excerpts from the student's tutoring memory. The excerpts are
already limited to learning evidence: quiz patterns, mastered and
misunderstood concepts, reading pace and sticking points, learning style,
knowledge level and the concepts the student is working on.

OUTPUT: Markdown only, exactly these four sections, in this order, each a
list of bullets ("- "). A section may be empty.

## Strengths
## Working on
## Learning style
## Suggested next steps

HARD RULES
- Only what the excerpts support. No guesses about the student as a person.
- Never state or hint at anything personal: no name, age, family, health,
  feelings, friends, home, opinions, what the student said, or which topics
  they talked about outside the subject. If an excerpt contains such a
  thing, leave it out.
- Bullets are about learning: a concept, a skill, a pattern in errors, a
  pace, a habit that helps or hinders learning, a concrete next step the
  teacher can take.
- Each bullet at most 200 characters. At most 6 bullets per section.
- No footnotes, no citations, no headings other than the four above.
- Hedge counts and claims ("recent quizzes show", "across several sessions").
- Banned absolutes: always, never, expert, mastered completely, loves, hates.
"""

USER_PROMPT = """# Student: {user_label}
# Today: {today}

{excerpts}

Write the summary now. Markdown only, the four sections, bullets only."""


# ── paths and reading ───────────────────────────────────────────────────────


def summary_dir(scope: UserScope) -> Path:
    return get_path_service_for_scope(scope).get_memory_dir() / SCHOOL_DIR


def summary_path(scope: UserScope) -> Path:
    return summary_dir(scope) / SUMMARY_NAME


def meta_path(scope: UserScope) -> Path:
    return summary_dir(scope) / META_NAME


def read_meta(scope: UserScope) -> dict[str, Any]:
    try:
        data = json.loads(meta_path(scope).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def read_summary(scope: UserScope) -> dict[str, Any]:
    """The summary as the evidence record carries it: sections of plain text."""
    from deeptutor.services.memory.document import parse

    path = summary_path(scope)
    if not path.is_file():
        return {"available": False, "generated_at": None, "sections": []}
    try:
        doc = parse(path.read_text(encoding="utf-8"))
    except OSError:
        return {"available": False, "generated_at": None, "sections": []}
    meta = read_meta(scope)
    return {
        "available": True,
        "generated_at": meta.get("generated_at"),
        "language": meta.get("language"),
        "sections": [
            {"title": section, "items": [entry.text for entry in entries]}
            for section, entries in doc.sections
            if entries
        ],
    }


# ── the allowed input ───────────────────────────────────────────────────────


def _memory_file(scope: UserScope, layer: str, key: str) -> Path:
    return get_path_service_for_scope(scope).get_memory_dir() / layer / f"{key}.md"


def _allowed_entries(path: Path, allowed: frozenset[str] | None) -> list[tuple[str, list[str]]]:
    """``(section, [text, ...])`` for the allowed sections of one document."""
    from deeptutor.services.memory.document import parse

    if not path.is_file():
        return []
    try:
        doc = parse(path.read_text(encoding="utf-8"))
    except OSError:
        return []
    out: list[tuple[str, list[str]]] = []
    for section, entries in doc.sections:
        if allowed is not None and section not in allowed:
            continue
        texts = [entry.text.strip() for entry in entries if entry.text.strip()]
        if texts:
            out.append((section, texts))
    return out


def allowed_input(scope: UserScope) -> tuple[str, dict[str, float]]:
    """The excerpt text the model sees, and the mtimes of the files it came from.

    The excerpt carries only allowed sections; the mtimes are what
    :func:`needs_refresh` compares against the last run.
    """
    blocks: list[str] = []
    sources: dict[str, float] = {}
    for layer, table in (("L2", ALLOWED_L2), ("L3", ALLOWED_L3)):
        for key, allowed in table.items():
            path = _memory_file(scope, layer, key)
            entries = _allowed_entries(path, allowed)
            if not entries:
                continue
            sources[f"{layer}/{key}"] = path.stat().st_mtime
            lines = [f"## {layer} {key}"]
            for section, texts in entries:
                lines.append(f"### {section}")
                lines.extend(f"- {text}" for text in texts)
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks), sources


def needs_refresh(scope: UserScope) -> bool:
    """Whether an allowed source changed since the last summary was written."""
    _text, sources = allowed_input(scope)
    if not sources:
        return False
    seen = read_meta(scope).get("sources")
    if not isinstance(seen, dict):
        return True
    return any(seen.get(name) != mtime for name, mtime in sources.items())


# ── the model's answer ──────────────────────────────────────────────────────

_SECTION_RE = re.compile(r"^\s*#{1,3}\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^\s*[-*•]\s+(.+?)\s*$")
_FOOTNOTE_RE = re.compile(r"\s*\[\^[^\]]*\]")
_PERSONAL_HINTS = ("[^", "<!--")


def parse_response(raw: str) -> dict[str, list[str]]:
    """The four sections from the model's markdown; anything else is dropped.

    Bullets outside a known section go nowhere. Footnote markers are
    stripped, over-long bullets are cut, and a section keeps at most
    :data:`_MAX_ITEMS_PER_SECTION` bullets.
    """
    from deeptutor.services.memory.consolidator.guards import _has_banned

    lowered = {name.lower(): name for name in SECTIONS}
    sections: dict[str, list[str]] = {name: [] for name in SECTIONS}
    current: str | None = None
    for line in (raw or "").splitlines():
        heading = _SECTION_RE.match(line)
        if heading:
            current = lowered.get(heading.group(1).strip().strip(":").lower())
            continue
        bullet = _BULLET_RE.match(line)
        if not bullet or current is None:
            continue
        text = _FOOTNOTE_RE.sub("", bullet.group(1)).strip()
        if not text or any(hint in text for hint in _PERSONAL_HINTS) or _has_banned(text):
            continue
        if len(sections[current]) >= _MAX_ITEMS_PER_SECTION:
            continue
        sections[current].append(text[:_MAX_ITEM_CHARS])
    return sections


def _write(
    scope: UserScope,
    sections: dict[str, list[str]],
    *,
    language: str,
    sources: dict[str, float],
    model: str | None,
) -> None:
    from deeptutor.services.file_io import atomic_write_text
    from deeptutor.services.memory.document import Document, Entry, serialize
    from deeptutor.services.memory.ids import new_entry_id

    doc = Document(title=_TITLE)
    for name in SECTIONS:
        entries = doc.section_entries(name)
        entries.extend(Entry(id=new_entry_id(), section=name, text=text) for text in sections[name])
    directory = summary_dir(scope)
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write_text(summary_path(scope), serialize(doc))
    atomic_write_text(
        meta_path(scope),
        json.dumps(
            {
                "generated_at": datetime.now(tz=timezone.utc).isoformat(),
                "language": language,
                "model": model,
                "sources": sources,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


async def generate_summary(
    scope: UserScope,
    *,
    language: str = "en",
    user_label: str = "student",
    force: bool = False,
) -> dict[str, Any]:
    """Write ``teacher.md`` for *scope* from the allowed input, with one LLM call.

    Returns ``{"status": ..., "sections": {...}}`` where status is one of
    ``written``, ``unchanged`` (nothing new since the last run), ``no_input``
    (the student has no allowed memory yet) or ``failed`` (the model returned
    nothing; the previous summary, if any, is kept).

    The model is the deployment default (``get_llm_config`` is not
    per-account): the school pays for its teachers' summaries, not the
    student, whether a teacher asked for it or the nightly run did.
    """
    from deeptutor.services.memory.consolidator.modes._runtime import call_llm, today_iso

    excerpts, sources = allowed_input(scope)
    if not sources:
        return {"status": "no_input", "sections": {}}
    if not force and not needs_refresh(scope):
        return {"status": "unchanged", "sections": {}}
    raw = await call_llm(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=USER_PROMPT.format(user_label=user_label, today=today_iso(), excerpts=excerpts),
        temperature=0.2,
        max_tokens=1200,
        label="teacher_summary",
        language=language,
    )
    sections = parse_response(raw)
    if not raw or not any(sections.values()):
        logger.warning("teacher summary: empty answer for %s; previous summary kept", scope.user_id)
        return {"status": "failed", "sections": {}}
    model = None
    try:
        from deeptutor.services.llm import get_llm_config

        model = get_llm_config().model or None
    except Exception:  # noqa: BLE001 - the label is informational
        model = None
    _write(scope, sections, language=language, sources=sources, model=model)
    return {"status": "written", "sections": sections}


__all__ = [
    "ALLOWED_L2",
    "ALLOWED_L3",
    "SECTIONS",
    "allowed_input",
    "generate_summary",
    "needs_refresh",
    "parse_response",
    "read_summary",
    "summary_path",
]
