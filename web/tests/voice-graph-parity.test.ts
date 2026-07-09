// Website-Graph ↔ real-routes parity.
//
// The voice layer's cross-page commands plan over a curated UI graph
// (deeptutor/services/voice_realtime/ui_graph.json): each node names a route
// and the controls that live there. The graph is written by hand, so a
// moved/renamed page (or a widget whitelist change) can silently strand it —
// the caller then hears "กำลังเปิดหน้านั้น" for a page that 404s. This test
// fails the suite the moment the graph and the app disagree.
//
// Mirrors voice-manifest-parity.test.ts: reads all sides as files.

import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'

const webRoot = process.cwd()
const appRoot = path.join(webRoot, 'app')
const graph = JSON.parse(
  readFileSync(
    path.join(webRoot, '..', 'deeptutor', 'services', 'voice_realtime', 'ui_graph.json'),
    'utf8'
  )
)
const widgetSource = readFileSync(
  path.join(webRoot, 'components', 'voice', 'VoiceCallWidget.tsx'),
  'utf8'
)

/** Does /a/b resolve to a page.tsx under app/, route groups "(x)" ignored? */
function routeExists(routePath: string): boolean {
  const segments = routePath.split('/').filter(Boolean)
  let dirs = [appRoot]
  for (const segment of segments) {
    const next: string[] = []
    for (const dir of dirs) {
      for (const name of readdirSync(dir)) {
        const full = path.join(dir, name)
        if (!statSync(full).isDirectory()) continue
        if (name.startsWith('(') && name.endsWith(')')) {
          // Route group: transparent — descend and retry this segment there.
          dirs.push(full)
          continue
        }
        if (name === segment) next.push(full)
      }
    }
    if (!next.length) return false
    dirs = next
  }
  return dirs.some(dir => existsSync(path.join(dir, 'page.tsx')))
}

function manifestPaths(): string[] {
  const matches = [...widgetSource.matchAll(/path:\s*['"]([^'"]+)['"]/g)]
  return matches.map(m => m[1])
}

test('every graph node path points at a real page', () => {
  const stale = (graph.nodes as { path: string }[]).map(n => n.path).filter(p => !routeExists(p))
  assert.deepEqual(
    stale,
    [],
    `graph node paths with no matching page.tsx (page moved/renamed?): ${stale.join(', ')}`
  )
})

test('every graph node path sits under a voice-steerable page (open_path whitelist)', () => {
  // The widget only honours open_path targets under a declared UI_PAGES
  // path — a graph node outside that whitelist would plan navigations the
  // client (correctly) refuses.
  const declared = manifestPaths()
  const orphans = (graph.nodes as { path: string }[])
    .map(n => n.path)
    .filter(p => !declared.some(d => p === d || p.startsWith(d + '/')))
  assert.deepEqual(
    orphans,
    [],
    `graph node paths outside the UI_PAGES whitelist: ${orphans.join(', ')}`
  )
})

test('every graph control is well-formed', () => {
  for (const node of graph.nodes as { id: string; path: string; controls: any[] }[]) {
    assert.ok(node.id && node.path.startsWith('/'), `node ${node.id}: bad id/path`)
    assert.ok(Array.isArray(node.controls) && node.controls.length, `node ${node.id}: no controls`)
    for (const control of node.controls) {
      assert.ok(control.capability, `node ${node.id}: control without capability id`)
      assert.ok(
        typeof control.click === 'string' && control.click.length,
        `control ${control.capability}: missing click text`
      )
      assert.ok(
        ['button', 'toggle', 'link', 'field'].includes(control.kind),
        `control ${control.capability}: unknown kind ${control.kind}`
      )
      assert.ok(
        Array.isArray(control.aliases) && control.aliases.every((a: any) => typeof a === 'string'),
        `control ${control.capability}: aliases must be strings`
      )
    }
  }
})
