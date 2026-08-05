#!/usr/bin/env python3
"""Compute, validate and apply the Thai locale delta for a sync.

Parity here means *exact key equality* with `en`, not "nothing missing" — every
sync so far has both added and orphaned keys, and leaving an orphan behind makes
the next sync's diff lie about what changed.

The validation that matters is placeholders. A translation that drops or renames
a `{{count}}` renders a broken string at runtime and no test in this repo would
notice, so --apply refuses to run until every placeholder set matches `en`.

  i18n_delta.py --plan                     # what would change
  i18n_delta.py --plan --out delta.json    # save for review/translation
  i18n_delta.py --apply --in delta.json    # apply a reviewed delta
  i18n_delta.py --check                    # parity only, for the verify stage
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
ROOT = pathlib.Path("web/locales")


def load(locale: str) -> dict:
    return json.loads((ROOT / locale / "app.json").read_text(encoding="utf-8"))


def save(locale: str, data: dict) -> None:
    p = ROOT / locale / "app.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def placeholders_ok(en: dict, key: str, value: str) -> bool:
    return set(PLACEHOLDER.findall(en.get(key, ""))) == set(PLACEHOLDER.findall(value))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--locale", default="th")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--in", dest="infile")
    args = ap.parse_args()

    en, loc = load("en"), load(args.locale)
    add = sorted(set(en) - set(loc))
    remove = sorted(set(loc) - set(en))

    if args.check:
        ok = not add and not remove
        print(f"{args.locale}: en={len(en)} {args.locale}={len(loc)} missing={len(add)} orphan={len(remove)}"
              f" — {'exact parity' if ok else 'NOT AT PARITY'}")
        return 0 if ok else 1

    if args.plan:
        print(f"en={len(en)}  {args.locale}={len(loc)}  add={len(add)}  remove={len(remove)}")
        for k in remove:
            print(f"  - {k[:100]}")
        for k in add:
            print(f"  + {k[:100]}")
        if args.out:
            payload = {
                "_note": f"Fill every value in add[] with {args.locale}. "
                         "Placeholders must match en exactly; --apply enforces it.",
                "add": {k: en[k] for k in add},   # seeded with en as a translation stub
                "remove": remove,
            }
            pathlib.Path(args.out).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"\nwrote {args.out} — translate the add[] values, then --apply")
        return 0

    if args.apply:
        if not args.infile:
            print("--apply needs --in <delta.json>", file=sys.stderr)
            return 2
        delta = json.loads(pathlib.Path(args.infile).read_text(encoding="utf-8"))
        d_add, d_rm = delta.get("add", {}), set(delta.get("remove", []))

        problems = []
        for k in set(d_add) - set(en):
            problems.append(f"add key not present in en: {k[:70]}")
        for k in d_rm & set(en):
            problems.append(f"remove key still present in en: {k[:70]}")
        for k, v in d_add.items():
            if not placeholders_ok(en, k, v):
                problems.append(f"placeholder mismatch: {k[:60]}")
        # Refuse a partial application: the point is exact parity afterwards.
        after = (set(loc) | set(d_add)) - d_rm
        if after != set(en):
            problems.append(f"result would not be at parity (would be {len(after)} vs en {len(en)})")
        if problems:
            print("REFUSING TO APPLY:")
            for p in problems:
                print(f"  - {p}")
            return 1

        loc.update(d_add)
        for k in d_rm:
            loc.pop(k, None)
        save(args.locale, loc)
        print(f"applied +{len(d_add)} / -{len(d_rm)} -> {len(loc)} keys (exact parity with en)")
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
