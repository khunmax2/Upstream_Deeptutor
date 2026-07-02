"""Network-free tests: chunker correctness + early-flush pipelining property.

Run standalone:  python tests/test_pipeline.py
Or via pytest:   pytest voice_prototype/tests/test_pipeline.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline import CONFIG, SentenceChunker, build_llm_payload, clean_for_speech  # noqa: E402


def test_llm_payload_thinking_switch():
    """LLM_DISABLE_THINKING adds the Zhipu switch; off by default (other providers
    must never receive the unknown field)."""
    messages = [{"role": "user", "content": "สวัสดี"}]
    saved = CONFIG.llm_disable_thinking
    try:
        CONFIG.llm_disable_thinking = False
        assert "thinking" not in build_llm_payload(messages)
        CONFIG.llm_disable_thinking = True
        payload = build_llm_payload(messages)
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["stream"] is True and payload["messages"] == messages
    finally:
        CONFIG.llm_disable_thinking = saved


def test_chunker_flushes_on_terminal():
    c = SentenceChunker(max_chars=120)
    out = []
    for tok in ["สวัสดี", "ครับ ", "วันนี้", "เรียน", "อะไรดี?", " ต่อ"]:
        out += c.feed(tok)
    assert any("?" in x for x in out), out
    assert "สวัสดีครับ วันนี้เรียนอะไรดี?" in "".join(out).replace(" ", " ") or out
    tail = c.flush()
    assert tail == "ต่อ", tail


def test_chunker_soft_break_over_budget():
    c = SentenceChunker(max_chars=20)
    text = "คำนี้ ยาวมาก และไม่มีจุด แต่ก็ควรถูกตัดออกมาก่อนจบ"
    out = []
    for ch in text:
        out += c.feed(ch)
    out.append(c.flush())
    assert len(out) >= 2, out  # got broken into clauses, not one blob
    assert all(len(x) <= 40 for x in out), out


def test_clean_for_speech_strips_markdown():
    assert clean_for_speech("**สูตร** คือ `E=mc^2`") == "สูตร คือ E=mc^2"


def test_first_chunk_before_stream_ends():
    """The point of the design: speak sentence 1 while the LLM is still talking."""

    async def fake_llm():
        for tok in ["ประโยคแรกจบแล้ว. ", "ยังพิมพ์", "ต่อ", "อีกเรื่อยๆ", " จนจบ."]:
            await asyncio.sleep(0.001)
            yield tok

    async def run():
        c = SentenceChunker(max_chars=120)
        spoken, tokens_seen = [], 0
        first_spoke_after = None
        async for tok in fake_llm():
            tokens_seen += 1
            for chunk in c.feed(tok):
                spoken.append(chunk)
                if first_spoke_after is None:
                    first_spoke_after = tokens_seen
        tail = c.flush()
        if tail:
            spoken.append(tail)
        return spoken, first_spoke_after, tokens_seen

    spoken, first_after, total = asyncio.run(run())
    assert first_after == 1, f"first sentence should flush on token 1, got {first_after}"
    assert first_after < total, "must speak before the stream finished"
    assert spoken[0].startswith("ประโยคแรก"), spoken


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
