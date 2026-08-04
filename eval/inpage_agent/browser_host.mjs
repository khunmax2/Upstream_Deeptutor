// Phase-E eval host: a real Chromium (Playwright) owns a live DeepTutor page and
// exposes our REAL page-actuator (serialize.ts + actions.ts, bundled) over a tiny
// HTTP bridge so the Python InPageAgentLoop can drive it unchanged.
//
// New file, isolated under eval/ — does not touch web/ or deeptutor/ source
// (fork policy §3). HTTP (not the production WS) only because it removes the 8K
// control-frame cap and needs zero extra deps; the serialize/act code exercised
// is the shipping code, which is what Phase E measures.
//
//   POST /goto   {url}            navigate + (re)inject bundle + fresh baseline
//   GET  /observe                 -> BrowserState JSON (our serializer)
//   POST /act    {name,args}      -> {ok,message} (our actions)
//   POST /reset                   fresh *[new] baseline (new task)
//   POST /shutdown
//
// Env: EVAL_BASE_URL (default http://localhost:3000), EVAL_HOST_PORT (default 8899),
//      EVAL_HEADLESS ("0" to watch).

import http from 'node:http'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { chromium } from 'playwright'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const BASE_URL = process.env.EVAL_BASE_URL || 'http://localhost:3000'
const PORT = Number(process.env.EVAL_HOST_PORT || 8899)
const HEADLESS = process.env.EVAL_HEADLESS !== '0'
const BUNDLE = readFileSync(path.join(__dirname, 'actuator.bundle.js'), 'utf8')

const browser = await chromium.launch({ headless: HEADLESS })
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await context.newPage()

async function inject() {
  // Bundle sets window.__evalActuator = new PageActuator(). Re-run after every
  // hard navigation; a fresh instance gives a fresh *[new] baseline.
  await page.evaluate(BUNDLE)
}

async function readBody(req) {
  const chunks = []
  for await (const c of req) chunks.push(c)
  return chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : {}
}

function send(res, code, obj) {
  const body = JSON.stringify(obj)
  res.writeHead(code, { 'content-type': 'application/json' })
  res.end(body)
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://x')
    if (req.method === 'POST' && url.pathname === '/goto') {
      const { url: to } = await readBody(req)
      // domcontentloaded, NOT networkidle: the DeepTutor SPA holds long-poll /
      // websocket connections that never idle, so networkidle burns the full
      // timeout on every navigation.
      await page.goto(to.startsWith('http') ? to : BASE_URL + to, {
        waitUntil: 'domcontentloaded',
        timeout: 30000,
      })
      await page.waitForTimeout(1200)
      await inject()
      return send(res, 200, { ok: true, url: page.url() })
    }
    if (req.method === 'POST' && url.pathname === '/reset') {
      await inject()
      return send(res, 200, { ok: true })
    }
    if (req.method === 'POST' && url.pathname === '/settheme') {
      // Clean a state leak: theme persists in localStorage across tasks, so a
      // prior run can make theme_dark trivially "pass". Force a known baseline.
      const { theme } = await readBody(req)
      await page.evaluate((t) => {
        try {
          localStorage.setItem('theme', t)
          localStorage.setItem('deeptutor-theme', t)
        } catch {}
      }, theme || 'snow')
      await page.reload({ waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(1000)
      await inject()
      return send(res, 200, { ok: true })
    }
    if (req.method === 'GET' && url.pathname === '/observe') {
      const state = await page.evaluate(() => {
        const a = window.__evalActuator
        if (!a) return null
        return a.observe()
      })
      if (!state) {
        await inject()
        const retry = await page.evaluate(() => window.__evalActuator.observe())
        return send(res, 200, retry)
      }
      return send(res, 200, state)
    }
    if (req.method === 'POST' && url.pathname === '/act') {
      const { name, args } = await readBody(req)
      const out = await page.evaluate(
        async ([n, a]) => {
          const act = window.__evalActuator
          if (!act) return { ok: false, message: 'actuator missing' }
          return await act.act(n, a || {})
        },
        [name, args],
      )
      // Let SPA navigation / re-render settle before the next observe.
      await page.waitForTimeout(400)
      return send(res, 200, out)
    }
    if (req.method === 'GET' && url.pathname === '/url') {
      return send(res, 200, { url: page.url() })
    }
    if (req.method === 'GET' && url.pathname === '/probe') {
      // Objective success signals the loop can't fake: applied theme, visible
      // text, open dialogs. Read straight off the live DOM.
      const info = await page.evaluate(() => {
        const de = document.documentElement
        return {
          url: location.href,
          htmlClass: de.className || '',
          dataTheme: de.getAttribute('data-theme') || '',
          themeLS:
            (window.localStorage && (localStorage.getItem('theme') || localStorage.getItem('deeptutor-theme'))) ||
            '',
          hasDialog: !!document.querySelector('[role="dialog"],[role="alertdialog"]'),
          bodyText: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 4000),
        }
      })
      return send(res, 200, info)
    }
    if (req.method === 'POST' && url.pathname === '/shutdown') {
      send(res, 200, { ok: true })
      await browser.close()
      server.close()
      process.exit(0)
    }
    return send(res, 404, { error: 'not found' })
  } catch (e) {
    return send(res, 500, { error: String(e && e.stack ? e.stack : e) })
  }
})

server.listen(PORT, () => {
  console.log(`[browser_host] listening on http://127.0.0.1:${PORT} base=${BASE_URL} headless=${HEADLESS}`)
})
