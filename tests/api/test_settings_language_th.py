"""Settings API accepts Thai (``th``) as an interface language."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from deeptutor.api.routers import settings as settings_router
from deeptutor.api.routers.settings import LanguageUpdate, UISettings


def test_language_update_accepts_th() -> None:
    assert LanguageUpdate(language="th").language == "th"


def test_language_update_still_accepts_zh_en() -> None:
    assert LanguageUpdate(language="zh").language == "zh"
    assert LanguageUpdate(language="en").language == "en"


def test_language_update_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        LanguageUpdate(language="xx")


def test_ui_settings_accepts_th() -> None:
    assert UISettings(language="th").language == "th"


@pytest.mark.asyncio
async def test_update_language_endpoint_persists_th(monkeypatch) -> None:
    store: dict[str, object] = {"language": "en"}

    monkeypatch.setattr(settings_router, "load_ui_settings", lambda: dict(store))

    def _save(settings: dict) -> None:
        store.update(settings)

    monkeypatch.setattr(settings_router, "save_ui_settings", _save)

    result = await settings_router.update_language(LanguageUpdate(language="th"))

    assert result == {"language": "th"}
    assert store["language"] == "th"
