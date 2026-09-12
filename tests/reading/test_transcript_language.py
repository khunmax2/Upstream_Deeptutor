"""Which caption track a clip is read through (fork, 2026-09-12).

Both workspaces used upstream's fixed `zh-CN, zh-Hans, zh, en` and disagreed
with each other on the same Apple keynote. The rule now: the spoken language
first, then English, then the interface language, uploaded before generated,
never a translation. The track list below is the real one for 39BalPDuTo0.
"""

from __future__ import annotations

import pytest

from deeptutor.reading.transcript_language import (
    DEFAULT_ORDER,
    CaptionTrack,
    choose_track,
    configured_order,
    spoken_language,
)

APPLE_KEYNOTE = [
    CaptionTrack("ar", False),
    CaptionTrack("de", False),
    CaptionTrack("en", True),  # auto-generated: the language that was spoken
    CaptionTrack("en", False),
    CaptionTrack("es-419", False),
    CaptionTrack("fr", False),
    CaptionTrack("id", False),
    CaptionTrack("it", False),
    CaptionTrack("ja", False),
    CaptionTrack("ko", False),
    CaptionTrack("pt-BR", False),
    CaptionTrack("th", False),
    CaptionTrack("tr", False),
    CaptionTrack("vi", False),
    CaptionTrack("zh-HK", False),
    CaptionTrack("zh-Hans", False),
    CaptionTrack("zh-TW", False),
]


def test_the_spoken_language_is_read_off_the_generated_track() -> None:
    assert spoken_language(APPLE_KEYNOTE) == "en"
    assert spoken_language([CaptionTrack("th", True), CaptionTrack("en", False)]) == "th"


def test_a_lone_uploaded_track_names_the_language_and_several_leave_it_at_english() -> None:
    assert spoken_language([CaptionTrack("ja", False)]) == "ja"
    assert spoken_language([CaptionTrack("ja", False), CaptionTrack("ko", False)]) == "en"


def test_apple_keynote_is_read_in_english_uploaded_not_chinese(monkeypatch) -> None:
    """The case that started this: a Thai interface, seventeen tracks, and the
    old rule picked zh-Hans on one page and en on the other."""
    monkeypatch.delenv("DEEPTUTOR_TRANSCRIPT_LANGUAGES", raising=False)
    chosen = choose_track(APPLE_KEYNOTE, interface_language="th")
    assert chosen is not None
    assert (chosen.language_code, chosen.generated) == ("en", False)


def test_uploaded_beats_generated_in_the_same_language() -> None:
    tracks = [CaptionTrack("en", True), CaptionTrack("en", False)]
    assert choose_track(tracks, interface_language="th").generated is False


def test_a_thai_lecture_is_read_in_thai_even_on_an_english_interface() -> None:
    tracks = [CaptionTrack("th", True), CaptionTrack("en", False)]
    # spoken = th (generated); the English upload is a translation of it.
    assert choose_track(tracks, interface_language="en").language_code == "th"


def test_interface_language_comes_after_english(monkeypatch) -> None:
    monkeypatch.delenv("DEEPTUTOR_TRANSCRIPT_LANGUAGES", raising=False)
    # Spoken language unknown among several uploads (assumed en, absent):
    # English is not there either, so the interface language wins.
    tracks = [CaptionTrack("ja", False), CaptionTrack("th", False), CaptionTrack("ko", False)]
    assert choose_track(tracks, interface_language="th").language_code == "th"


def test_a_translation_never_beats_the_spoken_language() -> None:
    """A Korean clip with a Japanese upload: the upload is a translation."""
    tracks = [CaptionTrack("ko", True), CaptionTrack("ja", False)]
    assert choose_track(tracks, interface_language="th").language_code == "ko"


def test_falls_back_to_the_first_upload_when_nothing_wanted_exists() -> None:
    tracks = [CaptionTrack("ja", False), CaptionTrack("de", False)]
    assert choose_track(tracks, interface_language="th").language_code == "ja"


def test_no_tracks_means_no_transcript() -> None:
    assert choose_track([], interface_language="th") is None


def test_region_variants_match_their_base_but_not_the_other_way() -> None:
    tracks = [CaptionTrack("en-US", False), CaptionTrack("zh-Hans", False)]
    assert choose_track(tracks, interface_language="", order=["en"]).language_code == "en-US"
    assert choose_track(tracks, interface_language="", order=["zh"]).language_code == "zh-Hans"
    assert choose_track(tracks, interface_language="", order=["zh-HK"]).language_code == "en-US"


def test_the_order_is_configurable_without_a_rebuild(monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_TRANSCRIPT_LANGUAGES", "interface, original, en")
    assert configured_order() == ("interface", "original", "en")
    # Thai-first: the same keynote is now read through Apple's Thai upload.
    assert choose_track(APPLE_KEYNOTE, interface_language="th").language_code == "th"
    monkeypatch.setenv("DEEPTUTOR_TRANSCRIPT_LANGUAGES", "  ,  ")
    assert configured_order() == DEFAULT_ORDER


@pytest.mark.parametrize("interface", ["", "th", "en"])
def test_no_hard_coded_chinese_anywhere_in_the_default(interface: str, monkeypatch) -> None:
    monkeypatch.delenv("DEEPTUTOR_TRANSCRIPT_LANGUAGES", raising=False)
    tracks = [CaptionTrack("zh-Hans", False), CaptionTrack("en", False), CaptionTrack("en", True)]
    assert choose_track(tracks, interface_language=interface).language_code == "en"
