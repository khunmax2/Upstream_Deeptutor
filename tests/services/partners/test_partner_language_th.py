"""Partner runtime resolves Thai (and never collapses it to en/zh)."""

from __future__ import annotations

from types import SimpleNamespace

from deeptutor.services.partners.runtime import PartnerRunner


def _language_for(value: str) -> str:
    # ``_language`` only reads ``self.config.language``; build a bare instance
    # without running __init__ so the test stays free of heavy dependencies.
    runner = PartnerRunner.__new__(PartnerRunner)
    runner.config = SimpleNamespace(language=value)
    return runner._language()


def test_partner_language_thai() -> None:
    assert _language_for("th") == "th"
    assert _language_for("thai") == "th"


def test_partner_language_other() -> None:
    assert _language_for("zh-CN") == "zh"
    assert _language_for("en") == "en"
    assert _language_for("") == "en"
