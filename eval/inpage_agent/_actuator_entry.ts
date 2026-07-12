// Eval-only entry: expose PageActuator on window for the Playwright host.
// New file, isolated under eval/ — does not touch web/ source (fork policy §3).
import { PageActuator } from '../../web/lib/page-actuator/actuator'
;(window as unknown as { __evalActuator?: unknown }).__evalActuator = new PageActuator()
;(window as unknown as { __PageActuator?: unknown }).__PageActuator = PageActuator
