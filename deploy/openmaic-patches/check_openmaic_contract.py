"""Check the handful of assumptions this fork makes about OpenMAIC.

The embed at `/maic` is not a code dependency — nothing here imports anything
there. What it depends on is a small runtime contract: a URL that serves the app,
an environment variable that widens its `frame-ancestors`, an access gate that
stays off, and a container port. Five things, and every one of them is a
behaviour of *their* code that a future release could change.

The failure mode is what makes this worth automating. If they rename
ALLOWED_FRAME_ANCESTORS or start sending `X-Frame-Options: DENY`, the iframe goes
blank with only a console error — the same symptom as a dozen unrelated problems,
and one that cost real time to diagnose the first time. This turns that into a
named assertion that fails in seconds.

Offline checks (no server needed) compare the checkout against
``openmaic-pin.json``: the commit we verified against, and the locale key count,
which drifts by roughly 50-90 keys a week upstream and is what silently puts the
Thai translation out of date.

Usage::

    # offline only — version pin and key-count drift
    python deploy/openmaic-patches/check_openmaic_contract.py --openmaic ../OpenMAIC

    # plus the runtime contract, against a running OpenMAIC
    python deploy/openmaic-patches/check_openmaic_contract.py \\
        --openmaic ../OpenMAIC \\
        --url http://localhost:3100 \\
        --origin http://localhost:3782

Exit code is non-zero when any check fails, so it can gate a sync.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
PIN = HERE / "openmaic-pin.json"
TIMEOUT = 20


class Report:
    """Collects pass/fail lines so every check runs before anything exits."""

    def __init__(self) -> None:
        self.failed = 0

    def ok(self, name: str, detail: str = "") -> None:
        print(f"  PASS  {name}{f' — {detail}' if detail else ''}")

    def fail(self, name: str, detail: str) -> None:
        self.failed += 1
        print(f"  FAIL  {name} — {detail}")

    def skip(self, name: str, detail: str) -> None:
        print(f"  SKIP  {name} — {detail}")

    def check(self, name: str, passed: bool, detail: str = "") -> None:
        self.ok(name, detail) if passed else self.fail(name, detail)


def load_pin() -> dict[str, Any]:
    return json.loads(PIN.read_text(encoding="utf-8"))


def count_leaves(node: Any) -> int:
    if isinstance(node, dict):
        return sum(count_leaves(v) for v in node.values())
    return 1


def offline_checks(repo: Path, pin: dict[str, Any], report: Report) -> None:
    print("\n[contract] checkout")

    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    pinned = pin["commit"]
    if head == pinned:
        report.ok("version pin", f"at the verified commit {pin['commit_short']}")
    else:
        # Not a failure on its own — moving forward is the point. It is a cue to
        # re-run the guard and re-measure before trusting the patches again.
        report.fail(
            "version pin",
            f"HEAD {head[:8]} != pinned {pin['commit_short']} — re-verify, then bump the pin",
        )

    source = repo / "lib" / "i18n" / "locales" / "en-US.json"
    if not source.is_file():
        report.fail("locale source", f"missing {source}")
        return

    keys = count_leaves(json.loads(source.read_text(encoding="utf-8")))
    expected = pin["verified_against"]["locale_keys_en_us"]
    if keys == expected:
        report.ok("locale key count", f"{keys} keys, unchanged since the pin")
    else:
        delta = keys - expected
        report.fail(
            "locale key count",
            f"{keys} keys, {delta:+d} since the pin — re-run build_th_locale.py --check",
        )


def fetch(url: str) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": "openmaic-contract-check"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
        headers = {k.lower(): v for k, v in response.headers.items()}
        return response.status, headers, response.read()


def runtime_checks(url: str, origin: str | None, report: Report) -> None:
    print(f"\n[contract] runtime — {url}")

    base = url.rstrip("/")
    try:
        status, headers, _ = fetch(base + "/")
    except (urllib.error.URLError, OSError) as exc:
        report.fail("reachable", f"{base}/ did not answer ({exc})")
        return

    report.check("reachable", status == 200, f"HTTP {status}")

    # X-Frame-Options only supports SAMEORIGIN, so OpenMAIC omits it whenever
    # ALLOWED_FRAME_ANCESTORS names an extra origin. Anything present here means
    # a cross-origin embed is refused before CSP is even consulted.
    xfo = headers.get("x-frame-options", "")
    report.check(
        "no X-Frame-Options",
        not xfo,
        f"header present: {xfo}" if xfo else "absent, as expected",
    )

    csp = headers.get("content-security-policy", "")
    if "frame-ancestors" not in csp:
        report.fail("frame-ancestors", "no frame-ancestors directive in the CSP")
    elif origin is None:
        report.ok("frame-ancestors", csp.strip())
    else:
        report.check(
            "frame-ancestors allows us",
            origin in csp,
            f"{origin} {'is' if origin in csp else 'is NOT'} in: {csp.strip()}",
        )

    # The embed inherits no authentication, so OpenMAIC's own gate must stay off:
    # with it on, its SameSite=Lax cookie cannot survive a cross-origin frame and
    # the embed locks out rather than locking down.
    try:
        _, _, body = fetch(base + "/api/access-code/status")
        payload = json.loads(body)
        enabled = bool(payload.get("data", payload).get("enabled"))
        report.check(
            "access gate off",
            not enabled,
            "ACCESS_CODE is set — the frame will lock out" if enabled else "unset, as expected",
        )
    except (urllib.error.URLError, OSError, ValueError, AttributeError) as exc:
        report.fail("access gate off", f"could not read /api/access-code/status ({exc})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openmaic", type=Path, default=Path("../OpenMAIC"))
    parser.add_argument("--url", help="Base URL of a running OpenMAIC, e.g. http://localhost:3100")
    parser.add_argument("--origin", help="Our origin, which its frame-ancestors must allow")
    args = parser.parse_args()

    pin = load_pin()
    report = Report()

    print(
        f"[contract] pinned to {pin['commit_short']} ({pin['commit_date']}), "
        f"verified {pin['verified']}"
    )

    if (args.openmaic / ".git").exists():
        offline_checks(args.openmaic, pin, report)
    else:
        print(f"\n[contract] checkout\n  SKIP  not a git checkout: {args.openmaic}")

    if args.url:
        runtime_checks(args.url, args.origin, report)
    else:
        print("\n[contract] runtime\n  SKIP  no --url given")

    print()
    if report.failed:
        print(f"[contract] {report.failed} check(s) failed.", file=sys.stderr)
        return 1
    print("[contract] all checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
