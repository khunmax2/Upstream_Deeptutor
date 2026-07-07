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

# Spoken once when a call connects, before the caller says anything — a phone
# that answers with silence feels dead.
GREETING_LINE = "สวัสดีครับ มีอะไรให้ผมช่วยไหมครับ"

# Spoken by the deterministic navigation shortcut (see ui_control.
# match_navigation_intent) — the screen has already changed, so this is the
# whole reply.
NAV_ACK_LINE = "ได้เลยครับ"

# Spoken for a stop/quiet control command. One syllable: the correct answer to
# "stop talking" is near-silence, never a paragraph about having stopped.
STOP_ACK_LINE = "ครับ"

# Spoken when the caller answers "ไม่" to a navigation confirmation
# ("คุณหมายถึงให้เปิด X ใช่ไหมครับ") — acknowledge and wait, no LLM turn.
CONFIRM_NO_ACK_LINE = "โอเคครับ"

# Secretary (dictation) mode boundaries. Entering states the contract in one
# breath — everything said will be typed — because a moded UI must never
# leave the user guessing which mode they are in (the Dragon lesson).
SECRETARY_ON_LINE = "เปิดโหมดเลขาแล้วครับ พูดได้เลย ผมจะพิมพ์ลงแชทให้ทุกประโยค"
SECRETARY_OFF_LINE = "ปิดโหมดเลขาแล้วครับ"

# Spoken when a dictation arrives while the caller is not on the chat page —
# the typed message would land somewhere they can't see. Short, states the
# problem, and the screen is already navigating as this plays.
SECRETARY_OFFPAGE_LINE = "ตอนนี้ไม่ได้อยู่หน้าแชทครับ ผมพาไปแล้ว พูดอีกครั้งนะครับ"

# Click-by-name outcomes. The miss/ambiguous lines are honest dead-ends —
# never guess a button the caller didn't clearly name.
CLICK_MISS_LINE = "ไม่เห็นปุ่มชื่อนั้นบนจอครับ"
CLICK_AMBIGUOUS_LINE = "มีปุ่มชื่อคล้ายกันหลายปุ่มครับ พูดชื่อเต็มอีกครั้งครับ"

# Spoken by the watchdog when a tool run stays silent past the soft threshold.
# This is the ONLY generic "please wait": a wait line must be earned by an
# actual wait, never spoken pre-emptively for a tool that may finish instantly.
REASSURE_LINE = "รอสักครู่นะครับ กำลังทำให้อยู่ครับ"

# Spoken when a turn goes silent past the hard limit and is aborted as hung.
HANG_LINE = "ขอโทษครับ ใช้เวลานานผิดปกติ รบกวนถามใหม่อีกครั้งได้ไหมครับ"


def filler_for_tool(tool_name: str) -> str:
    """Spoken line for the start of *tool_name*; "" = stay silent.

    Only tools that are *known slow* (retrieval, web, code) get an immediate
    spoken filler. Unknown tools stay silent — many finish in well under a
    second, and announcing a wait that doesn't happen sounds broken. If an
    unknown tool does run long, the watchdog speaks :data:`REASSURE_LINE`
    once the silence is real.
    """
    return _TOOL_FILLERS.get((tool_name or "").strip(), "")


__all__ = [
    "filler_for_tool",
    "CLICK_AMBIGUOUS_LINE",
    "CLICK_MISS_LINE",
    "CONFIRM_NO_ACK_LINE",
    "GREETING_LINE",
    "SECRETARY_OFF_LINE",
    "SECRETARY_OFFPAGE_LINE",
    "SECRETARY_ON_LINE",
    "HANG_LINE",
    "NAV_ACK_LINE",
    "REASSURE_LINE",
    "STOP_ACK_LINE",
]
