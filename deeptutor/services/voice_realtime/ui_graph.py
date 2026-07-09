"""Website Graph — cross-page voice commands over a curated UI graph.

The grounding design's "Website Graph / Navigation Reasoning" stage: turn a
goal ("เปลี่ยนธีมเป็นโหมดมืด", spoken from *any* page) into a plan —
``navigate(/settings/appearance) → click "Dark"`` — without an LLM call.

The graph itself (`ui_graph.json`) is **provenance-agnostic data**: nodes are
routes/screens, each carrying its action catalog (semantic capability id, the
visible text to click, spoken aliases). For DeepTutor it is hand-curated and
parity-tested against the real routes (``web/tests/voice-graph-parity.test.ts``
fails CI when they drift); a future foreign-site connector populates the same
schema from a runtime learner instead — nothing in this module may assume the
DeepTutor provenance beyond the default file path.

Execution rides the post-action verify loop: the pipeline emits an
``open_path`` action and parks the follow-up click on
``nav_state["pending_graph_step"]``; when the client's ``ui_action_result``
confirms the route landed, the router dispatches the parked step. Poll +
verify, never a fixed sleep.
"""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import time
from typing import Any

from deeptutor.services.voice_realtime.ui_control import (
    _CLICK_TRAILING,
    _QUESTION_WORDS,
    _consonant_skeleton,
    _label_score,
    is_dangerous_button,
)

_GRAPH_PATH = Path(__file__).with_name("ui_graph.json")

# How long a parked follow-up step stays valid. Navigation verify polls up to
# ~2.5s client-side; anything much older is a stale plan from an abandoned
# command and must never fire on an unrelated later navigation.
PENDING_STEP_TTL_SECONDS = 15.0

# Goal verbs a cross-page command starts with ("เปลี่ยนธีมเป็นโหมดมืด",
# "ใช้ธีมครีม"). Longest first so the most specific form wins the strip.
_GRAPH_VERBS = (
    "เปลี่ยนธีมเป็น",
    "เปลี่ยนธีมไปเป็น",
    "เปลี่ยนเป็น",
    "เปลี่ยนไปใช้",
    "สลับเป็น",
    "สลับไปใช้",
    "ใช้ธีม",
    "เอาธีม",
    "เปิดใช้",
)
_MAX_GRAPH_CHARS = 48


@lru_cache(maxsize=1)
def load_graph() -> dict[str, Any]:
    """The curated UI graph (parsed once per process)."""
    with open(_GRAPH_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def match_graph_intent(text: str) -> str | None:
    """The control name a goal phrasing targets, else ``None``.

    Catches goal forms the click matcher has no verb for ("เปลี่ยนธีมเป็น X",
    "ใช้ธีม X"). Click phrasings ("กด X") reach the graph through the click
    rung's miss branch instead — this matcher must NOT shadow it.
    """
    t = (text or "").strip()
    if not t or len(t) > _MAX_GRAPH_CHARS:
        return None
    low = t.lower()
    if any(q in low for q in _QUESTION_WORDS):
        return None
    for prefix in ("ช่วย", "ขอ", "รบกวน"):
        low = low.removeprefix(prefix)
    for verb in _GRAPH_VERBS:
        if not low.startswith(verb):
            continue
        name = low[len(verb) :].strip()
        while True:  # peel trailing politeness
            trimmed = name
            for tail in _CLICK_TRAILING:
                trimmed = trimmed.removesuffix(tail).strip()
            if trimmed == name:
                break
            name = trimmed
        return name or None
    return None


def find_graph_control(
    name: str, graph: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve a spoken *name* against the graph's action catalog.

    Returns ``("hit", node, control)`` when exactly one control's vocabulary
    (click text + aliases) top-scores, ``("ambiguous", None, None)`` when
    several distinct controls tie, ``("missing", None, None)`` otherwise.
    Matching reuses the weighted label scorer, so the same garble tolerance
    (phonetic / cross-script) callers get on-screen applies to the graph.
    """
    spoken = (name or "").replace(" ", "").lower()
    if not spoken:
        return ("missing", None, None)
    skeleton = _consonant_skeleton(spoken)
    best_score = 0
    winners: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for node in (graph or load_graph()).get("nodes") or []:
        for control in node.get("controls") or []:
            vocab = [str(control.get("click") or "")] + [
                str(a) for a in control.get("aliases") or []
            ]
            score = max((_label_score(spoken, skeleton, v) for v in vocab if v), default=0)
            if score == 0:
                continue
            if score > best_score:
                best_score = score
                winners = [(node, control)]
            elif score == best_score:
                winners.append((node, control))
    if not winners:
        return ("missing", None, None)
    if len(winners) > 1:
        return ("ambiguous", None, None)
    node, control = winners[0]
    # Curated ≠ blindly trusted: never auto-press a destructive-sounding
    # control across pages — fall out as a miss so the normal (confirmable)
    # paths own it.
    if is_dangerous_button(str(control.get("click") or "")):
        return ("missing", None, None)
    return ("hit", node, control)


def plan_graph_step(
    node: dict[str, Any], control: dict[str, Any], current_path: str
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """The (navigate?, act) plan for a resolved graph control.

    Returns ``(navigate_frame, action_frame)``; ``navigate_frame`` is ``None``
    when the caller is already on the control's page (the click executor's
    element poll covers late mounts either way).
    """
    action = {
        "type": "ui_action",
        "action": "navigate",
        "target": "click_element",
        "argument": str(control.get("click") or ""),
    }
    path = str(node.get("path") or "")
    if current_path.split("?")[0] == path:
        return (None, action)
    navigate = {"type": "ui_action", "action": "navigate", "target": "open_path", "argument": path}
    return (navigate, action)


def make_pending_step(node: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    """The ``nav_state['pending_graph_step']`` record for a parked follow-up."""
    return {
        "page_path": str(node.get("path") or ""),
        "action": action,
        "expires_at": time.time() + PENDING_STEP_TTL_SECONDS,
    }


def take_pending_step(nav_state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    """Pop-and-return the parked follow-up when *result* confirms its page.

    The step fires exactly once, only on a verified ``open_path`` arrival at
    the planned path, and only within its TTL. Any ``open_path`` outcome for
    the pending plan — success, failure, wrong page — consumes the pending
    entry so a stale step can never fire on an unrelated later navigation.
    """
    pending = nav_state.get("pending_graph_step")
    if not isinstance(pending, dict) or result.get("target") != "open_path":
        return None
    nav_state.pop("pending_graph_step", None)
    if (
        result.get("ok")
        and result.get("argument") == pending.get("page_path")
        and time.time() < float(pending.get("expires_at") or 0)
    ):
        action = pending.get("action")
        return action if isinstance(action, dict) else None
    return None


__all__ = [
    "PENDING_STEP_TTL_SECONDS",
    "find_graph_control",
    "load_graph",
    "make_pending_step",
    "match_graph_intent",
    "plan_graph_step",
    "take_pending_step",
]
