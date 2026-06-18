"""Thai support in the prompt language helpers and PromptManager fallback."""

from __future__ import annotations

import pytest

from deeptutor.services.prompt.language import (
    language_directive,
    language_label,
    normalize_agent_language,
)
from deeptutor.services.prompt.manager import PromptManager


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("th", "th"),
        ("thai", "th"),
        ("Thai", "th"),
        ("TH", "th"),
        ("zh", "zh"),
        ("zh-CN", "zh"),
        ("zh-tw", "zh"),
        ("chinese", "zh"),
        ("cn", "zh"),
        ("en", "en"),
        ("english", "en"),
        ("", "en"),
        (None, "en"),
        ("garbage", "en"),
    ],
)
def test_normalize_agent_language(raw, expected) -> None:
    assert normalize_agent_language(raw) == expected


def test_language_label_th_is_thai_word() -> None:
    # Critical: without the _LANGUAGE_LABELS entry this would echo raw "th".
    assert language_label("th") == "ภาษาไทย"


def test_language_directive_th_contains_thai_label_not_raw_code() -> None:
    directive = language_directive("th")
    assert "ภาษาไทย" in directive
    assert "strictly in th" not in directive


def test_prompt_manager_th_fallback_does_not_throw() -> None:
    assert PromptManager.LANGUAGE_FALLBACKS["th"] == ["th", "en"]

    manager = PromptManager()
    # Requesting a module in Thai must not raise even when no th asset exists;
    # the fallback chain (th -> en) should kick in transparently.
    try:
        result = manager.load_prompts("question", "pipeline", language="th")
    except Exception as exc:  # noqa: BLE001 - we assert no exception escapes
        pytest.fail(f"PromptManager raised for th fallback: {exc!r}")
    assert isinstance(result, dict)
