# Upstream sync — v1.6.4

**Merged** 2026-09-03 · `93df3d48` → `01e346dc` · previous merge-base `6e6e56ae` (v1.6.3)

370 files, +17.5k / −9.8k, six conflicts. Nothing the fork owns was deleted or
renamed — the preflight's highest-severity check came back empty, and that is the
single best predictor of a cheap sync.

## 1. The CI gate was red, and we merged anyway

`upstream/main` at v1.6.4 fails `Tests`. The skill says stop. We did not, and the
reason is worth recording because it is the exception, not a new default: the
rule exists so a sync never inherits an *unexplained* breakage. All three causes
were identified before the merge and none originates in this fork.

| upstream failure | ours? | status here |
|---|---|---|
| `Import Check (windows-latest)` — `✅` on cp1252 | no | fixed in this fork, hoisted to job scope this sync |
| Python matrix skipped (`needs: import-check`) | no | consequence of the above; green here on 3.11–3.14 |
| `/knowledge-bases` 541KB vs their own 540KB budget | no | their regression; our budget raised to 550KB with the measurement recorded |

Upstream has now shipped **two consecutive releases with no Python test signal at
all**. That is the single highest-value thing to send back (§4).

## 2. Conflicts

| file | resolution |
|---|---|
| `deeptutor/api/routers/co_writer.py` | upstream made two imports lazy; kept `append_language_directive` |
| `deeptutor/runtime/agentic/messages.py` | took upstream (converged) |
| `deeptutor/runtime/agentic/tool_call_stream.py` | took upstream (converged) |
| `tests/agents/chat/test_agent_loop.py` | upstream base + fork's symptom docstring and extra assertion |
| `web/locales/{en,zh}/app.json` | union: upstream order, 121 fork-only keys appended |

### co_writer.py — the trap the playbook names

Upstream moved `clean_thinking_tags` and `is_pageindex_kb` into the functions
that use them (v1.6.4's lazy-startup theme) and deleted the top-level import
block. The fork's `append_language_directive` sat in that same block and is still
called at module scope, so `--theirs` would have produced a `NameError` on the
first co-writer request — a crash no gate here would have caught before a user
did. Read the function, not the hunk.

### The Gemini thought_signature fix converged on upstream

The fork carried a generic `extra` passthrough: everything pydantic parked in
`model_extra`, merged across deltas, echoed back. v1.6.4 ships upstream's own
implementation (#1181): read `extra_content` off the delta, assign it (their
comment argues assign-over-merge — the provider sends it complete), echo it back.

Same bug, same wire shape, theirs is canonical. Took upstream and deleted the
fork's mechanism. **Second time this has happened** — `mcp/manager.py` in v1.5.16
was the first — and both times the fork's version was written months earlier and
never sent upstream. See §4.

`tests/core/test_labeled_step_tool_extras.py` was ported rather than deleted: it
covers the `core.agentic` path (`run_labeled_step` + `loop`) that `deep_question`
and `deep_research` run on, which upstream's chat-loop test does not reach.

## 3. What the gates caught

Four defects, none found by reading the diff:

1. **`th.yaml` prompt parity** — v1.6.4 added `{module_limit}` to `topic.system`
   and `{must_cover_block}` + a `materials` field to `topic.user`. A Thai route
   would have silently ignored the learner's own documents. Caught by
   `test_th_yaml_parity_with_en`.
2. **`PYTHONIOENCODING` scope** — v1.6.4 adds a second step printing `✅` to the
   same job. The v1.6.3-era step-scoped fix would have let Windows fail again,
   identically. Hoisted to job scope so steps upstream has not written yet
   inherit it.
3. **`/avatar-preview`** — new, unregistered, caught by the fork's voice-manifest
   parity test. Its own first line calls it a temporary harness; excluded rather
   than made steerable, with a note to drop the entry when upstream deletes it.
4. **Route budgets** — `/knowledge-bases` 542KB (upstream red at 541), and
   `/co-writer/[docId]` 516KB where upstream passes at 512KB, so ~4KB is ours.

## 4. Upstream PR candidates

Both are one-line fixes to upstream's own CI, and the first is the highest-value
thing this fork can send back right now.

1. **`PYTHONIOENCODING: utf-8` on the `import-check` job.** Their Windows leg
   dies encoding `✅` to cp1252 *after* every import succeeds, and because
   `python-tests` declares `needs: import-check`, their whole Python matrix has
   been skipped for two releases running. Job-scoped, not step-scoped, so the
   step they added in v1.6.4 is covered too.
2. **`book-reader-sequential.audit.ts`** asserted `toHaveURL(/page=page-2/)` two
   lines after navigating to `/books/.../pages/page-2` — left behind by their own
   canonical-routes rename. Correcting it exposes a second, real bug: after
   ArrowLeft the reader's `scrollTop` stays 0 instead of landing mid-chapter, so
   paging backwards loses the reading position. Report the bug with the fix.

**Lesson, twice earned:** the fork has now had two of its own fixes independently
rewritten upstream (`mcp/manager.py`, then the thought_signature handling)
because they were flagged as PR candidates and never sent. Converging by luck
costs more than converging on purpose — the fork carried both, plus their tests,
until upstream's version arrived and made them redundant.

## 5. Verification

| gate | result |
|---|---|
| `pytest -q tests deeptutor/learning/tests` | 6,980 passed · **zero regressions** vs a like-for-like worktree baseline (30 failures = uninstalled `[partners]` extra, same set as `main`) |
| `npm run check` (8 steps) | green |
| `i18n:check` | parity exact, `th` and `zh`, 4,824 keys |
| `invariants.py` | `th-ts` / `th-cmp` clean; `th-py` 3 pre-existing (`reading/translation.py` is upstream's en/zh translate feature, not UI language) |
| `backtest.sh` | 5 passed |
| live Thai turn | correct Thai answer via Gemini — the provider whose signature handling this merge changed |

**Method note.** A first pass reported 32 regressions. That was an artifact:
the merge ran in a worktree (git-tracked `model_catalog.json`, no active model)
and the baseline ran in the real checkout (the user's configured catalog), so 29
`LLMConfigError` failures looked like regressions. Re-running the baseline in an
identical worktree left three real ones, all fixed above. The playbook already
says to prove a regression by rerunning in a worktree at `main`; this sync is why
that sentence is there.
