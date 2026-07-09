// Current-screen context for the voice call — the "read" half of voice UI
// control. The widget sits in the root layout, so whatever page the caller is
// on, its DOM is visible here. Before each spoken turn we serialise a compact
// text outline of that DOM (headings, nav links, tabs, buttons) and stream it
// to the voice layer as a `ui_context` control frame; the model then answers
// "หน้านี้มีเมนูอะไรบ้าง" from the real screen instead of guessing.
//
// Read-only by design: we serialise text the page already shows and never
// read input/textarea *values* (form contents, keys, passwords stay out of
// the prompt). Acting on the page remains the manifest whitelist's job.
//
// Split in two so the formatting/capping logic is testable under node:test
// (no DOM): `collectPageOutline` reads the DOM, `formatPageContext` is pure.

export interface PageOutline {
  path: string
  /** Human page name from the UI_PAGES manifest (when the path matches). */
  pageName?: string
  title: string
  headings: string[]
  navLinks: string[]
  tabs: string[]
  buttons: string[]
}

// The whole control frame must stay under the server's 8K frame cap
// (MAX_MANIFEST_BYTES); the stored summary is capped server-side at 3000
// chars — stay under both with margin.
export const MAX_SUMMARY_CHARS = 2400
const MAX_ITEM_CHARS = 60
const MAX_ITEMS_PER_SECTION = 25

function cleanItems(items: string[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const raw of items) {
    const text = raw.replace(/\s+/g, ' ').trim().slice(0, MAX_ITEM_CHARS)
    if (!text || seen.has(text)) continue
    seen.add(text)
    out.push(text)
    if (out.length >= MAX_ITEMS_PER_SECTION) break
  }
  return out
}

/** Pure formatter: outline → capped one-string summary (node-testable). */
export function formatPageContext(o: PageOutline): string {
  const sections: [string, string[]][] = [
    ['หัวข้อ', cleanItems(o.headings)],
    ['เมนู/ลิงก์', cleanItems(o.navLinks)],
    ['แท็บ', cleanItems(o.tabs)],
    ['ปุ่ม', cleanItems(o.buttons)],
  ]
  const lines: string[] = []
  // Current-page identity first and in plain words — the model must answer
  // "ตอนนี้อยู่หน้าไหน" from here, not from stale navigation turns in the
  // conversation history (the caller can click around by hand at any time).
  const pageName = (o.pageName || '').replace(/\s+/g, ' ').trim()
  if (pageName) lines.push(`หน้าปัจจุบัน: ${pageName.slice(0, MAX_ITEM_CHARS)} (${o.path})`)
  const title = o.title.replace(/\s+/g, ' ').trim()
  if (title) lines.push(`ชื่อหน้า: ${title.slice(0, MAX_ITEM_CHARS)}`)
  for (const [label, items] of sections) {
    if (items.length) lines.push(`${label}: ${items.join(' | ')}`)
  }
  return lines.join('\n').slice(0, MAX_SUMMARY_CHARS)
}

function isVisible(el: Element): boolean {
  // offsetParent is null for display:none (correct to exclude) BUT ALSO for
  // position:fixed and sticky elements that are perfectly visible — those
  // dropped out of the streamed context, so a fixed toolbar's field / button
  // intermittently read as "not on screen". Fall back to real layout boxes.
  if ((el as HTMLElement).offsetParent !== null) return true
  const rects = el.getClientRects()
  return rects.length > 0 && rects[0].width > 0 && rects[0].height > 0
}

function grabTexts(selector: string, exclude: Element | null): string[] {
  const out: string[] = []
  document.querySelectorAll(selector).forEach(el => {
    if (exclude && exclude.contains(el)) return // never describe our own panel
    if (!isVisible(el)) return
    const text = el.textContent || (el as HTMLElement).getAttribute?.('aria-label') || ''
    if (text.trim()) out.push(text)
  })
  return out
}

/**
 * Read the visible page into a `{path, summary}` context ready to send as a
 * `ui_context` frame. `exclude` is the widget's own root element so the call
 * panel never describes itself; `pageName` is the human label for the current
 * path (from the UI_PAGES manifest) so "which page am I on" has a plain-words
 * answer.
 */
export function collectPageContext(
  exclude: Element | null,
  pageName?: string
): {
  path: string
  page?: string
  summary: string
  buttons: string[]
  fields: string[]
  activeField?: string
} {
  const outline: PageOutline = {
    path: window.location.pathname,
    pageName,
    title: document.title,
    headings: grabTexts('h1, h2, h3', exclude),
    navLinks: grabTexts("nav a, aside a, [role='navigation'] a", exclude),
    tabs: grabTexts("[role='tab']", exclude),
    buttons: grabTexts("button, [role='button'], a[role='menuitem']", exclude),
  }
  // `page`, `buttons` and `fields` ride as structured fields (not only inside
  // the summary prose): `page` answers "ตอนนี้อยู่หน้าไหน" deterministically,
  // `buttons` is what click-by-name resolves spoken names against, and
  // `fields` is the same contract for fill-by-voice. Each list comes from the
  // SAME collector its executor uses, so every name the server can approve is
  // guaranteed actionable.
  return {
    path: outline.path,
    page: pageName,
    summary: formatPageContext(outline),
    buttons: cleanItems(visibleClickables(exclude).map(c => c.label)),
    fields: capFieldEntries(visibleFields(exclude).map(f => formatFieldEntry(f.label, f.options))),
    // The field with the caret right now — a bare "พิมพ์ X" (no field named)
    // targets it first (Tier A implicit fill). Empty when nothing fillable is
    // focused (or the caret is in our own panel).
    activeField: activeFieldLabel(exclude) || undefined,
  }
}

/** The label of the currently focused fillable field, or "" — the caret's
 * field, used by implicit fill. Same label rule and exclusions as
 * visibleFields, so it names something the fill executor can find. */
function activeFieldLabel(exclude: Element | null): string {
  const el = document.activeElement
  if (
    !el ||
    !(
      el instanceof HTMLInputElement ||
      el instanceof HTMLTextAreaElement ||
      el instanceof HTMLSelectElement
    )
  ) {
    return ''
  }
  if (exclude && exclude.contains(el)) return ''
  if (!isVisible(el)) return ''
  if (el.disabled || ('readOnly' in el && el.readOnly)) return ''
  if (el instanceof HTMLInputElement && SKIP_INPUT_TYPES.has(el.type)) return ''
  return fieldLabelFor(el)
}

// The whole ui_context frame must stay under the server's 8K cap alongside
// the ~2400-char summary and ~2400-char buttons list. A page full of long
// dropdowns could blow that on fields alone — and an oversized frame is
// DROPPED whole, killing the screen context with it. Budget the fields list:
// per-entry cap (mirrors the server's _MAX_FIELD_CHARS) + a total budget.
const MAX_FIELD_ENTRY_CHARS = 120
const MAX_FIELDS_TOTAL_CHARS = 1500

export function capFieldEntries(entries: string[]): string[] {
  const out: string[] = []
  let total = 0
  for (const raw of entries) {
    const entry = raw.slice(0, MAX_FIELD_ENTRY_CHARS)
    if (out.length >= MAX_FIELDS || total + entry.length > MAX_FIELDS_TOTAL_CHARS) break
    out.push(entry)
    total += entry.length
  }
  return out
}

// Everything a finger could tap: real buttons/tabs, and links — settings-hub
// style cards are <Link href> around a heading, not <button>. Main-content
// clickables are listed before nav/sidebar ones so, under the caps, the page's
// own actions win over the ever-present sidebar links.
const CLICKABLE_SELECTOR = "button, [role='button'], [role='tab'], a[role='menuitem'], a[href]"

// A card's whole text ("LlamaIndex พร้อมใช้งาน Local vector retrieval…") is
// unmatchable by voice; past this length we fall back to the card's first
// text chunk, which is its visible title.
const MAX_WHOLE_LABEL_CHARS = 40

/** First rendered text chunk inside *el* — a card's title, whatever tag it is. */
function firstTextChunk(el: HTMLElement): string {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
  let node: Node | null
  while ((node = walker.nextNode())) {
    const text = (node.textContent || '').replace(/\s+/g, ' ').trim()
    if (text.length >= 2) return text
  }
  return ''
}

/** Short spoken-friendly label for a clickable: aria-label, else the heading
 * inside it, else its full text when short, else its first text chunk (card
 * titles are often plain <span>s — the Knowledge-Center engine cards). */
function clickableLabel(el: HTMLElement): string {
  const aria = el.getAttribute('aria-label') || ''
  const heading = el.querySelector('h1, h2, h3, h4, h5, h6')?.textContent || ''
  const full = (el.textContent || '').replace(/\s+/g, ' ').trim()
  const text =
    aria.trim() ||
    heading.replace(/\s+/g, ' ').trim() ||
    (full.length <= MAX_WHOLE_LABEL_CHARS ? full : firstTextChunk(el) || full)
  return text.slice(0, MAX_ITEM_CHARS)
}

/**
 * The visible clickable elements (outside `exclude`) with their labels —
 * single source of truth for BOTH the streamed `buttons` context and the
 * click executor, so reporting and acting can never disagree.
 */
function visibleClickables(exclude: Element | null): { el: HTMLElement; label: string }[] {
  const main: { el: HTMLElement; label: string }[] = []
  const nav: { el: HTMLElement; label: string }[] = []
  for (const el of Array.from(document.querySelectorAll<HTMLElement>(CLICKABLE_SELECTOR))) {
    if (exclude && exclude.contains(el)) continue
    if (!isVisible(el)) continue
    const label = clickableLabel(el)
    if (!label) continue
    ;(el.closest("nav, aside, [role='navigation']") ? nav : main).push({ el, label })
  }
  return [...main, ...nav]
}

// ── fill-by-voice: visible form fields ─────────────────────────────────
//
// Same see→name→act contract as clicks: the streamed `fields` list and the
// fill executor share one collector, so the server can only approve a field
// the caller could see and the client can actually set. Native controls only
// (input/textarea/select) — custom comboboxes render as buttons and are
// already reachable through click-by-voice (open, then press an option).

const MAX_FIELDS = 20
const MAX_FIELD_OPTIONS = 8
const MAX_OPTION_CHARS = 30
// Never read or type into these: secrets, binary pickers, button-shaped inputs.
const SKIP_INPUT_TYPES = new Set([
  'hidden',
  'password',
  'checkbox',
  'radio',
  'file',
  'submit',
  'button',
  'reset',
  'image',
  'range',
  'color',
])

type FillableElement = HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement

interface FieldEntry {
  el: FillableElement
  label: string
  options: string[] // non-empty = a <select>'s choices
}

/** Spoken-friendly label for a form field: aria-label → its <label> →
 * placeholder → name attribute. Empty = unaddressable by voice, skipped. */
function fieldLabelFor(el: FillableElement): string {
  const aria = (el.getAttribute('aria-label') || '').trim()
  if (aria) return aria.slice(0, MAX_ITEM_CHARS)
  let labelled = ''
  if (el.id) {
    const forLabel = document.querySelector(`label[for="${CSS.escape(el.id)}"]`)
    labelled = (forLabel?.textContent || '').trim()
  }
  if (!labelled) labelled = (el.closest('label')?.textContent || '').trim()
  const placeholder = ('placeholder' in el ? el.placeholder : '').trim()
  const text = labelled || placeholder || (el.getAttribute('name') || '').trim()
  return text.replace(/\s+/g, ' ').slice(0, MAX_ITEM_CHARS)
}

/** Marker must match the server's `_FIELD_OPTIONS_MARKER` (ui_control.py). */
export function formatFieldEntry(label: string, options: string[]): string {
  if (!options.length) return label
  return `${label} (เลือกได้: ${options.join(' | ')})`
}

function visibleFields(exclude: Element | null): FieldEntry[] {
  const out: FieldEntry[] = []
  const seen = new Set<string>()
  for (const el of Array.from(
    document.querySelectorAll<FillableElement>('input, textarea, select')
  )) {
    if (exclude && exclude.contains(el)) continue
    if (!isVisible(el)) continue
    if (el.disabled || ('readOnly' in el && el.readOnly)) continue
    if (el instanceof HTMLInputElement && SKIP_INPUT_TYPES.has(el.type)) continue
    const label = fieldLabelFor(el)
    if (!label || seen.has(label)) continue // duplicate labels are unaddressable
    seen.add(label)
    const options =
      el instanceof HTMLSelectElement
        ? Array.from(el.options)
            .map(o => (o.textContent || o.value).replace(/\s+/g, ' ').trim())
            .filter(Boolean)
            .slice(0, MAX_FIELD_OPTIONS)
            .map(o => o.slice(0, MAX_OPTION_CHARS))
        : []
    out.push({ el, label, options })
    if (out.length >= MAX_FIELDS) break
  }
  return out
}

/** Set a field's value the way React expects: through the native prototype
 * setter (so the controlled-component value tracker notices the change),
 * then a bubbling `input` + `change` — the page-agent framework-patch lesson. */
function setNativeValue(el: FillableElement, value: string): void {
  const proto =
    el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : el instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
  if (setter) setter.call(el, value)
  else el.value = value
  el.dispatchEvent(new Event('input', { bubbles: true }))
  el.dispatchEvent(new Event('change', { bubbles: true }))
}

/**
 * Type *value* into the visible field whose label matches *fieldLabel*
 * (exact normalised match first, then substring). For a <select>, *value*
 * picks the option whose text or value matches. Returns whether anything was
 * set. Uses the same collector as collectPageContext, so the server can only
 * name what the caller could see.
 */
function findFieldByLabel(fieldLabel: string, exclude: Element | null): FieldEntry | null {
  const norm = (s: string) => s.replace(/\s+/g, ' ').trim().toLowerCase()
  const target = norm(fieldLabel)
  if (!target) return null
  let exact: FieldEntry | null = null
  let partial: FieldEntry | null = null
  for (const entry of visibleFields(exclude)) {
    const text = norm(entry.label)
    if (text === target && !exact) exact = entry
    else if (!partial && (text.includes(target) || target.includes(text))) partial = entry
  }
  return exact ?? partial
}

export function fillFieldByVoice(
  fieldLabel: string,
  value: string,
  exclude: Element | null
): boolean {
  const norm = (s: string) => s.replace(/\s+/g, ' ').trim().toLowerCase()
  const chosen = findFieldByLabel(fieldLabel, exclude)
  if (!chosen || !value) return false
  const el = chosen.el
  if (el instanceof HTMLSelectElement) {
    const wanted = norm(value)
    const options = Array.from(el.options)
    const option =
      options.find(o => norm(o.textContent || '') === wanted || norm(o.value) === wanted) ??
      options.find(o => {
        const t = norm(o.textContent || o.value)
        return t.includes(wanted) || wanted.includes(t)
      })
    if (!option) return false
    setNativeValue(el, option.value)
  } else {
    setNativeValue(el, value)
  }
  el.focus?.()
  return true
}

/** *text* without its last word. Thai has no spaces between words —
 * Intl.Segmenter (word granularity) finds the real boundary; the whitespace
 * fallback covers runtimes without it. Pure, node-testable. */
export function removeLastWord(text: string): string {
  if (!text) return text
  const trimmed = text.replace(/\s+$/, '')
  try {
    const segments = [...new Intl.Segmenter('th', { granularity: 'word' }).segment(trimmed)]
    for (let i = segments.length - 1; i >= 0; i--) {
      if (segments[i].isWordLike) {
        return (
          trimmed.slice(0, segments[i].index) +
          trimmed.slice(segments[i].index + segments[i].segment.length)
        ).replace(/\s+$/, '')
      }
    }
    return ''
  } catch {
    return trimmed.replace(/\S+$/, '').replace(/\s+$/, '')
  }
}

/**
 * Undo typing in the visible field matching *fieldLabel*: `op` is "clear"
 * (empty the field) or "delete_word" (drop the last word — Thai-aware).
 * Selects are not editable this way. Returns whether anything changed.
 */
export function editFieldByVoice(fieldLabel: string, op: string, exclude: Element | null): boolean {
  const chosen = findFieldByLabel(fieldLabel, exclude)
  if (!chosen || chosen.el instanceof HTMLSelectElement) return false
  const el = chosen.el
  if (op === 'clear') setNativeValue(el, '')
  else if (op === 'delete_word') setNativeValue(el, removeLastWord(el.value))
  else return false
  el.focus?.()
  return true
}

/**
 * The page's main scrollable container. DeepTutor's shell is
 * `h-screen overflow-hidden`, so `window` almost never scrolls — the real
 * scroller is some inner div. Pick the visible scrollable element (outside
 * the widget) with the largest viewport area; fall back to the document.
 */
function mainScrollable(exclude: Element | null): HTMLElement | null {
  const doc = document.scrollingElement as HTMLElement | null
  let best: HTMLElement | null = null
  let bestArea = 0
  for (const el of Array.from(document.querySelectorAll<HTMLElement>('*'))) {
    if (exclude && exclude.contains(el)) continue
    if (el.scrollHeight <= el.clientHeight + 40) continue
    const style = getComputedStyle(el)
    if (style.overflowY !== 'auto' && style.overflowY !== 'scroll') continue
    if (!isVisible(el)) continue
    const rect = el.getBoundingClientRect()
    const area = rect.width * rect.height
    if (area > bestArea) {
      best = el
      bestArea = area
    }
  }
  if (best) return best
  if (doc && doc.scrollHeight > doc.clientHeight + 40) return doc
  return null
}

/** Voice scroll: direction is one of scroll_down/up/bottom/top. */
export function scrollByVoice(direction: string, exclude: Element | null): boolean {
  const el = mainScrollable(exclude)
  if (!el) return false
  const page = el.clientHeight * 0.75
  if (direction === 'scroll_down') el.scrollBy({ top: page, behavior: 'smooth' })
  else if (direction === 'scroll_up') el.scrollBy({ top: -page, behavior: 'smooth' })
  else if (direction === 'scroll_bottom') el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  else if (direction === 'scroll_top') el.scrollTo({ top: 0, behavior: 'smooth' })
  else return false
  return true
}

/**
 * Click the visible element whose label matches *name* (exact normalised
 * match first, then substring). Returns whether something was clicked. Uses
 * the same collector as collectPageContext, so the server can only name what
 * the caller could see.
 */
export function findClickableByText(name: string, exclude: Element | null): HTMLElement | null {
  const norm = (s: string) => s.replace(/\s+/g, ' ').trim().toLowerCase()
  const target = norm(name)
  if (!target) return null
  let exact: HTMLElement | null = null
  let partial: HTMLElement | null = null
  for (const { el, label } of visibleClickables(exclude)) {
    const text = norm(label)
    if (text === target && !exact) exact = el
    else if (!partial && (text.includes(target) || target.includes(text))) partial = el
  }
  return exact ?? partial
}

export function clickVisibleByText(name: string, exclude: Element | null): boolean {
  const chosen = findClickableByText(name, exclude)
  chosen?.click()
  return Boolean(chosen)
}

/** The DOM element of the visible field matching *fieldLabel* (same matcher
 * the fill/edit executors use) — for pointing at it before acting. */
export function findFieldElement(fieldLabel: string, exclude: Element | null): HTMLElement | null {
  return findFieldByLabel(fieldLabel, exclude)?.el ?? null
}
