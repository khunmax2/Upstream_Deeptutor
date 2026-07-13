// Locks the agent's eye format (lib/page-actuator/serialize.ts). The server
// loop's LLM reads EXACTLY these strings; a drifted bracket or indent silently
// degrades every task, so the format is pinned here on fabricated trees —
// no DOM, no browser.

import test from 'node:test'
import assert from 'node:assert/strict'

import type { FlatDomTree } from '../components/voice/dom_tree/type'
import {
  TRUNCATION_NOTICE,
  buildHeaderFooter,
  chunkString,
  markNewElements,
  serializeTree,
} from '../lib/page-actuator/serialize'

// Fake element refs: plain objects work — serialize/markNew only use identity.
const ref = () => ({}) as unknown as HTMLElement

function tree(map: FlatDomTree['map']): FlatDomTree {
  return { rootId: 'root', map }
}

test('indexed line format: [n]<tag attrs>text />', () => {
  const t = tree({
    root: { tagName: 'body', children: ['b'], isVisible: true, isTopElement: true },
    b: {
      tagName: 'button',
      attributes: { 'aria-label': 'บันทึกไฟล์' },
      children: ['t'],
      isVisible: true,
      isInteractive: true,
      highlightIndex: 0,
      ref: ref(),
    },
    t: { type: 'TEXT_NODE', text: 'บันทึก', isVisible: true },
  })
  const out = serializeTree(t)
  assert.equal(out.content, '[0]<button aria-label=บันทึกไฟล์>บันทึก />')
  assert.equal(out.elementTextMap.get(0), '[0]<button aria-label=บันทึกไฟล์>บันทึก />')
  assert.equal(out.selectorMap.size, 1)
})

test('indentation marks children; free text renders as plain lines', () => {
  const t = tree({
    root: { tagName: 'body', children: ['nav', 'txt'], isVisible: true, isTopElement: true },
    nav: {
      tagName: 'div',
      children: ['a'],
      isVisible: true,
      isInteractive: true,
      highlightIndex: 0,
      ref: ref(),
    },
    a: {
      tagName: 'a',
      children: [],
      isVisible: true,
      isInteractive: true,
      highlightIndex: 1,
      ref: ref(),
    },
    txt: { type: 'TEXT_NODE', text: 'คำอธิบายหน้า', isVisible: true },
  })
  const lines = serializeTree(t).content.split('\n')
  assert.equal(lines[0], '[0]<div  />')
  assert.equal(lines[1], '\t[1]<a  />') // child indented under [0]
  assert.equal(lines[2], 'คำอธิบายหน้า') // visible text, no index
})

test('blank icon link falls back to its href tail (settings sub-nav stays distinct)', () => {
  const t = tree({
    root: { tagName: 'body', children: ['a1', 'a2'], isVisible: true, isTopElement: true },
    a1: {
      tagName: 'a',
      attributes: { href: '/settings/models' }, // href is not a rendered attr
      children: [], // icon-only: no text
      isVisible: true,
      isInteractive: true,
      highlightIndex: 0,
      ref: ref(),
    },
    a2: {
      tagName: 'a',
      attributes: { href: '/settings/search?tab=1#top' },
      children: [],
      isVisible: true,
      isInteractive: true,
      highlightIndex: 1,
      ref: ref(),
    },
  })
  const lines = serializeTree(t).content.split('\n')
  assert.equal(lines[0], '[0]<a >models />')
  assert.equal(lines[1], '[1]<a >search />') // query/hash stripped
})

test('blank interactive element salvages nested text collectText skipped', () => {
  const t = tree({
    root: { tagName: 'body', children: ['a'], isVisible: true, isTopElement: true },
    a: {
      tagName: 'a',
      attributes: { href: '/x' },
      children: ['inner'],
      isVisible: true,
      isInteractive: true,
      highlightIndex: 0,
      ref: ref(),
    },
    inner: {
      tagName: 'span',
      children: ['t'],
      isVisible: true,
      isInteractive: true, // collectText stops here → the anchor would be blank
      highlightIndex: 1,
      ref: ref(),
    },
    t: { type: 'TEXT_NODE', text: 'Appearance', isVisible: true },
  })
  // nested text wins over the href tail; the anchor is no longer a blank [0]<a />
  assert.equal(serializeTree(t).content.split('\n')[0], '[0]<a >Appearance />')
})

test('labelled and truly-empty lines are unchanged by the fallback', () => {
  const t = tree({
    root: { tagName: 'body', children: ['btn', 'empty'], isVisible: true, isTopElement: true },
    btn: {
      tagName: 'button',
      attributes: { 'aria-label': 'บันทึก' }, // already labelled → untouched
      children: [],
      isVisible: true,
      isInteractive: true,
      highlightIndex: 0,
      ref: ref(),
    },
    empty: {
      tagName: 'div', // no text, no attrs, no href → stays blank
      children: [],
      isVisible: true,
      isInteractive: true,
      highlightIndex: 1,
      ref: ref(),
    },
  })
  const lines = serializeTree(t).content.split('\n')
  assert.equal(lines[0], '[0]<button aria-label=บันทึก />')
  assert.equal(lines[1], '[1]<div  />') // unchanged: nothing to fall back to
})

test('markNewElements: unseen refs get *[n], seen refs do not', () => {
  const sharedRef = ref()
  const make = () =>
    tree({
      root: { tagName: 'body', children: ['b'], isVisible: true, isTopElement: true },
      b: {
        tagName: 'button',
        children: [],
        isVisible: true,
        isInteractive: true,
        highlightIndex: 3,
        ref: sharedRef,
      },
    })
  const seen = new WeakSet<object>()

  const first = make()
  markNewElements(first, seen)
  assert.match(serializeTree(first).content, /^\*\[3\]/)

  const second = make()
  markNewElements(second, seen)
  assert.match(serializeTree(second).content, /^\[3\]/) // same ref → not new
})

test('attribute hygiene: dedup long values, drop role==tag, drop label==text, cap at 20', () => {
  const t = tree({
    root: { tagName: 'body', children: ['b'], isVisible: true, isTopElement: true },
    b: {
      tagName: 'button',
      attributes: {
        role: 'button', // == tagName → dropped
        'aria-label': 'ตกลง', // == text → dropped
        title: 'เปิดหน้าการตั้งค่าของระบบทั้งหมด', // >20 chars → capped
        name: 'เปิดหน้าการตั้งค่าของระบบทั้งหมด', // dup of title value → dropped
      },
      children: ['t'],
      isVisible: true,
      isInteractive: true,
      highlightIndex: 0,
      ref: ref(),
    },
    t: { type: 'TEXT_NODE', text: 'ตกลง', isVisible: true },
  })
  const content = serializeTree(t).content
  assert.ok(!content.includes('role='))
  assert.ok(!content.includes('aria-label='))
  assert.ok(!content.includes('name='))
  assert.match(content, /title=.{20}\.\.\./)
})

test('scrollable containers advertise remaining distance', () => {
  const t = tree({
    root: { tagName: 'body', children: ['list'], isVisible: true, isTopElement: true },
    list: {
      tagName: 'div',
      children: [],
      isVisible: true,
      isInteractive: true,
      highlightIndex: 0,
      ref: ref(),
      extra: { scrollable: true, scrollData: { top: 120, bottom: 480 } },
    },
  })
  assert.match(serializeTree(t).content, /data-scrollable="top=120, bottom=480"/)
})

test('hard cap cuts on a line boundary and says so out loud', () => {
  const map: FlatDomTree['map'] = {
    root: { tagName: 'body', children: [], isVisible: true, isTopElement: true },
  }
  const children: string[] = []
  for (let i = 0; i < 200; i++) {
    const id = `b${i}`
    children.push(id)
    map[id] = {
      tagName: 'button',
      attributes: { 'aria-label': `ปุ่มหมายเลขที่ ${i} ของหน้านี้` },
      children: [],
      isVisible: true,
      isInteractive: true,
      highlightIndex: i,
      ref: ref(),
    }
  }
  ;(map.root as { children?: string[] }).children = children

  const out = serializeTree(tree(map), { maxContentChars: 2000 })
  assert.ok(out.truncated)
  assert.ok(out.content.length < 2200)
  assert.ok(out.content.endsWith(TRUNCATION_NOTICE))
  const lastDataLine = out.content.split('\n').at(-2)! // every kept line is whole
  assert.match(lastDataLine, /^\[\d+\]<button .* \/>$/)
})

test('header/footer carry scroll position the way the prompt expects', () => {
  const info = {
    viewportWidth: 1280,
    viewportHeight: 800,
    pageWidth: 1280,
    pageHeight: 2400,
    pixelsAbove: 800,
    pixelsBelow: 800,
  }
  const { header, footer } = buildHeaderFooter(info, 'DeepTutor', 'http://x/home')
  assert.match(header, /Current Page: \[DeepTutor\]\(http:\/\/x\/home\)/)
  assert.match(header, /1\.0 pages above/)
  assert.match(header, /800 pixels above/)
  assert.match(footer, /800 pixels below/)

  const top = buildHeaderFooter({ ...info, pixelsAbove: 0, pixelsBelow: 0 }, 't', 'u')
  assert.match(top.header, /\[Start of page\]$/)
  assert.equal(top.footer, '[End of page]')
})

test('chunkString: exact reassembly, every part within budget', () => {
  const payload = 'x'.repeat(6000 * 2 + 123)
  const parts = chunkString(payload, 6000)
  assert.equal(parts.length, 3)
  assert.ok(parts.every(p => p.length <= 6000))
  assert.equal(parts.join(''), payload)
  assert.deepEqual(chunkString('', 6000), [''])
})
