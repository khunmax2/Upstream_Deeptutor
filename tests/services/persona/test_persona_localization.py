"""The bundled personas follow the interface language — and stop when edited."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.persona import localization as loc
from deeptutor.services.persona.service import PRESETS_DIR, PersonaService

PRESET_NAMES = ("peer", "research-assistant", "teacher")


@pytest.fixture
def personas_root(tmp_path: Path) -> Path:
    root = tmp_path / "personas"
    root.mkdir()
    return root


def _service(root: Path, language: str, monkeypatch: pytest.MonkeyPatch) -> PersonaService:
    monkeypatch.setattr(loc, "current_language", lambda *_a, **_k: language)
    return PersonaService(root=root)


def _descriptions(service: PersonaService) -> dict[str, str]:
    return {p.name: p.description for p in service.list_personas()}


def test_every_preset_ships_a_thai_translation() -> None:
    """A partially translated set would silently fall back mid-list."""
    for name in PRESET_NAMES:
        assert (PRESETS_DIR / name / "PERSONA.th.md").exists(), name


def test_a_thai_interface_seeds_thai_personas(
    personas_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(personas_root, "th", monkeypatch)

    assert sorted(service.seed_presets()) == sorted(PRESET_NAMES)

    teacher = service.get_detail("teacher")
    assert "ติวเตอร์" in teacher.description
    # The rule the fork translates by: genuinely technical terms stay English.
    assert "Socratic" in teacher.content


def test_switching_the_interface_language_switches_untouched_personas(
    personas_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _service(personas_root, "th", monkeypatch).seed_presets()

    english = _descriptions(_service(personas_root, "en", monkeypatch))
    assert english["peer"].startswith("Curious study partner")

    thai = _descriptions(_service(personas_root, "th", monkeypatch))
    assert "เพื่อนร่วมเรียน" in thai["peer"]


def test_a_persona_the_user_edited_is_never_rewritten(
    personas_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _service(personas_root, "th", monkeypatch).seed_presets()

    mine = "---\nname: teacher\ndescription: ของฉันเอง\n---\n\nเนื้อหาของฉัน\n"
    (personas_root / "teacher" / "PERSONA.md").write_text(mine, encoding="utf-8")

    after = _descriptions(_service(personas_root, "en", monkeypatch))

    assert after["teacher"] == "ของฉันเอง", "an edited persona must survive the switch"
    assert after["peer"].startswith("Curious"), "untouched ones still follow the language"


def test_an_untranslated_language_falls_back_to_english(
    personas_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Half a translated prompt is worse than an English one."""
    service = _service(personas_root, "zh", monkeypatch)
    service.seed_presets()

    assert service.get_detail("teacher").description.startswith("Patient Socratic tutor")


def test_relocalizing_a_workspace_that_was_never_seeded_writes_nothing(
    personas_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loc, "current_language", lambda *_a, **_k: "th")

    assert loc.relocalize_seeded_presets(PRESETS_DIR, personas_root) == []
    assert list(personas_root.iterdir()) == []
