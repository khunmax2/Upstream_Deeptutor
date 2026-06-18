"""Memory consolidator collapses Thai to en assets but keeps the directive path."""

from __future__ import annotations

from deeptutor.services.memory.consolidator.modes._runtime import _lang_code


def test_lang_code_thai_uses_english_assets() -> None:
    # Consolidator prompt assets exist only for en/zh, so th selects en files;
    # the Thai directive is applied in call_llm(language=...), not here.
    assert _lang_code("th") == "en"
    assert _lang_code("thai") == "en"


def test_lang_code_chinese_and_default() -> None:
    assert _lang_code("zh") == "zh"
    assert _lang_code("zh-CN") == "zh"
    assert _lang_code("en") == "en"
    assert _lang_code("") == "en"
