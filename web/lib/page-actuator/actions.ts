/**
 * Copyright (C) 2025 Alibaba Group Holding Limited
 * All rights reserved.
 *
 * Ported for DeepTutor (PLAN_inpage_agent_parity A2) from page-agent's
 * `page-controller/src/actions.ts` (MIT). What is kept is the load-bearing
 * craft the evaluation validated:
 *  - clicks fire the FULL W3C pointer+mouse sequence (React/antd listen to
 *    pointerdown/mousedown, not just .click())
 *  - a hit-test refines the click to the innermost child INSIDE the target,
 *    falling back to the target itself — never to an outside element
 *  - typing goes through the NATIVE value setter (beats React controlled
 *    inputs), contenteditable gets Plan A (synthetic events) → verify →
 *    Plan B (execCommand)
 * Our adaptation: the visible hand is our simulatorCursor (pointAt/clickPulse)
 * instead of their mask-cursor custom events, and the run-mask's pass-through
 * toggle wraps the hit-test.
 */

import { clickPulse, pointAt } from '@/components/voice/simulatorCursor'
import { withPassThrough } from './runMask'

const sleep = (s: number) => new Promise<void>(resolve => setTimeout(resolve, s * 1000))

function isInput(el: Element): el is HTMLInputElement {
  return el.tagName === 'INPUT'
}
function isTextArea(el: Element): el is HTMLTextAreaElement {
  return el.tagName === 'TEXTAREA'
}
function isSelect(el: Element): el is HTMLSelectElement {
  return el.tagName === 'SELECT'
}

function nativeValueSetter(el: HTMLInputElement | HTMLTextAreaElement) {
  const proto = isInput(el) ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
  if (!setter) throw new Error('Native value setter unavailable')
  return setter
}

function scrollIntoViewIfNeeded(element: Element): void {
  const el = element as Element & { scrollIntoViewIfNeeded?: (center?: boolean) => void }
  if (typeof el.scrollIntoViewIfNeeded === 'function') el.scrollIntoViewIfNeeded()
  else element.scrollIntoView({ behavior: 'auto', block: 'center', inline: 'nearest' })
}

let lastClicked: HTMLElement | null = null

function blurLastClicked(): void {
  if (!lastClicked) return
  lastClicked.dispatchEvent(new PointerEvent('pointerout', { bubbles: true }))
  lastClicked.dispatchEvent(new PointerEvent('pointerleave', { bubbles: false }))
  lastClicked.dispatchEvent(new MouseEvent('mouseout', { bubbles: true }))
  lastClicked.dispatchEvent(new MouseEvent('mouseleave', { bubbles: false }))
  lastClicked.blur()
  lastClicked = null
}

/** Full spec-order synthetic click on *element* (see module docblock). */
export async function clickElement(element: HTMLElement): Promise<void> {
  blurLastClicked()
  lastClicked = element

  scrollIntoViewIfNeeded(element)
  const frame = element.ownerDocument.defaultView?.frameElement
  if (frame) scrollIntoViewIfNeeded(frame)

  const rect = element.getBoundingClientRect()
  const x = rect.left + rect.width / 2
  const y = rect.top + rect.height / 2

  // The visible hand: glide our cursor there and pulse (pure presentation).
  await pointAt(element)
  clickPulse()

  await sleep(0.1)

  // Innermost-target refinement, mask lifted for the hit-test only.
  const doc = element.ownerDocument
  const hit = withPassThrough(() => doc.elementFromPoint(x, y))
  const target = hit instanceof HTMLElement && element.contains(hit) ? hit : element

  const pointerOpts = {
    bubbles: true,
    cancelable: true,
    clientX: x,
    clientY: y,
    pointerType: 'mouse',
  }
  const mouseOpts = { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 }

  target.dispatchEvent(new PointerEvent('pointerover', pointerOpts))
  target.dispatchEvent(new PointerEvent('pointerenter', { ...pointerOpts, bubbles: false }))
  target.dispatchEvent(new MouseEvent('mouseover', mouseOpts))
  target.dispatchEvent(new MouseEvent('mouseenter', { ...mouseOpts, bubbles: false }))

  target.dispatchEvent(new PointerEvent('pointerdown', pointerOpts))
  target.dispatchEvent(new MouseEvent('mousedown', mouseOpts))

  // Focus the original element (nearest focusable), matching browser behavior.
  element.focus({ preventScroll: true })

  target.dispatchEvent(new PointerEvent('pointerup', pointerOpts))
  target.dispatchEvent(new MouseEvent('mouseup', mouseOpts))

  target.click()

  await sleep(0.2)
}

/** Type into input/textarea/contenteditable, replacing existing content. */
export async function inputTextElement(element: HTMLElement, text: string): Promise<void> {
  const contentEditable = element.isContentEditable
  if (!isInput(element) && !isTextArea(element) && !contentEditable) {
    throw new Error('Element is not an input, textarea, or contenteditable')
  }

  await clickElement(element)

  if (contentEditable) {
    // Plan A: synthetic beforeinput/input pairs (React contenteditable, Quill).
    if (
      element.dispatchEvent(
        new InputEvent('beforeinput', {
          bubbles: true,
          cancelable: true,
          inputType: 'deleteContent',
        })
      )
    ) {
      element.innerText = ''
      element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContent' }))
    }
    if (
      element.dispatchEvent(
        new InputEvent('beforeinput', {
          bubbles: true,
          cancelable: true,
          inputType: 'insertText',
          data: text,
        })
      )
    ) {
      element.innerText = text
      element.dispatchEvent(
        new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text })
      )
    }

    // Verify, then Plan B: execCommand (Slate.js and friends; native undo stack).
    if (element.innerText.trim() !== text.trim()) {
      element.focus()
      const doc = element.ownerDocument
      const selection = (doc.defaultView || window).getSelection()
      const range = doc.createRange()
      range.selectNodeContents(element)
      selection?.removeAllRanges()
      selection?.addRange(range)
      doc.execCommand('delete', false)
      doc.execCommand('insertText', false, text)
    }

    element.dispatchEvent(new Event('change', { bubbles: true }))
    element.blur()
  } else {
    // Narrowed above: non-contenteditable here is input or textarea.
    const field = element as HTMLInputElement | HTMLTextAreaElement
    nativeValueSetter(field).call(field, text)
    element.dispatchEvent(new Event('input', { bubbles: true }))
  }

  await sleep(0.1)
  blurLastClicked()
}

/** Select a <select> option by its visible text. */
export async function selectOptionElement(element: HTMLElement, optionText: string): Promise<void> {
  if (!isSelect(element)) throw new Error('Element is not a select element')
  const option = Array.from(element.options).find(o => o.textContent?.trim() === optionText.trim())
  if (!option) throw new Error(`Option with text "${optionText}" not found in select element`)
  element.value = option.value
  element.dispatchEvent(new Event('change', { bubbles: true }))
  await sleep(0.1)
}

/**
 * Scroll the page, or (with an element) its nearest scrollable ancestor.
 * Returns a sentence describing what actually moved — the LLM plans on it.
 */
export async function scrollVertically(
  amountPx: number,
  element?: HTMLElement | null
): Promise<string> {
  if (element) {
    let current: HTMLElement | null = element
    for (let attempts = 0; current && attempts < 10; attempts++) {
      const style = window.getComputedStyle(current)
      const scrollableY = /(auto|scroll|overlay)/.test(style.overflowY)
      const canScroll = current.scrollHeight > current.clientHeight
      if (scrollableY && canScroll) {
        const before = current.scrollTop
        current.scrollTop = before + amountPx
        const moved = current.scrollTop - before
        if (Math.abs(moved) > 0.5) {
          return `✅ Scrolled container (${current.tagName}) by ${Math.round(moved)}px.`
        }
      }
      if (current === document.body || current === document.documentElement) break
      current = current.parentElement
    }
    return `⚠️ No scrollable container found for element (${element.tagName}).`
  }

  const before = window.scrollY
  window.scrollBy(0, amountPx)
  const moved = window.scrollY - before
  if (Math.abs(moved) < 1) {
    return amountPx > 0
      ? '⚠️ Already at the bottom of the page, cannot scroll down further.'
      : '⚠️ Already at the top of the page, cannot scroll up further.'
  }
  return `✅ Scrolled page by ${Math.round(moved)}px.`
}
