"""The loop's system prompt carries the grounding guidance (regression guard).

These pin the behavioural rules that live-testing surfaced as gaps
(docs/issues/inpage-agent-grounding): verify the destination before claiming
success (issue 01), and the ask/proceed/confirm policy for form-fill + commit
flows (issue 03). They assert the *guidance is present* — the model's actual
compliance is verified live, but stripping these lines should fail CI loudly.
"""

from __future__ import annotations

from deeptutor.services.voice_realtime.agent.macro_tool import available_actions
from deeptutor.services.voice_realtime.agent.prompt import build_system_prompt


def _prompt(language: str = "th") -> str:
    return build_system_prompt(available_actions(include_ask_user=True), language=language)


def test_verify_destination_before_done_is_instructed():
    prompt = _prompt()
    # issue 01: no confident success on the wrong page.
    assert "success=true" in prompt.lower() or "success=True" in prompt
    assert "confirm you actually reached" in prompt.lower()
    assert "success=false" in prompt.lower()


def test_form_commit_policy_is_present():
    prompt = _prompt()
    assert "<forms_and_commits>" in prompt
    # ask once, batched — not field-by-field.
    assert "ask_user" in prompt
    assert "never one question" in prompt.lower()
    # stop at the review/proposal before the expensive final commit.
    assert "before pressing the final button" in prompt.lower()


def test_language_hint_still_threads_through():
    assert "Thai" in _prompt("th")
    assert "the user's language" in _prompt("en")
