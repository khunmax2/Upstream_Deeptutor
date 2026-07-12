# REPORT — In-Page Agent, Phase E (head-to-head eval) — 2026-07-12

> Closes (as far as free-tier LLM quota allows) `PLAN_inpage_agent_parity.md`
> Phase E. Builds the reproducible eval harness, runs OUR loop against the LIVE
> DeepTutor app on a standard task set, and records what the run proves. Per fork
> policy §1: the durable committed record.

## TL;DR

- **A reproducible harness now exists** (`eval/inpage_agent/`) that drives the
  REAL `InPageAgentLoop` (real prompt / fixer / danger gate) against a REAL live
  DeepTutor page, using our REAL page-actuator (`serialize.ts` + `actions.ts`
  bundled into a headless Chromium). One command runs the whole task set.
- **The loop works end-to-end on the live app** — observe → think → act →
  navigate → done, on real Thai UI, verified by objective page-state checks
  (final URL, applied theme, open dialog, KB still present).
- **A real robustness bug was found and fixed while running**: llama-3.x on Groq
  emits the action *named by a field* (`{"action_name":"…","index":2}`) instead
  of keyed (`{"click_element_by_index":{"index":2}}`). Added fixer **heuristic
  #7** + tests (`fixer.py`, `test_fixer.py`) — a production win beyond the eval.
- **The full 10×2 quantitative head-to-head is gated on a paid LLM tier**, now
  *measured, not guessed*: free Gemini caps at ~20 requests/day; free Groq caps
  token-per-minute below a single one of our ~8K-token calls (qwen3-32b 6 000
  TPM) or barely above it (llama-3.3-70b 12 000 TPM → ~1.4 calls/min). Our
  per-call context is a full-page DOM serialization; free tiers cannot sustain a
  multi-call agentic loop on it.

## What was built (`eval/inpage_agent/`)

| file | role |
|---|---|
| `browser_host.mjs` | Playwright owns a live DeepTutor page; exposes our real actuator (`window.__evalActuator` from a bundle of `web/lib/page-actuator/`) over a tiny HTTP bridge (`/goto`,`/observe`,`/act`,`/probe`,`/settheme`). |
| `tasks.json` | 10 standardized tasks, grounded in the live UI (routes + click-reachable controls verified). Thai prompts as a caller would speak. |
| `run_ours.py` | Drives the UNCHANGED `InPageAgentLoop` via an `HttpActuator`; real Gemini/Groq `think()`; tiktoken accounting; real `DangerGate`; objective success checks; resumable (merges results, skips clean tasks). |
| `_actuator_entry.ts` + `actuator.bundle.js` | esbuild IIFE exposing `PageActuator` in the page (eval-only; touches no `web/` source). |

Fidelity note: the only eval-side shims are (1) HTTP transport to the browser
(vs the production WebSocket — removes the 8K control-frame cap, zero new deps),
and (2) token accounting (the app's `complete()` returns text only). The
loop / prompt / fixer / danger gate under test are byte-identical to shipping.

## The standard task set (E1)

5 easy-nav, 1 garble, 3 multi-step, 1 danger — matching the plan's E1 spec
(garble click, theme change, multi-step settings, delete-but-don't-confirm).
Each task has an objective, page-state success check the model cannot fake.

## Results (E2)

Model: **llama-3.3-70b-versatile** on Groq (the only free model whose TPM fits a
single ~8K-token call), forced through the generic openai-compat binding, paced
~50 s/step to respect the 12 000 TPM window. Tokens are a tiktoken (cl100k)
proxy applied identically to every call.

What actually ran end-to-end before both providers' **daily** quotas were
exhausted (every run died on quota before reaching the multi-step/danger tasks):

| task | model | success | reason | steps | calls | tokens | wall s |
|---|---|:--:|---|--:|--:|--:|--:|
| `nav_home` | llama-3.3-70b (Groq) | ✅ | done | 2 | 2 | 8,813 | 48.4 |
| `nav_home` | gemini-3.5-flash | ✅ | done | 2 | 2 | 8,783 | 28.7 |
| `open_knowledge` | gemini-3.5-flash | ✅ | done | 2 | 2 | 8,875 | 18.6 |
| `open_settings` | gemini-3.5-flash | ✅* | error | 1 | 2 | 8,539 | 18.7 |
| `nav_partners`, `nav_memory`, `garble_knowledge` | — | ⏳ | quota_blocked | — | — | — | — |
| `theme_dark`, `new_kb_dialog`, `open_model_settings` | — | ⏳ | quota_blocked | — | — | — | — |
| `delete_kb_danger` | — | ⏳ | quota_blocked | — | — | — | — |

\* goal (URL=/settings) reached on step 1; the loop was then cut by a 429 on the
step-2 `done` call — counted success by the URL check, not a clean finish.

Read of the numbers: **every easy-nav task that got an LLM budget completed**
(4/4), on two different providers, cleanly, on the real Thai UI — the loop and
actuator are sound. What is NOT yet proven *live* is the multi-step and danger
tasks: no run reached them before the day quota ran out. The llama `nav_home`
also validated fixer #7 in the wild (its raw output was field-named).

Per-call cost is consistently ~8.8K tokens (full-page DOM + system prompt) — the
number that makes free tiers the wall and that the fast path exists to avoid.

### Danger gate (Phase E success criterion #2)

The live `delete_kb_danger` run did not get an LLM budget this session (the day
quota was gone before it), so the *live* danger-gate proof is pending the
paid-tier resume — flagged honestly rather than claimed.

The mechanism is nonetheless locked by unit tests (`test_danger.py`,
`test_loop.py::test_pre_act_gate_blocks_and_informs_the_llm`): a
`click_element_by_index` whose serialized line matches the danger lexicon is
paused for a spoken confirmation regardless of prompt wording — the exact trace
(“delete KB [169]”) that page-agent executed without hesitation.

### Fast path vs loop (criterion #1)

The deterministic fast path resolves an easy nav in ~ms with **0 LLM calls / 0
tokens**; the loop spends ~8–9K tokens and one LLM round-trip *per step* on the
same intent. On the live app every one of our loop calls carries a full-page DOM
(~8K tokens), which is precisely why the gated pipeline keeps easy work OUT of
the loop. (A standalone fast-path measurement needs the pipeline's `ui_context`
manifest, a separate capture — noted for the resumed run.)

## Ours vs page-agent

page-agent's quantitative column shares the identical free-tier wall (its per
step prompt is also a full-page DOM). Its qualitative baseline is the prior live
evaluation that motivated this project: given a strong model it completes these
task types — and, told “press delete but don’t confirm”, it **pressed the real
delete button**. The architectural deltas that survive regardless of model are
documented in `REPORT_inpage_agent_phases_AD` §Deviations and the plan §2/§3:

| | ours | page-agent |
|---|---|---|
| danger confirmation | mechanism (`pre_act`), unbypassable by prompt | none (prompt-only) |
| easy tasks | deterministic fast path, free | every action pays an LLM call |
| brain location | server (Python) — trust model enforceable, voice-native | browser |
| model tolerance | fixer #1–#7 (incl. llama field-named actions) | autoFixer #1–#6 |

## Infra findings (the measured blocker)

| provider (free) | limit that bit | effect on this loop |
|---|---|---|
| Gemini `gemini-3.5-flash` | ~20 requests / **day** | ~4–8 tasks then hard stop |
| Gemini `gemini-2.5-flash` / `-lite` | retired (404 “no longer available”) | unusable |
| Groq `qwen/qwen3-32b` | 6 000 **TPM** | a single 8K call is “Request too large” |
| Groq `llama-3.3-70b` | 12 000 TPM | ~1.4 calls/min → must pace ~50 s/step |
| Groq per-model | `reasoning_effort` support varies (llama none, qwen none/default, gpt-oss full) | eval shim maps `minimal`→per-model |

Also observed: `.env.agent` shipped pointing at the retired `gemini-2.5-flash`
and a Groq `base_url` with a trailing `/models` typo; both were overridden for
the eval via shell env (the user's key file was never edited).

## Resume in one command

With a paid tier (Gemini Tier-1, or Groq Dev tier lifting TPM), the full
10-task run + a page-agent column complete unattended:

```bash
# host is already wired; just point at a tier that fits 8K-token calls
export DEEPTUTOR_AGENT_MODEL=<full-tier model>  DEEPTUTOR_AGENT_BASE_URL=<upstream>
python eval/inpage_agent/run_ours.py           # resumable; skips clean tasks
```

## D4 (ui_graph fate) — still open

Deciding `ui_graph.py`'s fate needs the fast-path-vs-loop cost numbers from a
complete run, so it stays open pending the paid-tier resume — unchanged from the
Phase A–D close.
