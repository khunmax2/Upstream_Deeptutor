// Neon restyle for the vision layer's highlight boxes.
//
// The vendored dom_tree engine draws loud 2px solid borders in a 12-color
// palette with opaque label chips — functional, but visually chaotic on a
// busy page (live feedback: "สีกรอบไม่ค่อยสวยเลย"). The engine file is kept
// byte-identical (vendor contract), so instead of editing it we restyle the
// overlays it just created: thin softened-hue borders with an outer glow and
// translucent pill labels — the "neon ฟุ้งๆ จางๆ" look.
//
// Color correlation is preserved for free: the engine derives box border and
// label background from the SAME base color per index, so transforming each
// element's own computed color keeps every label matching its box.

const CONTAINER_ID = 'playwright-highlight-container' // engine.ts:152
const LABEL_CLASS = 'playwright-highlight-label'

/** Blend an 0-255 channel toward white — pure #F00-style hues read harsh;
 * pastel-neon is what actually glows nicely on both themes. */
function soften(channel: number): number {
  return Math.round(channel + (255 - channel) * 0.35)
}

function parseRgb(value: string): [number, number, number] | null {
  const match = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(value)
  if (!match) return null
  return [soften(+match[1]), soften(+match[2]), soften(+match[3])]
}

function rgba(rgb: [number, number, number], alpha: number): string {
  return `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`
}

/**
 * Restyle every overlay the engine just appended. Call right after a
 * highlighted dom_tree pass; safe to call when nothing was drawn.
 */
export function neonizeHighlights(): void {
  const container = document.getElementById(CONTAINER_ID)
  if (!container) return

  for (const el of Array.from(container.querySelectorAll<HTMLElement>('div'))) {
    const isLabel = el.classList.contains(LABEL_CLASS)
    // Inline styles only: the engine wrote hex+alpha there and the browser
    // hands it back normalized to rgba(). (computedStyle would lie for
    // labels — no border set means currentcolor, i.e. white.)
    const source = isLabel ? el.style.background : el.style.borderColor
    const rgb = parseRgb(source)
    if (!rgb) continue

    if (isLabel) {
      // Translucent dark pill, hue carried by the glowing text + hairline ring.
      el.style.background = 'rgba(15, 20, 28, 0.55)'
      el.style.color = rgba(rgb, 1)
      el.style.border = `1px solid ${rgba(rgb, 0.65)}`
      el.style.borderRadius = '999px'
      el.style.padding = '0px 5px'
      el.style.fontWeight = '600'
      el.style.textShadow = `0 0 6px ${rgba(rgb, 0.9)}`
      el.style.boxShadow = `0 0 8px ${rgba(rgb, 0.35)}`
      el.style.backdropFilter = 'blur(2px)'
    } else {
      // Hairline border + soft outer/inner glow, barely-there fill.
      el.style.border = `1px solid ${rgba(rgb, 0.8)}`
      el.style.borderRadius = '6px'
      el.style.backgroundColor = rgba(rgb, 0.04)
      el.style.boxShadow = `0 0 10px 1px ${rgba(rgb, 0.4)}, inset 0 0 8px ${rgba(rgb, 0.1)}`
    }
  }
}
