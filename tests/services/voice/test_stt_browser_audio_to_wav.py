"""Browser recordings reach the STT provider as WAV.

Fork. A workplace Whisper-compatible server (``ptm-asr-1`` behind LiteLLM)
answered the chat composer's WebM/Opus recording with HTTP 422 "Failed to
decode audio ... Format not recognised" and transcribed the same speech as
16 kHz mono WAV (measured 2026-09-14). These tests build a real WebM/Opus clip
the way Chrome's MediaRecorder does; they need PyAV, which the image carries
with Manim, and skip where it is absent. The pass-through cases need nothing.
"""

from __future__ import annotations

import io
import math
import struct
import sys
from types import SimpleNamespace
import wave

import pytest

from deeptutor.services.voice.audio_normalize import browser_audio_to_wav, needs_wav


def _wav(seconds: float = 1.0, rate: int = 22_050) -> bytes:
    frames = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * n / rate)))
        for n in range(int(seconds * rate))
    )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(frames)
    return buffer.getvalue()


def _webm_opus(seconds: float = 1.0) -> bytes:
    """WebM container, Opus, 48 kHz mono — what Chrome's MediaRecorder emits."""
    av = pytest.importorskip("av")
    out = io.BytesIO()
    source = av.open(io.BytesIO(_wav(seconds)))
    target = av.open(out, mode="w", format="webm")
    codec = "libopus" if "libopus" in av.codecs_available else "opus"
    stream = target.add_stream(codec, rate=48_000)
    stream.layout = "mono"
    resampler = av.AudioResampler(
        format="s16" if codec == "libopus" else "flt", layout="mono", rate=48_000
    )
    for frame in source.decode(audio=0):
        for resampled in resampler.resample(frame):
            for packet in stream.encode(resampled):
                target.mux(packet)
    for packet in stream.encode(None):
        target.mux(packet)
    target.close()
    return out.getvalue()


def _wav_info(data: bytes) -> tuple[int, int, int]:
    with wave.open(io.BytesIO(data), "rb") as wav:
        return wav.getframerate(), wav.getnchannels(), wav.getnframes()


def test_a_browser_webm_recording_becomes_16k_mono_wav() -> None:
    webm = _webm_opus(1.0)
    audio, filename, content_type = browser_audio_to_wav(webm, "recording.webm", "audio/webm")

    assert audio[:4] == b"RIFF"
    assert (filename, content_type) == ("recording.wav", "audio/wav")
    rate, channels, frames = _wav_info(audio)
    assert (rate, channels) == (16_000, 1)
    assert 14_000 <= frames <= 18_000  # one second, give or take codec padding


def test_an_unlabeled_webm_upload_is_recognised_by_its_bytes() -> None:
    audio, filename, content_type = browser_audio_to_wav(
        _webm_opus(0.5), "blob", "application/octet-stream"
    )
    assert audio[:4] == b"RIFF"
    assert (filename, content_type) == ("blob.wav", "audio/wav")


def test_wav_goes_through_untouched() -> None:
    wav = _wav(0.2)
    assert browser_audio_to_wav(wav, "recording.wav", "audio/wav") == (
        wav,
        "recording.wav",
        "audio/wav",
    )
    assert not needs_wav(wav, "clip.webm", "audio/webm")  # the bytes win over the label


def test_formats_nobody_reported_go_through_untouched() -> None:
    mp3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64
    assert browser_audio_to_wav(mp3, "voice.mp3", "audio/mpeg") == (mp3, "voice.mp3", "audio/mpeg")


def test_a_clip_that_will_not_decode_is_sent_as_recorded() -> None:
    broken = b"\x1a\x45\xdf\xa3" + b"not really a webm file" * 4
    assert browser_audio_to_wav(broken, "recording.webm", "audio/webm") == (
        broken,
        "recording.webm",
        "audio/webm",
    )


def test_without_pyav_the_clip_is_sent_as_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "av", None)  # `import av` now raises ImportError
    webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 64
    assert browser_audio_to_wav(webm, "recording.webm", "audio/webm") == (
        webm,
        "recording.webm",
        "audio/webm",
    )


class _RecordingAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str, str]] = []

    async def transcribe(self, audio, config, *, filename, content_type):  # noqa: ANN001
        self.calls.append((audio, filename, content_type))
        return "ok"

    async def transcribe_cues(self, audio, config, *, filename, content_type):  # noqa: ANN001
        self.calls.append((audio, filename, content_type))
        return []


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> _RecordingAdapter:
    import deeptutor.services.voice as voice

    fake = _RecordingAdapter()
    monkeypatch.setattr(
        "deeptutor.services.config.provider_runtime.resolve_stt_runtime_config",
        lambda catalog=None: SimpleNamespace(language=None, adapter="openai_compat"),
    )
    monkeypatch.setattr(voice, "get_stt_adapter", lambda _name: fake)
    return fake


@pytest.mark.asyncio
async def test_the_provider_receives_wav_for_a_browser_recording(adapter) -> None:
    from deeptutor.services.voice import transcribe_audio

    await transcribe_audio(_webm_opus(0.5), filename="recording.webm", content_type="audio/webm")

    audio, filename, content_type = adapter.calls[-1]
    assert audio[:4] == b"RIFF"
    assert (filename, content_type) == ("recording.wav", "audio/wav")


@pytest.mark.asyncio
async def test_a_voice_call_utterance_reaches_the_provider_as_wav(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The voice-call guard posts multipart itself, so it converts too."""
    from deeptutor.services.voice_realtime import stt_guard

    seen: list[tuple[bytes, str, str]] = []

    async def fake_verbose(audio, config, *, filename, content_type):  # noqa: ANN001
        seen.append((audio, filename, content_type))
        return "ok", None

    monkeypatch.setattr(
        "deeptutor.services.config.provider_runtime.resolve_stt_runtime_config",
        lambda catalog=None: SimpleNamespace(
            language=None, adapter="openai_compat", request_style="multipart"
        ),
    )
    monkeypatch.setattr(stt_guard, "_transcribe_verbose", fake_verbose)

    await stt_guard.transcribe_utterance(_webm_opus(0.5))

    audio, filename, content_type = seen[-1]
    assert audio[:4] == b"RIFF"
    assert (filename, content_type) == ("audio.wav", "audio/wav")


@pytest.mark.asyncio
async def test_timed_transcription_receives_wav_too(adapter) -> None:
    from deeptutor.services.voice import transcribe_audio_cues

    await transcribe_audio_cues(
        _webm_opus(0.5), filename="recording.webm", content_type="audio/webm"
    )

    _audio, filename, content_type = adapter.calls[-1]
    assert (filename, content_type) == ("recording.wav", "audio/wav")
