"""Voice-driven UI control — the "say it, the page does it" seam.

Lets a caller steer the client UI by voice ("ไปหน้า settings", "เปิด knowledge
base"), Botnoi-WebAvatar style but with DeepTutor's own brain:

1. The client declares what can be steered — it sends a **UI manifest** control
   frame after connecting (``{"type": "ui_manifest", "manifest": {...}}``).
   The manifest is a whitelist: pages/actions the page is willing to perform.
2. When a manifest is present on the turn, :class:`VoiceUICapability` activates
   and mounts the :class:`UINavigateTool` on top of chat's normal surface,
   with a system block listing the allowed targets.
3. The LLM calls ``ui_navigate(target=...)``; the voice pipeline forwards the
   ``TOOL_CALL`` to the client as a ``{"type": "ui_action", ...}`` frame; the
   page executes it (switch view, scroll, highlight). The tool itself is a
   server-side no-op — the *client* owns the effect, and only for targets it
   declared.

Everything here is fork-additive: the tool registers through the public
``ToolRegistry.register()`` and the capability is appended to
``deeptutor.capabilities.registry.LOOP_CAPABILITIES`` at runtime by
:func:`install_ui_control` — zero upstream file edits (fork policy §3). The
capability's ``is_active`` is gated on the manifest metadata, so non-voice
turns never see any of this.

Manifest shape (all fields optional, unknown fields ignored)::

    {
      "pages":   [{"id": "settings", "label": "หน้าตั้งค่า"}, ...],
      "actions": [{"id": "open_kb",  "label": "เปิด knowledge base",
                   "argument": "ชื่อ KB"}, ...]
    }

Besides the manifest (what the page *can do*), the client may also stream
**UI context** (what the page *currently shows*): a ``ui_context`` control
frame carrying ``{"path": "/settings", "summary": "หัวข้อ: … | ปุ่ม: …"}``.
The summary is an opaque, size-capped text outline the client serialised from
its own visible DOM — the server never parses it, it only injects it into the
system block so the model can answer "หน้านี้มีเมนูอะไรบ้าง" from the real
screen instead of guessing. Read-only by design: the whitelist above stays the
only path that *acts* on the page.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import UnifiedContext
from deeptutor.core.tool_protocol import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolResult,
)

logger = logging.getLogger(__name__)

UI_NAVIGATE_TOOL = "ui_navigate"
UI_CLICK_TOOL = "ui_click"
UI_FILL_TOOL = "ui_fill"

# Guard rails on the client-supplied manifest (it rides a WS control frame).
MAX_MANIFEST_BYTES = 8_192
_MAX_TARGETS = 64

# Guard rails on the client-supplied screen context. The router already caps
# whole control frames at MAX_MANIFEST_BYTES; these keep what we *store* (and
# re-inject into every turn's prompt) well under that.
_MAX_CONTEXT_SUMMARY_CHARS = 3_000
_MAX_CONTEXT_PATH_CHARS = 200
_MAX_BUTTONS = 40
_MAX_BUTTON_CHARS = 60
# Visible form fields (labels, with a dropdown's options folded into the
# string client-side) — fewer than buttons but each entry can be longer.
_MAX_FIELDS = 20
_MAX_FIELD_CHARS = 120


def sanitize_manifest(raw: Any) -> dict[str, Any] | None:
    """Validate + trim a client manifest; ``None`` when unusable.

    Only the fields the prompt/tool actually use survive: ``pages`` and
    ``actions`` as lists of ``{"id", "label", "argument"}`` string entries,
    capped at ``_MAX_TARGETS`` total. Anything malformed is dropped silently —
    a UI manifest must never be able to crash a call.
    """
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    total = 0
    for section in ("pages", "actions"):
        entries = raw.get(section)
        if not isinstance(entries, list):
            continue
        kept: list[dict[str, str]] = []
        for entry in entries:
            if total >= _MAX_TARGETS:
                break
            if not isinstance(entry, dict):
                continue
            target_id = str(entry.get("id") or "").strip()
            if not target_id:
                continue
            row = {"id": target_id, "label": str(entry.get("label") or target_id).strip()}
            argument = str(entry.get("argument") or "").strip()
            if argument:
                row["argument"] = argument
            kept.append(row)
            total += 1
        if kept:
            out[section] = kept
    return out or None


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def sanitize_ui_context(raw: Any) -> dict[str, Any] | None:
    """Validate + trim a client screen-context frame; ``None`` when unusable.

    Keeps only ``path``, ``page`` (the manifest label of the current page) and
    ``summary`` as control-char-stripped, size-capped strings. Like the
    manifest, malformed input is dropped silently — screen context is a
    nicety and must never be able to crash a call.
    """
    if not isinstance(raw, dict):
        return None
    path = _CONTROL_CHARS.sub("", str(raw.get("path") or "").strip())
    page = _CONTROL_CHARS.sub("", str(raw.get("page") or "").strip())
    summary = _CONTROL_CHARS.sub("", str(raw.get("summary") or "").strip())
    active_field = _CONTROL_CHARS.sub("", str(raw.get("activeField") or "").strip())
    out: dict[str, Any] = {}
    if path:
        out["path"] = path[:_MAX_CONTEXT_PATH_CHARS]
    if page:
        out["page"] = page[:_MAX_CONTEXT_PATH_CHARS]
    if summary:
        out["summary"] = summary[:_MAX_CONTEXT_SUMMARY_CHARS]
    if active_field:
        # The field with the caret right now — Tier A implicit fill targets it.
        out["activeField"] = active_field[:_MAX_FIELD_CHARS]
    # Structured clickables (visible button/tab texts) — the click-by-name
    # rung resolves spoken names against THIS list, never by parsing the
    # summary prose.
    raw_buttons = raw.get("buttons")
    if isinstance(raw_buttons, list):
        buttons: list[str] = []
        for item in raw_buttons:
            text = _CONTROL_CHARS.sub("", str(item or "").strip())[:_MAX_BUTTON_CHARS]
            if text and text not in buttons:
                buttons.append(text)
            if len(buttons) >= _MAX_BUTTONS:
                break
        if buttons:
            out["buttons"] = buttons
    # Structured visible form fields — what fill-by-voice resolves spoken
    # field names against (same contract as `buttons` for clicks). A dropdown
    # entry carries its options inline: "ภาษา (เลือกได้: ไทย | English)".
    raw_fields = raw.get("fields")
    if isinstance(raw_fields, list):
        fields: list[str] = []
        for item in raw_fields:
            text = _CONTROL_CHARS.sub("", str(item or "").strip())[:_MAX_FIELD_CHARS]
            if text and text not in fields:
                fields.append(text)
            if len(fields) >= _MAX_FIELDS:
                break
        if fields:
            out["fields"] = fields
    return out or None


_MAX_RESULT_CHARS = 80


def sanitize_action_result(raw: Any) -> dict[str, Any] | None:
    """Validate + trim a client ``ui_action_result`` frame; ``None`` when unusable.

    The post-action verify verdict the client reports after executing a
    ``ui_action`` (the grounding design's "Verify (after)" stage). Kept as
    data on the session (``nav_state``) so the turn ladder / future agentic
    loop can confirm a step landed before taking the next. Same discipline
    as the other client frames: malformed input drops silently.
    """
    if not isinstance(raw, dict):
        return None
    target = _CONTROL_CHARS.sub("", str(raw.get("target") or "").strip())
    if not target:
        return None
    out: dict[str, Any] = {
        "target": target[:_MAX_RESULT_CHARS],
        "ok": bool(raw.get("ok")),
        "detail": _CONTROL_CHARS.sub("", str(raw.get("detail") or "").strip())[:_MAX_RESULT_CHARS],
    }
    field = _CONTROL_CHARS.sub("", str(raw.get("field") or "").strip())
    if field:
        out["field"] = field[:_MAX_FIELD_CHARS]
    return out


# ── deterministic "which page am I on" answer ─────────────────────────
#
# "ตอนนี้อยู่หน้าไหน" is a fixed-shape question with a known-true answer the
# server already holds (the streamed ui_context) — same species as the stop
# and navigation shortcuts, so it gets the same treatment: match with rules,
# answer without the LLM. This makes the answer model-independent — prompt
# weighting can't regress it when the LLM changes — and near-instant. Matching
# is exact-after-normalisation (the "วันหยุด" lesson): long or compound
# phrasings ("อยู่หน้าไหน แล้วหน้านี้ทำอะไรได้") fall through to the LLM, which
# still gets the per-turn screen note as its safety net.

_WHERE_FILLERS = (
    "ครับ",
    "ค่ะ",
    "คะ",
    "นะ",
    "เนี่ย",
    "อ่ะ",  # NOT bare "อะ" — it would eat the "อะ" in "อะไร"
    "เหรอ",
    "หรอ",
    "แล้ว",
    "ตอนนี้",
    "ที่",
    "คือ",
    "กัน",
    " ",
    "?",
)
_WHERE_FORMS = {
    "อยู่หน้าไหน",
    "อยู่หน้าอะไร",
    "นี่หน้าอะไร",
    "นี่หน้าไหน",
    "หน้าอะไร",
    "หน้าไหน",
    "whereami",
    "whatpage",
    "whatpageisthis",
    "whichpage",
    "whichpageamion",
    "currentpage",
}
_MAX_WHERE_CHARS = 32


def match_where_am_i(text: str) -> bool:
    """Whether *text* is a bare "which page am I on" question."""
    t = (text or "").strip().lower()
    if not t or len(t) > _MAX_WHERE_CHARS:
        return False
    for bit in _WHERE_FILLERS:
        t = t.replace(bit, "")
    return t in _WHERE_FORMS


def spoken_page_name(ui_context: dict[str, str] | None) -> str:
    """The current page's name in speakable form ("" when unknown).

    Manifest labels carry parenthetical hints and slash-separated aliases
    ("หน้าแชทหลัก / หน้าหลัก / หน้าแรก (home, ...)") — spoken, we want just the
    first alias. Empty result = let the LLM turn (with its screen note)
    handle the question instead.
    """
    page = str((ui_context or {}).get("page") or "")
    return page.split("(")[0].split("/")[0].strip()


# ── deterministic navigation shortcut ─────────────────────────────────
#
# Clear navigation commands ("ไปหน้า X", "เปิดหน้า settings") are a fixed-shape
# intent — the same trick production assistants use: match them with rules and
# execute directly, skipping the LLM round entirely. 100% deterministic for
# unambiguous phrasings AND faster (no LLM latency at all). Anything long,
# ambiguous, or multi-intent falls through to the LLM as before.

_NAV_VERBS = ("ไป", "เปิด", "พา", "เข้า", "กลับ", "สลับ", "ขอ", "go", "open", "show")
_NAV_PAGE_WORDS = ("หน้า", "page")
# Longer than this = probably a compound request ("ไปหน้า settings แล้วช่วย…")
# where the LLM should own the turn.
_MAX_SHORTCUT_CHARS = 48
_LABEL_SPLIT = re.compile(r"[\s()/—·,\-]+")


def _page_match_strings(entry: dict[str, Any]) -> set[str]:
    """Strings that count as 'the caller named this page'.

    Each label token is kept both as-is and with a leading "หน้า" stripped, so
    a label alias like "หน้าหลัก" matches "ไปที่หน้าหลัก" (full form) as well
    as looser phrasings.
    """
    out = {str(entry.get("id") or "").strip().lower()}
    label = str(entry.get("label") or "").lower()
    for token in _LABEL_SPLIT.split(label):
        token = token.strip()
        if len(token) >= 3:
            out.add(token)
        if token.startswith("หน้า"):
            token = token[len("หน้า") :]
            if len(token) >= 3:
                out.add(token)
    # Generic words ("หน้า" from a label like "หน้า KB") match every
    # navigation phrase and would make all pages collide into ambiguity.
    out -= set(_NAV_PAGE_WORDS)
    out.discard("")
    return out


# Words that mark the utterance as a *question about* a page rather than a
# command to open it ("หน้าความจำคืออะไร") — those belong to the LLM.
_QUESTION_WORDS = ("อะไร", "คือ", "ไหม", "ทำไม", "ยังไง", "อย่างไร", "ไหน", "เมื่อไหร่")


def _normalize_nav_text(text: str) -> str:
    return (text or "").strip().lower()


# ── fuzzy verb slot (STT-garble tolerance, the generalised fix) ────────
#
# Browser STT garbles the navigation verb constantly: "ไปหน้า" arrives as
# "ไฟหน้า", "ใบหน้า", "ไอหน้า", … A hardcoded garble list loses that war one
# entry at a time. The industry answer is phonetic-aware fuzzy matching on the
# verb slot: take the 2–4 characters right before the page word, normalise
# Thai homophone letters (ใ/ไ are pronounced identically, ณ/น, ศ ษ/ส, …) and
# strip tone marks (STT swaps them freely), then accept an edit distance ≤ 1
# from any known verb. "ไฟ→ไป" (1 sub), "ใบ→ไบ→ไป" (homophone + 1 sub) and
# every future variant land automatically. Safe because the shortcut ALSO
# requires a short utterance naming exactly one manifest page — and anything
# that misses the fuzzy bar entirely still falls into the confirm rung
# ("คุณหมายถึง…ใช่ไหม") rather than being dropped.

_THAI_HOMOPHONES = str.maketrans(
    {
        "ใ": "ไ",
        "ร": "ล",  # casual Thai pronounces ร as ล — STT swaps them freely (เลขา↔เรขา)
        "ณ": "น",
        "ฎ": "ด",
        "ฏ": "ต",
        "ศ": "ส",
        "ษ": "ส",
        "ฬ": "ล",
        "ฆ": "ค",
        "ฑ": "ท",
        "ฒ": "ท",
        "ภ": "พ",
        "ฐ": "ถ",
    }
)
_TONE_MARKS = re.compile(r"[่-๋์]")  # ่ ้ ๊ ๋ ์


def _phonetic(s: str) -> str:
    return _TONE_MARKS.sub("", s.translate(_THAI_HOMOPHONES))


def _edit_distance(a: str, b: str) -> int:
    """Plain Levenshtein — the strings here are 2–5 chars, no need for speed."""
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _has_nav_verb(t: str) -> bool:
    """Whether *t* carries a navigation verb — exact, or garbled within reason.

    Fuzzy pass: for each page word occurrence, compare the 2–4 preceding
    characters (the verb slot) against every verb of length ≥ 2, phonetically
    normalised, accepting edit distance ≤ 1.
    """
    if any(v in t for v in _NAV_VERBS):
        return True
    for w in _NAV_PAGE_WORDS:
        start = t.find(w)
        if start <= 0:
            continue
        prefix = t[max(0, start - 4) : start]
        for length in (2, 3, 4):
            cand = _phonetic(prefix[-length:])
            if len(cand) < 2:
                continue
            for verb in _NAV_VERBS:
                if len(verb) >= 2 and _edit_distance(cand, _phonetic(verb)) <= 1:
                    return True
    return False


def _unique_page_hit(t: str, manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    """The single manifest page named in *t*, or ``None`` if zero/ambiguous."""
    hits: list[dict[str, Any]] = []
    for entry in (manifest or {}).get("pages") or []:
        if not isinstance(entry, dict):
            continue
        if any(m in t for m in _page_match_strings(entry)):
            if entry.get("id") and entry not in hits:
                hits.append(entry)
    return hits[0] if len(hits) == 1 else None


def match_navigation_intent(text: str, manifest: dict[str, Any] | None) -> dict[str, str] | None:
    """Return ``{"target": id}`` when *text* is an unambiguous page command.

    Conservative on purpose: requires a navigation verb (exact or an STT
    garble within one phonetic edit — see ``_has_nav_verb``), a page word, a
    short utterance, and exactly ONE matching manifest page. Everything else
    returns ``None`` and the LLM decides (multi-intent, ambiguity, non-UI
    questions).
    """
    if not manifest:
        return None
    t = _normalize_nav_text(text)
    if not t or len(t) > _MAX_SHORTCUT_CHARS:
        return None
    if not any(w in t for w in _NAV_PAGE_WORDS):
        return None
    if any(q in t for q in _QUESTION_WORDS):
        return None  # "ไฟหน้าตั้งค่าคืออะไร" is a question, not a command
    if not _has_nav_verb(t):
        return None
    hit = _unique_page_hit(t, manifest)
    if hit is None:
        return None
    return {"target": str(hit["id"])}


def match_navigation_guess(text: str, manifest: dict[str, Any] | None) -> dict[str, str] | None:
    """A *probable* page command that needs spoken confirmation first.

    Fires when the utterance is short, names exactly one manifest page with a
    page word, is NOT a question — but lacks a navigation verb (usually STT
    dropping/garbling it, e.g. "หน้าหน่วยความจำ"). The caller should be asked
    "คุณหมายถึงให้เปิด X ใช่ไหมครับ" rather than silently guessing or, worse,
    acknowledging without acting. Returns ``{"target", "label"}`` with a
    speakable label, or ``None``.
    """
    if not manifest:
        return None
    t = _normalize_nav_text(text)
    if not t or len(t) > _MAX_SHORTCUT_CHARS:
        return None
    if not any(w in t for w in _NAV_PAGE_WORDS):
        return None
    if any(q in t for q in _QUESTION_WORDS):
        return None
    if _has_nav_verb(t):
        return None  # a (possibly garbled) verbed command is match_navigation_intent's job
    hit = _unique_page_hit(t, manifest)
    if hit is None:
        return None
    label = str(hit.get("label") or hit["id"]).split("(")[0].split("/")[0].strip()
    return {"target": str(hit["id"]), "label": label or str(hit["id"])}


# ── deterministic in-page action shortcut ──────────────────────────────
#
# Fixed-shape action commands ("สร้างแชทใหม่", "ย้อนกลับ") get the same
# treatment as page navigation: match with rules, dispatch without the LLM.
# The E2E lesson repeating itself — the LLM sometimes acknowledges these
# without calling the tool (sampling), and a fixed-shape command should never
# be a coin flip. Only actions whose utterance carries everything needed are
# listed here; open_kb stays on the LLM path because it needs the KB *name*
# interpreted (often against what's visible on screen).

_ACTION_PATTERNS: dict[str, tuple[str, ...]] = {
    "new_chat": ("สร้างแชทใหม่", "เริ่มแชทใหม่", "เปิดแชทใหม่", "แชทใหม่", "คุยเรื่องใหม่", "new chat"),
    "go_back": ("ย้อนกลับ", "กลับหน้าเดิม", "กลับหน้าที่แล้ว", "ถอยกลับ", "go back"),
    # Scroll: verb+direction pairs so bare "เลื่อน" ("เลื่อนนัดประชุม" =
    # reschedule!) never triggers. "เลื่อนลงล่างสุด" hits two ids → ambiguous
    # → LLM decides; fine, it's rare.
    "scroll_down": ("เลื่อนลง", "ปัดลง", "สกอลง", "scroll down", "เลื่อนหน้าจอลง"),
    "scroll_up": ("เลื่อนขึ้น", "ปัดขึ้น", "สกอขึ้น", "scroll up", "เลื่อนหน้าจอขึ้น"),
    "scroll_bottom": ("ล่างสุด", "ท้ายสุดของหน้า", "ท้ายหน้า", "scroll to bottom"),
    "scroll_top": ("บนสุด", "หัวหน้าเพจ", "ต้นหน้า", "scroll to top"),
}

# Action patterns get the same STT-garble tolerance as navigation verbs:
# match on the phonetic fold (homophones + tone marks + spaces), then a
# start-anchored edit-distance-1 pass. Live failure this closes: "เลื่อนลง"
# arriving as "เลือนลง"/"เลื่อน ลง"/"เลื่อนหลง" fell past the shortcut to the
# LLM, which sometimes acked without acting. The fuzzy pass is anchored to the
# utterance head (commands start with the verb; a polite prefix may precede
# it) so mid-sentence sound-alikes ("เอาเลื่อยลงมา…") stay out of reach.
_ACTION_POLITE_PREFIXES = ("ช่วย", "ขอ", "รบกวน", "please")
_ACTION_FUZZY_MIN_CHARS = 5
_ACTION_FUZZY_MAX_OFFSET = 3


def _fold_action_text(s: str) -> str:
    return _phonetic(s.lower()).replace(" ", "")


def _action_pattern_hit(t_fold: str, pattern: str) -> bool:
    p = _fold_action_text(pattern)
    if p in t_fold:
        return True
    if len(p) < _ACTION_FUZZY_MIN_CHARS:
        return False
    head = t_fold
    for prefix in _ACTION_POLITE_PREFIXES:
        folded = _fold_action_text(prefix)
        if head.startswith(folded):
            head = head[len(folded) :]
            break
    for offset in range(_ACTION_FUZZY_MAX_OFFSET):
        for width in (len(p) - 1, len(p), len(p) + 1):
            seg = head[offset : offset + width]
            if len(seg) >= len(p) - 1 and _edit_distance(seg, p) <= 1:
                return True
    return False


def match_action_intent(text: str, manifest: dict[str, Any] | None) -> dict[str, str] | None:
    """Return ``{"target": id}`` when *text* is a clear declared-action command.

    Same conservatism as the page matcher: short utterance, not a question,
    exactly ONE matching action, and the action must be declared in the
    manifest. Runs AFTER the page matcher so "ย้อนกลับไปหน้าหลัก" (which names
    a page) navigates rather than triggering go_back.
    """
    if not manifest:
        return None
    t = _normalize_nav_text(text)
    if not t or len(t) > _MAX_SHORTCUT_CHARS:
        return None
    if any(q in t for q in _QUESTION_WORDS):
        return None
    declared = {
        str(entry.get("id"))
        for entry in manifest.get("actions") or []
        if isinstance(entry, dict) and entry.get("id")
    }
    t_fold = _fold_action_text(t)
    hits: list[str] = []
    for action_id, patterns in _ACTION_PATTERNS.items():
        if action_id in declared and any(_action_pattern_hit(t_fold, p) for p in patterns):
            hits.append(action_id)
    if len(hits) != 1:
        return None
    return {"target": hits[0]}


# ── click-by-name: press a visible button the caller names ─────────────
#
# The middle rung between curated actions and a full page-agent: the CALLER
# points ("กดปุ่มสร้างโน้ตใหม่"), the system only verifies the named button is
# actually visible right now (the streamed ui_context carries the clickable
# texts) and tells the client to press that exact text. No LLM chooses a
# button, ever — see → name → act, with the human doing the naming.

_CLICK_PREFIXES = (  # longest first so "กดปุ่ม" wins over "กด"
    "ช่วยกดปุ่ม",
    "ช่วยคลิกปุ่ม",
    "กดปุ่ม",
    "คลิกปุ่ม",
    "แตะปุ่ม",
    "จิ้มปุ่ม",
    "ช่วยกด",
    "ช่วยคลิก",
    "กด",
    "คลิก",
    "แตะ",
    "click",
)
_CLICK_TRAILING = ("ให้หน่อย", "หน่อย", "ให้ที", "ที", "ครับ", "ค่ะ", "คะ", "นะ", "เลย", "ด้วย")
# Connectives between the verb and the name ("กดที่ประวัติแชต", "กดที่ปุ่ม X")
# — leaked into the name they make every lookup miss. Longest first.
_CLICK_LEADING = ("ตรงที่", "ที่", "ตรง", "ปุ่ม", "การ์ด", "เมนู", "ลิงก์")
_MAX_CLICK_CHARS = 48

# Button texts that may have irreversible effects — never pressed without a
# spoken confirmation (the Siri send-message lesson).
_DANGER_WORDS = (
    "ลบ",
    "ยกเลิก",
    "ล้าง",
    "รีเซ็ต",
    "ออกจากระบบ",
    "delete",
    "remove",
    "reset",
    "clear",
    "logout",
    "sign out",
)


def match_click_intent(text: str) -> str | None:
    """The button name in a "กดปุ่ม X" command, else ``None``.

    Requires the utterance to START with a click verb (mid-sentence "กด" is
    conversation), be short, and not be a question. The returned name is what
    the caller said — resolution against the actually visible buttons happens
    in :func:`resolve_click_target`.
    """
    t = _normalize_nav_text(text)
    if not t or len(t) > _MAX_CLICK_CHARS:
        return None
    if any(q in t for q in _QUESTION_WORDS):
        return None
    for prefix in _CLICK_PREFIXES:
        if t.startswith(prefix):
            name = t[len(prefix) :].strip()
            # Peel leading connectives ("ที่ / ปุ่ม / ตรงที่ …") until stable —
            # "กดที่ปุ่มประวัติแชต" must resolve the bare name.
            while True:
                trimmed = name
                for lead in _CLICK_LEADING:
                    trimmed = trimmed.removeprefix(lead).strip()
                if trimmed == name:
                    break
                name = trimmed
            # Peel trailing politeness until stable ("…ให้หน่อยครับ").
            while True:
                trimmed = name
                for tail in _CLICK_TRAILING:
                    trimmed = trimmed.removesuffix(tail).strip()
                if trimmed == name:
                    break
                name = trimmed
            return name or None
    return None


# ── fill-by-voice: type into / select in a form field the caller names ─
#
# Same trust model as click-by-name: the CALLER points at a field and says
# the value ("พิมพ์ กฎหมายแรงงาน ในช่องค้นหา"); the system only verifies the
# named field is visible right now (ui_context.fields) and tells the client
# to set that exact field. The LLM never picks a field or invents a value.
# Typing is non-destructive by design — nothing is submitted; pressing a
# submit button stays a separate (click) step with its own danger rung.

_FILL_VERBS = (  # longest first so "ช่วยพิมพ์" wins over "พิมพ์"
    "ช่วยพิมพ์",
    "ช่วยใส่",
    "ช่วยกรอก",
    "ช่วยเลือก",
    "พิมพ์",
    "ใส่",
    "กรอก",
    "เขียน",
    "เลือก",
    "type",
    "fill",
    "select",
)
_FIELD_MARKERS = (  # longest first: "ลงในช่อง" must win over "ในช่อง"
    "ลงในช่อง",
    "ในช่อง",
    "ลงช่อง",
    "ที่ช่อง",
    "ตรงช่อง",
    "ช่อง",
)
# Values are free text — allow longer utterances than nav/click commands.
_MAX_FILL_CHARS = 80


def match_fill_intent(text: str) -> dict[str, str] | None:
    """The ``{"field", "value"}`` of a "พิมพ์ X ในช่อง Y" command, else ``None``.

    Requires the utterance to START with a fill verb, name the field behind an
    explicit "ช่อง" marker, and not be a question. The value keeps the
    caller's original casing/spacing ("LAWs_thai" must be typed as said);
    field resolution against the actually visible fields happens in
    :func:`resolve_field_target`.
    """
    t_orig = (text or "").strip()
    t = t_orig.lower()
    if not t or len(t) > _MAX_FILL_CHARS:
        return None
    if any(q in t for q in _QUESTION_WORDS):
        return None
    for verb in _FILL_VERBS:
        if not t.startswith(verb):
            continue
        rest_orig = t_orig[len(verb) :].strip()
        rest = rest_orig.lower()
        for marker in _FIELD_MARKERS:
            # rfind: the VALUE may itself contain "ช่อง"; the field name
            # (last, short) realistically never contains a marker again.
            idx = rest.rfind(marker)
            if idx <= 0:
                continue
            # "พิมพ์คำว่าสวัสดี" — "คำว่า" is quoting, not content.
            value = rest_orig[:idx].strip().removeprefix("คำว่า").strip()
            field = rest_orig[idx + len(marker) :].strip()
            while True:  # peel trailing politeness off the field name
                trimmed = field
                for tail in _CLICK_TRAILING:
                    trimmed = trimmed.removesuffix(tail).strip()
                if trimmed == field:
                    break
                field = trimmed
            if value and field:
                return {"field": field, "value": value}
        return None
    return None


# ── implicit fill (Tier A): "พิมพ์ X" with NO field named ───────────────
#
# The "he didn't even name the field" UX. When the caller just says "พิมพ์ X"
# the target is inferred deterministically: the focused field (caret), else the
# last field filled this call, else the only visible field. TYPE verbs only —
# "เลือก" (select) is excluded because an implicit dropdown pick is too
# ambiguous. Fires only when a target actually resolves (see
# :func:`implicit_fill_field`); otherwise the pipeline falls through untouched.
_IMPLICIT_FILL_VERBS = ("พิมพ์ว่า", "พิมพ์", "ใส่", "กรอก", "เขียนว่า", "เขียน", "type", "fill")


def match_implicit_fill(text: str) -> str | None:
    """The value for a bare "พิมพ์ X" (no field named), else ``None``.

    Returns ``None`` when a field IS named (that's :func:`match_fill_intent`'s
    job) or when the utterance isn't a bare type command.
    """
    t_orig = (text or "").strip()
    t = t_orig.lower()
    if not t or len(t) > _MAX_FILL_CHARS:
        return None
    if any(q in t for q in _QUESTION_WORDS):
        return None
    if any(m in t for m in _FIELD_MARKERS):
        return None  # names a field → explicit path owns it
    for verb in _IMPLICIT_FILL_VERBS:
        if not t.startswith(verb):
            continue
        value = t_orig[len(verb) :].strip()
        value = value.removeprefix("ว่า").strip().removeprefix("คำว่า").strip()
        while True:  # peel trailing politeness
            trimmed = value
            for tail in _CLICK_TRAILING:
                trimmed = trimmed.removesuffix(tail).strip()
            if trimmed == value:
                break
            value = trimmed
        return value or None
    return None


def implicit_fill_field(
    ui_context: dict[str, Any] | None, nav_state: dict[str, Any] | None
) -> str | None:
    """The field a bare "พิมพ์ X" targets, or ``None`` when it can't be inferred.

    Priority: the focused field (``activeField``, streamed by the client) →
    the last field filled this call (``last_field``, only if still on screen) →
    the single visible field. Ambiguous (2+ fields, none focused/remembered) →
    ``None`` so the caller isn't silently guessed at.
    """
    labels = [
        field_label(entry)
        for entry in (ui_context or {}).get("fields") or []
        if isinstance(entry, str)
    ]
    active = str((ui_context or {}).get("activeField") or "").strip()
    if active:
        return active
    last = str((nav_state or {}).get("last_field") or "").strip()
    if last and last in labels:
        return last
    if len(labels) == 1:
        return labels[0]
    return None


# ── edit-by-voice: undo typing in a field ("ล้างช่อง X", "ลบคำสุดท้าย") ──
#
# The correction half of fill-by-voice. Two curated ops only: clear the whole
# field, or remove the last word. A missing field name means "the field I
# just typed into" — the pipeline remembers the last fill target per call
# (nav_state), Voice-Control style. Anything with a remainder that is not a
# field reference ("ลบโน้ตนี้", "ล้างจานให้หน่อย") falls through: deleting
# *content* elsewhere stays behind the click/confirm rungs.

_EDIT_POLITE_PREFIXES = ("ช่วย", "ขอ", "รบกวน")
# Longest first. Tone-dropped twins (ล้าง→ลาง) are listed outright — the
# cheap fix for a closed, short list.
_EDIT_CLEAR_PREFIXES = (
    "ลบข้อความทั้งหมด",
    "ลบข้อความ",
    "ลบทั้งหมด",
    "ลบที่พิมพ์",
    "ล้างข้อความ",
    "ลางข้อความ",
    "เคลียร์",
    "เคลีย",
    "ล้าง",
    "ลาง",
    "clear",
)
_EDIT_WORD_PREFIXES = (
    "ลบคำสุดท้าย",
    "ลบคำล่าสุด",
    "ลบคำท้าย",
    "ลบหนึ่งคำ",
    "ลบอีกคำ",
    "ถอยหนึ่งคำ",
    "ลบคำ",
    "deletelastword",
)
_EDIT_FIELD_LEADS = ("ในช่อง", "ที่ช่อง", "ของช่อง", "ช่อง")
_MAX_EDIT_CHARS = 48


def match_edit_intent(text: str) -> dict[str, str] | None:
    """``{"op": "clear"|"delete_word", "field": name-or-""}`` for an edit
    command, else ``None``.

    The utterance (politeness peeled) must BE a known edit form: the verb at
    the start and, after it, nothing but an optional field reference. ``""``
    field = apply to the last field this call typed into.
    """
    t = _normalize_nav_text(text).replace(" ", "")
    if not t or len(t) > _MAX_EDIT_CHARS:
        return None
    if any(q in t for q in _QUESTION_WORDS):
        return None
    for prefix in _EDIT_POLITE_PREFIXES:
        if t.startswith(prefix):
            t = t[len(prefix) :]
            break
    while True:  # peel trailing politeness ("…ให้หน่อยครับ")
        trimmed = t
        for tail in _CLICK_TRAILING:
            trimmed = trimmed.removesuffix(tail)
        if trimmed == t:
            break
        t = trimmed
    for op, prefixes in (("delete_word", _EDIT_WORD_PREFIXES), ("clear", _EDIT_CLEAR_PREFIXES)):
        for prefix in prefixes:
            if not t.startswith(prefix):
                continue
            rest = t[len(prefix) :].removeprefix("ออก")
            if not rest:
                return {"op": op, "field": ""}
            for lead in _EDIT_FIELD_LEADS:
                if rest.startswith(lead) and rest[len(lead) :]:
                    return {"op": op, "field": rest[len(lead) :]}
            return None  # a remainder that names no field = not our command
    return None


# Cross-script matching for transliterated loanwords: the screen says
# "เพอร์โซนา" but STT romanises the caller's word to "persona" (or the UI is
# English and the caller speaks Thai). Comparing *consonant skeletons* in
# Latin bridges the scripts: vowels are the unstable part of transliteration,
# consonants survive. Karan-marked consonants (ร์ in เพอร์) are silent — drop.
_KARAN = "์"
_TH_CONSONANT_LATIN = {
    "ก": "k",
    "ข": "k",
    "ค": "k",
    "ฆ": "k",
    "ง": "g",
    "จ": "j",
    "ฉ": "c",
    "ช": "c",
    "ฌ": "c",
    "ซ": "s",
    "ญ": "y",
    "ฎ": "d",
    "ฏ": "t",
    "ฐ": "t",
    "ฑ": "t",
    "ฒ": "t",
    "ณ": "n",
    "ด": "d",
    "ต": "t",
    "ถ": "t",
    "ท": "t",
    "ธ": "t",
    "น": "n",
    "บ": "b",
    "ป": "p",
    "ผ": "p",
    "พ": "p",
    "ฟ": "f",
    "ภ": "p",
    "ม": "m",
    "ย": "y",
    "ร": "r",
    "ล": "l",
    "ฬ": "l",
    "ว": "w",
    "ศ": "s",
    "ษ": "s",
    "ส": "s",
    "ห": "h",
    "ฮ": "h",
}
_LATIN_SOUND_FOLD = str.maketrans({"c": "k", "q": "k", "g": "k", "x": "s", "z": "s", "v": "w"})
# Dropped entirely, both scripts: `h` is mostly digraph residue (th/ph/gh —
# Thai ท/ฟ already carry the sound), and the semivowel `y`/ย is written or
# omitted inconsistently across transliteration ("ไทย" spells /ai/ with ย,
# "thai" spells it with vowels): ลาวไทย → lwt vs laws_thai → lwst.
_SKELETON_NOISE = frozenset("hy")


def _consonant_skeleton(s: str) -> str:
    """Latin consonant skeleton of Thai or Latin text ("เพอร์โซนา"/"persona" → psn/prsn)."""
    s = re.sub(f".{_KARAN}", "", s.lower())  # karan'd consonant is silent
    out: list[str] = []
    for ch in s:
        if ch in _TH_CONSONANT_LATIN:
            out.append(_TH_CONSONANT_LATIN[ch])
        elif ch.isascii() and ch.isalpha() and ch not in "aeiou":
            out.append(ch)
    folded = "".join(out).translate(_LATIN_SOUND_FOLD)
    return "".join(ch for ch in folded if ch not in _SKELETON_NOISE)


# ── weighted resolver ───────────────────────────────────────────────────
#
# One score per candidate instead of the old fixed 4-tier ladder. Label-match
# quality still dominates: the tier scores are spaced (100 apart) wider than
# the sum of every situational boost (30 + 20 = 50), so focus/recency can only
# break a tie WITHIN a label tier — never promote a weaker label match over a
# stronger one, never resurrect a non-match (label score 0 = excluded). That
# invariant is what keeps the regression suite the authority on matching.
_SCORE_EXACT = 400  # normalised text equal
_SCORE_CONTAINS = 300  # substring either way
_SCORE_FUZZY = 200  # phonetic fold within edit budget (STT garbles)
_SCORE_CROSS = 100  # cross-script consonant skeleton (loanwords)
_BOOST_FOCUS = 30  # candidate is the focused field (caret, streamed)
_BOOST_RECENT = 20  # candidate is the last field filled this call


def _label_score(spoken: str, spoken_skeleton: str, candidate: str) -> int:
    """How well *candidate*'s text matches the spoken name (0 = no match)."""
    c = candidate.replace(" ", "").lower()
    if c == spoken:
        return _SCORE_EXACT
    if (len(spoken) >= 3 and spoken in c) or (len(c) >= 3 and c in spoken):
        return _SCORE_CONTAINS
    if _edit_distance(_phonetic(spoken), _phonetic(c)) <= max(1, len(c) // 4):
        return _SCORE_FUZZY
    cs = _consonant_skeleton(c)
    # Budget len//4 (was //3): the looser budget let "ช่องค้นหา" (kkkn) reach
    # "เอเจนต์ของฉัน" (jnkkkn, ed 2) — a live mis-click. All intended
    # cross-script hits sit at ed ≤ 1.
    if (
        len(spoken_skeleton) >= 3
        and len(cs) >= 3
        and _edit_distance(spoken_skeleton, cs) <= max(1, len(cs) // 4)
    ):
        return _SCORE_CROSS
    return 0


def _resolve_spoken_name(
    name: str, candidates: list[str], boosts: dict[str, int] | None = None
) -> tuple[str, str | None]:
    """Resolve a spoken *name* against visible candidate texts.

    Returns ``("hit", text)`` for exactly one top-scored match,
    ``("ambiguous", None)`` for a tie, ``("missing", None)`` for none.
    Each candidate gets a label-match score (exact → substring → phonetic →
    cross-script, see :func:`_label_score`) plus any situational *boosts*
    (focus/recency, capped below the tier spacing — tie-breakers only).
    Shared by click-by-name (buttons) and fill-by-voice (fields).
    """
    spoken = (name or "").replace(" ", "").lower()
    if not spoken or not candidates:
        return ("missing", None)
    spoken_skeleton = _consonant_skeleton(spoken)
    scored: list[tuple[int, str]] = []
    for candidate in candidates:
        label = _label_score(spoken, spoken_skeleton, candidate)
        if label:
            scored.append((label + (boosts or {}).get(candidate, 0), candidate))
    if not scored:
        return ("missing", None)
    top = max(score for score, _ in scored)
    winners = [candidate for score, candidate in scored if score == top]
    if len(winners) == 1:
        return ("hit", winners[0])
    return ("ambiguous", None)


def resolve_click_target(name: str, ui_context: dict[str, Any] | None) -> tuple[str, str | None]:
    """Resolve a spoken button *name* against the visible buttons."""
    buttons = [b for b in (ui_context or {}).get("buttons") or [] if isinstance(b, str)]
    return _resolve_spoken_name(name, buttons)


# A dropdown field entry folds its options into the streamed string
# ("ภาษา (เลือกได้: ไทย | English)"), and a typed input its value type
# ("อีเมล (ชนิด: email)" — Tier B semantics); only the label part left of a
# marker counts when resolving what the caller named. Markers must match the
# client's `formatFieldEntry` (pageContext.ts).
_FIELD_OPTIONS_MARKER = " (เลือกได้:"
_FIELD_TYPE_MARKER = " (ชนิด:"


def field_label(entry: str) -> str:
    """The spoken-matchable label part of a streamed field entry."""
    return entry.split(_FIELD_OPTIONS_MARKER)[0].split(_FIELD_TYPE_MARKER)[0].strip()


def field_options(entry: str) -> list[str]:
    """A streamed field entry's dropdown options ([] for a plain input)."""
    if _FIELD_OPTIONS_MARKER not in entry:
        return []
    tail = entry.split(_FIELD_OPTIONS_MARKER, 1)[1].rstrip(")")
    return [opt.strip() for opt in tail.split("|") if opt.strip()]


def field_options_for(label: str, ui_context: dict[str, Any] | None) -> list[str]:
    """The options of the visible field whose label part equals *label*."""
    for entry in (ui_context or {}).get("fields") or []:
        if isinstance(entry, str) and field_label(entry) == label:
            return field_options(entry)
    return []


def resolve_fill_value(
    value: str, field: str, ui_context: dict[str, Any] | None
) -> tuple[str, str | None]:
    """The value to actually type, corrected against the screen's vocabulary.

    STT transliterates on-screen names freely ("LAWs_thai" arrives as
    "ลาวไทย") — typing the transcript verbatim would put the garble into the
    form. The screen is the vocabulary:

    - Dropdown (the resolved *field* declares options): the value MUST be one
      of them — resolve through the shared tiers. ``("ok", option)`` /
      ``("no_option", None)`` (missing or ambiguous): better an honest ask
      than a silent non-select behind a spoken "ได้เลยครับ".
    - Plain input: free text stays verbatim, EXCEPT when the value uniquely
      names something visible on screen cross-script (case-insensitive exact
      or consonant-skeleton hit vs buttons/cards): then the on-screen
      spelling wins — that is what the caller was reading aloud. Fuzzy
      substring tiers are deliberately NOT used here: a search term must
      never be rewritten just for resembling a button.
    """
    options = field_options_for(field, ui_context)
    if options:
        outcome, resolved = _resolve_spoken_name(value, options)
        return ("ok", resolved) if outcome == "hit" else ("no_option", None)
    spoken = value.replace(" ", "").lower()
    spoken_skeleton = _consonant_skeleton(spoken)
    candidates = [b for b in (ui_context or {}).get("buttons") or [] if isinstance(b, str)]
    exact: list[str] = []
    cross: list[str] = []
    for candidate in candidates:
        c = candidate.replace(" ", "").lower()
        if c == spoken:
            exact.append(candidate)
        else:
            cs = _consonant_skeleton(c)
            if (
                len(spoken_skeleton) >= 3
                and len(cs) >= 3
                and _edit_distance(spoken_skeleton, cs) <= max(1, len(cs) // 3)
            ):
                cross.append(candidate)
    for hits in (exact, cross):
        if len(hits) == 1:
            return ("ok", hits[0])
        if hits:
            break  # several look-alikes → trust the caller's own words
    return ("ok", value)


def exact_field_hit(name: str, ui_context: dict[str, Any] | None) -> str | None:
    """The visible field whose label equals *name* exactly (normalised; the
    spoken side may carry a "ช่อง" prefix).

    Used by the click rung to prefer FOCUSING a field over a fuzzy button
    match: "กดที่ค้นหาหนังสือ" means the search box labelled exactly that, not
    the sidebar button "หนังสือ" it happens to contain.
    """
    spoken = (name or "").replace(" ", "").lower()
    if not spoken:
        return None
    for entry in (ui_context or {}).get("fields") or []:
        if not isinstance(entry, str):
            continue
        label = field_label(entry)
        folded = label.replace(" ", "").lower()
        if spoken in (folded, f"ช่อง{folded}"):
            return label
    return None


def resolve_field_target(
    name: str, ui_context: dict[str, Any] | None, *, last_field: str | None = None
) -> tuple[str, str | None]:
    """Resolve a spoken form-field *name* against the visible fields.

    Same outcome contract and scoring as :func:`resolve_click_target`;
    matching runs on the label part only, and the returned text is that
    label (what the client looks the element up by). Fields carry two extra
    tie-breaking signals: the focused field (``activeField`` in the streamed
    context) and, when the caller passes it, the last field filled this call
    — a tie between equally-matching labels resolves to the one the caller
    is plausibly *in* instead of asking back. Pass ``last_field`` only where
    every resolve of the same utterance sees it (the deterministic rungs);
    the LLM tool + dispatch pair must resolve identically, so they rely on
    ``activeField`` alone.
    """
    labels: list[str] = []
    for entry in (ui_context or {}).get("fields") or []:
        if isinstance(entry, str):
            label = field_label(entry)
            if label and label not in labels:
                labels.append(label)
    boosts: dict[str, int] = {}
    active = str((ui_context or {}).get("activeField") or "").strip()
    if active and active in labels:
        boosts[active] = _BOOST_FOCUS
    if last_field and last_field in labels:
        boosts[last_field] = boosts.get(last_field, 0) + _BOOST_RECENT
    return _resolve_spoken_name(name, labels, boosts)


def effective_fill_field(field: str, ui_context: dict[str, Any] | None) -> str:
    """The field a fill targets when the model may omit it (Tier B).

    The given name when present; else the SINGLE visible field (unambiguous);
    else ``""``. Shared by ``UIFillTool.execute`` and the pipeline's fill
    dispatch so the tool result the LLM sees and the action the client runs
    are computed from the same fallback — speech and action can't disagree.
    """
    field = (field or "").strip()
    if field:
        return field
    entries = [e for e in (ui_context or {}).get("fields") or [] if isinstance(e, str)]
    if len(entries) == 1:
        return field_label(entries[0])
    return ""


def is_dangerous_button(text: str) -> bool:
    """Whether a button press must be confirmed by voice before executing."""
    t = (text or "").lower()
    return any(w in t for w in _DANGER_WORDS)


# ── secretary (dictation) mode commands ────────────────────────────────
#
# Explicit moded dictation, Dragon / macOS-Voice-Control style: the caller
# says "เปิดโหมดเลขา" and from then on EVERY utterance is typed into the
# on-screen chat — no per-sentence guessing, no LLM. The mode-off commands
# must stay active inside the mode (never trap the user), which the pipeline
# guarantees by checking them before the in-mode routing.

_MODE_FILLERS = ("ครับ", "ค่ะ", "คะ", "นะ", "หน่อย", "ให้", "ที", "ด้วย", "เลย", "จ้า", " ")
_SECRETARY_ON_FORMS = {
    "เปิดโหมดเลขา",
    "เข้าโหมดเลขา",
    "ใช้โหมดเลขา",
    "โหมดเลขา",
    "เปิดโหมดพิมพ์",
    "เข้าโหมดพิมพ์",
    "โหมดพิมพ์",
    # Bare "open/enter the mode" — there is only one mode, and live STT can
    # mangle the mode NAME beyond recovery ("เปิดโหมดเลขา" → "เปิดหมดเลย…"):
    # the short forms keep such garbles within the fuzzy budget.
    "เปิดโหมด",
    "เข้าโหมด",
    "secretarymode",
    "dictationmode",
}
_SECRETARY_OFF_FORMS = {
    "ปิดโหมดเลขา",
    "ออกจากโหมดเลขา",
    "เลิกโหมดเลขา",
    "ปิดโหมดพิมพ์",
    "ออกจากโหมดพิมพ์",
    "ออกจากโหมด",
    "ปิดโหมด",
    "exitdictation",
    "exitsecretarymode",
}
_MAX_MODE_CHARS = 32


# First-char anchor for the fuzzy form matcher — by SOUND class, not glyph.
# STT swaps same-place stops freely on the onset too: live it produced
# "บิดหมดเลขา" for "ปิดโหมดเลขา" (บ↔ป), which the old exact-char anchor
# rejected even though the edit distance was within budget — trapping the
# caller in dictation mode. Fold Thai consonants to Latin (homophone table),
# then voiced→voiceless so บ/ป, ด/ต, ก/ค land in one class.
_ONSET_VOICE_FOLD = str.maketrans({"b": "p", "d": "t", "g": "k", "j": "c"})


def _onset_class(ch: str) -> str:
    latin = _TH_CONSONANT_LATIN.get(ch, ch.lower())
    return latin.translate(_LATIN_SOUND_FOLD).translate(_ONSET_VOICE_FOLD)


def _fuzzy_form_distance(t: str, forms: set[str]) -> int | None:
    """Best phonetic edit distance from *t* to any form within its budget.

    Budget scales with form length (``len // 4``, min 1) and the first char
    must match by sound class (see ``_onset_class``), so short unrelated
    words can't drift in. Live STT produced "ปิดหมดเรขาค" for "ปิดโหมดเลขา" —
    phonetic normalisation (ร→ล) plus two edits — and a caller inside
    dictation mode MUST be able to leave: for the exit command, matching too
    eagerly beats trapping the user.
    """
    best: int | None = None
    tp = _phonetic(t)
    for form in forms:
        budget = max(1, len(form) // 4)
        if not t or not form or _onset_class(t[0]) != _onset_class(form[0]):
            continue
        d = _edit_distance(tp, _phonetic(form))
        if d <= budget and (best is None or d < best):
            best = d
    return best


def match_mode_command(text: str) -> str | None:
    """``"secretary_on"`` / ``"secretary_off"`` for a bare mode command, else ``None``.

    Exact-after-normalisation first, like every control matcher here —
    "โหมดเลขาคืออะไร" is a question and must reach the LLM. A fuzzy pass then
    absorbs STT garbles ("ปิดหมดเรขาค"); when a garble sits equally close to
    the on- and off-forms the matcher declines rather than guessing.
    """
    t = (text or "").strip().lower()
    if not t or len(t) > _MAX_MODE_CHARS:
        return None
    for bit in _MODE_FILLERS:
        t = t.replace(bit, "")
    if t in _SECRETARY_ON_FORMS:
        return "secretary_on"
    if t in _SECRETARY_OFF_FORMS:
        return "secretary_off"
    d_on = _fuzzy_form_distance(t, _SECRETARY_ON_FORMS)
    d_off = _fuzzy_form_distance(t, _SECRETARY_OFF_FORMS)
    if d_off is not None and (d_on is None or d_off < d_on):
        return "secretary_off"
    if d_on is not None and (d_off is None or d_on < d_off):
        return "secretary_on"
    return None


# Bare yes/no for the confirmation turn (exact after stripping politeness —
# same discipline as the stop matcher).
_YES_FORMS = {"ใช่", "ช่าย", "ถูกต้อง", "ตกลง", "เอา", "yes", "yeah", "ok", ""}
_NO_FORMS = {"ไม่", "ไม่ใช่", "ไม่เอา", "ไม่ต้อง", "ยกเลิก", "no", "nope"}
_MAX_CONFIRM_CHARS = 20


def _strip_polite(text: str) -> str | None:
    t = (text or "").strip().lower()
    if not t or len(t) > _MAX_CONFIRM_CHARS:
        return None
    for bit in ("ครับ", "ค่ะ", "คะ", "จ้า", "จ้ะ", "เลย", "นะ", " "):
        t = t.replace(bit, "")
    return t


def is_affirmative(text: str) -> bool:
    """Bare yes ("ใช่", "ใช่ครับ", plain "ครับ") for a pending confirmation."""
    t = _strip_polite(text)
    return t is not None and t in _YES_FORMS


def is_negative(text: str) -> bool:
    """Bare no ("ไม่", "ไม่ใช่ครับ") for a pending confirmation."""
    t = _strip_polite(text)
    return t is not None and t in _NO_FORMS


def allowed_target_ids(manifest: dict[str, Any]) -> set[str]:
    """Every target id the client declared (the whitelist)."""
    return {
        str(entry.get("id"))
        for section in ("pages", "actions")
        for entry in manifest.get(section, [])
        if isinstance(entry, dict) and entry.get("id")
    }


class UINavigateTool(BaseTool):
    """Steer the caller's UI. Server-side no-op — the client executes.

    The pipeline forwards the ``TOOL_CALL`` frame to the client, which is the
    component that actually performs (and re-validates) the action, so the
    tool result only tells the LLM the command was dispatched.
    """

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=UI_NAVIGATE_TOOL,
            description=(
                "Navigate or control the user's on-screen UI during a voice call. "
                "Call this when the user asks to open/go to a page or trigger a UI "
                "action. `target` MUST be one of the target ids listed in the "
                "'Voice UI control' section of the system prompt — never invent one."
            ),
            parameters=[
                ToolParameter(
                    name="target",
                    type="string",
                    description="Target id from the declared UI manifest.",
                ),
                ToolParameter(
                    name="argument",
                    type="string",
                    description=(
                        "REQUIRED whenever the chosen target declares an argument in "
                        "the system prompt: pass the exact value the caller named or "
                        "that is visible on their screen (e.g. the KB name, verbatim, "
                        "like 'LAWs_thai'). Only omit it when the caller named none."
                    ),
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        target = str(kwargs.get("target") or "").strip()
        if not target:
            return ToolResult(content="No target given; nothing dispatched.", success=False)
        return ToolResult(
            content=(
                f"Done — the caller's screen already shows {target!r}. "
                "Reply with EXACTLY 'ได้เลยครับ' and nothing else."
            )
        )


class UIClickTool(BaseTool):
    """Press a visible button/card/link the caller named.

    The LLM fallback for click phrasings the deterministic shortcut doesn't
    recognise ("เปิดประวัติแชต", "เลือกสมุดบันทึก"). Same trust model as the
    shortcut: the tool only *verifies* the name against the buttons the
    screen actually shows (``_ui_context`` injected by the capability) — the
    press itself is dispatched by the pipeline, dangerous names go through
    the spoken-confirmation rung, and the client re-validates before acting.
    The LLM never chooses a button the caller didn't name.
    """

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=UI_CLICK_TOOL,
            description=(
                "Press a button/card/link that is VISIBLE on the caller's screen "
                "during a voice call, when the caller asks to press/click/open it "
                "by name. `button` must be a name shown in the 'Current screen' "
                "section of the system prompt — never invent one, never pick a "
                "button the caller did not name."
            ),
            parameters=[
                ToolParameter(
                    name="button",
                    type="string",
                    description="The visible button name the caller said (verbatim).",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        button = str(kwargs.get("button") or "").strip()
        ui_context = kwargs.get("_ui_context")
        if not button:
            return ToolResult(content="No button name given; nothing pressed.", success=False)
        outcome, resolved = resolve_click_target(
            button, ui_context if isinstance(ui_context, dict) else None
        )
        if outcome == "missing":
            return ToolResult(
                content=(
                    f"No visible button named {button!r} on the caller's screen right "
                    "now. Tell the caller honestly (e.g. 'ไม่เห็นปุ่มชื่อนั้นบนจอครับ') — "
                    "do NOT claim anything was pressed."
                ),
                success=False,
            )
        if outcome == "ambiguous":
            return ToolResult(
                content=(
                    f"Several visible buttons match {button!r}. Ask the caller which "
                    "one they mean (say the full names) — nothing was pressed."
                ),
                success=False,
            )
        if resolved and is_dangerous_button(resolved):
            return ToolResult(
                content=(
                    f"{resolved!r} looks destructive, so it was NOT pressed. Ask the "
                    f"caller to confirm in one short sentence (e.g. 'ปุ่ม{resolved}"
                    "อาจมีผลถาวรนะครับ ให้กดเลยไหมครับ') — if they answer ใช่, the "
                    "system presses it."
                )
            )
        return ToolResult(
            content=(
                f"Pressed {resolved!r} — already done on the caller's screen. "
                "Reply with EXACTLY 'ได้เลยครับ' and nothing else."
            )
        )


class UIFillTool(BaseTool):
    """Type a caller-named value into a visible form field (or pick a
    dropdown option).

    The LLM fallback for fill phrasings the deterministic shortcut doesn't
    recognise ("ช่องค้นหาใส่คำว่ากฎหมายให้หน่อย"). Same trust model as click:
    the tool only *verifies* the field name against the fields the screen
    actually shows (``_ui_context``); the client sets the value with native
    setters and dispatches nothing else — no form is submitted, so there is
    no danger rung. The LLM never invents a value the caller didn't say.

    Tier B (implicit fill): when the caller named NO field and the screen
    shows several, the model picks the field whose *meaning* matches the
    value from the streamed schema (labels + declared type/options) — but
    the pick still goes through :func:`resolve_field_target`, so only a
    visible field can ever be filled (trust model intact). ``field`` may
    even be omitted: one visible field is unambiguous; otherwise the tool
    hands the schema back and demands an explicit choice — the server
    never guesses on the model's behalf.
    """

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=UI_FILL_TOOL,
            description=(
                "Type a value into a form field (or choose a dropdown option) "
                "that is VISIBLE on the caller's screen during a voice call, when "
                "the caller says what to type. `field` must be a field name "
                "shown in the 'Current screen' section of the system prompt — "
                "never invent one. If the caller named the field, use their "
                "words; if they only said what to type, pick the visible field "
                "whose MEANING matches the value (an email address goes in the "
                "email-typed field, a date in the date field). "
                "Nothing is submitted: filling is preview-only until the caller "
                "asks to press a button."
            ),
            parameters=[
                ToolParameter(
                    name="field",
                    type="string",
                    description=(
                        "The visible field name: the caller's words verbatim when "
                        "they named one, else the listed field whose meaning "
                        "matches the value. Omit only when you cannot tell."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="value",
                    type="string",
                    description=(
                        "The exact text to type (or dropdown option to choose), "
                        "verbatim as the caller said it."
                    ),
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        field = str(kwargs.get("field") or "").strip()
        value = str(kwargs.get("value") or "").strip()
        ui_context = kwargs.get("_ui_context")
        ctx = ui_context if isinstance(ui_context, dict) else None
        if not value:
            return ToolResult(content="A value is required; nothing was typed.", success=False)
        if not field:
            # Tier B safety net: the model omitted the field. One visible
            # field is unambiguous; several → hand the schema back and make
            # the model choose explicitly (or ask the caller). The server
            # never picks a field on the model's behalf. Shared with the
            # pipeline's dispatch (effective_fill_field) so the tool result
            # and the executed action can't disagree.
            field = effective_fill_field(field, ctx)
            if not field:
                entries = [e for e in (ctx or {}).get("fields") or [] if isinstance(e, str)]
                listing = " | ".join(entries) if entries else "(none)"
                return ToolResult(
                    content=(
                        f"No `field` was given. Visible fields: {listing}. Call "
                        "the tool again with `field` set to the ONE whose meaning "
                        "matches the value — or, if none clearly matches, ask the "
                        "caller which field they mean. Nothing was typed."
                    ),
                    success=False,
                )
        outcome, resolved = resolve_field_target(field, ctx)
        if outcome == "missing":
            return ToolResult(
                content=(
                    f"No visible form field named {field!r} on the caller's screen "
                    "right now. Tell the caller honestly (e.g. 'ไม่เห็นช่องชื่อนั้น"
                    "บนจอครับ') — do NOT claim anything was typed."
                ),
                success=False,
            )
        if outcome == "ambiguous":
            return ToolResult(
                content=(
                    f"Several visible fields match {field!r}. Ask the caller which "
                    "one they mean (say the full field names) — nothing was typed."
                ),
                success=False,
            )
        value_status, final_value = resolve_fill_value(value, resolved or "", ctx)
        if value_status != "ok" or final_value is None:
            options = field_options_for(resolved, ctx)
            return ToolResult(
                content=(
                    f"{resolved!r} is a dropdown and none of its options matches "
                    f"{value!r}. Its options are: {' | '.join(options)}. Ask the "
                    "caller which option they mean — nothing was selected."
                ),
                success=False,
            )
        return ToolResult(
            content=(
                f"Typed {final_value!r} into {resolved!r} — already done on the "
                "caller's screen. Reply with EXACTLY 'ได้เลยครับ' and nothing else."
            )
        )


class VoiceUICapability:
    """LoopCapability that mounts ``ui_navigate`` when a UI manifest is present.

    Also injects the client's current-screen context (when streamed) so the
    model can answer questions about what the caller sees — read side and act
    side of the same "voice knows the screen" seam.
    """

    name = "voice_ui"
    owned_tools = (UI_NAVIGATE_TOOL, UI_CLICK_TOOL, UI_FILL_TOOL)

    def is_active(self, context: UnifiedContext) -> bool:
        return bool(context.metadata.get("ui_manifest")) or bool(context.metadata.get("ui_context"))

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        _ = language, prompts
        manifest = context.metadata.get("ui_manifest")
        screen = context.metadata.get("ui_context")
        lines: list[str] = []
        if isinstance(manifest, dict):
            lines += [
                "## Voice UI control",
                "The caller is looking at a screen you can steer with the "
                f"`{UI_NAVIGATE_TOOL}` tool. Allowed targets (id — what it does):",
            ]
            for section, header in (("pages", "Pages"), ("actions", "Actions")):
                entries = manifest.get(section) or []
                if not entries:
                    continue
                lines.append(f"{header}:")
                for entry in entries:
                    row = f"- `{entry['id']}` — {entry.get('label', entry['id'])}"
                    if entry.get("argument"):
                        row += f" (argument: {entry['argument']})"
                    lines.append(row)
            lines.append(
                "Use the tool only for explicit UI requests; answer normal questions "
                "with speech alone. Never pass a target that is not listed above. "
                "ARGUMENT RULE: when a target above declares an (argument: …) and "
                "the caller named one — e.g. 'เปิดคลังความรู้ LAWs_thai' — you MUST "
                "pass it verbatim as `argument`; calling the tool without it opens "
                "the wrong thing. "
                "When the caller asks to go to / open a page OR to perform a "
                "listed action (scroll, new chat, go back, …), you MUST actually "
                f"call `{UI_NAVIGATE_TOOL}` — never answer with an acknowledgement "
                "alone: saying 'ได้เลยครับ' without the tool call means nothing "
                "happened. "
                "If the request sounds like a UI command (navigation, scrolling, "
                "pressing) but you cannot map it to one listed target (speech "
                "recognition garbles words), do NOT acknowledge and do NOT guess: "
                "ask one short question instead — 'คุณหมายถึงหน้าไหนครับ' or "
                "'คุณหมายถึงหน้า X ใช่ไหมครับ'. "
                "An acknowledgement ('ได้เลยครับ'/'จัดให้ครับ') is ONLY allowed in "
                "the same reply as a ui_navigate call, never on its own. "
                "VOICE MODES: you have NO control over voice modes (โหมดเลขา / "
                "dictation) — the system layer handles those commands before "
                "you. If a request to open or close โหมดเลขา reaches you, it "
                "means the system did NOT catch it (garbled speech): NEVER "
                "claim a mode is now on or off — instead ask the caller to "
                "repeat clearly, e.g. 'พูดว่า เปิดโหมดเลขา อีกครั้งครับ'. "
                "TIMING: the screen changes the instant you call the tool — before "
                "your voice reaches the caller. HARD RULE for the reply after a "
                "ui_navigate call: output EXACTLY one short phrase — 'ได้เลยครับ' or "
                "'จัดให้ครับ' — and STOP. No unprompted page description, no "
                "'รอสักครู่', no 'กำลังเปิด', no offers of further help, no "
                "follow-up questions. A one-phrase reply is correct behaviour, not "
                "rudeness: the caller is watching the screen, not waiting for "
                "narration."
            )
        if isinstance(screen, dict) and screen.get("summary"):
            if lines:
                lines.append("")
            lines += [
                "## Current screen",
                "What the caller's screen shows right now (captured when they last spoke):",
            ]
            if screen.get("path"):
                lines.append(f"Path: {screen['path']}")
            lines.append(str(screen["summary"]))
            fields = [f for f in screen.get("fields") or [] if isinstance(f, str)]
            if fields:
                lines.append("ช่องกรอกที่มองเห็น (form fields): " + " | ".join(fields))
            lines.append(
                "When the caller ASKS what is on their screen (เมนู/ปุ่ม/หัวข้อ "
                "อะไรบ้าง), answer from this section only — never invent menus or "
                "buttons that are not listed here. STALENESS RULE: the caller can "
                "navigate by hand (clicking) at any moment, so pages you steered "
                "to in earlier turns are NOT evidence of where they are now. For "
                "'ตอนนี้อยู่หน้าไหน' trust ONLY this section — it always reflects "
                "the screen at their latest utterance and overrides anything the "
                "conversation history suggests. This overrides nothing else "
                "above: the one-phrase rule applies to your reply right after a "
                "ui_navigate call, while answering the caller's own question "
                "about the screen is normal conversation. "
                f"PRESSING THINGS: with `{UI_CLICK_TOOL}` you can press a "
                "button/card/link listed above when the caller asks to press or "
                "open it by name — pass the caller's words as `button`; the "
                "system verifies visibility, handles destructive-button "
                "confirmation, and presses. You MUST actually call the tool: "
                "'ได้เลยครับ' without a tool call means nothing happened. Follow "
                "the tool result exactly — if it says nothing was pressed, never "
                "claim otherwise. Only press what the caller named; never choose "
                "a button for them. "
                f"TYPING: with `{UI_FILL_TOOL}` you can type into a form field "
                "(or choose a dropdown option) listed under 'ช่องกรอกที่มองเห็น' "
                "when the caller says what to type — pass the caller's value "
                "verbatim. FIELD CHOICE: when the caller names the field, pass "
                "their words verbatim; when they only say what to type "
                "('พิมพ์ X') and several fields are visible, pick the listed "
                "field whose MEANING matches the value — an entry may declare "
                "its type ('(ชนิด: email)') or its options ('(เลือกได้: …)'); "
                "use those to decide. If no field clearly matches, ask the "
                "caller which field they mean instead of guessing. Filling "
                "never submits anything; pressing a button is a separate "
                "request. The same honesty rules apply: call the tool (no bare "
                "'ได้เลยครับ'), follow its result, never invent a value the "
                "caller did not say. CORRECTIONS: you have no erase tool — the "
                "system layer handles 'ล้างช่อง X' (clear) and 'ลบคำสุดท้าย' "
                "(remove last word) before you, and typing into a field again "
                "REPLACES its value. If an erase request reaches you, it means "
                "the system did not catch it: never claim text was deleted — "
                "tell the caller those commands instead."
            )
        if not lines:
            return None
        return PromptBlock(self.name, "\n".join(lines))

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        if tool_name in (UI_CLICK_TOOL, UI_FILL_TOOL):
            # Click and fill verify names against what the screen actually
            # shows — inject the turn's streamed context (server-owned, the
            # model cannot fabricate it).
            updated = dict(kwargs)
            updated["_ui_context"] = context.metadata.get("ui_context")
            return updated
        return kwargs

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        _ = context
        return ""


def install_ui_control() -> None:
    """Register the tool + capability (idempotent, runtime-only).

    Called from the voice router at import time. Uses only public extension
    surfaces: ``ToolRegistry.register()`` and rebinding the capability
    registry's ``LOOP_CAPABILITIES`` tuple — no upstream file is edited.
    """
    from deeptutor.capabilities import registry as capability_registry
    from deeptutor.runtime.registry.tool_registry import get_tool_registry

    tool_registry = get_tool_registry()
    if tool_registry.get(UI_NAVIGATE_TOOL) is None:
        tool_registry.register(UINavigateTool())
        logger.info("voice_ui: registered %s tool", UI_NAVIGATE_TOOL)
    if tool_registry.get(UI_CLICK_TOOL) is None:
        tool_registry.register(UIClickTool())
        logger.info("voice_ui: registered %s tool", UI_CLICK_TOOL)
    if tool_registry.get(UI_FILL_TOOL) is None:
        tool_registry.register(UIFillTool())
        logger.info("voice_ui: registered %s tool", UI_FILL_TOOL)

    caps = capability_registry.LOOP_CAPABILITIES
    if not any(getattr(cap, "name", "") == VoiceUICapability.name for cap in caps):
        capability_registry.LOOP_CAPABILITIES = (*caps, VoiceUICapability())
        logger.info("voice_ui: appended VoiceUICapability to LOOP_CAPABILITIES")


__all__ = [
    "MAX_MANIFEST_BYTES",
    "UI_CLICK_TOOL",
    "UI_FILL_TOOL",
    "UI_NAVIGATE_TOOL",
    "UIClickTool",
    "UIFillTool",
    "UINavigateTool",
    "VoiceUICapability",
    "allowed_target_ids",
    "exact_field_hit",
    "field_label",
    "field_options",
    "field_options_for",
    "effective_fill_field",
    "implicit_fill_field",
    "install_ui_control",
    "is_affirmative",
    "is_dangerous_button",
    "is_negative",
    "match_action_intent",
    "match_click_intent",
    "match_edit_intent",
    "match_fill_intent",
    "match_implicit_fill",
    "match_mode_command",
    "match_navigation_guess",
    "match_navigation_intent",
    "match_where_am_i",
    "resolve_click_target",
    "resolve_field_target",
    "resolve_fill_value",
    "sanitize_action_result",
    "sanitize_manifest",
    "sanitize_ui_context",
    "spoken_page_name",
]
