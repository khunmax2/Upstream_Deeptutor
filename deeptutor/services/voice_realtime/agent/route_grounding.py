"""Hard destination grounding — did the loop actually land where it was asked?

Issue 01's live verdict: the prompt rule "confirm the URL before a confident
``done``" is necessary but NOT sufficient — even a full-tier model rationalized a
false success ~2/5, conflating ``/settings/tools`` (a "Web Search" *tool* toggle)
with the dedicated ``/settings/search``. A confident "done" on the wrong page is
worse than an honest miss, so the loop cannot be left trusting the model to
self-verify.

This module is the **independent** source of truth the loop checks against, so
the acting model's self-congratulation never gets the last word:

* :func:`resolve_target_route` maps a navigation task to the ONE canonical route
  it named — deterministically, no LLM. It is deliberately HIGH-PRECISION: only
  exact / substring alias matches count (no phonetic/cross-script fuzz — that
  garble tolerance is the acting model's job, not the grounding gate's), and a
  contains-tie between two DISTINCT routes resolves to ``None`` (skip) rather
  than a guess. Tasks that name no route in the manifest resolve to ``None`` too
  — the hybrid gate: enforce only when confident, otherwise fall back to the
  prompt. This keeps the false-FAILURE risk near zero (the cost of a wrong hard
  gate) while still catching the tools-vs-search class.
* :func:`landed_path` + :func:`path_satisfies` compare the achieved URL against
  that target; the loop forces ``success=false`` on a mismatch.

Scope is **nav-destination tasks only** (a resolved target IS the signal). Action
tasks ("toggle X", "create a book") resolve to ``None`` and stay on the prompt +
DangerGate — their success criterion isn't a URL, so a URL gate there would only
manufacture false failures.

The route data lives in ``route_manifest.json`` (curated, additive, and
deliberately separate from ``ui_graph.json``'s open_path whitelist — a route may
be grounded without being voice-steerable). Paths are parity-tested against the
real Next.js routes (``web/tests/voice-route-manifest-parity.test.ts``).
"""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_MANIFEST_PATH = Path(__file__).with_name("route_manifest.json")

# Below this, an alias is too generic to trust as a destination signal (a stray
# 2-char fragment appearing anywhere in a sentence). Acronym routes (mcp, llm)
# sit right at the floor; that is intentional — they are distinctive tokens.
_MIN_ALIAS_LEN = 3

# Match tiers, spaced so tier always dominates matched length: an exact match
# beats any substring match regardless of length (and an exact match's alias is
# necessarily as long as the whole task, so length can never invert this).
_TIER_EXACT = 2
_TIER_CONTAINS = 1


@lru_cache(maxsize=1)
def load_route_manifest() -> list[dict[str, Any]]:
    """The curated route→aliases list (parsed once per process)."""
    with open(_MANIFEST_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    routes = data.get("routes") or []
    return [r for r in routes if isinstance(r, dict) and r.get("path")]


def _normalize(text: str) -> str:
    """Fold a task/alias to the comparison form: spaces dropped, lower-cased.

    Spaces are dropped because Thai is written unspaced and the STT/typed input
    mixes both; matching on the space-free form makes "web search" and
    "websearch" the same candidate.
    """
    return (text or "").replace(" ", "").lower()


def resolve_target_route(task: str) -> str | None:
    """The single canonical route a navigation *task* names, else ``None``.

    ``None`` means "don't hard-ground this turn" — either the task named no
    route in the manifest (an action task, not a navigation), or two distinct
    routes tied on the strongest alias match (ambiguous → never guess). Both are
    the safe outcome: the loop keeps trusting the prompt for that turn.
    """
    norm = _normalize(task)
    if not norm:
        return None

    best_key = (0, 0)
    winners: list[str] = []
    for route in load_route_manifest():
        path = str(route["path"])
        route_key = (0, 0)
        for alias in route.get("aliases") or []:
            a = _normalize(str(alias))
            if len(a) < _MIN_ALIAS_LEN:
                continue
            if a == norm:
                key = (_TIER_EXACT, len(a))
            elif a in norm:
                key = (_TIER_CONTAINS, len(a))
            else:
                continue
            if key > route_key:
                route_key = key
        if route_key == (0, 0):
            continue
        if route_key > best_key:
            best_key = route_key
            winners = [path]
        elif route_key == best_key and path not in winners:
            winners.append(path)

    if best_key == (0, 0) or len(winners) != 1:
        return None
    return winners[0]


def landed_path(url: str) -> str:
    """The pathname of a landed URL — origin, query, and hash stripped.

    Accepts a full href (``location.href``, what the actuator reports) or an
    already-bare path. Trailing slashes are trimmed (except root) so
    ``/settings/`` and ``/settings`` compare equal.
    """
    if not url:
        return ""
    # urlsplit puts a scheme-less "/settings/x" entirely in .path already.
    path = urlsplit(url).path or ""
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def path_satisfies(target: str, landed: str) -> bool:
    """True when *landed* reaches *target* — the same route, or deeper under it.

    "deeper under it" lets a task that named only a hub ("go to settings",
    target ``/settings``) accept landing on any of its sub-pages, while a task
    that named the specific leaf (``/settings/search``) still rejects a sibling
    (``/settings/tools``) — the sibling is not under the leaf.
    """
    want = target.rstrip("/") or "/"
    got = landed.rstrip("/") or "/"
    return got == want or got.startswith(want + "/")


__all__ = [
    "landed_path",
    "load_route_manifest",
    "path_satisfies",
    "resolve_target_route",
]
