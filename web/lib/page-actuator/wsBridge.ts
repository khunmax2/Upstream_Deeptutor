// WS bridge for the in-page agent (PLAN_inpage_agent_parity A4): translates
// agent frames on the EXISTING voice socket into PageActuator calls. The
// server-side loop is the only caller; nothing here runs until it asks.
//
// Frame protocol (server ⇄ browser):
//   → {type:'agent_ready'}                                call pickup: flash the vision sweep
//   → {type:'agent_run',    running: true|false}          mask on/off, task reset
//   → {type:'agent_observe', id}                          look at the page
//   ← {type:'agent_state_chunk', id, seq, total, part}    JSON payload, chunked
//   → {type:'agent_act',    id, action, args}             do one action
//   ← {type:'agent_acted',  id, ok, message}
//   ← {type:'agent_takeover'}                             user clicked the mask
//
// agent_state is CHUNKED because control frames are size-capped server-side
// (MAX_MANIFEST_BYTES ~8K; pageInventory once had a whole frame rejected).
// The payload is JSON-stringified first, then split — the server reassembles
// by (id, seq/total) and parses once. Never silent-drop.

import { PageActuator } from './actuator'
import { hideRunMask, showRunMask } from './runMask'
import { chunkString } from './serialize'

// Comfortably under the server cap once the envelope + JSON escaping ride along.
const CHUNK_CHARS = 6000

type SendJson = (payload: Record<string, unknown>) => void

export interface PageAgentBridge {
  /** Returns true when the frame was an agent frame (caller stops routing). */
  handleFrame(msg: Record<string, unknown>): boolean
  dispose(): void
}

export function attachPageAgentBridge(send: SendJson): PageAgentBridge {
  const actuator = new PageActuator()

  // Manual/devtools acceptance handle (A gate): window.pageActuator.observe()
  ;(window as unknown as { pageActuator?: PageActuator }).pageActuator = actuator

  const handleFrame = (msg: Record<string, unknown>): boolean => {
    switch (msg.type) {
      case 'agent_ready': {
        // Call pickup with the loop enabled: flash the neon vision sweep so
        // the caller SEES the agent seeing the page. No mask — show only.
        actuator.flashVision()
        return true
      }
      case 'agent_run': {
        if (msg.running) {
          actuator.resetTask()
          showRunMask(() => send({ type: 'agent_takeover' }))
        } else {
          hideRunMask()
          actuator.dispose()
        }
        return true
      }
      case 'agent_observe': {
        const state = actuator.observe()
        const payload = JSON.stringify(state)
        const parts = chunkString(payload, CHUNK_CHARS)
        parts.forEach((part, seq) => {
          send({ type: 'agent_state_chunk', id: msg.id, seq, total: parts.length, part })
        })
        return true
      }
      case 'agent_act': {
        const action = String(msg.action ?? '')
        const args = (msg.args ?? {}) as Record<string, unknown>
        void actuator.act(action, args).then(outcome => {
          send({ type: 'agent_acted', id: msg.id, ok: outcome.ok, message: outcome.message })
        })
        return true
      }
      default:
        return false
    }
  }

  return {
    handleFrame,
    dispose() {
      hideRunMask()
      actuator.dispose()
      const w = window as unknown as { pageActuator?: PageActuator }
      if (w.pageActuator === actuator) delete w.pageActuator
    },
  }
}
