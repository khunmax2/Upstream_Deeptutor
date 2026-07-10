// DOM-tree serialization for the in-page agent (PLAN_inpage_agent_parity A1).
//
// Adapted from page-agent's `dom/index.ts` (MIT, Copyright (C) 2025 Alibaba
// Group Holding Limited) — the format the evaluation proved LLMs read well:
//
//   [12]<button aria-label=บันทึก>บันทึก />     ← only [index] lines are actionable
//   \t*[13]<div role=menu />                    ← indent = child, * = new since last step
//   plain text line                             ← visible but not interactive
//
// Deliberately PURE: no window/document access, so the whole format is locked
// by node tests. The actuator feeds it the engine's FlatDomTree and page info.
//
// Our deltas from the original: a hard content cap with an explicit truncation
// notice (agent_state rides a WebSocket control channel — see A4 frame budget),
// and new-element marking lives here behind a caller-owned WeakSet.

// Relative import on purpose: this module is also compiled by the node-tests
// tsconfig, which has no `@/` path mapping.
import type {
  DomNode,
  ElementDomNode,
  FlatDomTree,
  TextDomNode,
} from '../../components/voice/dom_tree/type'

// Attributes that carry meaning for an LLM choosing an element (their list).
const DEFAULT_INCLUDE_ATTRIBUTES = [
  'title',
  'type',
  'checked',
  'name',
  'role',
  'value',
  'placeholder',
  'data-date-format',
  'alt',
  'aria-label',
  'aria-expanded',
  'data-state',
  'aria-checked',
  'id',
  'for',
  'target',
  'aria-haspopup',
  'aria-controls',
  'aria-owns',
  'contenteditable',
]

const ATTR_VALUE_MAX = 20
// Keeps a full agent_state under a handful of WS chunks even on busy pages.
const DEFAULT_MAX_CONTENT_CHARS = 30_000
export const TRUNCATION_NOTICE =
  '... content truncated to fit the transport — scroll or navigate to see more ...'

export interface SerializedPage {
  content: string
  /** index → live element ref (typed loosely so pure node tests can fake refs) */
  selectorMap: Map<number, HTMLElement>
  /** index → its serialized line (danger rung + messages read this) */
  elementTextMap: Map<number, string>
  truncated: boolean
}

export interface PageInfo {
  viewportWidth: number
  viewportHeight: number
  pageWidth: number
  pageHeight: number
  pixelsAbove: number
  pixelsBelow: number
}

/**
 * Flag interactive elements whose ref has not been seen before (`*[n]` in the
 * output — "a menu or dialog probably just opened"). The caller owns *seen*
 * so the lifetime is one agent task, not the page's.
 */
export function markNewElements(tree: FlatDomTree, seen: WeakSet<object>): void {
  for (const id of Object.keys(tree.map)) {
    const node = tree.map[id] as ElementDomNode
    const ref = node.ref as object | undefined
    if (node.isInteractive && ref) {
      if (!seen.has(ref)) {
        seen.add(ref)
        node.isNew = true
      } else {
        node.isNew = false
      }
    }
  }
}

function isText(node: DomNode): node is TextDomNode {
  return (node as TextDomNode).type === 'TEXT_NODE'
}

function capText(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) + '...' : text
}

/** All visible text under *node*, stopping at nested interactive elements. */
function collectText(tree: FlatDomTree, node: ElementDomNode, self: boolean): string {
  const parts: string[] = []
  const walk = (n: DomNode, isSelf: boolean) => {
    if (!isText(n) && !isSelf && (n as ElementDomNode).highlightIndex !== undefined) return
    if (isText(n)) {
      if (n.text) parts.push(n.text)
      return
    }
    for (const childId of (n as ElementDomNode).children ?? []) {
      const child = tree.map[childId]
      if (child) walk(child, false)
    }
  }
  walk(node, self)
  return parts.join('\n').trim()
}

function renderAttributes(node: ElementDomNode, include: string[], text: string): string {
  const attrs = node.attributes ?? {}
  const picked: Record<string, string> = {}
  for (const key of include) {
    const value = attrs[key]
    if (value && value.trim()) picked[key] = value.trim()
  }

  // De-dup long values across attributes (aria-label repeating title, etc.).
  const seen: Record<string, string> = {}
  for (const key of Object.keys(picked)) {
    const value = picked[key]
    if (value.length > 5) {
      if (value in seen) delete picked[key]
      else seen[value] = key
    }
  }
  if (picked.role === node.tagName) delete picked.role
  for (const key of ['aria-label', 'placeholder', 'title']) {
    if (picked[key] && picked[key].toLowerCase().trim() === text.toLowerCase().trim()) {
      delete picked[key]
    }
  }

  return Object.entries(picked)
    .map(([key, value]) => `${key}=${capText(value, ATTR_VALUE_MAX)}`)
    .join(' ')
}

function renderScrollData(node: ElementDomNode): string {
  const extra = node.extra as { scrollable?: boolean; scrollData?: Record<string, number> }
  if (!extra?.scrollable) return ''
  const d = extra.scrollData ?? {}
  const parts: string[] = []
  if (d.left) parts.push(`left=${d.left}`)
  if (d.top) parts.push(`top=${d.top}`)
  if (d.right) parts.push(`right=${d.right}`)
  if (d.bottom) parts.push(`bottom=${d.bottom}`)
  return parts.length ? ` data-scrollable="${parts.join(', ')}"` : ''
}

export function serializeTree(
  tree: FlatDomTree,
  options?: { includeAttributes?: string[]; maxContentChars?: number }
): SerializedPage {
  const include = [...(options?.includeAttributes ?? []), ...DEFAULT_INCLUDE_ATTRIBUTES]
  const maxChars = options?.maxContentChars ?? DEFAULT_MAX_CONTENT_CHARS

  const selectorMap = new Map<number, HTMLElement>()
  const elementTextMap = new Map<number, string>()
  const lines: string[] = []

  const hasIndexedAncestor = (ancestors: boolean[]) => ancestors.some(Boolean)

  const walk = (id: string, depth: number, indexedAncestors: boolean[]) => {
    const node = tree.map[id]
    if (!node) return

    if (isText(node)) {
      // Text under an indexed element is already inlined into that element's
      // line; free-standing visible text renders as its own plain line.
      if (!hasIndexedAncestor(indexedAncestors) && node.isVisible && node.text?.trim()) {
        lines.push('\t'.repeat(depth) + node.text.trim())
      }
      return
    }

    const el = node as ElementDomNode
    let nextDepth = depth
    let selfIndexed = false

    if (el.highlightIndex !== undefined) {
      selfIndexed = true
      nextDepth += 1
      const text = collectText(tree, el, true)
      const attrs = renderAttributes(el, include, text)
      const marker = el.isNew ? `*[${el.highlightIndex}]` : `[${el.highlightIndex}]`

      let line = `${'\t'.repeat(depth)}${marker}<${el.tagName ?? ''}`
      if (attrs) line += ` ${attrs}`
      line += renderScrollData(el)
      if (text) {
        if (!attrs) line += ' '
        line += `>${text}`
      } else if (!attrs) {
        line += ' '
      }
      line += ' />'
      lines.push(line)

      if (el.isInteractive && el.ref) {
        selectorMap.set(el.highlightIndex, el.ref as HTMLElement)
        elementTextMap.set(el.highlightIndex, line.trim())
      }
    }

    for (const childId of el.children ?? []) {
      walk(childId, nextDepth, [...indexedAncestors, selfIndexed])
    }
  }

  walk(tree.rootId, 0, [])

  let content = lines.join('\n')
  let truncated = false
  if (content.length > maxChars) {
    // Cut on a line boundary so we never ship half an [index] line.
    const cut = content.lastIndexOf('\n', maxChars)
    content = content.slice(0, cut > 0 ? cut : maxChars) + '\n' + TRUNCATION_NOTICE
    truncated = true
  }

  return { content, selectorMap, elementTextMap, truncated }
}

/** Header/footer exactly in the shape the loop's prompt expects (their format). */
export function buildHeaderFooter(
  info: PageInfo,
  title: string,
  url: string
): { header: string; footer: string } {
  const pagesAbove = info.viewportHeight ? info.pixelsAbove / info.viewportHeight : 0
  const pagesBelow = info.viewportHeight ? info.pixelsBelow / info.viewportHeight : 0
  const totalPages = info.viewportHeight ? info.pageHeight / info.viewportHeight : 0

  const header =
    `Current Page: [${title}](${url})\n` +
    `Page info: ${info.viewportWidth}x${info.viewportHeight}px viewport, ` +
    `${info.pageWidth}x${info.pageHeight}px total page size, ` +
    `${pagesAbove.toFixed(1)} pages above, ${pagesBelow.toFixed(1)} pages below, ` +
    `${totalPages.toFixed(1)} total pages\n\n` +
    `Interactive elements from top layer of the current page:\n\n` +
    (info.pixelsAbove > 4
      ? `... ${info.pixelsAbove} pixels above (${pagesAbove.toFixed(1)} pages) - scroll to see more ...`
      : '[Start of page]')

  const footer =
    info.pixelsBelow > 4
      ? `... ${info.pixelsBelow} pixels below (${pagesBelow.toFixed(1)} pages) - scroll to see more ...`
      : '[End of page]'

  return { header, footer }
}

/**
 * Split a string for the WS control channel (A4 frame budget: control frames
 * are capped server-side; a full agent_state does NOT fit in one frame —
 * pageInventory already had a whole frame rejected once. Never silent-drop).
 */
export function chunkString(value: string, chunkSize: number): string[] {
  if (chunkSize <= 0) throw new Error('chunkSize must be positive')
  if (value === '') return ['']
  const chunks: string[] = []
  for (let i = 0; i < value.length; i += chunkSize) {
    chunks.push(value.slice(i, i + chunkSize))
  }
  return chunks
}
