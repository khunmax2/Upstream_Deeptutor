"""Formal STT / TTS provider interfaces + OpenAI-compatible adapters.

This is the *plug-and-play* seam the mentor asked for: the voice engine depends
only on these abstract interfaces, never on a concrete vendor. Any provider —
the senior's TokenMind endpoint (``ptm-asr-1`` / ``ptm-tts-1``), OpenAI, Groq,
a local server — is just an adapter behind ``BaseSTT`` / ``BaseTTS``.

Design notes
------------
* Providers are constructed with their own config (base_url/api_key/model); they
  read NO globals, so the whole module drops into another project unchanged.
* TTS is **streaming-first**: ``stream()`` yields ``AudioChunk``s as they arrive
  (TokenMind returns PCM incrementally), which is what makes the reply start
  playing almost immediately. ``synthesize()`` is a convenience that collects.
* Thai text normalization (numbers → words, phrase breaks) lives in the TTS
  adapter because the TokenMind guidelines require it client-side.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
import re

import httpx


# ── data types ────────────────────────────────────────────────────────────
@dataclass(slots=True)
class AudioChunk:
    """One piece of synthesized audio."""

    data: bytes
    sample_rate: int = 24_000
    channels: int = 1
    fmt: str = "pcm_s16le"  # pcm_s16le | mp3 | wav


@dataclass(slots=True)
class STTResult:
    """Transcription result. ``segments`` carries verbose_json timing if present."""

    text: str
    language: str | None = None
    duration_s: float | None = None
    segments: list[dict] = field(default_factory=list)


# ── abstract interfaces (the plug-and-play seam) ────────────────────────────
class BaseSTT(ABC):
    """Speech-to-text provider."""

    @abstractmethod
    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "audio.wav",
        content_type: str = "audio/wav",
        language: str | None = None,
    ) -> STTResult:
        """Transcribe one utterance's audio bytes."""


class BaseTTS(ABC):
    """Text-to-speech provider. Streaming-first."""

    #: PCM sample rate the provider emits (used to build WAV / play back).
    sample_rate: int = 24_000
    output_format: str = "pcm_s16le"

    @abstractmethod
    def stream(self, text: str, *, voice: str | None = None) -> AsyncIterator[AudioChunk]:
        """Yield audio chunks as they are synthesized (low first-audio latency)."""

    async def synthesize(self, text: str, *, voice: str | None = None) -> AudioChunk:
        """Collect the whole stream into one chunk (convenience / batch use)."""
        buf = bytearray()
        sr, ch, fmt = self.sample_rate, 1, self.output_format
        async for c in self.stream(text, voice=voice):
            buf += c.data
            sr, ch, fmt = c.sample_rate, c.channels, c.fmt
        return AudioChunk(bytes(buf), sample_rate=sr, channels=ch, fmt=fmt)


# ── OpenAI-compatible adapters (covers TokenMind, OpenAI, Groq, local) ──────
class OpenAICompatSTT(BaseSTT):
    """`/audio/transcriptions` — TokenMind ``ptm-asr-1``, Groq Whisper, OpenAI."""

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float = 60.0) -> None:
        self._url = f"{base_url.rstrip('/')}/audio/transcriptions"
        self._key = api_key
        self._model = model
        self._timeout = timeout

    async def transcribe(
        self, audio, *, filename="audio.wav", content_type="audio/wav", language=None
    ) -> STTResult:
        files = {
            "file": (filename, audio, content_type),
            "model": (None, self._model),
            "response_format": (None, "verbose_json"),
        }
        if language:
            files["language"] = (None, language)
        headers = {"Authorization": f"Bearer {self._key}"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(self._url, headers=headers, files=files)
            resp.raise_for_status()
            data = resp.json()
        return STTResult(
            text=(data.get("text") or "").strip(),
            language=data.get("language"),
            duration_s=data.get("duration"),
            segments=data.get("segments") or [],
        )


class OpenAICompatTTS(BaseTTS):
    """`/audio/speech` streaming — TokenMind ``ptm-tts-1`` (PCM), OpenAI TTS.

    TokenMind emits raw PCM (s16le) at ``sample_rate``. We normalize Thai text
    (numbers → words) before sending, per the provider's guidelines.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        voice: str,
        sample_rate: int = 24_000,
        response_format: str = "pcm",
        normalize_thai: bool = True,
        timeout: float = 60.0,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/audio/speech"
        self._key = api_key
        self._model = model
        self._voice = voice
        self.sample_rate = sample_rate
        self._response_format = response_format
        self.output_format = "pcm_s16le" if response_format == "pcm" else response_format
        self._normalize = normalize_thai
        self._timeout = timeout

    async def stream(self, text, *, voice=None) -> AsyncIterator[AudioChunk]:
        prepared = normalize_thai_for_tts(text) if self._normalize else text
        payload = {
            "model": self._model,
            "voice": voice or self._voice,
            "input": prepared,
            "response_format": self._response_format,
        }
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream("POST", self._url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        yield AudioChunk(
                            chunk, sample_rate=self.sample_rate, channels=1, fmt=self.output_format
                        )


_CT_FMT = {
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/aac": "aac",
    "audio/flac": "flac",
}


def audio_format_from_content_type(content_type: str) -> str:
    """Map a MIME type to the ``format`` string OpenRouter STT expects."""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _CT_FMT:
        return _CT_FMT[ct]
    if "/" in ct:
        sub = ct.split("/", 1)[1]
        return "mp3" if sub == "mpeg" else sub
    return "wav"


class OpenRouterSTT(BaseSTT):
    """OpenRouter `/audio/transcriptions` — JSON body with base64 ``input_audio``.

    NOTE: OpenRouter's STT is NOT the OpenAI multipart shape — it takes
    ``{model, input_audio:{data, format}}`` and returns ``{text, usage}``.
    """

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float = 90.0) -> None:
        self._url = f"{base_url.rstrip('/')}/audio/transcriptions"
        self._key = api_key
        self._model = model
        self._timeout = timeout

    async def transcribe(
        self, audio, *, filename="audio.webm", content_type="audio/webm", language=None
    ) -> STTResult:
        import base64

        payload: dict = {
            "model": self._model,
            "input_audio": {
                "data": base64.b64encode(audio).decode("ascii"),
                "format": audio_format_from_content_type(content_type),
            },
        }
        if language:
            payload["language"] = language
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(self._url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        usage = data.get("usage") or {}
        return STTResult(text=(data.get("text") or "").strip(), duration_s=usage.get("seconds"))


# ── Thai text normalization for TTS ─────────────────────────────────────────
_DIGITS = ["ศูนย์", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"]
_PLACES = ["", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน"]
_NUM_RE = re.compile(r"\d[\d,]*")


def read_thai_number(n: int) -> str:
    """Read a non-negative integer as Thai words (สิบ/ยี่สิบ/เอ็ด rules applied)."""
    if n == 0:
        return _DIGITS[0]
    if n >= 1_000_000:  # split on millions, recurse
        high, low = divmod(n, 1_000_000)
        return read_thai_number(high) + "ล้าน" + (read_thai_number(low) if low else "")
    out = ""
    digits = [int(d) for d in str(n)]
    length = len(digits)
    for i, d in enumerate(digits):
        place = length - i - 1  # 0=units .. 5=แสน
        if d == 0:
            continue
        if place == 1 and d == 1:
            out += "สิบ"
        elif place == 1 and d == 2:
            out += "ยี่สิบ"
        elif place == 0 and d == 1 and length > 1:
            out += "เอ็ด"
        else:
            out += _DIGITS[d] + _PLACES[place]
    return out


def normalize_thai_for_tts(text: str) -> str:
    """Convert digit runs to Thai words so TTS pronounces them naturally.

    English-word transliteration (window → วินโดว์) is a documented future hook —
    it needs a lexicon and is left to the provider / a later pass.
    """

    def repl(m: re.Match) -> str:
        raw = m.group(0).replace(",", "")
        try:
            return read_thai_number(int(raw))
        except ValueError:
            return m.group(0)

    return _NUM_RE.sub(repl, text)


__all__ = [
    "AudioChunk",
    "STTResult",
    "BaseSTT",
    "BaseTTS",
    "OpenAICompatSTT",
    "OpenAICompatTTS",
    "OpenRouterSTT",
    "audio_format_from_content_type",
    "read_thai_number",
    "normalize_thai_for_tts",
]
