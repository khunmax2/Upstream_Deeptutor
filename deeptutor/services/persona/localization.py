"""Serve the bundled persona presets in the interface language.

Fork addition (khunmax2/Upstream_Deeptutor). The soul-library counterpart lives
in ``deeptutor/services/partners/soul_localization.py``; the rule is the same in
both places, and deliberately so.

``seed_presets`` copies ``presets/<name>/PERSONA.md`` into the workspace once and
then skips any name that already exists, so a Thai interface kept showing three
English personas forever. A PERSONA.md is a *prompt*, not a label, so the
``locales/th`` catalogue cannot reach it.

A translated preset lives beside the original as ``PERSONA.th.md``. Nothing else
about the layout changes: the directory name is still the persona id, the
frontmatter still carries the same ``name``, and a language with no translation
falls back to English rather than shipping a half-translated prompt.

Rewriting is allowed only while a file is **provably untouched** — byte-identical
to a preset we ship in one of the languages we know. The moment the user edits
it, it is theirs, in whatever language they left it, and we never touch it again.
"""

from __future__ import annotations

from pathlib import Path

from deeptutor.services.i18n import current_language

PERSONA_FILE = "PERSONA.md"

# Languages with a complete translated set of presets. Absent → English.
_TRANSLATED_LANGUAGES: frozenset[str] = frozenset({"th"})


def _resolve(language: str | None) -> str:
    if language is not None:
        return str(language).strip().lower()[:2]
    try:
        return current_language()
    except Exception:  # settings unreadable — English is the safe default
        return "en"


def _variant_file(preset_dir: Path, language: str) -> Path:
    """The preset file for one language, falling back to the English original."""
    if language in _TRANSLATED_LANGUAGES:
        candidate = preset_dir / f"PERSONA.{language}.md"
        if candidate.exists():
            return candidate
    return preset_dir / PERSONA_FILE


def preset_source_file(preset_dir: Path, *, language: str | None = None) -> Path:
    """Which bundled file to seed for this preset in the interface language."""
    return _variant_file(preset_dir, _resolve(language))


def _shipped_bodies(preset_dir: Path) -> set[str]:
    """Every body we ship for this preset, across all languages."""
    bodies: set[str] = set()
    for path in (preset_dir / PERSONA_FILE, *preset_dir.glob("PERSONA.*.md")):
        try:
            bodies.add(path.read_text(encoding="utf-8").strip())
        except OSError:
            continue
    return bodies


def relocalize_seeded_presets(
    presets_dir: Path,
    workspace_root: Path,
    *,
    language: str | None = None,
) -> list[str]:
    """Rewrite untouched seeded presets into the interface language.

    Returns the names actually rewritten, so callers can log or test the switch.
    Writes nothing when a persona is missing, user-edited, or already correct —
    this sits on a read path and must stay quiet in the common case.
    """
    if not presets_dir.is_dir() or not workspace_root.is_dir():
        return []

    lang = _resolve(language)
    switched: list[str] = []

    for preset_dir in sorted(presets_dir.iterdir()):
        if not preset_dir.is_dir():
            continue
        target = workspace_root / preset_dir.name / PERSONA_FILE
        if not target.exists():
            continue
        try:
            current = target.read_text(encoding="utf-8")
        except OSError:
            continue
        if current.strip() not in _shipped_bodies(preset_dir):
            continue  # user-authored or user-edited — leave it alone
        try:
            wanted = _variant_file(preset_dir, lang).read_text(encoding="utf-8")
        except OSError:
            continue
        if wanted.strip() == current.strip():
            continue
        try:
            target.write_text(wanted, encoding="utf-8")
        except OSError:
            continue
        switched.append(preset_dir.name)

    return switched


__all__ = ["preset_source_file", "relocalize_seeded_presets"]
