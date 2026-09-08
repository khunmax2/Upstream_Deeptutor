"""Scenario UAT for the embedded course studio.

Drives `/api/generate-classroom` the way the browser does — through the public
origin, past the gatekeeper, with a real DeepTutor session — and then measures
what actually came back, because "the job says succeeded" and "the course is
usable" are different claims.

The measurement exists for one specific doubt: the configured LLM is a *lite*
model, and a course is mostly long HTML. A model that runs out of output budget
does not error; it stops mid-tag, and the scene still counts as generated. So
this checks each scene's HTML for balance and for the shapes a truncated
generation leaves behind, and reports sizes rather than a pass/fail alone.

Run inside the deeptutor container (it needs `create_token`):

    docker exec -w /app -e PYTHONPATH=/app deeptutor2 \
        python3 /tmp/uat_course_studio.py "https://HOST/course-studio-app" "TOPIC"
"""

from __future__ import annotations

import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request

POLL_LIMIT_S = 900


def _req(url: str, token: str, *, data: dict | None = None, timeout: int = 60):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(
        url,
        data=body,
        headers={
            "Cookie": f"dt_token={token}",
            **({"Content-Type": "application/json"} if body else {}),
        },
        method="POST" if body else "GET",
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(r, timeout=timeout, context=ctx) as resp:
        return resp.status, json.loads(resp.read().decode())


def looks_truncated(html: str) -> list[str]:
    """Signs that a generation stopped early rather than finished."""
    problems = []
    opens = len(re.findall(r"<(?!/)(?!br|img|hr|input|meta|link)([a-zA-Z][\w-]*)", html))
    closes = len(re.findall(r"</([a-zA-Z][\w-]*)", html))
    if opens - closes > 2:
        problems.append(f"unclosed tags (open {opens} vs close {closes})")
    tail = html.rstrip()[-60:]
    if tail and not tail.endswith(">"):
        problems.append(f"ends mid-markup: …{tail[-40:]!r}")
    if "```" in html:
        problems.append("carries a markdown code fence")
    return problems


def main(origin: str, topic: str, username: str) -> int:
    from deeptutor.services.auth import create_token

    token = create_token(username, "admin")
    origin = origin.rstrip("/")

    print(f"→ requirement: {topic!r}")
    t0 = time.time()
    status, payload = _req(
        f"{origin}/api/generate-classroom", token, data={"requirement": topic}
    )
    if status != 202:
        print(f"✗ submit returned {status}: {json.dumps(payload)[:300]}")
        return 1
    job = payload.get("data", payload)
    job_id = job.get("jobId")
    print(f"✓ accepted, jobId={job_id}")

    seen_steps: list[str] = []
    last = None
    while True:
        if time.time() - t0 > POLL_LIMIT_S:
            print(f"✗ still running after {POLL_LIMIT_S}s — steps seen: {seen_steps}")
            return 1
        time.sleep(5)
        try:
            _, p = _req(f"{origin}/api/generate-classroom/{job_id}", token)
        except urllib.error.HTTPError as e:
            print(f"✗ poll failed: {e.code} {e.read()[:200]}")
            return 1
        d = p.get("data", p)
        step, scenes = d.get("step"), d.get("scenesGenerated")
        if (step, scenes) != last:
            print(f"  [{time.time() - t0:6.1f}s] {step}  scenes={scenes}")
            last = (step, scenes)
            if step and step not in seen_steps:
                seen_steps.append(step)
        if d.get("done"):
            break

    elapsed = time.time() - t0
    if d.get("status") != "succeeded":
        print(f"\n✗ FAILED after {elapsed:.0f}s: {d.get('error')}")
        return 1

    result = d.get("result") or {}
    raw = json.dumps(result, ensure_ascii=False)
    scenes = result.get("scenes") or result.get("stages") or []
    print(f"\n✓ succeeded in {elapsed:.0f}s")
    print(f"  steps      : {' → '.join(seen_steps)}")
    print(f"  payload    : {len(raw):,} chars")
    print(f"  scenes     : {len(scenes)}")

    if not scenes:
        print("  ! no scenes in the result — keys:", list(result)[:12])
        return 1

    bad = 0
    for i, sc in enumerate(scenes, 1):
        blob = json.dumps(sc, ensure_ascii=False)
        html = "".join(re.findall(r"<[^>]+>.*?(?=<|$)", blob, re.S))[:200000]
        title = (sc.get("title") or sc.get("name") or "")[:34]
        problems = looks_truncated(blob)
        thai = len(re.findall(r"[฀-๿]", blob))
        flag = "  ⚠ " + "; ".join(problems) if problems else ""
        if problems:
            bad += 1
        print(f"    {i:2}. {title:<34} {len(blob):>7,} chars  thai={thai:>5}{flag}")

    print(f"\n  scenes with truncation signs: {bad}/{len(scenes)}")
    return 1 if bad else 0


if __name__ == "__main__":
    o = sys.argv[1] if len(sys.argv) > 1 else "https://203.185.144.41/course-studio-app"
    t = sys.argv[2] if len(sys.argv) > 2 else "สอนพื้นฐานการสังเคราะห์แสงสำหรับนักเรียนมัธยมต้น 5 บท"
    u = sys.argv[3] if len(sys.argv) > 3 else "admin@example.com"
    raise SystemExit(main(o, t, u))
