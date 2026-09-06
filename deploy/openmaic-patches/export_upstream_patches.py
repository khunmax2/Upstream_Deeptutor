#!/usr/bin/env python3
"""Turn our OpenMAIC commits into patches an upstream maintainer can apply.

Before the subtree, `deploy/openmaic-patches/*.patch` *were* the change: applied
to a sibling checkout to build, reversed afterwards. Now the change is a commit
in `integration/maic`, and keeping the patch files alongside it would be two
copies of the same thing — the kind that stay in step until the day one of them
does not.

So the patches are generated on demand instead. `git format-patch --relative`
rewrites every path so it is relative to the OpenMAIC root rather than to
`integration/maic/`, which is what a THU-MAIC maintainer needs to apply it:

    a/lib/i18n/locales.ts        not   a/integration/maic/lib/i18n/locales.ts

Ours are the commits after the subtree import. That boundary is found by looking
for the squash commit git wrote when the subtree was added, so nothing here has
to be kept up to date by hand.

    python export_upstream_patches.py                  # list what would be exported
    python export_upstream_patches.py --out /tmp/pr    # write them

The output is not committed. It is an export for sending somewhere, and
regenerating it is one command.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

PREFIX = "integration/maic"
SQUASH_SUBJECT = re.compile(r"^Squashed '" + re.escape(PREFIX) + r"/?' content from commit")


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout


def import_commit() -> str:
    """The squash commit git wrote when the subtree was added — our starting line."""
    log = git("log", "--format=%H%x1f%s", "--all")
    for line in log.splitlines():
        sha, _, subject = line.partition("\x1f")
        if SQUASH_SUBJECT.match(subject):
            return sha
    raise SystemExit(
        f"no subtree import commit found for {PREFIX}.\n"
        "Expected a commit whose subject begins \"Squashed '"
        f"{PREFIX}/' content from commit …\", which `git subtree add --squash` writes."
    )


def our_commits(since: str) -> list[tuple[str, str]]:
    log = git(
        "log", "--reverse", "--no-merges", "--format=%H%x1f%s", f"{since}..HEAD", "--", PREFIX
    )
    return [
        (sha, subject)
        for sha, _, subject in (line.partition("\x1f") for line in log.splitlines())
        if sha
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write the patches here (default: list only)")
    args = parser.parse_args()

    since = import_commit()
    commits = our_commits(since)

    print(f"[export] subtree imported at {since[:8]}")
    if not commits:
        print("[export] nothing of ours on top of it yet.")
        return 0

    print(f"[export] {len(commits)} commit(s) of ours in {PREFIX}:")
    for index, (sha, subject) in enumerate(commits, 1):
        print(f"  {index:02d}  {sha[:8]}  {subject}")

    if args.out is None:
        print("\n[export] pass --out DIR to write them.")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    written = git(
        "format-patch",
        f"--relative={PREFIX}",
        "--no-signature",
        "-o",
        str(args.out),
        f"{since}..HEAD",
        "--",
        PREFIX,
    ).split()

    print(f"\n[export] wrote {len(written)} patch(es) to {args.out}")
    for path in written:
        print(f"  {Path(path).name}")

    print(
        "\n[export] Paths inside are relative to the OpenMAIC root, so they apply to a"
        "\n[export] plain THU-MAIC checkout with `git am`. Read one before sending it:"
        "\n[export] a commit message written for this repository is not always the"
        "\n[export] message an upstream reviewer should receive."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
