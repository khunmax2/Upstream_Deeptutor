"""Thai language plumbing: config + interface-settings normalization."""

from __future__ import annotations

import pytest

from deeptutor.services.config.loader import parse_language
from deeptutor.services.settings.interface_settings import _normalize_language


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("th", "th"),
        ("thai", "th"),
        ("Thai", "th"),
        ("TH", "th"),
        ("zh", "zh"),
        ("chinese", "zh"),
        ("en", "en"),
        ("english", "en"),
    ],
)
def test_parse_language_th(raw: str, expected: str) -> None:
    assert parse_language(raw) == expected


def test_parse_language_empty_defaults_chinese() -> None:
    # Existing behaviour preserved: empty -> default "zh".
    assert parse_language("") == "zh"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("th", "th"),
        ("thai", "th"),
        ("  Thai  ", "th"),
        ("zh", "zh"),
        ("cn", "zh"),
        ("en", "en"),
        ("garbage", "en"),  # falls back to default
    ],
)
def test_interface_normalize_language_th(raw: str, expected: str) -> None:
    assert _normalize_language(raw) == expected
