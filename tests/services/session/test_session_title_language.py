"""A generated session title is written in the interface language.

The prompt used to branch zh / everything-else, so a Thai (or Japanese, or any
other non-en/zh) interface got an English instruction and the title's language
was left to whatever the model picked up from the conversation. Real data showed
the drift: 19 of 62 stored memory labels were English on a Thai interface,
including one reading "Greeting and assistance in Thai language".
"""

from __future__ import annotations

import inspect

from deeptutor.services.prompt.language import language_label
from deeptutor.services.session.turns import title_service


def _prompt_source() -> str:
    return inspect.getsource(title_service.SessionTitleService._maybe_generate_session_title)


def test_the_prompt_names_the_interface_language() -> None:
    source = _prompt_source()
    # The English branch must not be a fixed string any more: it has to carry
    # the resolved language into the instruction.
    assert "language_label(ui_language)" in source
    assert "language_directive(ui_language)" in source


def test_thai_resolves_to_a_thai_instruction() -> None:
    # The helper the prompt now depends on must actually name Thai, otherwise
    # the wiring above would be cosmetic.
    assert language_label("th") == "ภาษาไทย"
    assert language_label("th-TH") == "ภาษาไทย"


def test_an_unlisted_language_still_gets_a_name_not_a_blank() -> None:
    for code in ("ja", "ko", "fr"):
        assert language_label(code).strip()
