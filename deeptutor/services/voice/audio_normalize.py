"""Browser recordings become WAV before they reach a speech-to-text provider.

Fork. The chat composer's microphone records with ``MediaRecorder``, which
gives WebM/Opus in Chrome and Firefox and MP4/AAC in Safari. OpenAI and Groq
decode those, but a self-hosted Whisper-compatible server often reads audio
through libsndfile, which cannot open WebM. Measured 2026-09-14 against a
workplace server behind LiteLLM (``ptm-asr-1``): the same Thai sentence failed
as browser-style WebM/Opus with HTTP 422 "Failed to decode audio ... Format not
recognised" and transcribed correctly as 16 kHz mono WAV. The Settings
diagnostics never showed it, because its probe clip is already WAV.

WAV is the one format every transcription server reads, and 16 kHz mono is
what Whisper-family models resample to anyway, so nothing is lost. PyAV (in the
image with Manim) does the decoding. Where it is missing, or a clip will not
decode, the original bytes go through unchanged: the conversion never makes a
request fail that would otherwise have been tried.
"""

from __future__ import annotations

import io
import logging
from pathlib import PurePosixPath
import wave

logger = logging.getLogger(__name__)

TARGET_RATE = 16_000

# What MediaRecorder produces across browsers, by media type and by extension.
_CONTAINER_TYPES = frozenset(
    {
        "audio/webm",
        "video/webm",
        "audio/ogg",
        "audio/opus",
        "audio/mp4",
        "video/mp4",
        "audio/m4a",
        "audio/x-m4a",
        "audio/aac",
    }
)
_CONTAINER_EXTENSIONS = frozenset({".webm", ".ogg", ".oga", ".opus", ".mp4", ".m4a", ".aac"})


def _media_type(content_type: str) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _is_wav(audio: bytes) -> bool:
    return audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"


def _sniffed_container(audio: bytes) -> bool:
    """WebM/Matroska (EBML), Ogg, or MP4 by magic bytes, for unlabeled uploads."""
    return audio[:4] in (b"\x1a\x45\xdf\xa3", b"OggS") or audio[4:8] == b"ftyp"


def needs_wav(audio: bytes, filename: str, content_type: str) -> bool:
    """Whether ``audio`` is a browser recording container rather than WAV."""
    if not audio or _is_wav(audio):
        return False
    if _media_type(content_type) in _CONTAINER_TYPES:
        return True
    if PurePosixPath(filename or "").suffix.lower() in _CONTAINER_EXTENSIONS:
        return True
    return _sniffed_container(audio)


def _decode_to_wav(audio: bytes) -> bytes:
    import av  # PyAV; ImportError is handled by the caller

    pcm = bytearray()
    with av.open(io.BytesIO(audio)) as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=TARGET_RATE)
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                pcm += out.to_ndarray().tobytes()
        for out in resampler.resample(None):
            pcm += out.to_ndarray().tobytes()
    if not pcm:
        raise ValueError("no audio frames decoded")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(TARGET_RATE)
        wav.writeframes(bytes(pcm))
    return buffer.getvalue()


def browser_audio_to_wav(audio: bytes, filename: str, content_type: str) -> tuple[bytes, str, str]:
    """Return ``(audio, filename, content_type)``, as 16 kHz mono WAV when possible."""
    if not needs_wav(audio, filename, content_type):
        return audio, filename, content_type
    try:
        wav = _decode_to_wav(audio)
    except ImportError:
        logger.debug("PyAV is not installed; sending %s to STT as recorded", filename)
        return audio, filename, content_type
    except Exception as exc:  # noqa: BLE001 — any decode failure falls back to the original
        logger.warning(
            "Could not convert %s to WAV for STT; sending it as recorded: %s", filename, exc
        )
        return audio, filename, content_type
    stem = PurePosixPath(filename or "").stem or "recording"
    return wav, f"{stem}.wav", "audio/wav"


__all__ = ["TARGET_RATE", "browser_audio_to_wav", "needs_wav"]
