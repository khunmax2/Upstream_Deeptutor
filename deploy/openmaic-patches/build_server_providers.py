#!/usr/bin/env python3
"""Write OpenMAIC's `server-providers.yml` from DeepTutor's provider settings.

The mapping itself lives in `deeptutor.services.config.openmaic_bridge`, which
ships inside the application — DeepTutor rewrites this file itself whenever
provider settings are saved, so a rotated key reaches OpenMAIC without anybody
opening a shell.

This CLI stays for the times you want to run it by hand: a first bring-up
before the app has saved anything, a dry run to read the mapping decisions, or
a deployment whose settings were edited on disk.

    python build_server_providers.py --dry-run
    python build_server_providers.py --out data/user/openmaic/server-providers.yml
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def _load_bridge():
    """Import the mapping, from an install or from a checkout.

    Inside the container `deeptutor` is already importable and this returns
    immediately. From a checkout it is not, so the repo root is found by
    looking for the module rather than by counting directories — a fixed
    `parents[2]` made the script unrunnable from anywhere but its own folder,
    which is exactly where an operator copying it to /tmp will not be.
    """
    try:
        from deeptutor.services.config.openmaic_bridge import build, to_yaml
    except ModuleNotFoundError:
        here = Path(__file__).resolve()
        target = Path("deeptutor/services/config/openmaic_bridge.py")
        root = next((p for p in here.parents if (p / target).is_file()), None)
        if root is None:
            raise SystemExit(
                "[server-providers] cannot find deeptutor/services/config/"
                "openmaic_bridge.py — run this from a checkout of the repository, "
                "or from inside the DeepTutor container where the package is "
                "installed."
            ) from None
        sys.path.insert(0, str(root))
        from deeptutor.services.config.openmaic_bridge import build, to_yaml
    return build, to_yaml


build, to_yaml = _load_bridge()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=Path("data/user/settings"))
    parser.add_argument("--out", type=Path, default=Path("data/user/openmaic/server-providers.yml"))
    parser.add_argument(
        "--host-alias",
        default="host.docker.internal",
        help="what the container should call the host (default: host.docker.internal)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print it with keys masked")
    args = parser.parse_args()

    catalog_path = args.settings / "model_catalog.json"
    if not catalog_path.is_file():
        print(f"[server-providers] not found: {catalog_path}", file=sys.stderr)
        return 2

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    sections, notes = build(catalog, args.host_alias)

    if not sections:
        print("[server-providers] nothing to write — no provider in DeepTutor maps to OpenMAIC.")
        for note in notes:
            print(f"  {note}")
        return 1

    for note in notes:
        print(f"[server-providers] {note}")

    counts = ", ".join(f"{name} {len(entries)}" for name, entries in sorted(sections.items()))
    print(f"[server-providers] {counts}")

    if args.dry_run:
        print()
        print(to_yaml(sections, mask=True))
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(to_yaml(sections, mask=False), encoding="utf-8", newline="\n")
    print(f"[server-providers] wrote {args.out}")
    print("[server-providers] OpenMAIC re-reads it on change; no restart needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
