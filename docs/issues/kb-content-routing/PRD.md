# KB-aware routing via a cheap topic manifest

Status: needs-triage
Owner: Attapon · Drafted: 2026-07-13

## Problem

The voice chat path runs the FULL chat capability — **including a RAG search** —
for every turn that isn't a UI command. Live (2026-07-13) a garbled fragment
"แล้วมาวิเคราะห์หรืออะไรสักอย่" was classified `chat` → `rung=llm` → a full
`Searching KB 'LAWs_thai'` (embed + vector search) before the LLM even answered.
Three distinct failures share one root — **the router has no idea what the KB
actually contains, so it cannot decide whether RAG is even relevant:**

1. **Garbled / incomplete input** is answered (hallucinated) instead of asking the
   user to repeat. (See `voice-intent-classifier` — the classifier is 2-bucket
   chat/ui_task with no `unclear`.)
2. **General questions unrelated to the KB** still trigger an irrelevant RAG
   search (wasted embed + retrieval, sometimes a wrong law-KB answer).
3. **Meta / global questions** ("มีเอกสารอะไรบ้าง", "KB นี้เกี่ยวกับอะไร", "สรุป
   ภาพรวม") are exactly what vanilla top-k RAG answers WORST — it retrieves a few
   chunks, never an inventory or a whole-corpus summary — yet they get routed to
   RAG anyway.

Grounding (verified on disk, `data/knowledge_bases/LAWs_thai/`): the llamaindex
ingestion stores **no topic/heading structure** — `docstore.json`'s 257 chunks
carry only `file_name`/`file_path`; `metadata.json` has a generic placeholder
`description: "Knowledge base: LAWs_thai"` and a `file_hashes` file list. So there
is nothing today that tells the router "what does this KB know?".

## Idea — a cheap per-KB "topic manifest" the router can read

Give the router a small, semantic description of each KB (its documents + main
topics + a one-line summary). With that in context it can decide, per turn:

```
turn → classifier            (layer 1: ui_task | chat | unclear)
  ui_task → agent loop
  unclear → ask the user to repeat            (no RAG, no answer)
  chat    → KB-relevance check (layer 2, manifest in context)
             ├ meta / overview  → answer from the MANIFEST      (no RAG)
             ├ specific content → RAG (kb_query)
             └ not about the KB → answer directly               (no RAG)
```

One manifest unlocks four wins: (1) garbled → ask back, (2) RAG only when it's
actually about KB content, (3) meta/inventory questions answered from the
manifest, (4) global questions answered at all (vanilla RAG can't). This is a
cheap "global summary" — the local/global split GraphRAG/LightRAG make, without
switching every KB onto them.

## Decisions settled (2026-07-13)

1. **Generation = lazy + cache.** Build the manifest the FIRST time a turn
   references a KB with no manifest yet, then cache it. Read the chunk text
   already stored in `docstore.json` (no re-upload, no ingest-pipeline change →
   stays off upstream code, fork policy §3). An eager upload-time hook is a later
   enhancement, not the MVP.
2. **Routing = two layers.** Layer 1 is the existing classifier
   (`intent_classifier.py`), extended to a third bucket `unclear`. Layer 2 (a
   second cheap call, **only for `chat`** — `ui_task`/`unclear` short-circuit)
   decides meta-vs-content-vs-unrelated using the manifest. A `chat` turn pays one
   extra lite call, cheap next to the RAG it may save.
3. **Multiple KBs = union.** When several KBs are selected, the manifest is the
   union of their topic lists, each topic tagged with its KB; RAG then runs only
   on the matched KB(s).
4. **Granularity = keyword-level.** Per document: a title, 3–7 main topics, and a
   one-line summary. Small enough to feed the router every turn.

## Manifest — what / where / how

- **Where:** enrich the EXISTING `data/knowledge_bases/<kb>/metadata.json`
  (additive fields, no new file). Shape (draft):
  ```json
  "content_manifest": {
    "generated_at": "…", "model": "…", "source_version": "version-1",
    "summary": "one line about the whole KB",
    "documents": [
      { "file": "pdpa.pdf", "title": "…", "topics": ["…","…"], "summary": "…" }
    ]
  }
  ```
- **How generated:** read each document's chunks from `docstore.json`, map-reduce
  a summary (chunk → per-doc topics/summary → KB-level summary) with ONE lite LLM
  tier (same "easy task, cheap model" logic as the classifier). Cache to
  `metadata.json`; invalidate when `file_hashes` / index version changes.
- **Meta answers** ("what documents?") can already use `file_hashes` even before a
  manifest exists — the manifest adds the "about what" answer.

## Routing changes (isolated, flagged)

- Layer 1: `intent_classifier.py` gains `unclear` (see `voice-intent-classifier`
  follow-up) — narrower `chat` definition + `unclear` examples; pipeline speaks a
  clarification and returns (no RAG/loop).
- Layer 2 (new, e.g. `kb_router.py`): given transcript + manifest, return
  `meta | content | unrelated`. `meta` → compose an answer from the manifest;
  `content` → today's RAG chat path; `unrelated` → chat answer with RAG suppressed.
- All new code in new files + a seam in `pipeline.run_text_turn`, behind a flag;
  flag off ⇒ today's behaviour byte-identical.

## Config + flag

- `DEEPTUTOR_VOICE_KB_ROUTING` (default OFF ⇒ unchanged).
- Reuse the classifier's lite model env for layer 2 + manifest generation, or a
  dedicated `DEEPTUTOR_KB_MANIFEST_MODEL` (decide during build). Provider
  adaptation (binding/reasoning) already handled centrally.

## Acceptance

- "มีเอกสารอะไรบ้าง" / "KB นี้เกี่ยวกับอะไร" → answered from the manifest, **no**
  `Searching KB` log line.
- A specific-content question ("PDPA มาตรา 26 …") → still runs RAG.
- A general question unrelated to the KB → answered with **no** RAG search.
- A garbled fragment → clarification asked, no RAG, no loop.
- Manifest built once per KB then cached (second reference logs no re-generation).
- Flag off ⇒ current routing unchanged (regression-guarded).
- Unit tests: manifest generate/parse/cache/invalidate; layer-2 routing table;
  meta-answer composition; flag-off parity.

## Risks

| risk | mitigation |
|---|---|
| manifest generation latency on the first KB turn | lazy + cache (one-time); map-reduce on a fast lite tier; consider a "กำลังอ่านคลัง…" filler |
| layer-2 mislabels content as meta (or vice-versa) | few-shot Thai examples; bias content→RAG on doubt (RAG bowing out beats a wrong manifest answer) |
| stale manifest after docs change | invalidate on `file_hashes` / index-version change |
| extra lite call per chat turn | only on `chat`; far cheaper than the RAG it can skip |
| touching shared RAG/chat path | new files + flag; RAG suppression is additive; land behind tests |

## Non-goals / open

- Not replacing RAG or switching KBs to GraphRAG/LightRAG — a cheap manifest beside
  the existing index.
- Not an eager upload-time hook yet (lazy MVP first).
- Open: exact manifest model + map-reduce prompt; how meta-answers are phrased for
  voice; whether layer-1 `unclear` ships in the same change or as its own step.

## Phasing

1. **Manifest** — generate (lazy, from docstore) + cache in `metadata.json` +
   tests. Foundation for everything else.
2. **Layer-1 `unclear`** — classifier third bucket + pipeline clarification seam.
3. **Layer-2 KB routing** — meta/content/unrelated + manifest-answer + RAG gate.

## Comments
