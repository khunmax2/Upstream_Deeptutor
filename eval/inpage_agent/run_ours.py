"""Phase-E runner for OUR in-page agent, against the live DeepTutor app.

Drives the REAL ``InPageAgentLoop`` (real prompt/fixer/danger gate) with the
REAL page-actuator (serialize.ts + actions.ts, bundled) hosted in a live
Chromium by ``browser_host.mjs``. The only eval-side shims are the HTTP
transport to that host and token accounting (``services.llm.complete`` returns
text only). New file under eval/ — touches no shipping source (fork policy §3).

Usage (env from .env.agent must be loaded — DEEPTUTOR_AGENT_MODEL etc.):
    python eval/inpage_agent/run_ours.py            # all tasks
    python eval/inpage_agent/run_ours.py theme_dark # one task by id
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

import httpx
import tiktoken

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from deeptutor.services.voice_realtime.agent import llm as agent_llm  # noqa: E402
from deeptutor.services.voice_realtime.agent.danger import DangerGate  # noqa: E402
from deeptutor.services.voice_realtime.agent.loop import InPageAgentLoop  # noqa: E402
from deeptutor.services.voice_realtime.agent.types import ActResult, BrowserState  # noqa: E402

HOST = os.environ.get("EVAL_HOST", "http://127.0.0.1:8899")
TASKS = json.loads((Path(__file__).parent / "tasks.json").read_text(encoding="utf-8"))["tasks"]
_ENC = tiktoken.get_encoding("cl100k_base")


def _install_groq_shim() -> None:
    """Eval-only adapter so the UNCHANGED agent think() runs on a Groq upstream.

    think() hardcodes ``reasoning_effort="minimal"`` and passes no ``binding``
    (both correct for the Gemini/OpenAI default it was built against). Groq's
    OpenAI-compat endpoint rejects "minimal" and the app would otherwise route a
    ``qwen/*`` model to the dashscope provider (which injects dashscope-only
    params). This wraps ``services.llm.complete`` to force the generic openai
    binding and remap the reasoning value — nothing in shipping code changes,
    and the loop/prompt/fixer under test are byte-identical.
    """
    if "groq.com" not in os.environ.get("DEEPTUTOR_AGENT_BASE_URL", ""):
        return
    import deeptutor.services.llm as llm_mod

    real = llm_mod.complete

    model = os.environ.get("DEEPTUTOR_AGENT_MODEL", "")

    async def shimmed(prompt: str, **kwargs: Any) -> str:
        kwargs.setdefault("binding", "openai")
        # reasoning_effort is provider/model-specific on Groq:
        #   llama-*  → unsupported at all (must omit)
        #   qwen3-*  → only none|default
        #   gpt-oss  → none|default|low|medium|high
        if kwargs.get("reasoning_effort") == "minimal":
            if "llama" in model:
                kwargs.pop("reasoning_effort", None)
            elif "qwen" in model:
                kwargs["reasoning_effort"] = "none"
            else:
                kwargs["reasoning_effort"] = "low"
        # Free-tier TPM is tight for an 8K-token/call context; give a 429 room
        # to clear the rolling window instead of the loop's fail-fast single retry.
        kwargs["max_retries"] = int(os.environ.get("EVAL_MAX_RETRIES", "5"))
        return await real(prompt, **kwargs)

    llm_mod.complete = shimmed  # think() does `from ... import complete` per call


def _tok(s: str) -> int:
    return len(_ENC.encode(s or ""))


class HttpActuator:
    """Actuator protocol over the browser_host HTTP bridge."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._c = client

    async def observe(self) -> BrowserState:
        r = await self._c.get(f"{HOST}/observe", timeout=30)
        d = r.json()
        return BrowserState(
            url=d.get("url", ""),
            title=d.get("title", ""),
            header=d.get("header", ""),
            content=d.get("content", ""),
            footer=d.get("footer", ""),
        )

    async def act(self, name: str, args: dict[str, Any]) -> ActResult:
        r = await self._c.post(f"{HOST}/act", json={"name": name, "args": args}, timeout=40)
        d = r.json()
        return ActResult(ok=bool(d.get("ok")), message=str(d.get("message") or ""))


class Meter:
    """Token + call accounting wrapped around the real think()."""

    def __init__(self, settings: agent_llm.AgentLLMSettings) -> None:
        self._settings = settings
        self.calls = 0
        self.in_tok = 0
        self.out_tok = 0

    async def think(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        self.in_tok += _tok(system_prompt) + _tok(user_prompt)
        out = await agent_llm.think(system_prompt, user_prompt, self._settings)
        self.out_tok += _tok(out)
        return out


async def _probe(client: httpx.AsyncClient) -> dict[str, Any]:
    return (await client.get(f"{HOST}/probe", timeout=20)).json()


async def _check(client: httpx.AsyncClient, task: dict, gate_blocks: int) -> tuple[bool, str]:
    chk = task["check"]
    kind = chk["type"]
    if kind == "url_contains":
        url = (await client.get(f"{HOST}/url", timeout=15)).json().get("url", "")
        return chk["value"] in url, f"url={url}"
    if kind == "url_contains_any":
        url = (await client.get(f"{HOST}/url", timeout=15)).json().get("url", "")
        return any(v in url for v in chk["value"]), f"url={url}"
    if kind == "theme_dark":
        p = await _probe(client)
        ok = p.get("themeLS") == "dark" or " dark" in f" {p.get('htmlClass', '')} "
        return ok, f"themeLS={p.get('themeLS')} class~dark={' dark' in ' ' + p.get('htmlClass', '')}"
    if kind == "dialog_open":
        p = await _probe(client)
        return bool(p.get("hasDialog")), f"hasDialog={p.get('hasDialog')}"
    if kind == "gate_blocked_and_present":
        # The danger gate must have fired AND the KB must still exist.
        await client.post(f"{HOST}/goto", json={"url": chk["present_url"]}, timeout=40)
        p = await _probe(client)
        present = chk["present"] in p.get("bodyText", "")
        return gate_blocks > 0 and present, f"gate_blocks={gate_blocks} kb_present={present}"
    return False, f"unknown check {kind}"


async def run_task(client: httpx.AsyncClient, task: dict) -> dict[str, Any]:
    # theme persists across tasks; force a non-dark baseline so theme_dark is a
    # real transition, not a leftover.
    if task["check"]["type"] == "theme_dark":
        await client.post(f"{HOST}/settheme", json={"theme": "snow"}, timeout=40)
    await client.post(f"{HOST}/goto", json={"url": task["start_url"]}, timeout=40)
    await client.post(f"{HOST}/reset", timeout=20)

    settings = agent_llm.resolve_agent_llm()
    meter = Meter(settings)

    gate_blocks = 0
    if task.get("danger"):
        confirms = bool(task.get("user_confirms", False))

        async def confirm(_q: str) -> bool:
            return confirms

        real_gate = DangerGate(confirm, timeout_s=10)

        async def counting_gate(name: str, args: dict, page: str) -> str | None:
            nonlocal gate_blocks
            verdict = await real_gate(name, args, page)
            if verdict is not None:
                gate_blocks += 1
            return verdict

        pre_act = counting_gate
    else:
        pre_act = None

    loop = InPageAgentLoop(
        HttpActuator(client),
        think=meter.think,
        pre_act=pre_act,
        # Pace steps to respect free-tier TPM (one ~8K-token call per rolling
        # minute on Groq's 12K llama tier). Override with EVAL_STEP_DELAY.
        step_delay_s=float(os.environ.get("EVAL_STEP_DELAY", "0.3")),
        max_steps=15,
    )

    t0 = time.perf_counter()
    try:
        result = await loop.execute(task["prompt"])
        err = ""
    except Exception as exc:  # noqa: BLE001 — record, don't abort the batch
        result = None
        err = f"{type(exc).__name__}: {exc}"
    dt = time.perf_counter() - t0

    if result is not None:
        ok, detail = await _check(client, task, gate_blocks)
    else:
        ok, detail = False, err

    return {
        "id": task["id"],
        "category": task["category"],
        "success": ok,
        "stopped_reason": result.stopped_reason if result else "exception",
        "steps": len(result.steps) if result else 0,
        "llm_calls": meter.calls,
        "in_tokens": meter.in_tok,
        "out_tokens": meter.out_tok,
        "total_tokens": meter.in_tok + meter.out_tok,
        "wall_s": round(dt, 1),
        "gate_blocks": gate_blocks,
        "done_text": (result.text if result else err)[:120],
        "detail": detail,
    }


async def main() -> None:
    # Resumable: a per-DAY free-tier quota can cut a batch short, so results
    # MERGE into results_ours.json and already-successful ids are skipped.
    # Re-run the same command after quota resets to fill in the rest.
    _install_groq_shim()
    only = sys.argv[1] if len(sys.argv) > 1 else None
    out = Path(__file__).parent / "results_ours.json"
    prior: dict[str, dict] = {}
    if out.exists():
        prior = {r["id"]: r for r in json.loads(out.read_text(encoding="utf-8"))}

    tasks = [t for t in TASKS if not only or t["id"] == only]
    async with httpx.AsyncClient() as client:
        for task in tasks:
            done = prior.get(task["id"], {})
            # A clean finish (not a mid-task quota/exception cut) is skippable.
            if done.get("success") and done.get("stopped_reason") == "done":
                print(f"\n=== {task['id']} :: already clean — skip", flush=True)
                continue
            print(f"\n=== {task['id']} ({task['category']}) :: {task['prompt']}", flush=True)
            res = await run_task(client, task)
            prior[res["id"]] = res
            print(
                f"  -> success={res['success']} reason={res['stopped_reason']} "
                f"steps={res['steps']} calls={res['llm_calls']} "
                f"tok={res['total_tokens']} {res['wall_s']}s gate={res['gate_blocks']} | {res['detail']}",
                flush=True,
            )
            # Persist after EACH task so a mid-batch quota kill never loses data.
            ordered = [prior[t["id"]] for t in TASKS if t["id"] in prior]
            out.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")
            # Let the token-per-minute window clear before the next task's first
            # call (free-tier TPM; no-op when EVAL_TASK_GAP=0).
            gap = float(os.environ.get("EVAL_TASK_GAP", "0"))
            if gap:
                await asyncio.sleep(gap)

    results = [prior[t["id"]] for t in TASKS if t["id"] in prior]
    succ = sum(r["success"] for r in results)
    print(f"\n==== OURS: {succ}/{len(results)} recorded | results → {out}")


if __name__ == "__main__":
    asyncio.run(main())
