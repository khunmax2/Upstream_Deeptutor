"""Thai display metadata for capabilities and tools."""

from __future__ import annotations

from deeptutor.i18n.metadata_i18n import (
    capability_description_i18n,
    localized_description,
    tool_description_i18n,
)


def test_capability_description_has_thai() -> None:
    values = capability_description_i18n("chat")
    assert "th" in values
    assert values["th"] and values["th"] != values["en"]


def test_tool_description_has_thai() -> None:
    values = tool_description_i18n("web_search")
    assert "th" in values
    assert values["th"] and values["th"] != values["en"]


def test_capability_fallback_includes_thai_key() -> None:
    values = capability_description_i18n("unknown_capability", fallback="x")
    assert values == {"en": "x", "zh": "x", "th": "x"}


def test_localized_description_picks_thai() -> None:
    values = {"en": "english", "zh": "中文", "th": "ไทย"}
    assert localized_description(values, "th") == "ไทย"
    assert localized_description(values, "thai") == "ไทย"
    assert localized_description(values, "zh-CN") == "中文"


def test_localized_description_th_falls_back_to_en_when_missing() -> None:
    values = {"en": "english", "zh": "中文"}
    assert localized_description(values, "th") == "english"
