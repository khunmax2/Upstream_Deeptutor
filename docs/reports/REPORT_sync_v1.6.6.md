# Upstream sync — v1.6.6

**Merged** 2026-09-09 · `003fa5013` + `7a96bba1a` → `4e04371ad`
**Skipped** v1.6.5 — its own `Tests` run is red, and the rule is to never sync
onto that. v1.6.6 is green on every check, including the Windows import leg that
had been failing since v1.6.2.

| | |
|---|---|
| commits | 83 |
| files | 597 (+51,805 / −13,278) |
| colliding files | 81 |
| **conflicts** | **24** |
| fork files upstream deleted or renamed | 3 |

## 1. What made this sync expensive

Not the conflict count. Three things upstream *moved*, each of which merged
cleanly in a way that would have been wrong.

### The pipeline moved out from under the fork

`deeptutor/agents/chat/agentic_pipeline.py` went from **1,869 lines to 48** — a
re-export shim. The implementation is now `deeptutor/agents/loop/pipeline.py`.

Git followed the rename for `prompt_blocks.py` (`R083`), so the fork's
`normalize_agent_language` work survived intact: 17 files referencing it before
the merge, 17 after, and upstream has no version of its own. That is the good
case, and it is worth naming because the same class of move has silently
orphaned fork fixes twice before.

The four fork edits *inside* the emptied file did not survive, and had to be
placed by hand:

| fork edit | new home |
|---|---|
| `self.language = normalize_agent_language(...)` | `loop/pipeline.py:236` |
| Thai notebook-list label | `loop/pipeline.py:995` |
| DeepWitya rebrand ×2 | gone with the deleted prompt |
| Thai turn-workspace prompt | **deliberately not ported** |

That last row is the judgement call. Upstream deleted the exec-workspace prompt
outright and replaced it with the Content Workspace note in
`agents/_shared/workspace_prompt.py`. Restoring the Thai text would have
described a workflow that no longer exists; the fork's actual behaviour — a Thai
reader gets a Thai system block — is preserved by adding a `th` arm to the
replacement. `DEEPTUTOR_WORKSPACE_ROOT` is an environment variable name and is
deliberately left unbranded.

### Git mis-aligned two hunks

Both are the trap the playbook names: "our side" was the tail of something
upstream had rewritten.

- `capabilities/mastery/loop.py` — the fork's `_load_system_prompt` was matched
  against the *body of `_load_playbook`*, which upstream had replaced. Taking
  "our side" wholesale deleted that function's body. Caught by reading the
  surrounding function; restored with `git checkout -m` and redone.
- `services/llm/factory.py` — the fork's `complete_with_usage` was matched
  against upstream's `complete`. Resolving hunk-by-hunk truncated `complete()`'s
  body; `ruff` caught it as nine `F821` undefined names.

### Three places a clean merge would have lost Thai

None of these conflicted.

1. The interface-language picker **moved** from `AppearanceSettingsSection` into
   `SettingsOverview`, and the version that moved offers `en` and `zh` only. A
   Thai reader would have had no way left to choose Thai.
2. `mastery`'s prompt became a PromptManager pack shipping `en`/`zh`;
   PromptManager answers a missing language with English rather than an error, so
   `_load_system_prompt` still appends the language directive for anything
   outside that set.
3. `LearningBoard` arrived taking `zh: boolean` while both things it hands the
   value to — `formatRelative` and `ObjectiveDetail` — already take a `Language`.
   The build does not pass without converting it.

`invariants.py --scope changed`, re-run **after** resolving, found **15 `th-ts`
violations**, every one in a file that never conflicted. All five checks are clean
now.

## 2. Decisions

| # | Decision | Outcome |
|---|---|---|
| 1 | `/co-writer/[docId]`: take upstream's 515, then measure | **290KB** — the fork's 525 described a bundle v1.6.6 no longer builds |
| 2 | Keep the `PYTHONIOENCODING` comment | Upstream has the same fix with no explanation; the job-vs-step reasoning is worth carrying |
| 3 | `mastery` prompts: take the YAML pack | Rebrand re-applied, one occurrence per language |
| 4 | `book-reader-sequential`: lift the quarantine | Upstream fixed the assertion in `97cb143c`; running it is how we learn whether the scrollTop half is fixed too |
| 5 | `complete_with_usage`: change the shared helper | It returns `TutorResponse`; the fork's sibling drops from ~30 lines to 15 and can no longer drift |
| 6 | `root-app-shell` 410 → 420 | Measured 414KB, and the growth is upstream's 252 new `en` keys — recorded as *not* a fork feature |

## 3. The failure that was not one

Four tests passed alone and failed in the full suite:

```
extract_document_text() got an unexpected keyword argument 'filename_hint'
```

`filename_hint` is a v1.6.6 parameter. `isolated_worker` runs its task in a
subprocess started from a **sandbox working directory**, so the worktree's
implicit `cwd` entry on `sys.path` is gone and `deeptutor` resolves through the
editable install — which points at the real checkout, still on `main`.

```
worktree, no PYTHONPATH   → 4 failed
worktree, PYTHONPATH set  → 7,583 passed
main baseline (full)      → 7,159 passed, 0 failed
```

This is the v1.5.16 lesson inverted: that one was the worktree having something
the real checkout lacked; this is the real checkout leaking into the worktree.

Two hypotheses were wrong before the measurement was right. The second is worth
recording: excluding `tests/services/rag` turned the suite green, which looked
like proof that those failures caused the others. They did not — removing files
also changes collection order. Upgrading `lightrag-hku` to the version v1.6.6
pins removed the five RAG failures and left the other four exactly where they
were. **An exclusion that makes a suite green is a hypothesis, not a result.**

## 4. One value the resolution lost

Rebuilding `en`/`zh` from JSON — upstream's key set plus fork-only keys, with the
fork's rebrand re-applied — was right for 12 of the 13 keys whose values differed
for a non-branding reason. The exception: `Partners tooltip`, where upstream ships
the key echoed back as its own value and the fork had written a real sentence.
Taking upstream discarded it, and `i18n:parity` caught it. Restored.

The other 12 were correct to take from upstream: their terminology changed
(学习主题 → 精通目标), or the fork's value was untranslated English.

## 5. Verification

| gate | result |
|---|---|
| `ruff check` / `format` (0.16.0, the CI pin) | pass |
| `pytest -q tests deeptutor/learning/tests` | **7,583 passed, 0 failed** |
| `invariants.py --scope changed` | 5/5 clean |
| `npm run i18n:check` | exit 0 |
| `npm run test:node` | 1,202 pass / 0 fail |
| `npm run build` | pass |
| `npm run perf:check` | every route under budget |
| live Thai turn | correct Thai, 8.4k tokens |

Locale: `en` and `zh` at 5,137 keys, `th` at exact parity (+252 this sync).
`lightrag-hku` upgraded `1.5.7rc2` → `1.5.7` to match what the merged
`pyproject.toml` declares.

## 6. Still open

- **252 new `th` keys carry their English text.** Parity is exact, so the gate is
  green and nothing renders as a raw key, but they are not translated yet.
- **`book-reader-sequential` is un-quarantined and unproven.** The Playwright job
  will say whether the scrollTop half is still broken.
- **1,129 fork-only `en` keys**, of which an earlier sweep found 270 unreachable.
  That is where the app-shell budget should be reclaimed rather than raised again.
