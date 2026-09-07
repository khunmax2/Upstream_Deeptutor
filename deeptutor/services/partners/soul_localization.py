"""Serve the soul-template library in the interface language.

Fork addition (khunmax2/Upstream_Deeptutor).

Upstream seeds ``_souls.yaml`` once from ``DEFAULT_SOUL_TEMPLATES`` and never
revisits it, so a Thai interface kept showing five English souls forever. The
seed is *content*, not a label, so ``locales/th/app.json`` cannot reach it.

The approach here mirrors upstream's own ``_refresh_stale_default_souls``:
rewrite a seeded entry only while it is still **provably untouched** — its
content matches a shipped template in one of the languages we know — and pass
every user-authored or user-edited soul through verbatim. That makes the
language switch reversible and lossless: flip the interface to Thai and the
untouched five follow; edit one and it is yours in whatever language you left
it.

Both callers live on the read path (``_load_souls``), so no hook into the
settings endpoint is needed and no upstream write path changes.

The English templates are passed in rather than imported: ``manager`` imports
this module, so importing ``manager`` back would be a cycle.
"""

from __future__ import annotations

from typing import Any

from deeptutor.services.i18n import current_language
from deeptutor.services.partners.soul_templates_th import DEFAULT_SOUL_TEMPLATES_TH

# Only languages with a complete translated set belong here. A language absent
# from this map falls back to the English seed, which is the correct outcome —
# a half-translated soul is a worse prompt than an English one.
_TRANSLATIONS: dict[str, tuple[dict[str, str], ...]] = {
    "th": DEFAULT_SOUL_TEMPLATES_TH,
}


def _resolve(language: str | None) -> str:
    if language is not None:
        return str(language).strip().lower()[:2]
    try:
        return current_language()
    except Exception:  # settings unreadable — English is the safe default
        return "en"


def localized_soul_templates(
    english: tuple[dict[str, str], ...],
    *,
    language: str | None = None,
) -> tuple[dict[str, str], ...]:
    """The default templates in the interface language, English if untranslated."""
    translated = _TRANSLATIONS.get(_resolve(language))
    if not translated:
        return english
    by_id = {str(entry.get("id") or ""): entry for entry in translated}
    return tuple(dict(by_id.get(str(entry.get("id") or ""), entry)) for entry in english)


def _known_seed_contents(
    english: tuple[dict[str, str], ...],
) -> dict[str, set[str]]:
    """For each seed id, every shipped body across all languages."""
    contents: dict[str, set[str]] = {}
    for group in (english, *_TRANSLATIONS.values()):
        for entry in group:
            sid = str(entry.get("id") or "")
            if sid:
                contents.setdefault(sid, set()).add(str(entry.get("content") or "").strip())
    return contents


def relocalize_seed_souls(
    souls: list[dict[str, Any]],
    english: tuple[dict[str, str], ...],
    *,
    language: str | None = None,
) -> list[dict[str, Any]] | None:
    """Swap untouched seeds to the interface language; ``None`` if unchanged.

    Returning ``None`` for "nothing to do" matches the contract of upstream's
    ``_refresh_stale_default_souls`` so both can sit on the same read path
    without either one writing the file needlessly.
    """
    wanted = {
        str(entry.get("id") or ""): entry
        for entry in localized_soul_templates(english, language=language)
    }
    if not wanted:
        return None

    known = _known_seed_contents(english)
    out: list[dict[str, Any]] = []
    changed = False

    for entry in souls:
        sid = str(entry.get("id") or "")
        target = wanted.get(sid)
        current = str(entry.get("content") or "").strip()
        # Untouched means: still byte-identical to something we shipped for this
        # id. A user edit — in any language — fails this and is left alone.
        if target is None or current not in known.get(sid, set()):
            out.append(entry)
            continue
        if current == str(target.get("content") or "").strip():
            out.append(entry)
            continue
        merged = dict(entry)
        merged["name"] = target.get("name", entry.get("name"))
        merged["content"] = target.get("content", entry.get("content"))
        out.append(merged)
        changed = True

    return out if changed else None


__all__ = ["localized_soul_templates", "relocalize_seed_souls"]
