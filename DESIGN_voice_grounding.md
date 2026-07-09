# DESIGN — Voice UI Grounding & Target-Locking Architecture

> Status: **draft / blueprint** (2026-07-09). Captures the target-design agreed
> in the voice-web-integration phase. Nothing here is a committed schedule —
> it is the reference map so that Graph / Scoring / Verify work does not
> accidentally couple to DeepTutor internals and stays portable to the future
> standalone connector. See `REPORT_voice_web_integration.md` for what is
> already built, and `AGENTS.md` for the surrounding architecture.

## 1. Purpose & the two goals in tension

"Target-locking" = turning a spoken/typed intent ("เปลี่ยนธีม", "พิมพ์กฎหมาย
ในช่องค้นหา", "กดที่ประวัติแชท") into **the exact element to act on**, then
acting and confirming it worked.

Two goals drive every decision here:

1. **Fast + accurate** — clear commands must resolve in milliseconds with high
   precision, not pay an LLM round-trip or a DOM dump per action.
2. **Portable** — the engine must survive the split from DeepTutor into a
   standalone voice connector usable on *other* websites (see the
   `voice-connector-to-computer-use` project note). What we own today (source,
   hand-authored manifest, known Thai labels) will not exist on a black-box
   third-party site.

The whole design follows from holding both at once.

## 2. The one structural rule: a gated pipeline, not a linear one

The reference computer-use grounding pipeline is often drawn as a straight
column:

```
Intent → Semantic Matching → Navigation Reasoning → Website Graph →
Target Grounding (DOM / AX / Vision / OCR / Spatial / Prev-actions / Context /
Memory) → Scoring → Action → Verify
```

Run **every stage on every command** and it is the most expensive path
possible — you pay semantic matching, graph search, multi-signal grounding and
scoring even for "ไปหน้าตั้งค่า" that a dict lookup resolves in 1 ms.

**Rule: this is a tiered pipeline with a fast-path short-circuit.**

```
utterance
  │
  ├─ FAST PATH (deterministic, no LLM, no DOM dump) ──────────► Action → Verify
  │    exact/known intent → catalog/graph lookup → resolver → act
  │    (this is today's "ladder"; ~90% of real commands end here)
  │
  └─ FALLBACK (only on a fast-path miss) ─────────────────────► Action → Verify
       Semantic Matching → Navigation Reasoning → Website Graph →
       multi-signal Grounding → Scoring
```

The fallback is the *deeper* net, not a replacement for the fast path. This
mirrors what already ships (deterministic matcher ladder → LLM fallback) and is
the reason the current system feels "faster than speaking."

## 3. The core/knowledge split (the portability seam)

Everything in target-locking falls into exactly one of two layers. **The whole
portability bet is keeping the boundary clean.**

### 3a. Portable CORE — works on any website, no app-specific knowledge inside

- Live collection of clickables/fields from the **DOM / accessibility tree**
  (today: `web/components/voice/pageContext.ts` — reads the visible DOM, not a
  manifest, so it is *already* portable).
- The **see→name→act contract** and the resolvers: normalize → substring →
  phonetic fold → cross-script consonant skeleton → (future) weighted scoring
  (`deeptutor/services/voice_realtime/ui_control.py`). The *techniques* are
  portable; only the *vocabulary/language* is swappable.
- **Executors**: native-setter fill, click, scroll, focus, edit; the simulator
  cursor and field glow (`pageContext.ts`, `simulatorCursor.ts`).
- **Safety**: danger-confirm rung, verify-before-act, honest-miss, and
  post-action verify (§6).
- The **WS protocol** (`ui_manifest` / `ui_context` / `ui_action`) — already
  system-agnostic.

### 3b. Per-site KNOWLEDGE — same shape, different provenance

| Knowledge | DeepTutor (now) | Foreign site (connector) |
|---|---|---|
| Page/action manifest | hand-authored (`UI_PAGES`, `UI_ACTIONS`) | auto-discovered from the live DOM at runtime |
| Website Graph / action catalog | generated from source + parity-tested | **learned at runtime** from observed transitions (R2D2-style replay buffer), cached per-origin |
| Label vocabulary / language | known Thai labels | whatever DOM/aria yields; language auto-detected |
| Whitelist / trust basis | the manifest *is* the whitelist | "visible + user-named + confirmed + verified" (no pre-authored list) |

**Decision that must not be gotten wrong now:** the Website Graph is defined as
a *provenance-agnostic data schema* (§4). We build the DeepTutor
source-generator first, but the schema must be populatable by a runtime learner
later **without changing its shape or the code that consumes it**.

## 4. Website Graph (a.k.a. UI Transition Graph / action catalog)

Turns a **goal** into a **path**: "เปลี่ยนธีม" from anywhere →
`(/settings, theme toggle)` → plan `navigate(/settings) → wait → focus/click`.
This is the missing piece for cross-page single commands *and* the substrate
the future agentic loop plans over.

### Schema (provenance-agnostic)

```jsonc
{
  "origin": "deeptutor",           // or a foreign site's origin
  "nodes": [                       // one per route/screen
    {
      "id": "settings",
      "path": "/settings",
      "label": "หน้าตั้งค่า (settings)",
      "controls": [                // the action catalog for this node
        {
          "capability": "change_theme",     // stable semantic id
          "label": "ธีม / theme",
          "kind": "toggle",                 // button | toggle | field | select | link
          "value_type": null,               // email|number|date|text|... for fields
          "aliases": ["เปลี่ยนธีม", "โหมดมืด", "dark mode"]
        }
      ]
    }
  ],
  "edges": [                       // how to get from A to B
    { "from": "*", "to": "settings", "via": "navigate", "cost": 1 }
    // DeepTutor is ~fully connected via router.push, so most edges are direct
    // navigate(cost 1). Foreign sites will have click-through edges with higher
    // cost, learned as they are traversed.
  ]
}
```

- **DeepTutor provenance:** a generator walks `web/app` routes + a curated
  control catalog; a **parity test** (mirroring
  `web/tests/voice-manifest-parity.test.ts`) fails CI when source and graph
  drift. Staleness is a build-time concern, not a runtime one.
- **Foreign provenance:** the graph starts empty; each visited page adds/updates
  a node from live DOM, each observed transition adds an edge (replay buffer).
  Cached per-origin, optionally persisted so it improves across visits.
- **Runtime use:** goal → find the control's node → shortest path from the
  current node (direct `navigate` for us; A*-style for learned multi-hop
  graphs) → execute the plan. Known entries need **no LLM per step**.

## 5. Target grounding — signal priority (cheapest, most reliable first)

On a fast-path miss, ground against the current screen using signals in this
order. **We own the DOM, so the cheap structured signals dominate; the
expensive pixel signals are deliberately deferred.**

1. **DOM text / label** — visible text, `<label>`, placeholder, name. (have)
2. **Accessibility tree** — aria role + accessible name; cleaner than raw DOM
   text, language-neutral. (partially have via aria-label; worth deepening)
3. **Context** — the streamed current-screen outline. (have)
4. **Memory / previous actions** — `last_field`, and a short action history for
   "อันเดิม / แก้อันเมื่อกี้". (have `last_field`; extend)
5. **Stable ref / indexed element** — page-agent-style index as a last-resort
   handle for unlabeled/icon-only controls. **Mainly for foreign sites**; ours
   rarely need it.
6. **Spatial reasoning** — "the field below the ชื่อ label", "the second
   button". Long-tail; defer.
7. **Vision / OCR** — **skip until proven necessary.** Redundant and expensive
   when the DOM gives labels for free; reserve for canvas/iframe/image-only
   controls a black-box site might have.

## 6. Scoring & Verify

- **Scoring** — collapse today's fixed 4-tier resolver into one **weighted
  score** combining signals (label match + value/type match + focus + recency +
  proximity). One ranked outcome → `hit` / `ambiguous` (ask) / `miss` (honest).
  This is where semantic matching, memory, and type-inference fold in cleanly.
- **Verify (before)** — client re-validates the target against the live screen
  before acting; danger words require spoken confirmation. (have)
- **Verify (after)** — confirm the action *landed* ("typed X → is X now the
  field's value?", "navigate → did the route change?"). Currently missing;
  **required** for the agentic loop (a step must confirm before the next) and
  raises accuracy on foreign sites where nothing else is trustworthy.

## 7. Implicit target-locking (the "he didn't even name the field" UX)

Industry (Salesforce voice-to-form, one-shot form fillers) maps **value →
field by meaning**, not by the user naming the field. Tiers to adopt:

- **Tier A (deterministic):** "พิมพ์ X" with no field named → the currently
  focused field (caret / `document.activeElement`, streamed in `ui_context`),
  else `last_field`, else the *only* visible field. No LLM. Covers most cases.
- **Tier B (LLM value→field):** ambiguous (2+ fields) → `ui_fill` may omit the
  field and the model picks by semantics from the streamed schema (labels +
  `value_type`); the resolver still verifies the chosen field is real (trust
  model intact).
- **Tier C:** one-shot multi-field from one sentence. Later.

## 8. Trust model, per environment

- **Own app (DeepTutor):** manifest = whitelist; curated actions; catalog-driven
  fast path.
- **Foreign site:** no pre-authored whitelist. Fall back to *visible + user-named
  + confirmed + post-verified*, with danger-confirm as a **default**, not an
  exception — we do not know what "delete" does on a site we do not control.
  Consider a propose-then-confirm default for first-time origins.

## 9. Interface discipline — do this now so it pays later

Extract target-locking as a standalone module behind a clean, app-ignorant
interface:

```
lockTarget(observation, intent) -> { element | plan, confidence, why }
```

- `observation` = live DOM/AX snapshot + optional cached graph (data, not
  hardcoded knowledge).
- **No DeepTutor route/label/vocabulary hardcoded inside.** Audit the resolvers
  for leaked couplings (they already take `ui_context` as data — keep it so).
- Build the DeepTutor graph generator **behind the graph interface** a runtime
  learner will later implement — the same swappable-seam discipline agreed for
  `pipeline.py` (ChatOrchestrator out → Gemini Live in), applied to the
  "site knowledge" seam.

## 10. Phasing

Serves the current active focus (voice controls everything in-app) first; the
autonomous multi-step loop stays deferred (per the project note), but Graph /
Scoring / Verify are built now because they are in-app assets *and* the loop's
substrate.

1. **Website Graph + Navigation Reasoning** — cross-page single commands.
2. **Scoring** — unify the resolver into weighted multi-signal.
3. **Post-action Verify** — loop prerequisite.
4. **Implicit target Tier A**, then **Tier B**.
5. **Defer:** runtime graph learner, ref/index & AX-deepening for foreign DOM,
   spatial, vision/OCR, cross-tab, full autonomous loop.

## 11. Non-goals (for now)

Vision/OCR grounding, black-box crawl/exploration, OS-level control, cross-tab
orchestration, and the full autonomous planner. These belong to the standalone
connector / computer-use phase, not the in-app phase.
