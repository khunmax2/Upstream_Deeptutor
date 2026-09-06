"""Guard the OpenMAIC checkout against changes riding along into an upstream PR.

The whole reason this fork can follow OpenMAIC with a `git pull` is that its
checkout stays a pristine mirror of upstream: our Thai work lives *here*, as
`th-TH.partial.json` plus a three-line registration patch, and is applied to the
checkout only long enough to build or test.

That property is easy to lose by accident rather than by decision. Someone
experiments with the Dockerfile, an agent fixes something in passing, a `.bak`
file gets left behind — and the next `git diff` destined for a PR carries all of
it. This script makes that visible before it matters.

Three buckets:

  allowed   files the named profile is *supposed* to touch
  ours      artifacts we generate and delete again (never sent upstream)
  foreign   everything else — the thing this script exists to catch

Usage::

    python deploy/openmaic-patches/check_openmaic_tree.py --openmaic ../OpenMAIC
    python deploy/openmaic-patches/check_openmaic_tree.py --profile th-locale --strict

`--strict` exits non-zero when anything foreign is present. Run it that way
before generating a patch or opening an upstream PR; run it plain to see where
the checkout stands.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

# What each patch set is allowed to touch upstream. Derived from what adding a
# language actually changed in OpenMAIC's own history (vi-VN, PR #1025), not
# from guesswork.
PROFILES: dict[str, set[str]] = {
    "th-locale": {
        "lib/i18n/locales/th-TH.json",
        "lib/i18n/locales.ts",
        "lib/video-export-app/cover-config.ts",
        "tests/video-export/cover-config.test.ts",
        "README.md",
        "README-zh.md",
    },
    # Generic embedding seams: serving under a reverse-proxy subpath, and
    # letting a host choose language and theme. Neither mentions DeepTutor —
    # both are capabilities any embedder or subpath deployment needs, which is
    # what makes them upstream candidates rather than integration adapters.
    "embed-seams": {
        "next.config.ts",
        "lib/hooks/use-i18n.tsx",
        "lib/hooks/use-theme.tsx",
        "lib/hooks/use-embed.ts",
        "components/language-switcher.tsx",
        "components/site-header/theme-toggle.tsx",
        "components/stage/header-controls.tsx",
        "app/page.tsx",
    },
    # Container build fixes (0006). These were sitting in the checkout as
    # uncommitted edits and this guard was calling them foreign — telling the
    # reader to revert the one thing the image build needs. They are ours, they
    # are a patch, and they are upstream candidates.
    "docker-build": {
        "Dockerfile",
        ".dockerignore",
    },
    # PR 1 — Thai script support. Nothing in this project's font stack covers
    # Thai, and the video-export registry enumerates only cyrillic and arabic.
    "th-font": {
        "package.json",
        "pnpm-lock.yaml",
        "app/layout.tsx",
        "app/globals.css",
        "scripts/generate-video-export-noto-script-fonts.mjs",
    },
}

# Generated locally, applied to the checkout to build or test, then removed.
# th-TH.json is a brand-new file, which needs no patch and cannot conflict; the
# other two come out of `pnpm run gen:video-export-noto-script-fonts` and are
# regenerated rather than carried, so a patch never has to hold a binary.
OURS = {
    "lib/i18n/locales/th-TH.json",
    "lib/video-export/emit-hyperframes/noto-script-font-assets.ts",
    "public/vendor/video-export/fonts/noto-sans-thai-thai-400-normal.woff2",
}


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SystemExit(f"[guard] git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout


def changed_paths(repo: Path) -> list[tuple[str, str]]:
    """(status, path) for every tracked modification and untracked file."""
    entries = []
    for line in git(repo, "status", "--porcelain=v1").splitlines():
        if not line.strip():
            continue
        status, path = line[:2].strip() or "?", line[3:].strip()
        # Renames read "old -> new"; the destination is what would ship.
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        entries.append((status, path.strip('"')))
    return sorted(entries, key=lambda e: e[1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openmaic", type=Path, default=Path("../OpenMAIC"))
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        help="Patch set being prepared; its files are expected and allowed.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when anything foreign is present.",
    )
    args = parser.parse_args()

    repo = args.openmaic
    if not (repo / ".git").exists():
        print(f"[guard] not a git checkout: {repo}", file=sys.stderr)
        return 2

    allowed = PROFILES.get(args.profile, set())
    entries = changed_paths(repo)
    head = git(repo, "log", "--oneline", "-1").strip()
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()

    print(f"[guard] {repo} on {branch} at {head}")
    if args.profile:
        print(f"[guard] profile: {args.profile}")

    if not entries:
        print("[guard] checkout is clean — a pristine mirror of upstream.")
        return 0

    buckets: dict[str, list[tuple[str, str]]] = {"allowed": [], "ours": [], "foreign": []}
    for status, path in entries:
        if path in OURS:
            buckets["ours"].append((status, path))
        elif path in allowed:
            buckets["allowed"].append((status, path))
        else:
            buckets["foreign"].append((status, path))

    for label, heading in (
        ("allowed", "expected for this profile"),
        ("ours", "generated by us, not for upstream"),
        ("foreign", "NOT ours — would ride along into a PR"),
    ):
        rows = buckets[label]
        if rows:
            print(f"\n[guard] {heading}: {len(rows)}")
            for status, path in rows:
                print(f"  {status:2} {path}")

    if buckets["foreign"]:
        print(
            f"\n[guard] {len(buckets['foreign'])} foreign change(s). Revert or stash them "
            "before generating a patch or opening an upstream PR.",
            file=sys.stderr,
        )
        return 1 if args.strict else 0

    print("\n[guard] nothing foreign.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
