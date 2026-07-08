// Voice screen-context formatter — the pure half of components/voice/pageContext.
//
// The DOM-reading half needs a browser; what node:test can (and should) pin
// down is the outline → summary formatting: section labels, dedupe, per-item
// and total caps. The caps matter operationally — the summary rides a WS
// control frame the server rejects above 8K and truncates above 3000 chars.

import test from 'node:test'
import assert from 'node:assert/strict'

import {
  capFieldEntries,
  formatFieldEntry,
  formatPageContext,
  MAX_SUMMARY_CHARS,
  removeLastWord,
} from '../components/voice/pageContext'

const base = {
  path: '/settings',
  title: 'DeepTutor — ตั้งค่า',
  headings: [] as string[],
  navLinks: [] as string[],
  tabs: [] as string[],
  buttons: [] as string[],
}

test('formats sections with Thai labels, skipping empty ones', () => {
  const out = formatPageContext({
    ...base,
    headings: ['ตั้งค่าระบบ'],
    buttons: ['บันทึก', 'ยกเลิก'],
  })
  assert.match(out, /^ชื่อหน้า: DeepTutor — ตั้งค่า$/m)
  assert.match(out, /^หัวข้อ: ตั้งค่าระบบ$/m)
  assert.match(out, /^ปุ่ม: บันทึก \| ยกเลิก$/m)
  assert.doesNotMatch(out, /เมนู|แท็บ/) // empty sections stay out
})

test('current-page identity leads the summary when the manifest names it', () => {
  // "ตอนนี้อยู่หน้าไหน" must be answerable from the summary itself — in plain
  // words, first line — so stale navigation turns in history can't win.
  const out = formatPageContext({
    ...base,
    pageName: 'หน้าตั้งค่า (settings)',
    headings: ['ตั้งค่าระบบ'],
  })
  assert.match(out.split('\n')[0], /^หน้าปัจจุบัน: หน้าตั้งค่า \(settings\) \(\/settings\)$/)
})

test('dedupes repeats and collapses whitespace', () => {
  const out = formatPageContext({
    ...base,
    title: '',
    navLinks: ['  Knowledge\n Base ', 'Knowledge Base', 'Chat'],
  })
  assert.equal(out, 'เมนู/ลิงก์: Knowledge Base | Chat')
})

test('caps item length, items per section, and total size', () => {
  const out = formatPageContext({
    ...base,
    title: 'x'.repeat(300),
    headings: Array.from({ length: 100 }, (_, i) => `หัวข้อยาวมาก${i} ` + 'ก'.repeat(200)),
    buttons: Array.from({ length: 100 }, (_, i) => `ปุ่ม${i}`),
  })
  assert.ok(out.length <= MAX_SUMMARY_CHARS, `total ${out.length} > ${MAX_SUMMARY_CHARS}`)
  const buttonsLine = out.split('\n').find(l => l.startsWith('ปุ่ม:'))
  if (buttonsLine) {
    assert.ok(buttonsLine.split(' | ').length <= 25)
  }
  for (const line of out.split('\n')) {
    for (const item of line.replace(/^[^:]+: /, '').split(' | ')) {
      assert.ok(item.length <= 60, `item too long: ${item.length}`)
    }
  }
})

test("field entries fold a dropdown's options behind the server's marker", () => {
  // The " (เลือกได้:" marker must match ui_control._FIELD_OPTIONS_MARKER —
  // the server cuts the label for matching at exactly this string.
  assert.equal(formatFieldEntry('ค้นหา', []), 'ค้นหา')
  assert.equal(formatFieldEntry('ภาษา', ['ไทย', 'English']), 'ภาษา (เลือกได้: ไทย | English)')
})

test('field list obeys per-entry and total char budgets (frame stays under 8K)', () => {
  // An oversized ui_context frame is dropped whole by the server — the
  // fields list must never be what pushes it over.
  const long = 'ช'.repeat(500)
  const capped = capFieldEntries(Array.from({ length: 50 }, () => long))
  assert.ok(capped.length >= 1)
  for (const entry of capped) assert.ok(entry.length <= 120)
  assert.ok(capped.reduce((n, e) => n + e.length, 0) <= 1500)
})

test('removeLastWord drops the final word, Thai-aware', () => {
  assert.equal(removeLastWord('hello world'), 'hello')
  assert.equal(removeLastWord('one'), '')
  assert.equal(removeLastWord(''), '')
  assert.equal(removeLastWord('hello world  '), 'hello')
  // Thai has no spaces — Intl.Segmenter finds the word boundary.
  const thai = removeLastWord('กฎหมายแรงงาน')
  assert.ok(thai.length < 'กฎหมายแรงงาน'.length)
  assert.ok(thai === 'กฎหมาย' || thai === '', `unexpected: ${thai}`)
})

test('empty outline yields an empty summary (widget then skips the frame)', () => {
  assert.equal(formatPageContext({ ...base, title: '  ' }), '')
})
