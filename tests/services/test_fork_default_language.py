"""The fork ships Thai as the first-run language.

A clone has no ``data/`` — it is gitignored — so these defaults are the only
thing a first run sees. When they said ``en``, cloning the repo onto a second
machine came up in English while the original machine, carrying its own saved
``interface.json``, was Thai. Pinned here because it is a product decision, not
an accident, and because an upstream sync will offer ``en`` back every time.
"""

from __future__ import annotations

from deeptutor.services.setup.init import (
    DEFAULT_INTERFACE_SETTINGS,
    DEFAULT_MAIN_SETTINGS,
)


def test_a_fresh_install_comes_up_in_thai() -> None:
    assert DEFAULT_INTERFACE_SETTINGS["language"] == "th"


def test_the_backend_default_matches_the_interface_default() -> None:
    """A split here would seed Thai templates behind an English UI, or vice versa."""
    assert DEFAULT_MAIN_SETTINGS["system"]["language"] == (DEFAULT_INTERFACE_SETTINGS["language"])
