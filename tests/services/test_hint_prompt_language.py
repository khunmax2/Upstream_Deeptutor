"""Every generated hint is written in the learner's own language.

Four generators shared one bug: ``reading_hints`` (the three opening
suggestions and the follow-up question), ``chat_hints`` (the composer
placeholder) and ``mastery_hints`` (the question under a learning path). Each
branched Chinese / everything-else and handed the whole everything-else side an
English brief that never named an output language, so what language the panel
came out in was decided by whatever the model happened to pick up from the
material.

That is why it looked intermittent rather than broken. A Thai document carries
enough Thai to pull the model along; a YouTube video with no transcript leaves
nothing but a title, the English brief wins, and a Thai reader gets three
English questions beside a Thai page — reproduced against the real model at 0/3
Thai before the fix and 3/3 after.
"""

from __future__ import annotations

import inspect

from deeptutor.services import chat_hints, mastery_hints, reading_hints
from deeptutor.services.prompt.language import append_language_directive, language_label

# (module, callable that builds the LLM call, the English brief it must localize)
_GENERATORS = (
    (reading_hints, reading_hints.get_openers, "_OPENER_SYSTEM_EN"),
    (reading_hints, reading_hints._call_llm, "_SYSTEM_EN"),
    (chat_hints, chat_hints._call_llm, "_SYSTEM_EN"),
    (mastery_hints, mastery_hints._generate, "_SYSTEM_EN"),
)


def test_every_generator_localizes_its_english_brief() -> None:
    for module, func, brief in _GENERATORS:
        source = inspect.getsource(func)
        assert f"append_language_directive({brief}, language)" in source, (
            f"{module.__name__}.{func.__name__} still passes {brief} unlocalized"
        )


def test_every_generator_keeps_its_authored_chinese_brief() -> None:
    # The zh side is a hand-written Chinese prompt, not a translation; the fix
    # must not have collapsed the two branches into one.
    for _module, func, _brief in _GENERATORS:
        assert "_SYSTEM_ZH" in inspect.getsource(func)


def test_the_directive_names_thai_and_leaves_the_brief_intact() -> None:
    built = append_language_directive("BRIEF", "th")
    # Appended, never edited — the upstream prompt literals still merge cleanly.
    assert built.startswith("BRIEF")
    assert language_label("th") == "ภาษาไทย"
    assert "ภาษาไทย" in built


def test_an_unlisted_language_still_gets_a_name_not_a_blank() -> None:
    for code in ("ja", "ko", "fr"):
        assert language_label(code).strip()
        assert language_label(code) in append_language_directive("BRIEF", code)


def test_each_cache_key_separates_languages() -> None:
    """A hint in the wrong language is unusable, not stale.

    Without the language in the key, changing the response language keeps
    serving the old-language hint for a full TTL.
    """
    assert reading_hints._cache_key("ws", "mat", 3, 7, "th") != reading_hints._cache_key(
        "ws", "mat", 3, 7, "en"
    )
    assert chat_hints._cache_key("s", 4, "th") != chat_hints._cache_key("s", 4, "en")
    assert mastery_hints._cache_key("p", "kp", "a", "th") != mastery_hints._cache_key(
        "p", "kp", "a", "en"
    )


def test_the_openers_cache_key_carries_the_language() -> None:
    # That key is built inline, so assert the language reaches it and is
    # resolved before the cache is consulted rather than after.
    source = inspect.getsource(reading_hints.get_openers)
    assert source.index("language = _response_language()") < source.index("_openers_cache.get(key)")
    assert "|{language}" in source
