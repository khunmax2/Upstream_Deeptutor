# In-page agent — Phase E eval harness

Reproducible head-to-head bed for the in-page agent (`PLAN_inpage_agent_parity`
Phase E). Drives the **real** `InPageAgentLoop` against a **real live DeepTutor
page** using the **real** page-actuator (`web/lib/page-actuator/`), so what the
numbers measure is the shipping loop/prompt/fixer/danger-gate — not a mock.

All files here are new and isolated (fork policy §3); nothing in `web/` or
`deeptutor/` source is modified. Results: `docs/reports/REPORT_inpage_agent_phaseE_*.md`.

## Pieces

- `browser_host.mjs` — Playwright owns a headless Chromium on the live app and
  exposes our actuator (`observe`/`act` bundled from `web/lib/page-actuator/`)
  over a small HTTP bridge.
- `tasks.json` — the 10 standardized tasks (grounded in the live UI).
- `run_ours.py` — runs the unchanged loop task-by-task; tiktoken token
  accounting; objective success checks; resumable (`results_ours.json`).
- `_actuator_entry.ts` → `actuator.bundle.js` — esbuild IIFE (generated,
  gitignored).

## Run it

```bash
# 0. deps (once): a Chromium for Playwright, and the actuator bundle
cd web && npx playwright install chromium && cd ..
cd web && npx esbuild ../eval/inpage_agent/_actuator_entry.ts \
  --bundle --format=iife --platform=browser --alias:@=. \
  --outfile=../eval/inpage_agent/actuator.bundle.js && cd ..
ln -sfn ../../web/node_modules eval/inpage_agent/node_modules   # ESM resolution

# 1. bring up the app (frontend :3000, backend :8001)
cd web && npm run dev &                 # :3000
deeptutor serve --port 8001 &           # backend

# 2. start the browser host (owns the live page)
EVAL_HEADLESS=1 node eval/inpage_agent/browser_host.mjs &

# 3. run the loop (needs a model whose tier fits ~8K-token calls; see the report
#    for why free tiers do not). Load .env.agent, then:
python eval/inpage_agent/run_ours.py            # all tasks, resumable
python eval/inpage_agent/run_ours.py theme_dark # one task
```

Env knobs: `EVAL_STEP_DELAY` (pace steps for free-tier TPM), `EVAL_TASK_GAP`,
`EVAL_MAX_RETRIES`, `EVAL_HOST`. When `DEEPTUTOR_AGENT_BASE_URL` contains
`groq.com`, the runner shims the call (generic openai binding + per-model
`reasoning_effort`) so the unchanged `think()` runs on Groq.

## page-agent column (pending)

The page-agent side (bundle `page-agent`, a token-counting LLM proxy, drive its
loop on the same live app + task set) is the remaining piece; it shares the same
paid-tier-quota prerequisite as ours. See the report's "Resume" section.
