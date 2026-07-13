// Hard-grounding route manifest ↔ real-routes parity.
//
// The voice loop verifies a navigation task landed where it was asked by
// resolving the task to a canonical route and comparing it to the achieved URL
// (deeptutor/services/voice_realtime/agent/route_grounding.py + route_manifest.json).
// If a page is moved/renamed the manifest would ground against a route that
// 404s — a landing there could NEVER satisfy it, turning every such task into a
// false failure. This test fails the suite the moment the manifest names a path
// with no page.
//
// Mirrors voice-graph-parity.test.ts (same routeExists logic).

import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'

const webRoot = process.cwd()
const appRoot = path.join(webRoot, 'app')
const manifest = JSON.parse(
  readFileSync(
    path.join(
      webRoot,
      '..',
      'deeptutor',
      'services',
      'voice_realtime',
      'agent',
      'route_manifest.json'
    ),
    'utf8'
  )
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
          dirs.push(full)
          continue
        }
        if (name === segment) next.push(full)
      }
    }
    if (!next.length) return false
    dirs = next
  }
  // A page.tsx directly here, OR under an optional catch-all "[[...x]]" child —
  // an optional catch-all renders at the base path too (e.g. /home is served by
  // home/[[...sessionId]]/page.tsx).
  return dirs.some(
    dir =>
      existsSync(path.join(dir, 'page.tsx')) ||
      readdirSync(dir).some(
        name => name.startsWith('[[...') && existsSync(path.join(dir, name, 'page.tsx'))
      )
  )
}

test('every grounding manifest path points at a real page', () => {
  const paths = (manifest.routes as { path: string }[]).map(r => r.path)
  const stale = paths.filter(p => !routeExists(p))
  assert.deepEqual(
    stale,
    [],
    `manifest paths with no matching page.tsx (page moved/renamed?): ${stale.join(', ')}`
  )
})

test('manifest paths are unique', () => {
  const paths = (manifest.routes as { path: string }[]).map(r => r.path)
  const dupes = paths.filter((p, i) => paths.indexOf(p) !== i)
  assert.deepEqual(dupes, [], `duplicate manifest paths: ${dupes.join(', ')}`)
})

test('every route carries at least one alias', () => {
  const bare = (manifest.routes as { path: string; aliases?: string[] }[])
    .filter(r => !r.aliases || r.aliases.length === 0)
    .map(r => r.path)
  assert.deepEqual(bare, [], `manifest routes with no aliases: ${bare.join(', ')}`)
})
