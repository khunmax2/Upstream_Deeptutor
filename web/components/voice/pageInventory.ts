// The collector's "eyes" upgrade: interactive-element discovery via the
// vendored browser-use/page-agent dom_tree engine (./dom_tree/engine.ts)
// instead of a fixed CSS-selector list. The engine walks the whole DOM and
// marks elements interactive from *behavioral* signals — cursor:pointer,
// event handlers, tabindex, contenteditable, ARIA roles — so div-based
// clickables and icon buttons the old selector never saw become visible to
// voice. Returns live element refs in document order.
//
// Deliberately a thin, failable seam: any engine error returns null and the
// caller falls back to the legacy CSS-selector path — a broken snapshot must
// never break the call (same contract as collectPageContext).

import domTreeEngine from './dom_tree/engine'
import type { FlatDomTree } from './dom_tree/type'

// The vendored engine is @ts-nocheck'd (kept byte-identical); give it a
// typed face here instead of annotating third-party code.
const domTree = domTreeEngine as (args: {
  doHighlightElements: boolean
  focusHighlightIndex: number
  viewportExpansion: number
  debugMode: boolean
  interactiveBlacklist: Element[]
  interactiveWhitelist: Element[]
  highlightOpacity: number
  highlightLabelOpacity: number
}) => FlatDomTree

/** Live interactive elements on the page (document order), or null when the
 * engine fails (caller falls back to the legacy selector collector).
 * `exclude`'s whole subtree is dropped — the voice widget never sees itself. */
export function collectInteractiveElements(exclude: Element | null): HTMLElement[] | null {
  try {
    const tree = domTree({
      doHighlightElements: false,
      focusHighlightIndex: -1,
      viewportExpansion: -1, // whole rendered page, not just the viewport
      debugMode: false,
      interactiveBlacklist: exclude ? [exclude] : [],
      interactiveWhitelist: [],
      highlightOpacity: 0,
      highlightLabelOpacity: 0,
    }) as FlatDomTree
    const found: { index: number; el: HTMLElement }[] = []
    for (const id of Object.keys(tree.map)) {
      const node = tree.map[id] as Record<string, unknown>
      if (!node.isInteractive || !node.ref) continue
      const el = node.ref as HTMLElement
      // The engine's blacklist is exact-element, not subtree — drop our own
      // panel's descendants here.
      if (exclude && exclude.contains(el)) continue
      found.push({ index: (node.highlightIndex as number) ?? found.length, el })
    }
    found.sort((a, b) => a.index - b.index)
    return found.map(f => f.el)
  } catch {
    return null
  }
}
