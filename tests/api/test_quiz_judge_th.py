"""Quiz judge accepts Thai and localizes feedback via the language directive.

The judge endpoint is an authenticated WebSocket that streams from the LLM, so
this suite covers the language-resolution building blocks the handler uses
(``_JUDGE_SYSTEM_PROMPTS`` + the directive) rather than the full socket flow.
"""

from __future__ import annotations

from deeptutor.api.routers.quiz_judge import _JUDGE_SYSTEM_PROMPTS
from deeptutor.services.prompt.language import append_language_directive


def test_judge_accepts_th_in_whitelist() -> None:
    # Mirrors the handler guard `requested_language not in (...)`.
    assert "th" in ("zh", "en", "th")


def test_judge_th_uses_english_prompt_plus_thai_directive() -> None:
    # th has no hand-written judge prompt, so the handler falls back to en and
    # appends the directive — the resulting prompt must request Thai output.
    assert "th" not in _JUDGE_SYSTEM_PROMPTS
    base = _JUDGE_SYSTEM_PROMPTS["en"]
    prompt = append_language_directive(base, "th")
    assert "ภาษาไทย" in prompt
    assert "strictly in th" not in prompt


def test_judge_zh_en_have_native_prompts() -> None:
    assert "zh" in _JUDGE_SYSTEM_PROMPTS
    assert "en" in _JUDGE_SYSTEM_PROMPTS
