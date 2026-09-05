"""Build a complete OpenMAIC ``th-TH.json`` from our partial translation.

OpenMAIC falls back to ``zh-CN`` — not English — for any key a locale file is
missing (``lib/i18n/types.ts`` sets ``defaultLocale = 'zh-CN'`` and
``lib/i18n/config.ts`` passes it as ``fallbackLng``). A half-translated Thai file
would therefore render Thai mixed with **Chinese**, which is worse for a Thai
reader than plain English.

So the file we ship is always complete: our own Thai where we have it, the
English string everywhere else. That is what makes an incremental translation
possible at all — without this step the work would be all-or-nothing, and their
``check:i18n-keys`` gate (exact key parity against ``en-US.json``) would reject
anything partial.

``th-TH.partial.json`` is the real artifact and lives in *this* repository; the
generated file is disposable. Nothing is ever written into the OpenMAIC
checkout, which stays a pristine mirror of upstream.

Usage::

    python deploy/openmaic-patches/build_th_locale.py \
        --openmaic ../OpenMAIC \
        --out build/th-TH.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
PARTIAL = HERE / "th-TH.partial.json"
INTERPOLATION = re.compile(r"{{\s*([A-Za-z0-9_]+)\s*}}")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    """Leaf paths to values. Their loader forbids arrays, so dicts and scalars only."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            out.update(flatten(value, f"{prefix}.{key}" if prefix else key))
        return out
    return {prefix: node}


def merge(base: Any, overlay: Any) -> Any:
    """Overlay wins, recursing into dicts so a partial subtree keeps its siblings."""
    if not isinstance(base, dict) or not isinstance(overlay, dict):
        return overlay
    merged = dict(base)
    for key, value in overlay.items():
        merged[key] = merge(base.get(key), value) if key in base else value
    return merged


def check_interpolation(english: dict[str, Any], thai: dict[str, Any]) -> list[str]:
    """Translated strings must carry exactly the variables the code passes in.

    The one rule OpenMAIC's TRANSLATION_GUIDE states outright: never drop or
    rename an interpolation variable. A dropped ``{{count}}`` is silent at build
    time and shows up as a sentence missing its number.
    """
    problems = []
    for key, value in flatten(thai).items():
        source = english.get(key)
        if not isinstance(value, str) or not isinstance(source, str):
            continue
        want = set(INTERPOLATION.findall(source))
        got = set(INTERPOLATION.findall(value))
        if want != got:
            missing = ", ".join(sorted(want - got)) or "-"
            extra = ", ".join(sorted(got - want)) or "-"
            problems.append(f"{key}: missing [{missing}] unexpected [{extra}]")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--openmaic",
        type=Path,
        default=Path("../OpenMAIC"),
        help="Path to the OpenMAIC checkout (default: ../OpenMAIC)",
    )
    parser.add_argument("--out", type=Path, help="Where to write the complete th-TH.json")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate and report coverage without writing anything",
    )
    args = parser.parse_args()

    source_path = args.openmaic / "lib" / "i18n" / "locales" / "en-US.json"
    if not source_path.is_file():
        print(f"[th-locale] cannot find {source_path}", file=sys.stderr)
        return 2

    english = load_json(source_path)
    partial = load_json(PARTIAL)

    flat_en = flatten(english)
    flat_th = flatten(partial)

    stale = sorted(set(flat_th) - set(flat_en))
    problems = check_interpolation(flat_en, partial)

    translated = len(set(flat_th) & set(flat_en))
    total = len(flat_en)
    pct = translated * 100 / total if total else 0
    print(f"[th-locale] translated {translated}/{total} keys ({pct:.1f}%)")

    if stale:
        print(f"[th-locale] {len(stale)} key(s) no longer exist upstream:", file=sys.stderr)
        for key in stale[:20]:
            print(f"  - {key}", file=sys.stderr)
        return 1

    if problems:
        print(f"[th-locale] {len(problems)} interpolation mismatch(es):", file=sys.stderr)
        for line in problems[:20]:
            print(f"  - {line}", file=sys.stderr)
        return 1

    if args.check:
        return 0

    if not args.out:
        print("[th-locale] --out is required unless --check is given", file=sys.stderr)
        return 2

    complete = merge(english, partial)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(complete, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[th-locale] wrote {args.out} ({total} keys, gaps filled from English)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
