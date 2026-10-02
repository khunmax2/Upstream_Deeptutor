"""Alice creates a course; Bob, another signed-in account, tries every read path.
Runs inside a container on the studio network, addressing the studio directly with
the identity header the gatekeeper would set (the audit's method)."""

import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1].rstrip("/")  # e.g. http://openmaic:3000/deepwitya/studio
H = "x-deeptutor-owner"


def call(owner, method, path, body=None):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=(json.dumps(body).encode() if body is not None else None),
        headers={H: owner, "x-deeptutor-role": "user", "content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, r.read(300)
    except urllib.error.HTTPError as e:
        return e.code, e.read(200)
    except Exception as e:
        return "T/O", b""


now = int(time.time() * 1000)
sid = f"stage-f1probe{now % 100000}"
doc = {
    "stage": {"id": sid, "name": "F1 probe course", "createdAt": now, "updatedAt": now},
    "scenes": [],
    "outline": {
        "outlines": [],
        "requirement": "F1 probe course",
        "generationComplete": False,
        "createdAt": now,
        "updatedAt": now,
    },
}
print("alice creates:", call("user:alice", "PUT", f"/api/persistence/documents/{sid}", doc)[0])


def sweep(label):
    print(f"--- {label} ---")
    for who in ("user:alice", "user:bob"):
        rows = []
        for m, p in [
            ("GET", f"/api/stages/{sid}"),
            ("GET", f"/api/persistence/documents/{sid}"),
            ("GET", f"/api/stages/{sid}/status"),
            ("GET", f"/api/stage-meta/{sid}"),
            ("GET", f"/api/stages/{sid}/manifest"),
            ("GET", f"/api/stages/{sid}/scenes"),
            ("GET", f"/api/stages/{sid}/freshness"),
        ]:
            st, _ = call(who, m, p)
            rows.append(
                f"{('doc' if 'persistence' in p else p.split('/')[-1] if not p.endswith(sid) else 'stage')}={st}"
            )
        wst, _ = call(
            who,
            "PUT",
            f"/api/persistence/documents/{sid}",
            {**doc, "stage": {**doc["stage"], "name": "edited by " + who}},
        )
        rows.append(f"PUT={wst}")
        print(f"  {who:11s}", "  ".join(rows))


sweep("private (as created)")
print("alice publishes:", call("user:alice", "POST", f"/api/stages/{sid}/publish")[0])
sweep("published")
print("alice unpublishes:", call("user:alice", "POST", f"/api/stages/{sid}/unpublish")[0])
sweep("unpublished again")
print("alice deletes:", call("user:alice", "DELETE", f"/api/stages/{sid}")[0])
