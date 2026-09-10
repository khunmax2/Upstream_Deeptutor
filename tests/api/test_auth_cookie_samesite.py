"""The session cookie's SameSite value, and why it is no longer derived.

``_SAMESITE`` used to be ``"none" if _SECURE else "lax"``. The comment above it
justified ``None`` by a development case — a frontend reached at ``127.0.0.1``
while the backend answers at ``localhost`` — but that case runs without HTTPS
and therefore took the *other* branch. ``None`` was applied only in production,
behind one reverse proxy, where the case does not arise and where it attaches
the session cookie to every cross-site request to this origin.

These tests pin the replacement: a setting, defaulting to ``lax``, that cannot
produce a cookie the browser will drop.
"""

import pytest

from deeptutor.services.config.runtime_settings import (
    DEFAULT_AUTH_SETTINGS,
    _normalize_cookie_samesite,
)


def test_default_is_lax_not_none() -> None:
    assert DEFAULT_AUTH_SETTINGS["cookie_samesite"] == "lax"


@pytest.mark.parametrize("value", ["lax", "strict", "none"])
def test_the_three_real_values_survive_when_secure(value: str) -> None:
    assert _normalize_cookie_samesite(value, secure=True) == value


def test_none_without_secure_degrades_rather_than_issuing_a_dropped_cookie() -> None:
    # Browsers refuse SameSite=None without Secure. Honouring the request would
    # produce a login that silently does not stick, which is worse than the
    # narrower cookie.
    assert _normalize_cookie_samesite("none", secure=False) == "lax"


def test_strict_and_lax_do_not_need_secure() -> None:
    assert _normalize_cookie_samesite("strict", secure=False) == "strict"
    assert _normalize_cookie_samesite("lax", secure=False) == "lax"


# "None " is deliberately absent: padding and case are normalised, so it is a
# recognised value, not an unrecognised one. See the test below.
@pytest.mark.parametrize("value", [None, "", "  ", "sameorigin", "lax;strict", 1, object()])
def test_anything_unrecognized_becomes_lax(value: object) -> None:
    # Fail to the narrow value, never to the wide one: a typo in a settings file
    # must not widen the cookie.
    assert _normalize_cookie_samesite(value, secure=True) == "lax"


def test_case_and_padding_are_tolerated() -> None:
    assert _normalize_cookie_samesite("  NONE  ", secure=True) == "none"
    assert _normalize_cookie_samesite("Strict", secure=True) == "strict"


def test_the_normalizer_is_what_the_loader_uses() -> None:
    # The value reaches auth.py through _normalize_auth, which rebuilds the dict
    # from a literal — a key added to the defaults alone is silently dropped.
    from deeptutor.services.config.runtime_settings import RuntimeSettingsService

    normalized = RuntimeSettingsService._normalize_auth(
        RuntimeSettingsService, {"cookie_secure": False, "cookie_samesite": "none"}
    )
    assert normalized["cookie_samesite"] == "lax"
    normalized = RuntimeSettingsService._normalize_auth(
        RuntimeSettingsService, {"cookie_secure": True, "cookie_samesite": "none"}
    )
    assert normalized["cookie_samesite"] == "none"
