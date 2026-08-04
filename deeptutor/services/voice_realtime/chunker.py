"""Sentence chunker — split a streamed LLM reply into speakable clauses.

The whole point of the realtime layer is to start speaking sentence 1 *before*
the model has finished the answer. As tokens arrive, :class:`SentenceChunker`
emits a chunk as soon as a clause boundary is reached (a terminal punctuation
mark, or — once a clause runs over budget — the last soft break), so the
pipeline can synthesize and stream that chunk's audio while later tokens are
still coming in.

Thai has no word spaces, so spaces and the *mai-yamok* (ๆ) are treated as soft
break points: a long Thai clause still flushes before the model finishes rather
than piling up into one late blob. Markdown stripping is **not** done here —
that is owned by the TTS facade (``synthesize_speech`` →
``strip_markdown_for_speech``); the chunker only decides *where* to cut.
"""

from __future__ import annotations

# Hard sentence terminals — cut right after one of these wherever it appears.
_TERMINALS = "。．.!?！？\n…"
# Soft break points used only once a clause is over budget (Thai has no word
# spaces, so the mai-yamok and punctuation double as clause boundaries).
_SOFT = " \tๆ,;:、，"


class SentenceChunker:
    """Accumulate streamed tokens; emit speakable chunks at clause boundaries."""

    def __init__(self, max_chars: int = 120) -> None:
        self.max_chars = max_chars
        self._buf = ""

    def feed(self, token: str) -> list[str]:
        """Add one streamed token; return any chunks that are ready to speak."""
        out: list[str] = []
        self._buf += token
        while True:
            cut = self._find_cut()
            if cut is None:
                break
            chunk, self._buf = self._buf[:cut].strip(), self._buf[cut:].lstrip()
            if chunk:
                out.append(chunk)
        return out

    def _find_cut(self) -> int | None:
        # Hard terminal anywhere → cut right after it.
        for i, ch in enumerate(self._buf):
            if ch in _TERMINALS:
                return i + 1
        # Otherwise, once we're over budget, cut at the last soft break.
        if len(self._buf) >= self.max_chars:
            soft = max((self._buf.rfind(c) for c in _SOFT), default=-1)
            if soft > 0:
                return soft + 1
            return len(self._buf)  # no break available — flush as-is
        return None

    def flush(self) -> str:
        """Return whatever is left in the buffer (the final, unterminated tail)."""
        chunk, self._buf = self._buf.strip(), ""
        return chunk


__all__ = ["SentenceChunker"]
