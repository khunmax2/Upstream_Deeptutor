"""Settings API accepts Thai (``th``) as an interface language."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from deeptutor.api.routers import settings as settings_router
from deeptutor.api.routers.settings import LanguageUpdate, UISettings, UISettingsUpdate


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
    # Patched on the field-level writer the endpoint actually calls. It used to
    # read-modify-write through load/save_ui_settings; upstream v1.5.16 moved it
    # to patch_ui_settings, which left this test patching names nobody calls —
    # it passed while writing to the real settings file.
    store: dict[str, object] = {"language": "en"}
    monkeypatch.setattr(settings_router, "patch_ui_settings", lambda **f: store.update(f))

    result = await settings_router.update_language(LanguageUpdate(language="th"))

    assert result == {"language": "th"}
    assert store["language"] == "th"


def test_ui_settings_update_accepts_th_response_language() -> None:
    """v1.5.16 split model-output language from UI language; th must reach both.

    A Literal that forgot "th" here is the silent failure this fork has already
    shipped once: the frontend sends th and the endpoint answers 422.
    """
    assert UISettingsUpdate(response_language="th").response_language == "th"
    assert UISettings(response_language="th").response_language == "th"


@pytest.mark.asyncio
async def test_ui_settings_endpoint_persists_th_response_language(monkeypatch) -> None:
    store: dict[str, object] = {"response_language": "en"}
    monkeypatch.setattr(settings_router, "patch_ui_settings", lambda **f: store.update(f))
    monkeypatch.setattr(settings_router, "load_ui_settings", lambda: dict(store))

    result = await settings_router.update_ui_settings(UISettingsUpdate(response_language="th"))

    assert result["response_language"] == "th"
    assert store["response_language"] == "th"
