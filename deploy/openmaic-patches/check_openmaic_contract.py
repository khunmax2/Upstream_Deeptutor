"""Check the handful of assumptions this fork makes about OpenMAIC.

The embed is not a code dependency — nothing here imports
anything there. What it depends on is a small contract: a URL that serves the
app, `frame-ancestors` that admits our origin, an access gate that stays off, a
container port, one identity header both sides agree on, and a compose file that
keeps the studio unreachable except through the gatekeeper. Every one of them is
a behaviour of code a future release could change — theirs, or ours.

The failure mode is what makes this worth automating. If they rename
ALLOWED_FRAME_ANCESTORS or start sending `X-Frame-Options: DENY`, the iframe goes
blank with only a console error — the same symptom as a dozen unrelated problems,
and one that cost real time to diagnose the first time. This turns that into a
named assertion that fails in seconds.

Offline checks (no server needed) compare the checkout against
``openmaic-pin.json``: the commit we verified against, and the locale key count,
which drifts by roughly 50-90 keys a week upstream and is what silently puts the
Thai translation out of date.

The identity-header and compose checks need neither a checkout nor a server, so
they run every time — they are the halves that drift without anyone noticing.
The compose half parses the overlay with PyYAML, because a grep cannot tell a
`ports:` key from the comment explaining why there is none.

Usage::

    # offline only — version pin, key-count drift, identity header, compose
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


def checkout_head(repo: Path) -> str | None:
    """The commit the studio checkout is currently on.

    Under ADR-0005 the studio is a sibling repository rather than a squashed
    subtree, so this is simply its HEAD. The previous version of this function
    read the subject of a `git subtree --squash` commit, which was the only
    durable statement of provenance while the code was vendored — and which
    stopped existing when the subtree came off `main` on 2026-09-09, leaving this
    check failing for a reason that had nothing to do with the contract.
    """
    import subprocess as _sp

    result = _sp.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return None
    head = result.stdout.strip()
    return head or None


GATEKEEPER = HERE.parent / "openmaic-gatekeeper" / "gatekeeper.mjs"


def identity_contract_checks(repo: Path, pin: dict[str, Any], report: Report) -> None:
    """The one name the two systems must agree on.

    The gatekeeper sets a header; the studio reads it and turns it into an
    ``owner_id``. Nothing else couples them, and a rename on either side is the
    quietest failure this design has: no error, no log line, the app keeps
    working, and every reader silently stops seeing their own documents because
    the studio falls back to minting an anonymous owner per browser.

    So both sides are read from source and compared against the pin, rather than
    either being trusted to still say what it said last week.
    """
    print("\n[contract] identity header")

    contract = pin.get("contract") or {}
    expected = contract.get("identity_header")
    if not expected:
        report.fail("identity pin", "openmaic-pin.json has no contract.identity_header")
        return

    if not GATEKEEPER.is_file():
        report.fail("gatekeeper source", f"missing {GATEKEEPER}")
    else:
        source = GATEKEEPER.read_text(encoding="utf-8")
        # The default in the `||` fallback is the value that ships. An env var can
        # override it, but a deployment that overrides it has to override the
        # studio too, and that is what this pin exists to force a decision about.
        if f"'{expected}'" in source:
            report.ok("gatekeeper sets", expected)
        else:
            report.fail(
                "gatekeeper sets",
                f"gatekeeper.mjs does not mention {expected!r} — renamed on this side?",
            )

        prefix = contract.get("identity_prefix")
        if prefix and f"'{prefix}'" in source:
            report.ok("identity prefix", prefix)
        elif prefix:
            report.fail("identity prefix", f"gatekeeper.mjs does not mention {prefix!r}")

    if not contract.get("studio_threaded"):
        report.skip(
            "studio reads",
            "the fork does not thread authenticatedOwnerId yet — flip "
            "contract.studio_threaded once it does, and this becomes a real check",
        )
        return

    # No checkout is not drift. CI runs this half deliberately without one -- the
    # gatekeeper side needs no studio source, which is the whole reason it can run
    # there -- so a missing tree has to skip, the same way the checkout section
    # above skips, rather than report the two sides as having come apart. Getting
    # this wrong turned a green job red and said something untrue about the fork
    # while doing it.
    if not (repo / "lib").is_dir():
        report.skip(
            "studio reads",
            f"no OpenMAIC source at {repo} — pass --openmaic <checkout> to verify "
            "the studio half; contract.studio_threaded says it is there to be found",
        )
        return

    # Once the fork is threaded, the header must appear in its source too.
    hits = [
        path
        for path in (repo / "lib").rglob("*.ts")
        if expected in path.read_text(encoding="utf-8", errors="replace")
    ]
    if hits:
        report.ok("studio reads", f"{expected} in {hits[0].relative_to(repo)}")
    else:
        report.fail(
            "studio reads",
            f"contract.studio_threaded is true but no file under {repo / 'lib'} mentions "
            f"{expected!r} — the two sides have drifted apart",
        )


COMPOSE = HERE.parent / "docker-compose.openmaic.yml"
STUDIO_SERVICE = "openmaic"
GATEKEEPER_SERVICE = "gatekeeper"
DB_SERVICE = "openmaic-postgres"


def _env_map(service: dict[str, Any]) -> dict[str, str]:
    """Compose accepts `environment` as a list or a mapping. Read both."""
    env = service.get("environment") or {}
    if isinstance(env, dict):
        return {str(k): "" if v is None else str(v) for k, v in env.items()}
    out: dict[str, str] = {}
    for item in env:
        name, _, value = str(item).partition("=")
        out[name] = value
    return out


def compose_checks(pin: dict[str, Any], report: Report) -> None:
    """T1, control 2 — the deploy-time assertion.

    Controls 1 and 3 protect a network property and a runtime behaviour. This one
    protects the file, because the file is what a hurried edit touches: one
    ``ports:`` line under the studio and the identity header stops meaning
    anything, with no error anywhere to say so.

    Read as YAML rather than grepped: a comment saying ``# ports:`` must not fail,
    and a ``ports:`` nested under the wrong service must not pass.
    """
    print("\n[contract] compose")

    try:
        import yaml
    except ModuleNotFoundError:
        # Deliberately not a SKIP. A security assertion that quietly stops running
        # is worth less than no assertion, because the file still looks checked.
        report.fail("PyYAML", "not installed — `pip install pyyaml` (it is a project dependency)")
        return

    if not COMPOSE.is_file():
        report.fail("overlay", f"missing {COMPOSE}")
        return

    doc = yaml.safe_load(COMPOSE.read_text(encoding="utf-8")) or {}
    services = doc.get("services") or {}

    studio = services.get(STUDIO_SERVICE)
    if not isinstance(studio, dict):
        report.fail("studio service", f"no `{STUDIO_SERVICE}` service in {COMPOSE.name}")
        return

    # --- T1.1: the studio publishes nothing -------------------------------------
    if "ports" in studio:
        report.fail(
            "studio publishes no port",
            f"`{STUDIO_SERVICE}` has a `ports:` key — anyone on the host can then send "
            "the identity header directly and become any user",
        )
    else:
        report.ok("studio publishes no port")

    if studio.get("network_mode") == "host":
        report.fail("studio is not on the host network", "`network_mode: host` bypasses `ports:`")
    else:
        report.ok("studio is not on the host network")

    studio_networks = set(studio.get("networks") or [])
    if "deeptutor-network" in studio_networks:
        report.fail(
            "studio is off the shared network",
            "the studio is reachable from every other container in the stack; the "
            "coupling is a URL and a header, not a container-to-container call",
        )
    else:
        report.ok("studio is off the shared network", ", ".join(sorted(studio_networks)))

    # --- T1.3: fail closed inside the studio ------------------------------------
    studio_env = _env_map(studio)
    if studio_env.get("STUDIO_REQUIRE_GATEWAY") == "1":
        report.ok("studio fails closed", "STUDIO_REQUIRE_GATEWAY=1")
    else:
        report.fail(
            "studio fails closed",
            "STUDIO_REQUIRE_GATEWAY is not 1 — a request that arrives without the "
            "identity header would fall back to a fresh anonymous owner",
        )

    # --- T3: upstream's development authenticator stays refused -----------------
    # Read from the parsed services, not from the text: the overlay explains in a
    # comment why this variable is absent, and a checker that cannot tell a comment
    # from a setting would fail on the explanation.
    # Two variables, one authenticator, and they are read in this order:
    # PERSISTENCE_DEV_TOKEN is what the route demands before it will serve at all
    # (503 without it), and PERSISTENCE_ALLOW_INSECURE_DEV_AUTH is what lets that
    # authenticator run under NODE_ENV=production (401 without it). Supplying the
    # first is the plausible mistake — it is how a deployer makes a 503 go away —
    # so it is checked in its own right, not only as the second one's companion.
    for variable, why in (
        (
            "PERSISTENCE_DEV_TOKEN",
            "its public half is compiled into the browser bundle, so identity would "
            "come from a client-supplied x-learner-key",
        ),
        (
            "PERSISTENCE_ALLOW_INSECURE_DEV_AUTH",
            "it re-enables that authenticator under NODE_ENV=production",
        ),
    ):
        setters = [
            name
            for name, service in services.items()
            if isinstance(service, dict) and variable in _env_map(service)
        ]
        label = f"no {variable}"
        if setters:
            report.fail(label, f"{setters} set it — {why}")
        else:
            report.ok(label)

    # --- T1.1's companion: the gate is the only published thing -----------------
    gate = services.get(GATEKEEPER_SERVICE)
    if not isinstance(gate, dict):
        report.fail("gatekeeper service", f"no `{GATEKEEPER_SERVICE}` service in {COMPOSE.name}")
    else:
        published = [str(p) for p in (gate.get("ports") or [])]
        stray = [p for p in published if not p.startswith("127.0.0.1:")]
        if not published:
            report.fail("gate is published to loopback", "the gatekeeper publishes nothing")
        elif stray:
            report.fail(
                "gate is published to loopback",
                f"{stray} binds every interface; nginx terminates TLS in front of it",
            )
        else:
            report.ok("gate is published to loopback", published[0])

    # --- the third side of the identity contract --------------------------------
    # The pin and the gatekeeper source are compared above. Compose is where a
    # rename would actually be applied, and it feeds both containers.
    expected = (pin.get("contract") or {}).get("identity_header")
    gate_env = _env_map(gate) if isinstance(gate, dict) else {}
    defaults = {
        name: env.get("STUDIO_IDENTITY_HEADER", "")
        for name, env in (("studio", studio_env), ("gatekeeper", gate_env))
    }
    if expected and all(f":-{expected}}}" in value for value in defaults.values()):
        report.ok("compose passes one header name", expected)
    else:
        report.fail(
            "compose passes one header name",
            f"expected both services to default STUDIO_IDENTITY_HEADER to {expected!r}, "
            f"got {defaults}",
        )

    # --- the two halves of the base path ---------------------------------------
    # NEXT_PUBLIC_STUDIO_BASE_PATH is compiled into the image, so the path the
    # studio serves under is a property of the IMAGE. The only thing compose
    # decides is where the healthcheck probes. When the two drift the container
    # never reports healthy and nothing says why — the healthcheck simply asks
    # for a path the image does not serve.
    expected_base = (pin.get("contract") or {}).get("base_path")
    if expected_base:
        probe = str(studio.get("healthcheck", {}).get("test", ""))
        wanted = "STUDIO_BASE_PATH:-" + expected_base + "}"
        if wanted in probe:
            report.ok("healthcheck probes the built base path", expected_base)
        else:
            report.fail(
                "healthcheck probes the built base path",
                f"the image is pinned as built for {expected_base!r}, so the "
                f"healthcheck must default STUDIO_BASE_PATH to it; the probe reads "
                f"{probe!r}",
            )

    # --- the database is not a second door --------------------------------------
    db = services.get(DB_SERVICE)
    if not isinstance(db, dict):
        report.fail("database service", f"no `{DB_SERVICE}` service in {COMPOSE.name}")
    elif "ports" in db:
        report.fail("database publishes no port", f"`{DB_SERVICE}` has a `ports:` key")
    elif db.get("profiles"):
        report.fail(
            "database always starts",
            f"`{DB_SERVICE}` is behind profile {db['profiles']} — per-account isolation "
            "needs the database, so a stack started without it silently loses it",
        )
    else:
        report.ok("database publishes no port")
        report.ok("database always starts")


def offline_checks(repo: Path, pin: dict[str, Any], report: Report) -> None:
    print("\n[contract] checkout")

    # The studio is its own checkout now, so the question is simply whether it
    # sits on the commit everything here was measured against.
    head = checkout_head(repo)
    pinned = pin["commit"]
    if head is None:
        report.fail("version pin", f"{repo} is not a git checkout — cannot read HEAD")
    elif pinned.startswith(head) or head.startswith(pinned):
        report.ok("version pin", f"checkout is on the verified commit {pin['commit_short']}")
    else:
        # Not a failure of the code — moving forward is the point. It is a cue to
        # re-measure before trusting the checkout again. Every rebase carries the
        # DDL-drift risk, so this reports the distance and does not force the move.
        report.fail(
            "version pin",
            f"checkout is on {head[:8]} != verified {pin['commit_short']} — "
            "re-run the checks, then bump the pin",
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

    # package.json is what says "the source is here". Under ADR-0005 the studio is
    # a sibling checkout with its own .git, so the version pin reads that checkout's
    # HEAD rather than a squash commit in this repository.
    if (args.openmaic / "package.json").is_file():
        offline_checks(args.openmaic, pin, report)
    else:
        print(f"\n[contract] checkout\n  SKIP  no OpenMAIC source at {args.openmaic}")

    # The gatekeeper half of the identity contract needs no studio checkout, and it
    # is the half that can drift without anyone noticing, so it runs either way.
    identity_contract_checks(args.openmaic, pin, report)

    # The compose overlay is ours and needs no checkout of anything, so it runs
    # unconditionally — it is the file where a network control is lost by accident.
    compose_checks(pin, report)

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
