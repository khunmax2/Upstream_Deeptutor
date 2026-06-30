"""Shared voice-activity / endpointing constants.

In the MVP the **browser** owns voice-activity detection and utterance
endpointing (energy VAD with a hangover timer) — it sends one finished
utterance per turn over the WebSocket. This module is the single source of
truth for the tuning values so the client and any future server-side
endpointer agree, and so the server can apply the same minimum-duration guard
the client uses before accepting an utterance.

Server-side streaming VAD (running endpointing over a raw PCM stream) is a
Phase 2 concern; nothing here does that yet.
"""

from __future__ import annotations

from dataclasses import dataclass

# Energy thresholds on a 0..1 RMS scale (must match static client tuning).
SPEECH_ONSET_RMS = 0.020
SPEECH_OFFSET_RMS = 0.012
# Trailing silence before an utterance is considered finished.
HANGOVER_MS = 700
# Shorter utterances are treated as noise / accidental taps and dropped.
MIN_UTTERANCE_MS = 350

# Reject pathological uploads early (providers cap well below this anyway).
MAX_UTTERANCE_BYTES = 25 * 1024 * 1024  # 25 MB, matching OpenAI's audio limit.


@dataclass(frozen=True, slots=True)
class EndpointTuning:
    """Bundle of endpointing thresholds, handy for serialising to the client."""

    speech_onset_rms: float = SPEECH_ONSET_RMS
    speech_offset_rms: float = SPEECH_OFFSET_RMS
    hangover_ms: int = HANGOVER_MS
    min_utterance_ms: int = MIN_UTTERANCE_MS


DEFAULT_TUNING = EndpointTuning()


def is_utterance_too_large(num_bytes: int) -> bool:
    """True when an uploaded utterance exceeds the accepted size ceiling."""
    return num_bytes > MAX_UTTERANCE_BYTES


__all__ = [
    "SPEECH_ONSET_RMS",
    "SPEECH_OFFSET_RMS",
    "HANGOVER_MS",
    "MIN_UTTERANCE_MS",
    "MAX_UTTERANCE_BYTES",
    "EndpointTuning",
    "DEFAULT_TUNING",
    "is_utterance_too_large",
]
