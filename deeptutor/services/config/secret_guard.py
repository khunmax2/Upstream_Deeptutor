"""A masked secret is never a credential.

Fork. Settings shows every stored key as ``***`` (``CATALOG_SECRET_MASK``) and
puts the real value back on the way in — but only for a profile already saved
in the same account's catalog. A profile that is not (added in the browser and
never applied, or carried over from somewhere else) keeps the literal ``***``.
Before this module that value went to the provider as the key — OpenRouter
answers ``Bearer ***`` with "Missing Authentication header" (measured
2026-09-14) — or was saved as the key. These helpers find what is still masked
so the test runner can fail with a clear message and the save routes can refuse.
"""

from __future__ import annotations

from typing import Any

from .model_catalog import CATALOG_SECRET_MASK, _is_secret_field


def _still_masked(value: Any) -> bool:
    if isinstance(value, str):
        return value == CATALOG_SECRET_MASK
    if isinstance(value, dict):
        return any(_still_masked(item) for item in value.values())
    if isinstance(value, list):
        return any(_still_masked(item) for item in value)
    return False


def has_unrestored_secret(entry: dict[str, Any]) -> bool:
    """Whether a profile or connection still carries the mask in a secret field."""
    return any(
        (key == "extra_headers" or _is_secret_field(key)) and _still_masked(value)
        for key, value in entry.items()
    )


def unrestored_secret_labels(catalog: dict[str, Any]) -> list[str]:
    """Human-readable names of every entry whose secret is still the mask."""
    labels: list[str] = []
    for connection in catalog.get("connections") or []:
        if isinstance(connection, dict) and has_unrestored_secret(connection):
            labels.append(f"connection “{connection.get('name') or connection.get('id')}”")
    for service_name, service in (catalog.get("services") or {}).items():
        if not isinstance(service, dict):
            continue
        for profile in service.get("profiles") or []:
            if isinstance(profile, dict) and has_unrestored_secret(profile):
                labels.append(f"{service_name} “{profile.get('name') or profile.get('id')}”")
    return labels


__all__ = ["has_unrestored_secret", "unrestored_secret_labels"]
