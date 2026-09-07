"""The soul library follows the interface language — and stops when edited."""

from __future__ import annotations

import pytest

from deeptutor.services.partners.manager import DEFAULT_SOUL_TEMPLATES
from deeptutor.services.partners.soul_localization import (
    localized_soul_templates,
    relocalize_seed_souls,
)
from deeptutor.services.partners.soul_templates_th import DEFAULT_SOUL_TEMPLATES_TH


def _by_id(entries) -> dict[str, dict]:
    return {str(e["id"]): e for e in entries}


def test_the_thai_set_covers_every_english_seed() -> None:
    """A missing id would leave one English soul in an otherwise Thai library."""
    assert _by_id(DEFAULT_SOUL_TEMPLATES_TH).keys() == _by_id(DEFAULT_SOUL_TEMPLATES).keys()


def test_thai_templates_keep_technical_terms_in_english() -> None:
    """The fork's translation rule, pinned where it is easy to regress."""
    souls = _by_id(DEFAULT_SOUL_TEMPLATES_TH)

    assert "Socratic" in souls["math-tutor"]["content"]
    assert "trade-off" in souls["coding-assistant"]["content"]
    assert "primary source" in souls["research-helper"]["content"]


def test_a_thai_interface_gets_thai_templates() -> None:
    thai = _by_id(localized_soul_templates(DEFAULT_SOUL_TEMPLATES, language="th"))

    assert thai["companion"]["name"] == "เพื่อนร่วมเรียน"
    assert "# Soul" in thai["companion"]["content"], "structure stays recognisable"


def test_an_untranslated_language_falls_back_to_english() -> None:
    assert localized_soul_templates(DEFAULT_SOUL_TEMPLATES, language="zh") == (
        DEFAULT_SOUL_TEMPLATES
    )


def test_switching_language_rewrites_untouched_seeds_both_ways() -> None:
    seeded = [dict(e) for e in DEFAULT_SOUL_TEMPLATES]

    to_thai = relocalize_seed_souls(seeded, DEFAULT_SOUL_TEMPLATES, language="th")
    assert to_thai is not None
    assert _by_id(to_thai)["math-tutor"]["name"] == "ติวเตอร์คณิตศาสตร์"

    back = relocalize_seed_souls(to_thai, DEFAULT_SOUL_TEMPLATES, language="en")
    assert back is not None
    assert _by_id(back)["math-tutor"]["name"] == "Math Tutor"


def test_nothing_is_written_when_the_library_already_matches() -> None:
    """``None`` is the contract that keeps the read path from rewriting the file."""
    seeded = [dict(e) for e in DEFAULT_SOUL_TEMPLATES]

    assert relocalize_seed_souls(seeded, DEFAULT_SOUL_TEMPLATES, language="en") is None


def test_a_soul_the_user_edited_is_never_rewritten() -> None:
    seeded = [dict(e) for e in DEFAULT_SOUL_TEMPLATES]
    seeded[0]["content"] = "# Soul\n\nฉันเขียนเอง\n"

    out = relocalize_seed_souls(seeded, DEFAULT_SOUL_TEMPLATES, language="th")

    assert out is not None, "the other four still switch"
    assert out[0]["content"] == "# Soul\n\nฉันเขียนเอง\n"
    assert out[1]["name"] == "ติวเตอร์คณิตศาสตร์"


def test_a_user_authored_soul_is_left_alone() -> None:
    mine = [{"id": "mine", "name": "My Soul", "content": "# Soul\n\nmine\n"}]

    assert relocalize_seed_souls(mine, DEFAULT_SOUL_TEMPLATES, language="th") is None


@pytest.mark.parametrize("language", ["th", "TH", "th-TH", "thai"])
def test_thai_is_recognised_however_the_setting_spells_it(language: str) -> None:
    thai = _by_id(localized_soul_templates(DEFAULT_SOUL_TEMPLATES, language=language))

    assert thai["companion"]["name"] == "เพื่อนร่วมเรียน"
