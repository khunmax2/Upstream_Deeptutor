"""No-mic latency probe: type Thai text → LLM(stream) → per-sentence TTS.

Proves the LLM+TTS half against your real endpoints without audio hardware.
Needs LLM_* (and a TTS backend) configured; STT is skipped here.

    python selftest.py "อธิบายทฤษฎีบทพีทาโกรัสสั้นๆ"
"""

from __future__ import annotations

import asyncio
import sys
import time

from config import CONFIG
from pipeline import SentenceChunker, stream_llm, synthesize


async def main(prompt: str) -> None:
    messages = [
        {"role": "system", "content": CONFIG.system_prompt},
        {"role": "user", "content": prompt},
    ]
    chunker = SentenceChunker(max_chars=CONFIG.chunk_max_chars)
    t0 = time.perf_counter()
    first_token = first_audio = None
    nchunks = 0

    async for token in stream_llm(messages):
        if first_token is None:
            first_token = time.perf_counter()
            print(f"[LLM TTFT]   {round((first_token - t0) * 1000)} ms")
        for chunk in chunker.feed(token):
            audio, _ctype, tts_s = await synthesize(chunk)
            nchunks += 1
            if first_audio is None:
                first_audio = time.perf_counter()
                print(
                    f"[TTS first]  {round(tts_s * 1000)} ms  "
                    f"(first audio at {round((first_audio - t0) * 1000)} ms)"
                )
            print(f"  ♪ chunk {nchunks}: {len(audio):>6} bytes  «{chunk}»")
    tail = chunker.flush()
    if tail:
        audio, _ctype, _ = await synthesize(tail)
        print(f"  ♪ chunk {nchunks + 1}: {len(audio):>6} bytes  «{tail}»")
    print(
        f"[TOTAL]      {round((time.perf_counter() - t0) * 1000)} ms  backend={CONFIG.tts_backend}"
    )


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "อธิบายทฤษฎีบทพีทาโกรัสสั้นๆ"
    asyncio.run(main(text))
