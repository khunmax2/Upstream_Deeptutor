"""Which caption track to read a video through.

Fork. Both places that pull a YouTube transcript — the reading workspace
(``deeptutor/reading/ingestion.py``) and the watching workspace
(``deeptutor/video_learning/service.py``) — carried upstream's hard-coded
preference ``zh-CN, zh-Hans, zh, en``: the language of upstream's own users,
applied to everyone. On an Apple keynote with seventeen uploaded tracks the two
pages disagreed with each other — one asked for ``zh-CN, zh`` (absent) and fell
through to English, the other asked for ``zh-Hans`` (present) and showed
Chinese — and neither asked what the speaker actually said.

The rule here, decided 2026-09-12: **the transcript is evidence, so it is read
in the language the clip was spoken in.** The tutor cites timestamps and quotes
from it, and a translated track — above all an auto-translated one — would put
words in the speaker's mouth. The learner still gets Thai: the tutor answers in
the interface language, and a human-uploaded track in that language is next in
line after the original.

Order, first match wins:

1. the spoken language, an uploaded track before the auto-generated one
2. English, uploaded
3. the interface language (Thai here), uploaded
4. any uploaded track
5. any auto-generated track
6. nothing — the material opens without a transcript, as before

Never an auto-*translated* track: those are not captions, they are a machine's
guess at them. The spoken language is known from the auto-generated track,
which YouTube produces only for the language it heard; a video without one is
assumed to be in English unless the only uploaded track says otherwise.

``DEEPTUTOR_TRANSCRIPT_LANGUAGES`` overrides the order without a rebuild: a
comma list of BCP-47 codes, where the word ``original`` stands for the spoken
language and ``interface`` for the interface language. The default is
``original,en,interface``.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Sequence

DEFAULT_ORDER = ("original", "en", "interface")


@dataclass(frozen=True)
class CaptionTrack:
    """One caption track as either backend reports it."""

    language_code: str
    generated: bool
    # The backend-specific object (a youtube_transcript_api Transcript, or an
    # Invidious caption row) so the caller can fetch the chosen one.
    source: Any = None

    @property
    def base_language(self) -> str:
        return self.language_code.split("-", 1)[0].lower()


def configured_order() -> tuple[str, ...]:
    raw = os.getenv("DEEPTUTOR_TRANSCRIPT_LANGUAGES", "").strip()
    if not raw:
        return DEFAULT_ORDER
    items = tuple(part.strip() for part in raw.split(",") if part.strip())
    return items or DEFAULT_ORDER


def spoken_language(tracks: Sequence[CaptionTrack]) -> str:
    """The language the clip was spoken in, as far as the tracks can tell.

    YouTube auto-generates captions only in the language it heard, so a
    generated track names the spoken language outright. Without one, a single
    uploaded track is taken at its word; several uploaded tracks with no
    generated one leave the question open, and English is the assumption.
    """
    for track in tracks:
        if track.generated:
            return track.language_code
    uploaded = [track for track in tracks if not track.generated]
    if len(uploaded) == 1:
        return uploaded[0].language_code
    return "en"


def _matches(track: CaptionTrack, code: str) -> bool:
    """``en`` matches ``en`` and ``en-US``; ``zh-Hans`` matches only itself."""
    wanted = code.lower()
    have = track.language_code.lower()
    if have == wanted:
        return True
    return "-" not in wanted and track.base_language == wanted


def choose_track(
    tracks: Sequence[CaptionTrack],
    *,
    interface_language: str = "",
    order: Sequence[str] | None = None,
) -> CaptionTrack | None:
    """Pick the track to read the clip through, or None when there is none.

    Auto-translated tracks are not in ``tracks`` by construction (neither
    backend lists them as tracks; they are a transform of one), so nothing
    here can pick one.
    """
    if not tracks:
        return None
    original = spoken_language(tracks)
    wanted: list[str] = []
    for item in order or configured_order():
        key = item.strip().lower()
        if key == "original":
            code = original
        elif key == "interface":
            code = interface_language.strip()
        else:
            code = item.strip()
        if code and code not in wanted:
            wanted.append(code)

    for code in wanted:
        uploaded = [t for t in tracks if not t.generated and _matches(t, code)]
        if uploaded:
            return uploaded[0]
        generated = [t for t in tracks if t.generated and _matches(t, code)]
        if generated:
            return generated[0]

    for track in tracks:
        if not track.generated:
            return track
    return tracks[0]


def interface_language_code() -> str:
    """The interface language as a caption language code, or "" when unknown."""
    try:
        from deeptutor.services.settings.interface_settings import get_ui_language

        value = str(get_ui_language() or "").strip()
    except Exception:
        return ""
    return {"th": "th", "en": "en", "zh": "zh-Hans", "ja": "ja"}.get(value, value)
