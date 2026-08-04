// Run-mask (PLAN_inpage_agent_parity A5): blocks the user's REAL mouse and
// keyboard while the agent loop is driving, so two hands never fight over one
// DOM. Shown only during a run — fast-path single actions never see it.
//
// Idea from page-agent's SimulatorMask (MIT, Alibaba); ours is leaner: the
// visible cursor is our existing simulatorCursor, highlights come from the
// dom_tree engine, so the mask itself is just the input shield + takeover.
//
// Takeover: any real click on the mask means "I want my page back" — the
// bridge reports it and the loop aborts. Same contract as voice barge-in.

const MASK_ID = 'deeptutor-agent-run-mask'
// Under the simulator cursor (2147483000) so the hand stays visible on top.
const MASK_Z = 2147482900

let mask: HTMLDivElement | null = null
let takeoverHandler: (() => void) | null = null

function block(e: Event): void {
  e.stopPropagation()
  e.preventDefault()
}

function ensureMask(): HTMLDivElement {
  if (mask && document.body.contains(mask)) return mask
  const el = document.createElement('div')
  el.id = MASK_ID
  el.setAttribute('aria-hidden', 'true')
  // A whisper of tint so the "agent is driving" state is visible but the page
  // stays readable — the highlights and cursor carry the real show.
  el.style.cssText =
    `position:fixed;inset:0;z-index:${MASK_Z};display:none;` +
    'background:rgba(20,40,30,0.06);cursor:wait;' +
    'opacity:0;transition:opacity 300ms ease;'

  el.addEventListener('mousedown', e => {
    block(e)
    takeoverHandler?.()
  })
  for (const type of ['click', 'mouseup', 'mousemove', 'wheel', 'keydown', 'keyup']) {
    el.addEventListener(type, block)
  }

  document.body.appendChild(el)
  mask = el
  return el
}

let maskHideTimer: number | null = null
const MASK_FADE_MS = 300

export function showRunMask(onTakeover?: () => void): void {
  takeoverHandler = onTakeover ?? null
  if (maskHideTimer !== null) {
    window.clearTimeout(maskHideTimer)
    maskHideTimer = null
  }
  const el = ensureMask()
  el.style.display = 'block'
  el.style.pointerEvents = 'auto' // shield up instantly; only the TINT eases
  requestAnimationFrame(() => {
    el.style.opacity = '1'
  })
}

export function hideRunMask(): void {
  takeoverHandler = null
  if (!mask) return
  const el = mask
  // Hand the page back IMMEDIATELY (pointer-events off) — only the tint
  // lingers while it eases out, then the node leaves the layout.
  el.style.pointerEvents = 'none'
  el.style.opacity = '0'
  if (maskHideTimer !== null) window.clearTimeout(maskHideTimer)
  maskHideTimer = window.setTimeout(() => {
    maskHideTimer = null
    el.style.display = 'none'
  }, MASK_FADE_MS)
}

/**
 * Lift the mask around a hit-test (`elementFromPoint` would find the mask
 * instead of the page — the one page-agent detail that MUST be kept).
 */
export function withPassThrough<T>(fn: () => T): T {
  if (!mask || mask.style.display === 'none') return fn()
  mask.style.pointerEvents = 'none'
  try {
    return fn()
  } finally {
    mask.style.pointerEvents = 'auto'
  }
}

export function disposeRunMask(): void {
  takeoverHandler = null
  mask?.remove()
  mask = null
}
