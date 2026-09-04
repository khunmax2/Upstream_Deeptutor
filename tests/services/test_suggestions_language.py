"""Starter suggestions are written in the learner's own language.

``_generate`` branched Chinese / everything-else and handed the whole
everything-else side ``_SYSTEM_EN`` — an English brief with nothing naming a
target language. A Thai learner therefore got English starting points under the
composer, and because the cache stores the language that was *requested* rather
than the one actually written, the set looked fresh and the English lines stayed
for a full TTL.
"""

from __future__ import annotations

import inspect

from deeptutor.services import suggestions
from deeptutor.services.prompt.language import language_directive, language_label


def _generate_source() -> str:
    return inspect.getsource(suggestions._generate)


def test_the_non_chinese_branch_names_the_output_language() -> None:
    source = _generate_source()
    # The English brief must no longer be passed as a fixed string: it has to
    # carry the resolved language into the instruction.
    assert "language_label(language)" in source
    assert "language_directive(language)" in source
    assert "_SYSTEM_ZH if zh else _SYSTEM_EN" not in source


def test_thai_resolves_to_a_thai_instruction() -> None:
    # The helpers the prompt now depends on must actually name Thai, otherwise
    # the wiring above would be cosmetic.
    assert language_label("th") == "ภาษาไทย"
    assert "ภาษาไทย" in language_directive("th")


def test_an_unlisted_language_still_gets_a_name_not_a_blank() -> None:
    for code in ("ja", "ko", "fr"):
        assert language_label(code).strip()


def test_chinese_keeps_its_own_authored_brief() -> None:
    # The zh side is a fully authored Chinese prompt, not a translated English
    # one; the fix must not have collapsed the two branches into one.
    source = _generate_source()
    assert "_SYSTEM_ZH" in source


def test_the_prompt_version_takes_part_in_the_fingerprint() -> None:
    """A prompt fix must retire the sets cached under the old prompt.

    The fingerprint is what decides whether a cached set is still the right
    answer. It is built from the material and the requested language, neither of
    which moves when the prompt changes — so without the version in the digest,
    this fix would stay invisible to everyone already holding a cached set.
    """
    material = suggestions._Material(profile="x", topics=[])
    before = suggestions._fingerprint(material, "th")

    original = suggestions._PROMPT_VERSION
    try:
        suggestions._PROMPT_VERSION = original + 1
        assert suggestions._fingerprint(material, "th") != before
    finally:
        suggestions._PROMPT_VERSION = original

    assert suggestions._fingerprint(material, "th") == before
