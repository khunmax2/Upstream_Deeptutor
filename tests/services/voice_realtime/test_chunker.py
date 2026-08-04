"""Tests for the realtime sentence chunker.

The behavioural contract that matters for "feels like a phone call": the first
sentence must flush while the stream is still going, and long Thai clauses must
break on soft boundaries instead of piling into one late blob.
"""

from __future__ import annotations

from deeptutor.services.voice_realtime.chunker import SentenceChunker


def test_flushes_on_hard_terminal() -> None:
    c = SentenceChunker(max_chars=120)
    out: list[str] = []
    for tok in ["สวัสดี", "ครับ ", "วันนี้", "เรียน", "อะไรดี?", " ต่อ"]:
        out += c.feed(tok)
    assert any("?" in chunk for chunk in out), out
    assert c.flush() == "ต่อ"


def test_soft_break_over_budget() -> None:
    c = SentenceChunker(max_chars=20)
    text = "คำนี้ ยาวมาก และไม่มีจุด แต่ก็ควรถูกตัดออกมาก่อนจบ"
    out: list[str] = []
    for ch in text:
        out += c.feed(ch)
    tail = c.flush()
    if tail:
        out.append(tail)
    assert len(out) >= 2, out  # broken into clauses, not one blob
    assert all(len(chunk) <= 40 for chunk in out), out


def test_first_chunk_flushes_before_stream_ends() -> None:
    """The design property: speak sentence 1 while the LLM is still talking."""
    tokens = ["ประโยคแรกจบแล้ว. ", "ยังพิมพ์", "ต่อ", "อีกเรื่อยๆ", " จนจบ."]
    c = SentenceChunker(max_chars=120)
    spoken: list[str] = []
    first_spoke_after: int | None = None
    for i, tok in enumerate(tokens, start=1):
        for chunk in c.feed(tok):
            spoken.append(chunk)
            if first_spoke_after is None:
                first_spoke_after = i
    tail = c.flush()
    if tail:
        spoken.append(tail)

    assert first_spoke_after == 1, first_spoke_after
    assert first_spoke_after < len(tokens), "must speak before the stream finished"
    assert spoken[0].startswith("ประโยคแรก"), spoken


def test_empty_and_whitespace_tokens_never_emit_blank_chunks() -> None:
    c = SentenceChunker(max_chars=120)
    out: list[str] = []
    for tok in ["", "   ", "\n", "ก."]:
        out += c.feed(tok)
    assert all(chunk.strip() for chunk in out), out
    assert "".join(out).replace(" ", "") == "ก."
