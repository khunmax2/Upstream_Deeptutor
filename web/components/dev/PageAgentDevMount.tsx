'use client'

// DEV-ONLY evaluation mount for Alibaba page-agent (MIT).
//
// This branch (`page-agent-clean-eval`) is cut from `main` and carries NO voice
// work, on purpose: it is the control variable. page-agent behaved oddly on the
// voice branch but fine in another project, and the question is whether our
// voice overlays (mascot, simulator cursor, MutationObserver, pointer layers)
// were interfering, or whether DeepTutor's own React DOM is what page-agent
// struggles with. Same setup, no voice → the answer.
//
// Inert unless NEXT_PUBLIC_ENABLE_PAGE_AGENT === "1".
//
// The provider API key never reaches the browser: page-agent's `baseURL` points
// at our own `/api/v1/llm-proxy`, which authenticates with the app's session
// cookie and forwards upstream with the server-side key (see
// `deeptutor/api/routers/llm_proxy.py`). Same shape as the suanrao project's
// PageAgentProvider, minus the JWT (DeepTutor uses cookie sessions).

import { useEffect, useRef, useState } from 'react'
import type { PageAgent, PageAgentConfig } from 'page-agent'
import { apiUrl } from '@/lib/api'

const ENABLED = process.env.NEXT_PUBLIC_ENABLE_PAGE_AGENT === '1'

// Safety rails for an agent that can click anything on the page. page-agent has
// no confirmation rung of its own (unlike our voice layer), so the guard rails
// have to live in the prompt.
const SYSTEM_INSTRUCTIONS = `You are an AI assistant embedded in DeepTutor, an agent-native learning app.
The UI is mostly Thai; the left sidebar holds the main navigation.
- NEVER click destructive or irreversible controls (ลบ / delete, ยกเลิก, ล้าง, รีเซ็ต, reset,
  ออกจากระบบ / logout) unless the user explicitly asked for exactly that action.
- NEVER click sidebar collapse/expand — it shifts the layout and misaims later clicks.
- Navigate by clicking one sidebar item at a time and wait for the page to settle
  before the next click.
- If you are unsure which element the user meant, ask instead of guessing.`

export default function PageAgentDevMount() {
  const [ready, setReady] = useState(false)
  const agentRef = useRef<PageAgent | null>(null)

  useEffect(() => {
    if (!ENABLED) return
    let cancelled = false

    const config: PageAgentConfig = {
      // Proxy mode: the model is pinned server-side, so this value is only a
      // label; the key is a placeholder the proxy ignores.
      model: 'proxy-default',
      baseURL: apiUrl('/api/v1/llm-proxy'),
      apiKey: 'via-session-proxy',
      // DeepTutor authenticates with a session cookie — send it.
      customFetch: (input, init) => fetch(input, { ...init, credentials: 'include' }),
      language: 'en-US', // page-agent has no Thai UI; it still reads the Thai DOM
      instructions: { system: SYSTEM_INSTRUCTIONS },
      // page-agent clicks via elementFromPoint, so a still-animating DOM makes
      // it miss. Let the page settle between steps (suanrao's lesson).
      stepDelay: 0.8,
    }

    import('page-agent')
      .then(({ PageAgent }) => {
        if (cancelled) return
        const agent = new PageAgent(config)
        agentRef.current = agent
        ;(window as unknown as { pageAgent?: PageAgent }).pageAgent = agent
        setReady(true)
      })
      // Dev scaffolding: a load failure just means no ✨ button — say so in the
      // console rather than painting a banner over the app.
      .catch(e => console.error('page-agent failed to load:', e))

    return () => {
      cancelled = true
      agentRef.current?.dispose()
      agentRef.current = null
      setReady(false)
    }
  }, [])

  if (!ENABLED || !ready) return null

  // page-agent's panel starts hidden (Panel constructor calls hide()) and only
  // auto-shows while a task is running — so it needs a trigger of our own.
  const openPanel = () => {
    const agent = agentRef.current
    if (!agent) return
    // Never reset mid-task; reset() clears the panel for a fresh prompt.
    if (agent.status !== 'running') agent.panel.reset()
    agent.panel.show()
  }

  // This branch carries no voice work, so nothing else owns the bottom-right.
  return (
    <button
      type="button"
      onClick={openPanel}
      title="เปิดแผง page-agent (eval)"
      style={{
        position: 'fixed',
        right: 24,
        bottom: 24,
        zIndex: 60,
        width: 44,
        height: 44,
        borderRadius: '50%',
        border: 'none',
        background: '#2D6A4F',
        color: '#fff',
        fontSize: 20,
        cursor: 'pointer',
        boxShadow: '0 2px 10px rgba(0,0,0,.35)',
      }}
    >
      ✨
    </button>
  )
}
