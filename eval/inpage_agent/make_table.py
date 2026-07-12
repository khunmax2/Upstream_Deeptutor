"""Render results_ours.json as the report's markdown table + summary lines."""

from __future__ import annotations

import json
from pathlib import Path

R = json.loads((Path(__file__).parent / "results_ours.json").read_text(encoding="utf-8"))

print("| task | category | success | reason | steps | LLM calls | tokens | wall s | gate |")
print("|---|---|:--:|---|--:|--:|--:|--:|:--:|")
for r in R:
    ok = "✅" if r["success"] else "❌"
    print(
        f"| `{r['id']}` | {r['category']} | {ok} | {r['stopped_reason']} | "
        f"{r['steps']} | {r['llm_calls']} | {r['total_tokens']:,} | {r['wall_s']} | "
        f"{r['gate_blocks']} |"
    )

n = len(R)
succ = sum(x["success"] for x in R)
clean = sum(x["success"] and x["stopped_reason"] == "done" for x in R)
toks = [x["total_tokens"] for x in R if x["total_tokens"]]
print(f"\nsuccess {succ}/{n} · clean-done {clean}/{n} · median tokens/task "
      f"{sorted(toks)[len(toks)//2] if toks else 0:,}")
danger = [x for x in R if x["category"] == "danger"]
if danger:
    d = danger[0]
    print(f"danger: gate_blocks={d['gate_blocks']} success={d['success']} — {d['detail']}")
