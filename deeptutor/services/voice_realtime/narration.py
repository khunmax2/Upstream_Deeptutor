"""Spoken filler + reassurance lines for the voice call.

When the agent calls a tool (RAG search, web fetch, …) the turn goes quiet
while the tool runs. On a phone call that silence feels like a dropped line, so
the voice layer speaks a short "hold on, I'm looking that up" line the moment a
``TOOL_CALL`` event arrives, keeps a watchdog reassurance for long runs, and
apologises if a tool hangs past the hard limit. Phrases are Thai-first (the
call is Thai-first); English callers still get intelligible, brief lines.
"""

from __future__ import annotations

# Tool name → what the assistant says the instant that tool starts. Kept short
# so the filler's own TTS (~1–2 s) roughly covers the tool's latency.
_TOOL_FILLERS: dict[str, str] = {
    "rag": "ขอค้นข้อมูลในเอกสารสักครู่นะครับ",
    "read_source": "ขอเปิดดูเอกสารสักครู่นะครับ",
    "web_search": "ขอค้นข้อมูลจากอินเทอร์เน็ตสักครู่นะครับ",
    "paper_search": "ขอค้นงานวิจัยสักครู่นะครับ",
    "web_fetch": "ขอเปิดดูหน้าเว็บสักครู่นะครับ",
    "read_memory": "ขอเปิดดูความจำก่อนนะครับ",
    "code_execution": "ขอคำนวณสักครู่นะครับ",
    "exec": "ขอรันคำสั่งสักครู่นะครับ",
    "github": "ขอดูข้อมูลใน GitHub สักครู่นะครับ",
}

_DEFAULT_FILLER = "รอสักครู่นะครับ กำลังดำเนินการให้อยู่"

# Spoken once when a call connects, before the caller says anything — a phone
# that answers with silence feels dead.
GREETING_LINE = "สวัสดีครับ มีอะไรให้ผมช่วยไหมครับ"

# Spoken by the watchdog when a tool run stays silent past the soft threshold.
REASSURE_LINE = "ยังค้นข้อมูลอยู่นะครับ อีกสักครู่"

# Spoken when a turn goes silent past the hard limit and is aborted as hung.
HANG_LINE = "ขอโทษครับ ใช้เวลานานผิดปกติ รบกวนถามใหม่อีกครั้งได้ไหมครับ"


def filler_for_tool(tool_name: str) -> str:
    """Return the spoken line to play when *tool_name* starts running."""
    return _TOOL_FILLERS.get((tool_name or "").strip(), _DEFAULT_FILLER)


__all__ = ["filler_for_tool", "GREETING_LINE", "HANG_LINE", "REASSURE_LINE"]
