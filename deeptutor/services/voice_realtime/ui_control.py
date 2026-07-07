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
    out: dict[str, Any] = {}
    if path:
        out["path"] = path[:_MAX_CONTEXT_PATH_CHARS]
    if page:
        out["page"] = page[:_MAX_CONTEXT_PATH_CHARS]
    if summary:
        out["summary"] = summary[:_MAX_CONTEXT_SUMMARY_CHARS]
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
    return out or None


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
}


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
    hits: list[str] = []
    for action_id, patterns in _ACTION_PATTERNS.items():
        if action_id in declared and any(p in t for p in patterns):
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
_LATIN_SOUND_FOLD = str.maketrans({"c": "k", "q": "k", "x": "s", "z": "s", "v": "w", "j": "y"})


def _consonant_skeleton(s: str) -> str:
    """Latin consonant skeleton of Thai or Latin text ("เพอร์โซนา"/"persona" → psn/prsn)."""
    s = re.sub(f".{_KARAN}", "", s.lower())  # karan'd consonant is silent
    out: list[str] = []
    for ch in s:
        if ch in _TH_CONSONANT_LATIN:
            out.append(_TH_CONSONANT_LATIN[ch])
        elif ch.isascii() and ch.isalpha() and ch not in "aeiou":
            out.append(ch)
    return "".join(out).translate(_LATIN_SOUND_FOLD)


def resolve_click_target(name: str, ui_context: dict[str, Any] | None) -> tuple[str, str | None]:
    """Resolve a spoken button *name* against the visible buttons.

    Returns ``("hit", button_text)`` for exactly one match, ``("ambiguous",
    None)`` for several, ``("missing", None)`` for none / no context. Match
    order: exact (normalised) → substring either way → phonetic fuzzy (STT
    garbles button names too) → cross-script consonant skeleton (loanwords:
    spoken "persona" vs on-screen "เพอร์โซนา") — each tier only consulted when
    the previous found nothing.
    """
    spoken = (name or "").replace(" ", "").lower()
    buttons = [b for b in (ui_context or {}).get("buttons") or [] if isinstance(b, str)]
    if not spoken or not buttons:
        return ("missing", None)
    spoken_skeleton = _consonant_skeleton(spoken)

    def tiers() -> list[list[str]]:
        exact: list[str] = []
        contains: list[str] = []
        fuzzy: list[str] = []
        cross: list[str] = []
        for button in buttons:
            b = button.replace(" ", "").lower()
            if b == spoken:
                exact.append(button)
            elif (len(spoken) >= 3 and spoken in b) or (len(b) >= 3 and b in spoken):
                contains.append(button)
            elif _edit_distance(_phonetic(spoken), _phonetic(b)) <= max(1, len(b) // 4):
                fuzzy.append(button)
            else:
                bs = _consonant_skeleton(b)
                if (
                    len(spoken_skeleton) >= 3
                    and len(bs) >= 3
                    and _edit_distance(spoken_skeleton, bs) <= max(1, len(bs) // 3)
                ):
                    cross.append(button)
        return [exact, contains, fuzzy, cross]

    for hits in tiers():
        if len(hits) == 1:
            return ("hit", hits[0])
        if len(hits) > 1:
            return ("ambiguous", None)
    return ("missing", None)


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


def _fuzzy_form_distance(t: str, forms: set[str]) -> int | None:
    """Best phonetic edit distance from *t* to any form within its budget.

    Budget scales with form length (``len // 4``, min 1) and the first char
    must match, so short unrelated words can't drift in. Live STT produced
    "ปิดหมดเรขาค" for "ปิดโหมดเลขา" — phonetic normalisation (ร→ล) plus two
    edits — and a caller inside dictation mode MUST be able to leave: for the
    exit command, matching too eagerly beats trapping the user.
    """
    best: int | None = None
    tp = _phonetic(t)
    for form in forms:
        budget = max(1, len(form) // 4)
        if not t or not form or t[0] != form[0]:
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


class VoiceUICapability:
    """LoopCapability that mounts ``ui_navigate`` when a UI manifest is present.

    Also injects the client's current-screen context (when streamed) so the
    model can answer questions about what the caller sees — read side and act
    side of the same "voice knows the screen" seam.
    """

    name = "voice_ui"
    owned_tools = (UI_NAVIGATE_TOOL, UI_CLICK_TOOL)

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
                "When the caller asks to go to / open a page, you MUST actually call "
                f"`{UI_NAVIGATE_TOOL}` — never answer with an acknowledgement alone: "
                "saying 'ได้เลยครับ' without the tool call means nothing happened. "
                "If the request sounds like navigation but you cannot map it to "
                "one listed target (speech recognition garbles words), do NOT "
                "acknowledge and do NOT guess: ask one short question instead — "
                "'คุณหมายถึงหน้าไหนครับ' or 'คุณหมายถึงหน้า X ใช่ไหมครับ'. "
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
                "a button for them."
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
        if tool_name == UI_CLICK_TOOL:
            # The click tool verifies names against what the screen actually
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

    caps = capability_registry.LOOP_CAPABILITIES
    if not any(getattr(cap, "name", "") == VoiceUICapability.name for cap in caps):
        capability_registry.LOOP_CAPABILITIES = (*caps, VoiceUICapability())
        logger.info("voice_ui: appended VoiceUICapability to LOOP_CAPABILITIES")


__all__ = [
    "MAX_MANIFEST_BYTES",
    "UI_CLICK_TOOL",
    "UI_NAVIGATE_TOOL",
    "UIClickTool",
    "UINavigateTool",
    "VoiceUICapability",
    "allowed_target_ids",
    "install_ui_control",
    "is_affirmative",
    "is_dangerous_button",
    "is_negative",
    "match_action_intent",
    "match_click_intent",
    "match_mode_command",
    "match_navigation_guess",
    "match_navigation_intent",
    "match_where_am_i",
    "resolve_click_target",
    "sanitize_manifest",
    "sanitize_ui_context",
    "spoken_page_name",
]
