#!/usr/bin/env python3
"""Check the fork's invariants against a merged (or about-to-be-merged) tree.

These are properties that must survive an upstream merge but that no existing
gate protects. Each exists because it failed a real sync:

  th-ts     The shared ``Lang`` type requires ``th``; upstream keeps adding
            zh/en-only entries. `tsc` does catch these, but only after a full
            build — finding them in seconds while the merge is still in your
            head is worth a lot.

  th-py     A language ``Literal`` that omits "th" is NOT a build error. It is a
            pydantic 422 at runtime. v1.5.8 added an entire UISettingsUpdate
            model that way: auto-merged cleanly, build green, i18n parity green,
            and Thai users simply could not save their language. No other gate
            in this repo can see it. This is the check that pays rent.

  seams     Upstream refactors can orphan a fork fix without touching its file.
            In v1.5.8 upstream added a canonical message builder and dropped the
            LoopHost hook the fork's Gemini thought_signature fix hung on: the
            override survived the merge byte-for-byte and became dead code —
            nothing conflicted, nothing failed, the fix just stopped running.

            Reference counting cannot see this. The override kept its name and
            all 12 of its references; only the *binding* moved. An earlier
            version of this script counted references and reported a confident
            "0 findings" when backtested against that exact merge — worse than
            no check, because it invites trust it hasn't earned.

            So this emits a review list, not a verdict: upstream files the fork
            imports from that this merge rewrote heavily. Read those seams and
            confirm each fork hook still fires.

Run from the repo root or a worktree root.

  invariants.py                          # th-ts + th-py over changed files
  invariants.py --only th-py
  invariants.py --seams BEFORE TARGET    # seams to review by hand
  invariants.py --scope all --json

Exit 0 when clean, 1 when any check reports a finding.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

# Test fixtures legitimately build zh/en maps for generic Record<string,string>
# helpers; they are not the shared Lang type.
TS_SKIP = re.compile(r"(^|/)(web/tests/|__tests__/)")

# A Lang *value* binds zh and en to strings. Type annotations like
# `{ en: ToolHints; zh: ToolHints }` and prop bags holding a `zh` boolean are not
# translations — requiring a string value keeps both out. (Both showed up as
# false positives on the first run of this script.)
TS_ZH_STR = re.compile(r"\bzh\s*:\s*['\"`]")
TS_EN_STR = re.compile(r"\ben\s*:\s*['\"`]")
TS_TH_KEY = re.compile(r"\bth\s*:")
LANG_OBJ = re.compile(r"\{[^{}]*\bzh\s*:[^{}]*\}", re.S)

PY_LANG_LITERAL = re.compile(r'Literal\[[^\]]*"zh"[^\]]*\]')

# No size threshold. The Gemini regression came from a 16-line edit to loop.py
# that swapped one call site — an earlier draft used a 40-line floor and missed
# it. How big the change is says nothing about whether it moved a seam.
SEAM_MIN_LINES = 1


def sh(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True).stdout


CONFLICT_MARKER = re.compile(r"^<{7} ", re.M)


def unresolved(text: str) -> bool:
    """Conflict markers interleave both sides, so any count taken mid-merge is
    fiction. Say that plainly rather than reporting a number nobody can act on.

    Anchored to the start of a line: git writes markers at column 0, while this
    file (and any tooling that talks about them) mentions the sequence inside a
    string. The first real run of this script flagged itself.
    """
    return bool(CONFLICT_MARKER.search(text))


def _read(p: str) -> str | None:
    f = pathlib.Path(p)
    if not f.exists() or f.is_dir():
        return None
    return f.read_text(encoding="utf-8", errors="replace")


def ts_missing_th(paths: list[str]) -> list[dict]:
    out = []
    for p in paths:
        if not p.endswith((".ts", ".tsx")) or TS_SKIP.search(p):
            continue
        text = _read(p)
        if text is None:
            continue
        if unresolved(text):
            out.append(
                {"file": p, "line": 0, "snippet": "UNRESOLVED CONFLICT — rerun after resolving"}
            )
            continue
        for m in LANG_OBJ.finditer(text):
            block = m.group(0)
            if TS_ZH_STR.search(block) and TS_EN_STR.search(block) and not TS_TH_KEY.search(block):
                out.append(
                    {
                        "file": p,
                        "line": text[: m.start()].count("\n") + 1,
                        "snippet": " ".join(block.split())[:70],
                    }
                )
    return out


def py_missing_th(paths: list[str]) -> list[dict]:
    out = []
    for p in paths:
        if not p.endswith(".py"):
            continue
        text = _read(p)
        if text is None:
            continue
        if unresolved(text):
            out.append(
                {"file": p, "line": 0, "snippet": "UNRESOLVED CONFLICT — rerun after resolving"}
            )
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = PY_LANG_LITERAL.search(line)
            if m and '"th"' not in m.group(0):
                out.append({"file": p, "line": i, "snippet": line.strip()[:70]})
    return out


def _changed_lines(path: str, a: str, b: str) -> int:
    total = 0
    for line in sh("git", "diff", "--numstat", f"{a}..{b}", "--", path).splitlines():
        parts = line.split("\t")
        for n in parts[:2]:
            if n.isdigit():
                total += int(n)
    return total


def seams_at_risk(before_ref: str, target_ref: str, merge_base: str) -> list[dict]:
    """Upstream files the fork imports from that this merge touched at all."""
    fork_files = set(sh("git", "diff", "--name-only", f"{merge_base}..{before_ref}").split())
    upstream_changed = [
        p for p in sh("git", "diff", "--name-only", f"{merge_base}..{target_ref}").split() if p
    ]

    imported: set[str] = set()
    for f in sorted(fork_files):
        if not f.endswith(".py"):
            continue
        text = _read(f) or sh("git", "show", f"{before_ref}:{f}")
        for m in re.finditer(r"^\s*from\s+(deeptutor[\w.]*)\s+import", text, re.M):
            mod = m.group(1).replace(".", "/")
            imported.add(mod + ".py")
            imported.add(mod + "/__init__.py")

    out = []
    for p in upstream_changed:
        if not p.endswith(".py"):
            continue
        both = p in fork_files
        # Files BOTH sides edited are the dangerous ones, not the safe ones. An
        # earlier draft skipped them assuming they would surface as conflicts —
        # but loop.py did not conflict (the two edits sat in different regions),
        # and that silence is exactly how the Gemini fix was orphaned.
        if not both and p not in imported:
            continue
        n = _changed_lines(p, merge_base, target_ref)
        if n < SEAM_MIN_LINES:
            continue
        why = (
            "fork edits this too — merged clean does NOT mean the seam held"
            if both
            else "fork imports this"
        )
        out.append(
            {
                "file": p,
                "line": 0,
                "changed": n,
                "both": both,
                "snippet": f"{why}; upstream changed {n} lines",
            }
        )
    # Shared-ownership files first: they carry the silent-orphan risk.
    return sorted(out, key=lambda d: (not d["both"], -d["changed"]))


# A language *comparison* that enumerates zh and en and forgets th. This is a
# different shape from a Lang object literal and the two earlier checks miss it
# entirely — v1.6.3's app-shell bootstrap shipped
# ``if (payload.language !== "zh" && payload.language !== "en") return;``, so a
# Thai account fell back to an English UI on any browser with no stored choice.
# Silent by construction: the guard just returns, nothing logs, nothing throws.
# Found by driving the running app, not by any gate — hence this check.
TS_LANG_CMP = re.compile(
    r'(?:[\w.]+\s*[!=]==\s*"(?:zh|en)"[^;\n]{0,120}?[!=]==\s*"(?:zh|en)")',
)


def ts_lang_comparison_missing_th(paths: list[str]) -> list[dict]:
    """Comparisons that gate on zh/en without admitting th."""
    out = []
    for p in paths:
        if not p.endswith((".ts", ".tsx")) or TS_SKIP.search(p):
            continue
        text = _read(p)
        if text is None:
            continue
        if unresolved(text):
            out.append(
                {"file": p, "line": 0, "snippet": "UNRESOLVED CONFLICT — rerun after resolving"}
            )
            continue
        for m in TS_LANG_CMP.finditer(text):
            frag = m.group(0)
            # a nearby "th" in the same expression means it was handled
            window = text[m.start() : m.end() + 120]
            if '"th"' in window:
                continue
            out.append(
                {
                    "file": p,
                    "line": text[: m.start()].count("\n") + 1,
                    "snippet": " ".join(frag.split())[:70],
                }
            )
    return out


CHECKS = {
    "th-ts": ("TypeScript Lang objects missing `th`", ts_missing_th),
    "th-py": ('Python language Literal missing "th" (silent 422)', py_missing_th),
    "th-cmp": (
        "TypeScript zh/en comparisons that forget `th` (silent English fallback)",
        ts_lang_comparison_missing_th,
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=list(CHECKS))
    ap.add_argument("--seams", nargs=2, metavar=("BEFORE_REF", "TARGET_REF"))
    ap.add_argument("--merge-base", default="")
    ap.add_argument("--scope", default="changed", choices=["changed", "all"])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    base = args.merge_base or sh("git", "merge-base", "HEAD", "upstream/main").strip()

    if args.scope == "changed":
        paths = sh("git", "diff", "--name-only", f"{base}..HEAD").split()
        paths += sh("git", "diff", "--name-only", "HEAD").split()
    else:
        paths = sh("git", "ls-files").split()
    paths = sorted({p for p in paths if p})

    results: dict[str, list[dict]] = {}
    for key, (_d, fn) in CHECKS.items():
        if args.only in (None, key):
            results[key] = fn(paths)
    if args.seams:
        results["seams"] = seams_at_risk(args.seams[0], args.seams[1], base)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 1 if any(results.values()) else 0

    for key, findings in results.items():
        desc = CHECKS.get(
            key, ("upstream seams the fork hooks into — REVIEW, not a verdict", None)
        )[0]
        print(f"[{'OK  ' if not findings else 'FIND'}] {key}: {desc} — {len(findings)} finding(s)")
        for f in findings:
            loc = f"{f['file']}:{f['line']}" if f["line"] else f["file"]
            print(f"        {loc}  {f['snippet']}")
    return 1 if any(results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
