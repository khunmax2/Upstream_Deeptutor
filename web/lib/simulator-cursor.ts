// Simulator cursor — the page-agent "SimulatorMask" idea, sized for voice:
// before a voice-driven action touches the page, a virtual cursor glides to
// the target and pulses, so the caller SEES where the agent is about to act.
// Pure presentation: it never performs the action itself (the executors in
// pageContext.ts stay the only hands), it cannot receive events
// (pointer-events: none), and losing it costs nothing but the show.
//
// One singleton overlay div lives on <body> (the widget is in the root
// layout, so it survives route changes) and fades out after a short idle.

const CURSOR_SIZE = 26
const CURSOR_Z = 2147483000
// Fast glide: visible pointing without a felt delay (~a quarter second).
const MOVE_MS = 200
const SETTLE_MS = 40
const SCROLL_WAIT_MS = 250
const IDLE_HIDE_MS = 1600
// How far from the target the cursor snaps in before its short glide, so a
// first (hidden) appearance never dashes across the whole screen.
const APPROACH_OFFSET = 46

let cursor: HTMLDivElement | null = null
let hideTimer: ReturnType<typeof setTimeout> | null = null

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function reducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
}

function ensureCursor(): HTMLDivElement {
  if (cursor && document.body.contains(cursor)) return cursor
  const el = document.createElement('div')
  el.setAttribute('aria-hidden', 'true')
  el.style.cssText =
    `position:fixed;left:0;top:0;width:${CURSOR_SIZE}px;height:${CURSOR_SIZE}px;` +
    `border-radius:50%;pointer-events:none;z-index:${CURSOR_Z};opacity:0;` +
    'transform:translate(-200px,-200px);' +
    `transition:transform ${MOVE_MS}ms cubic-bezier(.22,1,.36,1),opacity 200ms ease;` +
    'background:radial-gradient(circle at 30% 30%,#8ecbff,#2f6fd0);' +
    'border:2.5px solid rgba(255,255,255,.95);' +
    'box-shadow:0 2px 10px rgba(0,0,0,.35),0 0 0 4px rgba(63,131,248,.25);'
  document.body.appendChild(el)
  cursor = el
  return el
}

/** Where on *rect* the cursor should point: horizontal centre, vertically
 * centred but never deeper than 80px from the top — pointing at the entry
 * area of a tall textarea reads better than its geometric middle. Pure,
 * node-testable. */
export function targetPoint(rect: { left: number; top: number; width: number; height: number }): {
  x: number
  y: number
} {
  return {
    x: rect.left + rect.width / 2,
    y: rect.top + Math.min(rect.height / 2, 80),
  }
}

/**
 * Glide the cursor onto *el* (scrolling it into view first when off-screen)
 * and resolve when it has landed — callers act after the pointing, so the
 * caller of the CALL sees "point, then press". Honors prefers-reduced-motion
 * by jumping instead of gliding.
 */
export async function pointAt(el: Element): Promise<void> {
  const c = ensureCursor()
  let rect = el.getBoundingClientRect()
  if (
    rect.bottom < 0 ||
    rect.top > window.innerHeight ||
    rect.right < 0 ||
    rect.left > window.innerWidth
  ) {
    ;(el as HTMLElement).scrollIntoView?.({
      block: 'center',
      behavior: reducedMotion() ? 'auto' : 'smooth',
    })
    await sleep(SCROLL_WAIT_MS)
    rect = el.getBoundingClientRect()
  }
  const p = targetPoint(rect)
  const jump = reducedMotion()
  const at = (x: number, y: number) =>
    `translate(${x - CURSOR_SIZE / 2}px, ${y - CURSOR_SIZE / 2}px)`
  if (jump) {
    c.style.transitionProperty = 'opacity'
    c.style.opacity = '1'
    c.style.transform = at(p.x, p.y)
    scheduleHide()
    return
  }
  // If the cursor is hidden (first action, or after an idle fade), snap it to
  // a short offset from the target with NO transition, so every glide is a
  // brief consistent hop instead of a full cross-screen dash that the click
  // outruns. A visible cursor keeps its position and glides from there.
  const hidden = c.style.opacity !== '1'
  if (hidden) {
    c.style.transition = 'none'
    c.style.transform = at(p.x - APPROACH_OFFSET, p.y - APPROACH_OFFSET)
    void c.offsetWidth // flush the snap before re-enabling the transition
    c.style.transition = `transform ${MOVE_MS}ms cubic-bezier(.22,1,.36,1),opacity 200ms ease`
  }
  c.style.opacity = '1'
  c.style.transform = at(p.x, p.y)
  await sleep(MOVE_MS + SETTLE_MS)
  scheduleHide()
}

/** A press ripple at the cursor's current spot — call right before the real
 * click/type executes. */
export function clickPulse(): void {
  if (!cursor || reducedMotion()) return
  cursor.animate(
    [
      { boxShadow: '0 2px 10px rgba(0,0,0,.35),0 0 0 4px rgba(63,131,248,.35)' },
      { boxShadow: '0 2px 10px rgba(0,0,0,.35),0 0 0 18px rgba(63,131,248,0)' },
    ],
    { duration: 420, easing: 'ease-out' }
  )
  cursor.animate(
    [
      { transform: cursor.style.transform + ' scale(1)' },
      { transform: cursor.style.transform + ' scale(.72)', offset: 0.35 },
      { transform: cursor.style.transform + ' scale(1)' },
    ],
    { duration: 260, easing: 'ease-out' }
  )
  scheduleHide()
}

function scheduleHide(): void {
  if (hideTimer) clearTimeout(hideTimer)
  hideTimer = setTimeout(() => {
    if (cursor) cursor.style.opacity = '0'
  }, IDLE_HIDE_MS)
}

/** Remove the overlay entirely — call on hang-up. */
export function disposeCursor(): void {
  if (hideTimer) clearTimeout(hideTimer)
  hideTimer = null
  cursor?.remove()
  cursor = null
  glow?.remove()
  glow = null
}

// ── field glow: a halo around the field the agent just locked onto ──────
//
// The visual companion to focus/fill/edit: once the target field is resolved,
// its outline blooms so the caller SEES which box the agent chose — a quick
// flash on focus, a few soft pulses while typing. Same rules as the cursor:
// one singleton overlay, pointer-events none, never touches the field itself.

const GLOW_PAD = 4
let glow: HTMLDivElement | null = null

/** The fixed-overlay box for a halo around *rect* — the element rect grown by
 * GLOW_PAD on every side, clamped to non-negative size. Pure, node-testable. */
export function glowBox(rect: { left: number; top: number; width: number; height: number }): {
  left: number
  top: number
  width: number
  height: number
} {
  return {
    left: rect.left - GLOW_PAD,
    top: rect.top - GLOW_PAD,
    width: Math.max(0, rect.width) + GLOW_PAD * 2,
    height: Math.max(0, rect.height) + GLOW_PAD * 2,
  }
}

function ensureGlow(): HTMLDivElement {
  if (glow && document.body.contains(glow)) return glow
  const el = document.createElement('div')
  el.setAttribute('aria-hidden', 'true')
  el.style.cssText =
    `position:fixed;pointer-events:none;z-index:${CURSOR_Z - 1};opacity:0;` +
    'border-radius:12px;border:2px solid rgba(63,131,248,.9);' +
    'box-shadow:0 0 18px 3px rgba(63,131,248,.55),inset 0 0 8px rgba(63,131,248,.25);'
  document.body.appendChild(el)
  glow = el
  return el
}

/**
 * Bloom a halo around *el*: `mode` "flash" is one quick shimmer (focus lock),
 * "pulse" is a few gentle cycles (typing / editing). Positions itself over the
 * field's current rect and matches its corner radius. reduced-motion → a
 * single static fade.
 */
export function glowField(el: Element, mode: 'flash' | 'pulse' = 'flash'): void {
  const g = ensureGlow()
  const rect = el.getBoundingClientRect()
  const box = glowBox(rect)
  g.style.left = `${box.left}px`
  g.style.top = `${box.top}px`
  g.style.width = `${box.width}px`
  g.style.height = `${box.height}px`
  const radius = getComputedStyle(el as HTMLElement).borderRadius
  if (radius && radius !== '0px') g.style.borderRadius = `calc(${radius} + ${GLOW_PAD}px)`
  if (reducedMotion()) {
    g.style.transition = 'opacity 200ms ease'
    g.style.opacity = '0.9'
    setTimeout(() => {
      if (glow) glow.style.opacity = '0'
    }, 600)
    return
  }
  g.style.transition = 'none'
  const cycles = mode === 'pulse' ? 3 : 1
  const frames: Keyframe[] =
    mode === 'pulse'
      ? [
          { opacity: 0 },
          { opacity: 1, offset: 0.15 },
          { opacity: 0.35, offset: 0.5 },
          { opacity: 0.9, offset: 0.75 },
          { opacity: 0 },
        ]
      : [{ opacity: 0 }, { opacity: 1, offset: 0.25 }, { opacity: 0 }]
  g.animate(frames, { duration: 420 * cycles + 260, easing: 'ease-in-out' })
}
