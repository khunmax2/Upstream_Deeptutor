// PageActuator — the in-page agent's eyes and hands (PLAN_inpage_agent_parity
// Phase A). The server-side brain (services/voice_realtime/agent/) speaks to
// this over WS frames; this class knows nothing about the loop, only how to
// LOOK (dom_tree engine → serialize) and how to DO (actions by index).
//
// Mirrors the seam page-agent proved with PageController: LLM-free, so it can
// be driven from the devtools console (window.pageActuator when attached).

import domTreeEngine from '@/components/voice/dom_tree/engine'
import type { FlatDomTree } from '@/components/voice/dom_tree/type'
import { glowBox } from '@/components/voice/simulatorCursor'

// The vendored engine is @ts-nocheck'd (kept byte-identical); typed face here,
// same pattern as pageInventory.ts.
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

import { clickElement, inputTextElement, scrollVertically, selectOptionElement } from './actions'
import { fadeOutHighlights, neonizeHighlights } from './neonHighlights'
import {
  buildHeaderFooter,
  markNewElements,
  serializeTree,
  type PageInfo,
  type SerializedPage,
} from './serialize'

export interface ObservedState {
  url: string
  title: string
  header: string
  content: string
  footer: string
}

export interface ActOutcome {
  ok: boolean
  message: string
}

// Highlight opacities for the vision layer ("show what the agent sees").
// The engine ships the full overlay/label machinery; these make it visible.
const HIGHLIGHT_OPACITY = 0.08
const HIGHLIGHT_LABEL_OPACITY = 0.65

function cleanupHighlights(): void {
  const w = window as unknown as { _highlightCleanupFunctions?: (() => void)[] }
  for (const fn of w._highlightCleanupFunctions ?? []) {
    try {
      fn()
    } catch {
      /* a dead overlay must not break a step */
    }
  }
  w._highlightCleanupFunctions = []
}

function pageInfo(): PageInfo {
  const doc = document.documentElement
  const pageHeight = Math.max(doc.scrollHeight, document.body?.scrollHeight ?? 0)
  const pageWidth = Math.max(doc.scrollWidth, document.body?.scrollWidth ?? 0)
  const above = Math.round(window.scrollY)
  const below = Math.max(0, Math.round(pageHeight - window.innerHeight - above))
  return {
    viewportWidth: window.innerWidth,
    viewportHeight: window.innerHeight,
    pageWidth,
    pageHeight,
    pixelsAbove: above,
    pixelsBelow: below,
  }
}

/**
 * React mounts often carry click handlers on the root, which reads as one
 * page-sized "button" (page-agent's patchReact lesson). Blacklist them, plus
 * anything we explicitly opt out (our own overlays: mask, cursor, voice UI).
 */
function interactiveBlacklist(): Element[] {
  return Array.from(
    document.querySelectorAll(
      '[data-reactroot], #root, #app, [id^="root-"], [id^="app-"], ' +
        '[data-deeptutor-not-interactive], #deeptutor-agent-run-mask'
    )
  )
}

export class PageActuator {
  /** Refs seen this task — powers the `*[new]` markers. Reset per task. */
  private seenRefs = new WeakSet<object>()
  private last: SerializedPage | null = null

  /** New task = every element is "old"; markers mean "new since MY last look". */
  resetTask(): void {
    this.seenRefs = new WeakSet<object>()
    // A pickup-flash timer still pending must not wipe the run's own boxes.
    if (this.visionFlashTimer !== null) {
      window.clearTimeout(this.visionFlashTimer)
      this.visionFlashTimer = null
    }
    cleanupHighlights()
  }

  private visionFlashTimer: number | null = null

  /**
   * The "eyes open" flash (call pickup, page-agent UX): one highlighted sweep
   * of the DOM so the neon boxes wash over the layout, then fade away. Pure
   * show — no mask, the caller keeps full control of the page; a running
   * task's own observe simply supersedes the timer's cleanup.
   */
  flashVision(durationMs = 2600): void {
    if (this.visionFlashTimer !== null) window.clearTimeout(this.visionFlashTimer)
    try {
      this.observe({ highlight: true })
    } catch {
      return // a failed flash is a lost nicety, never a broken call
    }
    this.visionFlashTimer = window.setTimeout(() => {
      this.visionFlashTimer = null
      fadeOutHighlights(cleanupHighlights) // soft exit, not a hard pop-out
    }, durationMs)
  }

  observe(options?: { highlight?: boolean }): ObservedState {
    const highlight = options?.highlight ?? true
    cleanupHighlights()

    const tree = domTree({
      doHighlightElements: highlight,
      focusHighlightIndex: -1,
      viewportExpansion: -1, // full page, like the evaluation baseline
      debugMode: false,
      interactiveBlacklist: interactiveBlacklist(),
      interactiveWhitelist: [],
      highlightOpacity: highlight ? HIGHLIGHT_OPACITY : 0,
      highlightLabelOpacity: highlight ? HIGHLIGHT_LABEL_OPACITY : 0,
    }) as FlatDomTree

    // Soften the engine's default loud boxes into the neon vision-layer look
    // (vendor file stays byte-identical; we restyle what it just drew).
    if (highlight) neonizeHighlights()

    markNewElements(tree, this.seenRefs)
    this.last = serializeTree(tree)

    const { header, footer } = buildHeaderFooter(pageInfo(), document.title, location.href)
    return {
      url: location.href,
      title: document.title,
      header,
      content: this.last.content,
      footer: this.last.truncated ? footer : footer,
    }
  }

  /** The serialized line of an index — the danger rung verifies against THIS. */
  elementLine(index: number): string | undefined {
    return this.last?.elementTextMap.get(index)
  }

  async act(name: string, args: Record<string, unknown>): Promise<ActOutcome> {
    if (!this.last) return { ok: false, message: '❌ Not indexed yet — observe first.' }

    try {
      switch (name) {
        case 'click_element_by_index': {
          const { el, line } = this.resolve(args.index)
          glowBox(el.getBoundingClientRect())
          await clickElement(el)
          const newTab =
            el instanceof HTMLAnchorElement && el.target === '_blank'
              ? ' ⚠️ Link opens in a new tab.'
              : ''
          return { ok: true, message: `✅ Clicked element (${line}).${newTab}` }
        }
        case 'input_text': {
          const { el, line } = this.resolve(args.index)
          glowBox(el.getBoundingClientRect())
          await inputTextElement(el, String(args.text ?? ''))
          return { ok: true, message: `✅ Input text (${args.text}) into element (${line}).` }
        }
        case 'select_dropdown_option': {
          const { el, line } = this.resolve(args.index)
          await selectOptionElement(el, String(args.text ?? ''))
          return { ok: true, message: `✅ Selected option (${args.text}) in element (${line}).` }
        }
        case 'scroll': {
          const down = args.down !== false
          const pages = typeof args.num_pages === 'number' ? args.num_pages : 0.5
          const el = args.index !== undefined ? this.resolve(args.index).el : null
          const amount = pages * window.innerHeight * (down ? 1 : -1)
          const message = await scrollVertically(amount, el)
          return { ok: !message.startsWith('⚠️'), message }
        }
        default:
          return { ok: false, message: `❌ Unknown action "${name}".` }
      }
    } catch (error) {
      return { ok: false, message: `❌ Action failed: ${error}` }
    }
  }

  dispose(): void {
    // End of a run: let the boxes ease away instead of vanishing mid-frame.
    fadeOutHighlights(cleanupHighlights)
    this.last = null
  }

  private resolve(index: unknown): { el: HTMLElement; line: string } {
    const i = Number(index)
    const el = this.last?.selectorMap.get(i)
    if (!el) throw new Error(`No interactive element found at index ${i}`)
    if (!el.isConnected) throw new Error(`Element at index ${i} is no longer on the page`)
    return { el, line: this.last?.elementTextMap.get(i) ?? String(i) }
  }
}
