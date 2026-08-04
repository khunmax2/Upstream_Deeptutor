// Voice-manifest ↔ real-routes parity.
//
// The voice call widget declares the pages a caller may steer to
// (UI_PAGES in components/voice/VoiceCallWidget.tsx). That table is written
// by hand, so a new/renamed page.tsx can silently drift away from it — the
// caller then hears "ไม่มีหน้านั้น" for a page that plainly exists. This test
// fails the suite the moment the app's top-level routes and the manifest
// disagree, in either direction.
//
// Reads both sides as files (no React import): routes from the app/ tree,
// manifest paths from the widget source.

import test from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'

const webRoot = process.cwd()
const appRoot = path.join(webRoot, 'app')
const widgetSource = readFileSync(
  path.join(webRoot, 'components', 'voice', 'VoiceCallWidget.tsx'),
  'utf8'
)

// Pages that are deliberately not voice-steerable (kept in sync with
// VOICE_MANIFEST_EXCLUDED_ROUTES in the widget).
const EXCLUDED = new Set(['/', '/login', '/register'])

function containsPage(dir: string): boolean {
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name)
    if (name === 'page.tsx') return true
    if (statSync(full).isDirectory() && containsPage(full)) return true
  }
  return false
}

function collectTopLevelRoutes(dir: string, segments: string[] = []): string[] {
  const routes: string[] = []
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name)
    if (statSync(full).isDirectory()) {
      // Route groups "(workspace)" don't appear in the URL. An optional
      // catch-all like home/[[...sessionId]]/page.tsx means the parent
      // segment itself resolves ("/home"). Other dynamic segments are
      // sub-pages of an already-counted route.
      const isGroup = name.startsWith('(') && name.endsWith(')')
      if (name.startsWith('[[') && segments.length === 1 && containsPage(full)) {
        routes.push('/' + segments.join('/'))
        continue
      }
      const nextSegments = isGroup ? segments : [...segments, name]
      if (nextSegments.length <= 1 && !name.startsWith('[')) {
        routes.push(...collectTopLevelRoutes(full, nextSegments))
      }
    } else if (name === 'page.tsx') {
      routes.push('/' + segments.join('/'))
    }
  }
  return routes
}

function manifestPaths(): string[] {
  // Quote-agnostic: prettier may render the widget with single or double
  // quotes, and this test must not care.
  const matches = [...widgetSource.matchAll(/path:\s*['"]([^'"]+)['"]/g)]
  return matches.map(m => m[1])
}

test('every top-level page is voice-steerable or explicitly excluded', () => {
  const routes = [...new Set(collectTopLevelRoutes(appRoot))].sort()
  const declared = new Set(manifestPaths())
  const missing = routes.filter(r => !declared.has(r) && !EXCLUDED.has(r))
  assert.deepEqual(
    missing,
    [],
    `pages missing from the voice manifest (add to UI_PAGES in VoiceCallWidget.tsx ` +
      `or to the exclusion lists): ${missing.join(', ')}`
  )
})

test('every manifest path points at a real page', () => {
  const routes = new Set(collectTopLevelRoutes(appRoot))
  const stale = manifestPaths().filter(p => !routes.has(p))
  assert.deepEqual(
    stale,
    [],
    `voice manifest paths with no matching page.tsx (page moved/renamed?): ${stale.join(', ')}`
  )
})
