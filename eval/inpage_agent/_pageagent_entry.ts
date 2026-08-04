// Eval-only: expose page-agent's CORE (brain + controller, no floating Panel and
// with the SimulatorMask disabled) so the headless Playwright run isn't blocked
// by mask/panel animations. MIT (Alibaba). New file under eval/.
import { PageAgentCore } from '@page-agent/core'
import { PageController } from '@page-agent/page-controller'
;(window as unknown as { __PageAgentCore?: unknown }).__PageAgentCore = PageAgentCore
;(window as unknown as { __PageController?: unknown }).__PageController = PageController
