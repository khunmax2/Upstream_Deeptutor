"""When does a spoken command belong to the agent loop? (Phase D2 routing)

This matcher is a FREE SHORT-CIRCUIT, not the loop's only door. Lexical
verb-matching can never cover how differently people phrase tasks (live-
tested: "กลับไป..." fell through until the verb was added — and the next
phrasing would fall through too). The catch-all is semantic: any utterance
that reaches the chat LLM can be routed by the model itself via the
``ui_agent_task`` tool (see ``ui_control.UIAgentTaskTool``), because the
model that already understood the sentence is the right router.

What this file still buys: when a phrasing DOES match, the turn skips the
chat LLM call entirely — ~ms and zero tokens instead of one completion.
So keep the list honest (obvious, common phrasings), and let the tool
route the long tail; a miss here costs one chat call, not a failed task.

The click-miss/ambiguous seams in the pipeline are the remaining doors —
they catch single-step phrasings whose target isn't on the current screen.
"""

from __future__ import annotations

# Verbs that open a page command (mirrors the fast path's verb families).
# Longest-first within a family (e.g. "กลับไปที่" before "กลับ") so the
# opener consumed is the most specific match, not just any short prefix.
_ACTION_VERBS = (
    "กลับไปที่",
    "กลับไปหน้า",
    "กลับไป",
    "กลับ",
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
    # Spoken Thai clips "ค้นหา" to "ค้น" routinely (live: "ไปhomeแล้วค้นราคาน้ำมัน"
    # slipped through and died as a navigate-only turn). Safe as a substring:
    # unlike "หา" it does not appear inside common nouns.
    "ค้น",
    "เสิร์ช",
    "เซิร์ช",
    "search",
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

# Rule 2 (spoken Thai drops connectors — live-tested: "ไปตั้งค่าเปลี่ยนธีมมืด"):
# a NAVIGATION opener followed by a second action verb is a task even with no
# "แล้ว" between the steps. Restricted to nav openers on purpose — a click
# opener + second verb ("กดปุ่มเปลี่ยนธีม") is usually ONE button whose label
# contains a verb, and the click rung (with its own agent seams) owns those.
_NAV_OPENERS = ("กลับไปที่", "กลับไปหน้า", "กลับไป", "กลับ", "ไปที่", "ไปหน้า", "ไป", "เปิด")
# Verbs scanned for in the remainder. "หา" is excluded: as a substring it
# false-fires inside ordinary nouns ("ปัญหา", "เลขหา…"); "ค้นหา" covers search.
_SECOND_STEP_VERBS = tuple(v for v in _ACTION_VERBS if v not in ("หา", "ไป", "กลับ"))


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

    # Rule 1: explicit connector + a real second step after it.
    for marker in _SEQUENCE_MARKERS:
        pos = rest.find(marker)
        # -1 = not found. 0 IS valid: an object-less opener ("กลับไป") can
        # butt straight up against the connector ("กลับไปแล้วเปิด...").
        if pos < 0:
            continue
        after = rest[pos + len(marker) :]
        # "…แล้วกัน" / "…แล้วนะ" are sentence particles, not second steps —
        # require a real action verb after the connector.
        if any(v in after for v in _ACTION_VERBS):
            return t

    # Rule 2: nav opener + a second action verb later in the sentence,
    # connector elided ("ไปตั้งค่า เปลี่ยนธีมมืด"). The verb must not sit at
    # position 0 of the remainder — that is a compound opener, not a step
    # ("เปิด เปลี่ยนธีม"? no: position 0 means the opener itself continues).
    if opener in _NAV_OPENERS and any(rest.find(v) > 0 for v in _SECOND_STEP_VERBS):
        return t

    return None
