"""When does a spoken command belong to the agent loop? (Phase D2 routing)

The gated-pipeline rule: simple commands stay on the deterministic fast path
(free, ~ms); the loop takes over only when the utterance is a *task* — several
actions chained in one breath ("ไปตั้งค่าแล้วเปลี่ยนธีมมืด"). Detection is
deterministic on purpose: an action verb opening the sentence, a sequencing
connector, and a second action verb after it. No LLM is spent deciding whether
to spend an LLM.

The click-miss/ambiguous seams in the pipeline are the OTHER doors into the
loop — this matcher only catches the multi-step phrasings that would otherwise
half-match a single-step fast-path rung and do half the job.
"""

from __future__ import annotations

# Verbs that open a page command (mirrors the fast path's verb families).
_ACTION_VERBS = (
    "ไปที่",
    "ไปหน้า",
    "ไป",
    "เปิด",
    "กดที่",
    "กดปุ่ม",
    "กด",
    "คลิก",
    "พิมพ์",
    "ใส่",
    "กรอก",
    "เลือก",
    "ค้นหา",
    "หา",
    "เปลี่ยน",
    "สร้าง",
    "ปิด",
    "ลบ",
    "แก้",
)

# "then" connectors — the smell of a multi-step task.
_SEQUENCE_MARKERS = ("แล้ว", "จากนั้น", "ต่อด้วย", "เสร็จ", "ค่อย", "and then", "then")

# Questions are conversation, not tasks ("ทำไมต้องไปตั้งค่าแล้วเปลี่ยนธีม?").
_QUESTION_WORDS = ("ไหม", "มั้ย", "อะไร", "ทำไม", "ยังไง", "อย่างไร", "เท่าไหร่", "หรือเปล่า", "?")

_MAX_TASK_CHARS = 120


def match_agent_task(text: str) -> str | None:
    """The task string when *text* reads as a multi-step page task, else None."""
    t = (text or "").strip()
    if not t or len(t) > _MAX_TASK_CHARS:
        return None
    lowered = t.lower()
    if any(q in lowered for q in _QUESTION_WORDS):
        return None

    opener = next((v for v in _ACTION_VERBS if lowered.startswith(v)), None)
    if opener is None:
        return None

    rest = lowered[len(opener) :]
    for marker in _SEQUENCE_MARKERS:
        pos = rest.find(marker)
        if pos <= 0:
            continue
        after = rest[pos + len(marker) :]
        # "…แล้วกัน" / "…แล้วนะ" are sentence particles, not second steps —
        # require a real action verb after the connector.
        if any(v in after for v in _ACTION_VERBS):
            return t
    return None
