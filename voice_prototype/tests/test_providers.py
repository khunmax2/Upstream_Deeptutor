"""Tests for the provider interfaces — Thai number reading + streaming contract.

Run:  python tests/test_providers.py   (or via pytest)
No network: STT/TTS adapters are exercised with a fake httpx transport.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from providers import (  # noqa: E402
    BaseSTT,
    BaseTTS,
    OpenAICompatSTT,
    OpenAICompatTTS,
    OpenRouterSTT,
    audio_format_from_content_type,
    normalize_thai_for_tts,
    read_thai_number,
)


def test_read_thai_number():
    cases = {
        0: "ศูนย์", 1: "หนึ่ง", 10: "สิบ", 11: "สิบเอ็ด", 20: "ยี่สิบ",
        21: "ยี่สิบเอ็ด", 100: "หนึ่งร้อย", 101: "หนึ่งร้อยเอ็ด",
        123: "หนึ่งร้อยยี่สิบสาม", 1000: "หนึ่งพัน", 1_000_000: "หนึ่งล้าน",
    }
    for n, expected in cases.items():
        assert read_thai_number(n) == expected, f"{n} → {read_thai_number(n)} (want {expected})"


def test_normalize_thai_for_tts():
    assert normalize_thai_for_tts("มี 3 ข้อ") == "มี สาม ข้อ"
    assert normalize_thai_for_tts("ราคา 1,000 บาท") == "ราคา หนึ่งพัน บาท"
    assert normalize_thai_for_tts("หน้า 123") == "หน้า หนึ่งร้อยยี่สิบสาม"


def test_adapters_conform_to_interface():
    stt = OpenAICompatSTT(base_url="http://x/v1", api_key="k", model="ptm-asr-1")
    tts = OpenAICompatTTS(base_url="http://x/v1", api_key="k", model="ptm-tts-1", voice="baifern")
    assert isinstance(stt, BaseSTT)
    assert isinstance(tts, BaseTTS)
    assert tts.sample_rate == 24_000 and tts.output_format == "pcm_s16le"


def test_tts_streams_and_collects_with_fake_transport():
    """stream() yields chunks incrementally; synthesize() collects them."""
    import httpx

    pcm = b"\x01\x02" * 8  # 16 bytes of fake PCM

    def handler(request: httpx.Request) -> httpx.Response:
        # verify the Thai normalization ran before the request went out
        import json
        body = json.loads(request.content)
        assert body["input"] == "มี สาม ข้อ", body["input"]
        assert body["voice"] == "baifern"
        return httpx.Response(200, content=pcm)

    tts = OpenAICompatTTS(base_url="http://x/v1", api_key="k", model="ptm-tts-1", voice="baifern")

    async def run():
        # inject a fake transport by monkeypatching the client factory
        orig = httpx.AsyncClient
        httpx.AsyncClient = lambda **kw: orig(transport=httpx.MockTransport(handler), **kw)  # type: ignore
        try:
            chunks = [c async for c in tts.stream("มี 3 ข้อ")]
            collected = await tts.synthesize("มี 3 ข้อ")
        finally:
            httpx.AsyncClient = orig  # type: ignore
        return chunks, collected

    chunks, collected = asyncio.run(run())
    assert chunks and chunks[0].fmt == "pcm_s16le"
    assert collected.data == pcm and collected.sample_rate == 24_000


def test_openrouter_stt_sends_base64_json():
    """OpenRouter STT uses {model, input_audio:{data,format}} JSON, not multipart."""
    import base64
    import json

    import httpx

    audio = b"RIFFfake-webm-bytes"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/audio/transcriptions")
        body = json.loads(request.content)
        assert body["model"] == "openai/gpt-audio-mini"
        assert body["input_audio"]["format"] == "webm"
        assert base64.b64decode(body["input_audio"]["data"]) == audio
        assert body["language"] == "th"
        return httpx.Response(200, json={"text": "สวัสดีครับ", "usage": {"seconds": 1.2}})

    stt = OpenRouterSTT(base_url="https://openrouter.ai/api/v1", api_key="k",
                        model="openai/gpt-audio-mini")

    async def run():
        orig = httpx.AsyncClient
        httpx.AsyncClient = lambda **kw: orig(transport=httpx.MockTransport(handler), **kw)  # type: ignore
        try:
            return await stt.transcribe(audio, content_type="audio/webm", language="th")
        finally:
            httpx.AsyncClient = orig  # type: ignore

    res = asyncio.run(run())
    assert res.text == "สวัสดีครับ" and res.duration_s == 1.2


def test_audio_format_mapping():
    assert audio_format_from_content_type("audio/webm") == "webm"
    assert audio_format_from_content_type("audio/mpeg") == "mp3"
    assert audio_format_from_content_type("audio/wav; codecs=1") == "wav"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
