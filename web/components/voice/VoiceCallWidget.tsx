'use client'

// Voice call widget — floating call button + full-screen mascot overlay.
//
// Botnoi-WebAvatar-style presentation over DeepTutor's own realtime voice
// layer: pressing the call button fades the mascot overlay in, hanging up
// fades it out. The call protocol is: WebSocket `/api/v1/voice/ws` →
// ChatOrchestrator, browser Web-Speech STT with an echo mute-guard, per-
// sentence TTS audio streamed back, lip-sync driven by the real audio
// amplitude. Three.js is loaded from CDN on first open (no bundle dep).
//
// Fork-additive: new file; mounted with a one-line include in the workspace
// layout.

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { wsUrl } from '@/lib/api'
import {
  collectPageContext,
  editFieldByVoice,
  fillFieldByVoice,
  findClickableByText,
  findFieldElement,
  findScannedElement,
  findWithPoll,
  type InventoryItem,
  scanInventory,
  scrollByVoice,
  verifyFieldFocused,
  verifyFieldValue,
  verifyPath,
  type UiActionVerdict,
} from './pageContext'
import { clickPulse, disposeCursor, glowField, pointAt } from './simulatorCursor'
import { pickUtterance } from './speechAlternatives'
import { VOICE_ACTION_EVENT, type VoiceActionDetail } from './VoiceActionBridge'
import { attachPageAgentBridge, type PageAgentBridge } from '@/lib/page-actuator/wsBridge'

// Steerable-UI whitelist sent to the voice layer as the `ui_manifest` control
// frame: the model may call `ui_navigate` only with these ids, and this
// component re-validates every `ui_action` against the same table before
// pushing the route (defense in depth — see services/voice_realtime/ui_control).
const UI_PAGES: { id: string; label: string; path: string }[] = [
  { id: 'chat', label: 'หน้าแชทหลัก / หน้าหลัก / หน้าแรก (home, คุยกับ DeepTutor)', path: '/home' },
  {
    id: 'knowledge',
    label: 'หน้า Knowledge Base (คลังความรู้/ศูนย์ความรู้/เอกสาร)',
    path: '/knowledge',
  },
  { id: 'notebook', label: 'หน้าสมุดโน้ต', path: '/notebook' },
  { id: 'memory', label: 'หน้าความจำ / หน่วยความจำ (memory)', path: '/memory' },
  { id: 'agents', label: 'หน้าเอเจนต์ของฉัน', path: '/agents' },
  { id: 'book', label: 'หน้าสร้างหนังสือ (book)', path: '/book' },
  { id: 'co_writer', label: 'หน้าเขียนงานร่วมกัน (co-writer)', path: '/co-writer' },
  { id: 'space', label: 'หน้า space', path: '/space' },
  { id: 'partners', label: 'หน้า partners (เพื่อนคู่คิด/บอทคู่หู)', path: '/partners' },
  { id: 'playground', label: 'หน้า playground (สนามทดลอง)', path: '/playground' },
  { id: 'settings', label: 'หน้าตั้งค่า (settings)', path: '/settings' },
  { id: 'profile', label: 'หน้าโปรไฟล์ผู้ใช้', path: '/profile' },
]

// Auth pages are deliberately NOT voice-steerable; everything else must be
// declared above — tests/voice-manifest-parity.test.mjs fails the build when
// a new page.tsx appears without a manifest entry.
export const VOICE_MANIFEST_EXCLUDED_ROUTES = ['/login', '/register']
export { UI_PAGES }

// In-page actions the voice may trigger — the first rung beyond navigation.
// Same whitelist discipline as pages: only what is declared here can run,
// and executeUiAction re-validates before acting. Curated low-risk set only
// (nothing destructive, nothing that changes settings).
const UI_ACTIONS: { id: string; label: string; argument?: string }[] = [
  {
    id: 'new_chat',
    label: 'สร้างแชทใหม่ / เริ่มแชทใหม่ / คุยเรื่องใหม่ (new chat)',
  },
  {
    id: 'open_kb',
    label: 'เปิดคลังความรู้ (knowledge base) ตามชื่อ',
    argument: 'ชื่อ KB ตามที่ปรากฏบนจอหรือที่ผู้ใช้พูด',
  },
  {
    id: 'go_back',
    label: 'ย้อนกลับหน้าก่อนหน้า (back)',
  },
  { id: 'scroll_down', label: 'เลื่อนหน้าจอลง (scroll down)' },
  { id: 'scroll_up', label: 'เลื่อนหน้าจอขึ้น (scroll up)' },
  { id: 'scroll_bottom', label: 'เลื่อนไปล่างสุดของหน้า (scroll to bottom)' },
  { id: 'scroll_top', label: 'เลื่อนไปบนสุดของหน้า (scroll to top)' },
]
export { UI_ACTIONS }

const THREE_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js'
const FADE_MS = 500

type MascotState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'searching'

interface MascotHandle {
  setState: (s: MascotState) => void
  lipAttach: (el: HTMLAudioElement) => void
  dispose: () => void
}

let threePromise: Promise<any> | null = null
function loadThree(): Promise<any> {
  const w = window as any
  if (w.THREE) return Promise.resolve(w.THREE)
  if (!threePromise) {
    threePromise = new Promise((resolve, reject) => {
      const s = document.createElement('script')
      s.src = THREE_CDN
      s.async = true
      s.onload = () => resolve((window as any).THREE)
      s.onerror = () => {
        threePromise = null
        reject(new Error('โหลด three.js ไม่ได้'))
      }
      document.head.appendChild(s)
    })
  }
  return threePromise
}

/** Build the 3D mascot on `canvas` (ported from the prototype call page). */
function initMascot(THREE: any, canvas: HTMLCanvasElement): MascotHandle {
  const V3 = (x: number, y: number, z: number) => new THREE.Vector3(x, y, z)
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.setClearColor(0x000000, 0) // transparent — mascot floats over the page
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFSoftShadowMap

  const scene = new THREE.Scene() // no background / fog / floor: widget layer
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100)
  camera.position.set(0, 1.75, 6.4)
  camera.lookAt(0, 1.3, 0)

  scene.add(new THREE.HemisphereLight(0x9fc0ff, 0x0a1730, 0.7))
  const key = new THREE.DirectionalLight(0xfff0d8, 1.0)
  key.position.set(3.5, 6.5, 4.5)
  key.castShadow = true
  scene.add(key)
  const fill = new THREE.DirectionalLight(0x6fa0ff, 0.45)
  fill.position.set(-5, 3, 2)
  scene.add(fill)
  const rim = new THREE.DirectionalLight(0x4f8fff, 0.55)
  rim.position.set(0, 3, -5)
  scene.add(rim)
  const front = new THREE.PointLight(0xffffff, 0.3, 30)
  front.position.set(0, 2.2, 4.5)
  scene.add(front)

  const M = (color: number, o: any = {}) =>
    new THREE.MeshStandardMaterial(Object.assign({ color, roughness: 0.7 }, o))
  const mat = {
    orange: M(0xef7f24, { roughness: 0.5 }),
    cream: M(0xf2cea6, { roughness: 0.6 }),
    blue: M(0x2f6fd0, { roughness: 0.4 }),
    blueDk: M(0x2356a8, { roughness: 0.45 }),
    blueLt: M(0x77abf0, { roughness: 0.25, metalness: 0.2 }),
    suit: M(0x717a86, { roughness: 0.68 }),
    suitDk: M(0x565d68, { roughness: 0.78 }),
    lapel: M(0x6c757f, { roughness: 0.66, side: THREE.DoubleSide }),
    shirt: M(0xeef1f4, { roughness: 0.6, side: THREE.DoubleSide }),
    white: M(0xeef1f4, { roughness: 0.6 }),
    tie: M(0x274a96, { roughness: 0.45 }),
    gold: M(0xd9a93a, { metalness: 0.6, roughness: 0.22 }),
    dark: M(0x262b34, { roughness: 0.5 }),
    hi: M(0xffffff, { roughness: 0.3 }),
    mouth: M(0x4a1f27, { roughness: 0.6 }),
    cheek: M(0xe89274, { roughness: 0.6, transparent: true, opacity: 0.5 }),
  }
  function mesh(geo: any, m: any, p = [0, 0, 0], r = [0, 0, 0]) {
    const e = new THREE.Mesh(geo, m)
    e.position.set(p[0], p[1], p[2])
    e.rotation.set(r[0], r[1], r[2])
    e.castShadow = true
    e.receiveShadow = true
    return e
  }
  function tube(pts: number[][], radius: number, m: any) {
    const curve = new THREE.CatmullRomCurve3(pts.map(p => V3(p[0], p[1], p[2])))
    const e = new THREE.Mesh(new THREE.TubeGeometry(curve, 56, radius, 12, false), m)
    e.castShadow = true
    return e
  }
  function extrudeShape(pts: number[][], depth: number, m: any, bevel: number) {
    const sh = new THREE.Shape()
    sh.moveTo(pts[0][0], pts[0][1])
    for (let i = 1; i < pts.length; i++) sh.lineTo(pts[i][0], pts[i][1])
    sh.closePath()
    const geo = new THREE.ExtrudeGeometry(sh, {
      depth,
      bevelEnabled: true,
      bevelThickness: bevel,
      bevelSize: bevel,
      bevelSegments: 2,
    })
    return mesh(geo, m)
  }

  const rocker = new THREE.Group()
  scene.add(rocker)
  const figure = new THREE.Group()
  rocker.add(figure)

  ;[-1, 1].forEach(s => {
    figure.add(
      mesh(new THREE.CylinderGeometry(0.17, 0.15, 0.34, 24), mat.suit, [s * 0.18, 0.32, 0])
    )
    figure.add(mesh(new THREE.BoxGeometry(0.02, 0.3, 0.02), mat.suitDk, [s * 0.18, 0.32, 0.15]))
    const sh = new THREE.Group()
    sh.position.set(s * 0.18, 0, 0)
    sh.rotation.y = s * 0.12
    const foot = mesh(new THREE.SphereGeometry(0.155, 30, 22), mat.gold, [0, 0.12, 0.12])
    foot.scale.set(1.08, 0.98, 1.95)
    sh.add(foot)
    const heel = mesh(new THREE.SphereGeometry(0.13, 22, 18), mat.gold, [0, 0.13, -0.07])
    heel.scale.set(1.0, 1.05, 1.0)
    sh.add(heel)
    sh.add(mesh(new THREE.SphereGeometry(0.018, 10, 8), mat.gold, [0, 0.2, 0.16]))
    figure.add(sh)
  })

  const torso = new THREE.Group()
  figure.add(torso)
  const bodyMesh = mesh(new THREE.SphereGeometry(0.42, 40, 30), mat.suit, [0, 0.78, 0])
  bodyMesh.scale.set(1.06, 1.2, 0.86)
  torso.add(bodyMesh)
  torso.add(mesh(new THREE.CylinderGeometry(0.17, 0.19, 0.16, 22), mat.white, [0, 1.16, 0.02]))
  torso.add(
    mesh(new THREE.TorusGeometry(0.21, 0.07, 14, 30), mat.suit, [0, 1.11, 0], [Math.PI / 2, 0, 0])
  )
  const shirt = extrudeShape(
    [
      [-0.12, 0.18],
      [0.12, 0.18],
      [0.0, -0.2],
    ],
    0.03,
    mat.shirt,
    0.01
  )
  shirt.position.set(0, 0.92, 0.3)
  shirt.rotation.x = -0.12
  torso.add(shirt)
  const lapelPts = [
    [0.0, 0.22],
    [0.05, 0.1],
    [0.11, 0.2],
    [0.17, 0.05],
    [0.13, -0.22],
    [0.0, -0.18],
  ]
  const lapR = extrudeShape(lapelPts, 0.05, mat.lapel, 0.012)
  lapR.position.set(0.075, 0.9, 0.31)
  lapR.rotation.set(-0.12, -0.34, 0)
  torso.add(lapR)
  const lapL = extrudeShape(
    lapelPts.map(p => [-p[0], p[1]]),
    0.05,
    mat.lapel,
    0.012
  )
  lapL.position.set(-0.075, 0.9, 0.31)
  lapL.rotation.set(-0.12, 0.34, 0)
  torso.add(lapL)
  ;[-1, 1].forEach(s =>
    torso.add(
      mesh(
        new THREE.BoxGeometry(0.012, 0.4, 0.04),
        mat.suitDk,
        [s * 0.07, 0.9, 0.37],
        [0, 0, -s * 0.06]
      )
    )
  )
  torso.add(mesh(new THREE.BoxGeometry(0.085, 0.085, 0.05), mat.tie, [0, 1.0, 0.42]))
  const blade = mesh(new THREE.CylinderGeometry(0.05, 0.085, 0.33, 4), mat.tie, [0, 0.79, 0.41])
  blade.rotation.y = Math.PI / 4
  torso.add(blade)
  torso.add(mesh(new THREE.SphereGeometry(0.022, 12, 10), mat.dark, [0, 0.55, 0.37]))
  torso.add(
    mesh(new THREE.BoxGeometry(0.07, 0.035, 0.02), mat.white, [-0.2, 0.9, 0.36], [0, 0, 0.12])
  )
  torso.add(mesh(new THREE.ConeGeometry(0.035, 0.06, 4), mat.gold, [0.17, 0.92, 0.4]))

  function arm(side: number) {
    const g = new THREE.Group()
    g.position.set(side * 0.4, 1.0, 0.0)
    const cap = mesh(new THREE.SphereGeometry(0.17, 26, 20), mat.suit, [0, 0, 0])
    cap.scale.set(1, 0.88, 0.95)
    g.add(cap)
    g.add(mesh(new THREE.CylinderGeometry(0.15, 0.115, 0.42, 22), mat.suit, [0, -0.23, 0]))
    g.add(mesh(new THREE.CylinderGeometry(0.13, 0.125, 0.05, 22), mat.suit, [0, -0.44, 0]))
    const glove = mesh(new THREE.SphereGeometry(0.155, 26, 20), mat.blue, [0, -0.51, 0.02])
    glove.scale.set(1, 1.05, 1)
    g.add(glove)
    g.add(mesh(new THREE.SphereGeometry(0.06, 16, 12), mat.blue, [side * -0.1, -0.47, 0.09]))
    g.rotation.z = side * 0.11
    torso.add(g)
    return g
  }
  const armL = arm(-1)
  const armR = arm(1)

  const head = new THREE.Group()
  head.position.set(0, 1.86, 0)
  figure.add(head)
  const shell = mesh(new THREE.SphereGeometry(0.62, 46, 36), mat.orange)
  shell.scale.set(1.0, 0.99, 0.9)
  head.add(shell)
  const facePanel = mesh(new THREE.SphereGeometry(0.45, 42, 32), mat.cream, [0, -0.02, 0.33])
  facePanel.scale.set(0.94, 1.0, 0.52)
  head.add(facePanel)
  function eye(side: number) {
    const g = new THREE.Group()
    g.position.set(side * 0.19, 0.05, 0.5)
    const e = mesh(new THREE.SphereGeometry(0.12, 30, 24), mat.dark)
    e.scale.set(0.82, 1.3, 0.8)
    g.add(e)
    g.add(mesh(new THREE.SphereGeometry(0.032, 14, 12), mat.hi, [side * 0.04, 0.07, 0.09]))
    g.add(mesh(new THREE.SphereGeometry(0.016, 12, 10), mat.hi, [-side * 0.03, -0.03, 0.1]))
    head.add(g)
    return g
  }
  const eyeL = eye(-1)
  const eyeR = eye(1)
  ;[-1, 1].forEach(s => {
    const ch = mesh(new THREE.SphereGeometry(0.075, 18, 14), mat.cheek, [s * 0.27, -0.06, 0.46])
    ch.scale.set(1, 0.7, 0.4)
    head.add(ch)
  })
  const mouth = mesh(new THREE.SphereGeometry(0.08, 28, 22), mat.mouth, [0, -0.23, 0.52])
  head.add(mouth)
  const arcF = [
    [-0.43, 0.28, 0.3],
    [-0.24, 0.37, 0.45],
    [0, 0.4, 0.49],
    [0.24, 0.37, 0.45],
    [0.43, 0.28, 0.3],
  ]
  head.add(tube(arcF, 0.075, mat.blue))
  head.add(
    tube(
      arcF.map(([x, y, z]) => [x, y + 0.005, z + 0.035]),
      0.04,
      mat.blueLt
    )
  )
  ;[-1, 1].forEach(s =>
    head.add(mesh(new THREE.SphereGeometry(0.085, 18, 14), mat.blue, [s * 0.43, 0.28, 0.3]))
  )
  head.add(
    tube(
      [
        [-0.43, 0.28, 0.3],
        [-0.55, 0.3, -0.05],
        [-0.34, 0.4, -0.45],
        [0, 0.44, -0.55],
        [0.34, 0.4, -0.45],
        [0.55, 0.3, -0.05],
        [0.43, 0.28, 0.3],
      ],
      0.045,
      mat.blueDk
    )
  )
  ;[-1, 1].forEach(s => {
    head.add(
      mesh(
        new THREE.CylinderGeometry(0.17, 0.17, 0.16, 30),
        mat.orange,
        [s * 0.6, -0.02, 0],
        [0, 0, Math.PI / 2]
      )
    )
    head.add(
      mesh(
        new THREE.TorusGeometry(0.12, 0.05, 14, 26),
        mat.dark,
        [s * 0.69, -0.02, 0],
        [0, Math.PI / 2, 0]
      )
    )
    head.add(
      mesh(
        new THREE.CylinderGeometry(0.075, 0.075, 0.04, 22),
        mat.suitDk,
        [s * 0.71, -0.02, 0],
        [0, 0, Math.PI / 2]
      )
    )
  })
  head.add(
    tube(
      [
        [-0.6, 0.0, -0.02],
        [-0.45, 0.5, -0.06],
        [0, 0.66, -0.06],
        [0.45, 0.5, -0.06],
        [0.6, 0.0, -0.02],
      ],
      0.05,
      mat.suitDk
    )
  )
  head.add(
    tube(
      [
        [-0.62, -0.02, 0.06],
        [-0.5, -0.16, 0.42],
        [-0.25, -0.23, 0.55],
        [-0.08, -0.24, 0.57],
      ],
      0.02,
      mat.dark
    )
  )
  head.add(mesh(new THREE.SphereGeometry(0.045, 16, 12), mat.blue, [-0.06, -0.24, 0.58]))

  // ── state + lip-sync ──
  let mascotState: MascotState = 'idle'
  let mouthOpen = 0
  const STATE_RIM: Record<MascotState, number> = {
    idle: 0x4f8fff,
    listening: 0x37d67a,
    thinking: 0xe0a53a,
    speaking: 0x59c2ff,
    searching: 0xa855f7,
  }
  const rimTarget = new THREE.Color(STATE_RIM.idle)

  let lipCtx: AudioContext | null = null
  let lipAnalyser: AnalyserNode | null = null
  let lipData: Uint8Array<ArrayBuffer> | null = null
  function lipAttach(el: HTMLAudioElement) {
    try {
      if (!lipCtx) {
        lipCtx = new AudioContext()
        lipAnalyser = lipCtx.createAnalyser()
        lipAnalyser.fftSize = 256
        lipData = new Uint8Array(lipAnalyser.fftSize)
        lipAnalyser.connect(lipCtx.destination)
      }
      if (lipCtx.state === 'suspended') void lipCtx.resume()
      lipCtx.createMediaElementSource(el).connect(lipAnalyser!)
    } catch {
      /* element still plays to the default output if capture fails */
    }
  }
  function mouthFromAudio(): number {
    if (!lipAnalyser || !lipData) return 0
    lipAnalyser.getByteTimeDomainData(lipData)
    let s = 0
    for (const v of lipData) {
      const x = (v - 128) / 128
      s += x * x
    }
    return Math.min(1, Math.sqrt(s / lipData.length) * 3.4)
  }

  const clock = new THREE.Clock()
  let nextBlink = 2
  let blinkAt = -1
  let yaw = 0.3
  let targetYaw = 0.3
  let raf = 0
  let disposed = false
  function animate() {
    if (disposed) return
    raf = requestAnimationFrame(animate)
    const t = clock.getElapsedTime()
    rocker.rotation.z = Math.sin(t * 1.0) * 0.06
    rocker.rotation.x = Math.sin(t * 0.85 + 0.5) * 0.025
    rocker.position.y = Math.abs(Math.sin(t * 1.0)) * 0.02
    torso.scale.set(1, 1 + Math.sin(t * 1.7) * 0.012, 1)
    const perk = mascotState === 'listening' ? 0.1 : mascotState === 'thinking' ? -0.05 : 0
    const tilt = mascotState === 'thinking' ? 0.18 : 0
    head.rotation.z = -Math.sin(t * 1.0) * 0.04 + tilt
    head.rotation.y = Math.sin(t * 0.45) * 0.16
    head.rotation.x = Math.sin(t * 0.9) * 0.03 - perk
    armL.rotation.x = Math.sin(t * 1.0 + Math.PI) * 0.08
    armR.rotation.x = Math.sin(t * 1.0) * 0.08

    let es = 1
    if (t > nextBlink && blinkAt < 0) {
      blinkAt = t
      nextBlink = t + 2.5 + Math.random() * 3.5
    }
    if (blinkAt >= 0) {
      const p = (t - blinkAt) / 0.16
      if (p >= 1) blinkAt = -1
      else es = 1 - Math.sin(p * Math.PI)
    }
    eyeL.scale.y = eyeR.scale.y = Math.max(0.05, es)

    let target = 0
    if (mascotState === 'speaking') target = mouthFromAudio()
    else if (mascotState === 'listening') target = 0.05
    mouthOpen += (target - mouthOpen) * 0.35
    mouth.scale.set(1.5 - mouthOpen * 0.4, 0.4 + mouthOpen * 1.9, 0.9)

    rim.color.lerp(rimTarget, 0.06)
    if (mascotState === 'searching') {
      targetYaw += 0.045 // spin = "searching" signal
    } else {
      // No idle drift: settle back to facing the user (nearest full turn,
      // so a post-search return never unwinds several revolutions).
      const TWO_PI = Math.PI * 2
      const home = 0.3 + TWO_PI * Math.round((targetYaw - 0.3) / TWO_PI)
      targetYaw += (home - targetYaw) * 0.04
    }
    yaw += (targetYaw - yaw) * 0.08
    figure.rotation.y = yaw
    renderer.render(scene, camera)
  }
  function resize() {
    const w = canvas.clientWidth || canvas.parentElement?.clientWidth || innerWidth
    const h = canvas.clientHeight || canvas.parentElement?.clientHeight || innerHeight
    camera.aspect = w / h
    camera.updateProjectionMatrix()
    renderer.setSize(w, h, false)
  }
  window.addEventListener('resize', resize)
  resize()
  animate()

  return {
    setState: (s: MascotState) => {
      mascotState = s
      if (STATE_RIM[s] !== undefined) rimTarget.setHex(STATE_RIM[s])
    },
    lipAttach,
    dispose: () => {
      disposed = true
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
      if (lipCtx) void lipCtx.close()
      renderer.dispose()
    },
  }
}

interface LogMsg {
  who: 'user' | 'bot' | 'sys'
  text: string
}

export default function VoiceCallWidget() {
  const router = useRouter()
  const [mounted, setMounted] = useState(false) // overlay in the DOM
  const [visible, setVisible] = useState(false) // fade state (opacity)
  const [status, setStatus] = useState('กำลังเชื่อมต่อ…')
  const [log, setLog] = useState<LogMsg[]>([])
  const [typed, setTyped] = useState('')
  // Secretary (dictation) mode — server-owned; mirrored here for the
  // always-visible indicator (a moded UI must show its mode: Dragon lesson).
  const [secretary, setSecretary] = useState(false)
  // Mic mute — lets the caller type-test without ambient noise leaking into STT.
  // The recognition callbacks read the ref (no stale closure); state drives the UI.
  const [micMuted, setMicMuted] = useState(false)
  const micMutedRef = useRef(false)
  // Mic permission denied (or blocked, e.g. an embedded pane): recognition emits
  // `not-allowed` and onend would restart it forever — a tight loop that floods
  // the console. Latch it to stop retrying; the caller can still type.
  const micDeniedRef = useRef(false)

  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const mascotRef = useRef<MascotHandle | null>(null)
  const panelRef = useRef<HTMLDivElement | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const agentBridgeRef = useRef<PageAgentBridge | null>(null)
  const recogRef = useRef<any>(null)
  const playingRef = useRef(false)
  const muteUntilRef = useRef(0)
  const playerRef = useRef<HTMLAudioElement | null>(null)
  const queueRef = useRef<Blob[]>([])
  const pendingMetaRef = useRef<any>(null)
  const runningRef = useRef(false)
  // Echo fingerprint: everything the bot spoke recently — a "user" utterance
  // matching it is the mic hearing our own TTS, not the caller.
  const botTextsRef = useRef<string[]>([])
  const restartTimerRef = useRef<number | null>(null)

  const rememberBotText = useCallback((text: string) => {
    if (!text) return
    botTextsRef.current = [...botTextsRef.current.slice(-11), text]
  }, [])

  const isEchoOfBot = useCallback((heard: string) => {
    const norm = (s: string) => s.toLowerCase().replace(/[\s.,!?…ๆฯ"'`-]/g, '')
    const h = norm(heard)
    if (h.length < 3) return false
    const spoken = norm(botTextsRef.current.join(''))
    return spoken.includes(h)
  }, [])

  const addMsg = useCallback((who: LogMsg['who'], text: string) => {
    setLog(l => [...l.slice(-19), { who, text }])
  }, [])

  const setMascot = useCallback((s: MascotState) => {
    mascotRef.current?.setState(s)
  }, [])

  // Post-action verify (the grounding design's "Verify (after)"): every
  // outcome — landed or not — is reported to the server as a
  // `ui_action_result` frame, so the turn ladder / future agentic loop can
  // trust that a step finished before taking the next. Failures also surface
  // in the widget log.
  const reportActionResult = useCallback(
    (target: string, field: string, verdict: UiActionVerdict, argument = '') => {
      if (!verdict.ok) {
        addMsg('sys', `⚠ ตรวจผลแล้วยังไม่สำเร็จ: ${target}${field ? ` (${field})` : ''}`)
      }
      if (wsRef.current?.readyState === 1) {
        wsRef.current.send(
          JSON.stringify({
            type: 'ui_action_result',
            result: { target, field, argument, ok: verdict.ok, detail: verdict.detail },
          })
        )
      }
    },
    [addMsg]
  )

  // Execute a voice-driven UI action — only targets we declared in the
  // manifest are honoured, everything else is reported and ignored.
  const executeUiAction = useCallback(
    (m: any) => {
      const target = String(m.target || '')
      const argument = String(m.argument || '')
      const page = UI_PAGES.find(p => p.id === target)
      if (page) {
        addMsg('sys', `🖱 ไปหน้า ${page.label}`)
        router.push(page.path)
        // The poll IS the page-load wait (never a fixed sleep).
        void verifyPath(page.path).then(v => reportActionResult(target, '', v))
        return
      }
      switch (target) {
        case 'open_path': {
          // Website Graph navigation: a path (possibly a sub-page like
          // /settings/appearance) instead of a page id. Whitelist discipline
          // holds — only paths under a declared UI_PAGES page are honoured.
          const allowed = UI_PAGES.some(
            p => argument === p.path || argument.startsWith(p.path + '/')
          )
          if (!allowed || !argument.startsWith('/')) {
            addMsg('sys', `⚠ เส้นทางไม่อยู่ในรายการ: ${argument}`)
            reportActionResult(target, '', { ok: false, detail: 'path_not_allowed' }, argument)
            return
          }
          addMsg('sys', `🖱 เปิด ${argument}`)
          router.push(argument)
          // The verified arrival is what releases the parked follow-up step
          // on the server — the poll IS the page-load wait.
          void verifyPath(argument).then(v => reportActionResult(target, '', v, argument))
          return
        }
        case 'click_index': {
          // Deep rung: the server's LLM picked an element by scan INDEX —
          // the live ref from the last ui_scan, verified still mounted.
          const label = String(m.label || '')
          void (async () => {
            const el = findScannedElement(parseInt(argument, 10))
            if (!el) {
              addMsg('sys', `⚠ เป้าจากการสแกนหายไปแล้ว (${label || argument})`)
              reportActionResult(target, '', { ok: false, detail: 'scan_target_gone' }, argument)
              return
            }
            await pointAt(el)
            clickPulse()
            el.click()
            addMsg('sys', `🖱 กด ${label || `รายการที่ ${argument}`}`)
          })()
          return
        }
        case 'click_element': {
          // Click-by-name: press the visible element whose text the caller
          // named (server already verified it against the streamed context —
          // or, for a cross-page graph step, against the curated graph).
          // The find POLLS briefly: right after a navigation the control may
          // not be mounted yet. The simulator cursor glides onto the target
          // first, so the caller sees WHERE the agent is pressing.
          void (async () => {
            const el = argument
              ? await findWithPoll(() => findClickableByText(argument, panelRef.current))
              : null
            if (!el) {
              addMsg('sys', `⚠ หาปุ่ม "${argument}" บนจอไม่เจอแล้ว`)
              reportActionResult(target, '', { ok: false, detail: 'element_not_found' }, argument)
              return
            }
            await pointAt(el)
            clickPulse()
            el.click()
            addMsg('sys', `🖱 กดปุ่ม ${argument}`)
          })()
          return
        }
        case 'scroll_down':
        case 'scroll_up':
        case 'scroll_bottom':
        case 'scroll_top': {
          if (!scrollByVoice(target, panelRef.current)) {
            addMsg('sys', '⚠ หน้านี้ไม่มีส่วนที่เลื่อนได้')
          }
          return
        }
        case 'fill_field': {
          // Fill-by-voice: type the caller's value into the visible field the
          // server resolved (against the streamed context). Nothing submits.
          // After typing, VERIFY the value actually stuck (a controlled input
          // can revert a native-setter write on re-render) — retry the write
          // once on failure, then report the verdict either way.
          const field = String(m.field || '')
          void (async () => {
            const fieldEl =
              field && argument
                ? await findWithPoll(() => findFieldElement(field, panelRef.current))
                : null
            if (fieldEl) {
              await pointAt(fieldEl)
              clickPulse()
              let written = fillFieldByVoice(field, argument, panelRef.current)
              if (written !== null) glowField(fieldEl, 'pulse') // soft shimmer while it fills
              addMsg(
                'sys',
                written !== null
                  ? `⌨️ พิมพ์ "${argument}" ในช่อง ${field}`
                  : `⚠ พิมพ์ลงช่อง "${field}" ไม่ได้`
              )
              if (written === null) {
                reportActionResult(target, field, { ok: false, detail: 'set_failed' })
                return
              }
              let verdict = await verifyFieldValue(field, written, panelRef.current)
              if (!verdict.ok) {
                written = fillFieldByVoice(field, argument, panelRef.current) // retry once
                verdict =
                  written === null
                    ? { ok: false, detail: 'set_failed_on_retry' }
                    : await verifyFieldValue(field, written, panelRef.current)
              }
              reportActionResult(target, field, verdict)
            } else {
              addMsg('sys', `⚠ หาช่อง "${field}" บนจอไม่เจอแล้ว`)
              reportActionResult(target, field, { ok: false, detail: 'field_not_found' })
            }
          })()
          return
        }
        case 'focus_field': {
          // "กดที่ช่อง X" — place the caret in the named field (no typing).
          // The find polls briefly (late mounts after navigation).
          const field = String(m.field || '')
          void (async () => {
            const focusEl = field
              ? await findWithPoll(() => findFieldElement(field, panelRef.current))
              : null
            if (focusEl) {
              await pointAt(focusEl)
              clickPulse()
              glowField(focusEl, 'flash') // a shimmer on the locked field
              focusEl.focus?.()
              focusEl.click?.()
              addMsg('sys', `🎯 โฟกัสช่อง ${field}`)
              reportActionResult(target, field, await verifyFieldFocused(field, panelRef.current))
            } else {
              addMsg('sys', `⚠ หาช่อง "${field}" บนจอไม่เจอแล้ว`)
              reportActionResult(target, field, { ok: false, detail: 'field_not_found' })
            }
          })()
          return
        }
        case 'edit_field': {
          // Correction: clear the field or drop its last word (argument = op).
          const field = String(m.field || '')
          const editEl = field ? findFieldElement(field, panelRef.current) : null
          if (editEl) {
            void (async () => {
              await pointAt(editEl)
              clickPulse()
              // expected = the value the field should now hold ('' is valid
              // for clear — test against null, not truthiness).
              const expected = editFieldByVoice(field, argument, panelRef.current)
              if (expected !== null) glowField(editEl, 'pulse')
              addMsg(
                'sys',
                expected === null
                  ? `⚠ แก้ข้อความในช่อง "${field}" ไม่ได้`
                  : argument === 'clear'
                    ? `🧹 ล้างช่อง ${field}`
                    : `⌫ ลบคำสุดท้ายในช่อง ${field}`
              )
              reportActionResult(
                target,
                field,
                expected === null
                  ? { ok: false, detail: 'edit_failed' }
                  : await verifyFieldValue(field, expected, panelRef.current)
              )
            })()
          } else {
            addMsg('sys', `⚠ แก้ข้อความในช่อง "${field}" ไม่ได้`)
            reportActionResult(target, field, { ok: false, detail: 'field_not_found' })
          }
          return
        }
        case 'go_back':
          addMsg('sys', '🖱 ย้อนกลับ')
          router.back()
          return
        case 'open_kb':
          addMsg('sys', `🖱 เปิดคลังความรู้${argument ? ` ${argument}` : ''}`)
          router.push(argument ? `/knowledge?kb=${encodeURIComponent(argument)}` : '/knowledge')
          void verifyPath('/knowledge').then(v => reportActionResult(target, '', v))
          return
        case 'type_in_chat': {
          // Secretary mode: hand the utterance to the workspace bridge, which
          // sends it as a real chat message in the current session.
          let typed = false
          const typeDetail: VoiceActionDetail = {
            target,
            argument,
            handled: () => {
              typed = true
            },
          }
          window.dispatchEvent(new CustomEvent(VOICE_ACTION_EVENT, { detail: typeDetail }))
          if (typed) {
            addMsg('sys', `⌨️ ${argument}`)
          } else {
            // No bridge on this page (outside the workspace) — take the
            // caller to the chat; the next dictated sentence will land.
            addMsg('sys', '⚠ พิมพ์ได้เฉพาะหน้าแชท — กำลังพาไปหน้าแชท พูดใหม่อีกครั้งครับ')
            router.push('/home')
          }
          return
        }
        case 'new_chat': {
          // Workspace pages own the session store — hand over via the bridge;
          // elsewhere a plain /home visit already starts a fresh draft session.
          let handled = false
          const detail: VoiceActionDetail = {
            target,
            argument,
            handled: () => {
              handled = true
            },
          }
          window.dispatchEvent(new CustomEvent(VOICE_ACTION_EVENT, { detail }))
          addMsg('sys', '🖱 สร้างแชทใหม่')
          if (!handled) router.push('/home')
          return
        }
        default:
          addMsg('sys', `⚠ ไม่รู้จักปลายทาง: ${target}`)
      }
    },
    [addMsg, router, reportActionResult]
  )

  const stopPlayback = useCallback(() => {
    queueRef.current = []
    if (playerRef.current) {
      playerRef.current.pause()
      playerRef.current = null
    }
    playingRef.current = false
  }, [])

  // Self-continuing playback chain: `onended` must call the *current* playNext,
  // so the recursion goes through a ref (also keeps the hook deps acyclic).
  const playNextRef = useRef<() => void>(() => {})
  const playNext = useCallback(() => {
    const queue = queueRef.current
    if (!queue.length) {
      playingRef.current = false
      muteUntilRef.current = Date.now() + 800 // echo tail guard
      if (runningRef.current) {
        setStatus('ฟังอยู่…')
        setMascot('listening')
        // Resume recognition after the echo tail (it was aborted at playback start).
        if (restartTimerRef.current) window.clearTimeout(restartTimerRef.current)
        restartTimerRef.current = window.setTimeout(() => {
          if (
            runningRef.current &&
            !playingRef.current &&
            !micMutedRef.current &&
            !micDeniedRef.current
          ) {
            try {
              recogRef.current?.start()
            } catch {
              /* already running */
            }
          }
        }, 800)
      }
      return
    }
    // Kill speech recognition the moment audio starts: Web Speech buffers what
    // it hears during playback and would deliver it *after* the mute window,
    // so a time-guard alone is not enough — abort discards that buffer.
    if (!playingRef.current) {
      try {
        recogRef.current?.abort()
      } catch {
        /* already stopped */
      }
    }
    playingRef.current = true
    setMascot('speaking')
    setStatus('🔊 กำลังพูด')
    const player = new Audio(URL.createObjectURL(queue.shift()!))
    playerRef.current = player
    mascotRef.current?.lipAttach(player)
    player.onended = () => playNextRef.current()
    player.onerror = () => playNextRef.current()
    void player.play().catch(() => playNextRef.current())
  }, [setMascot])
  useEffect(() => {
    playNextRef.current = playNext
  }, [playNext])

  const bargeIn = useCallback(() => {
    if (playingRef.current && wsRef.current?.readyState === 1) {
      stopPlayback()
      wsRef.current.send(JSON.stringify({ type: 'barge' }))
      if (runningRef.current) setMascot('listening')
    }
  }, [setMascot, stopPlayback])

  // Stream what the caller's screen currently shows (read-only outline of the
  // visible DOM, our own panel excluded) so the model can answer "what's on
  // this page" from reality. Sent before every turn — pages change under a
  // live call (voice navigation, the user clicking around).
  const sendUiContext = useCallback(() => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== 1) return
    try {
      const pageName = UI_PAGES.find(p => p.path === window.location.pathname)?.label
      const context = collectPageContext(panelRef.current, pageName)
      // Diagnosis line: what the voice layer can actually SEE right now —
      // a miss with a healthy count is a naming problem; a tiny count is a
      // collection problem; no line at all means the frame never went out.
      addMsg('sys', `📸 อ่านจอ: ${context.buttons.length} ปุ่ม ${context.fields.length} ช่อง`)
      if (context.summary) ws.send(JSON.stringify({ type: 'ui_context', context }))
    } catch {
      /* a context snapshot must never break the call */
    }
  }, [addMsg])

  // Deep-rung reply: the server hit a fast-path miss and asks for the FULL
  // indexed element inventory (no name matching, no buttons budget). Always
  // answer — an empty reply beats letting the server wait out its timeout.
  const sendInventory = useCallback(() => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== 1) return
    let items: InventoryItem[] = []
    try {
      items = scanInventory(panelRef.current)
      addMsg('sys', `🔎 สแกนจอลึก: ${items.length} รายการ`)
    } catch {
      /* scan must never break the call — reply empty below */
    }
    try {
      ws.send(JSON.stringify({ type: 'ui_inventory', inventory: items }))
    } catch {
      /* socket died mid-turn; the server times out honestly */
    }
  }, [addMsg])

  // Staleness guard: pages mutate under a live call (async cards mounting,
  // menus opening). Re-stream the screen context once the DOM settles so the
  // server resolves the NEXT command against reality instead of the last
  // utterance's snapshot. One pending send at a time (no rescheduling — a
  // constantly-animating page must not starve it), ≥1.5s between sends, and
  // mutations inside our own panel don't count (the call log updates
  // constantly while speaking).
  useEffect(() => {
    if (!mounted) return
    let pending: number | null = null
    let lastSent = 0
    const observer = new MutationObserver(mutations => {
      const panel = panelRef.current
      if (panel && mutations.every(m => panel.contains(m.target))) return
      if (pending !== null) return
      pending = window.setTimeout(
        () => {
          pending = null
          lastSent = Date.now()
          sendUiContext()
        },
        Math.max(400, 1500 - (Date.now() - lastSent))
      )
    })
    observer.observe(document.body, { childList: true, subtree: true, characterData: true })
    return () => {
      observer.disconnect()
      if (pending !== null) window.clearTimeout(pending)
    }
  }, [mounted, sendUiContext])

  const sendText = useCallback(
    (raw: string) => {
      const text = raw.trim()
      const ws = wsRef.current
      if (!text || !ws || ws.readyState !== 1) return
      bargeIn()
      addMsg('user', text)
      setMascot('thinking')
      sendUiContext()
      ws.send(JSON.stringify({ type: 'user_text', text }))
    },
    [addMsg, bargeIn, sendUiContext, setMascot]
  )

  const hangUp = useCallback(() => {
    runningRef.current = false
    if (restartTimerRef.current) window.clearTimeout(restartTimerRef.current)
    if (recogRef.current) {
      recogRef.current.onend = null
      recogRef.current.stop()
      recogRef.current = null
    }
    stopPlayback()
    disposeCursor() // the simulator cursor must not outlive its call
    agentBridgeRef.current?.dispose() // nor the agent mask/actuator
    agentBridgeRef.current = null
    wsRef.current?.close()
    wsRef.current = null
    setMascot('idle')
    setSecretary(false) // a mode must never outlive its call
    micMutedRef.current = false
    setMicMuted(false) // next call starts listening
    setVisible(false) // fade out…
    window.setTimeout(() => {
      mascotRef.current?.dispose()
      mascotRef.current = null
      setMounted(false) // …then unmount
      setLog([])
    }, FADE_MS)
  }, [setMascot, stopPlayback])

  // Mic mute toggle — abort recognition immediately on mute (Web Speech buffers
  // audio, so a flag alone would still deliver a late transcript; abort discards
  // the buffer), and resume on un-mute if the call is live and the bot is quiet.
  const toggleMute = useCallback(() => {
    setMicMuted(prev => {
      const next = !prev
      micMutedRef.current = next
      if (next) {
        try {
          recogRef.current?.abort()
        } catch {
          /* already stopped */
        }
        setStatus('🔇 ไมค์ปิด — พิมพ์ทดสอบได้')
      } else if (runningRef.current && !playingRef.current && !micDeniedRef.current) {
        try {
          recogRef.current?.start()
        } catch {
          /* already running */
        }
        setStatus('ฟังอยู่…')
      }
      return next
    })
  }, [])

  const startCall = useCallback(async () => {
    setMounted(true)
    setStatus('กำลังเชื่อมต่อ…')
    runningRef.current = true
    micMutedRef.current = false
    setMicMuted(false)
    micDeniedRef.current = false // fresh call re-attempts the mic
    // Next frame: start the fade-in once the overlay is in the DOM.
    requestAnimationFrame(() => requestAnimationFrame(() => setVisible(true)))

    try {
      const THREE = await loadThree()
      if (!runningRef.current) return
      if (canvasRef.current && !mascotRef.current) {
        mascotRef.current = initMascot(THREE, canvasRef.current)
      }
    } catch (e: any) {
      addMsg('sys', `⚠ ${e.message}`)
    }

    const ws = new WebSocket(wsUrl('/api/v1/voice/ws'))
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws
    // In-page agent eyes/hands (lib/page-actuator): inert until the server's
    // agent loop sends agent_* frames on this same socket.
    agentBridgeRef.current?.dispose()
    agentBridgeRef.current = attachPageAgentBridge(payload => {
      if (wsRef.current?.readyState === 1) wsRef.current.send(JSON.stringify(payload))
    })
    ws.onopen = () => {
      setStatus('ฟังอยู่…')
      setMascot('listening')
      // Declare the steerable pages + curated in-page actions.
      ws.send(
        JSON.stringify({
          type: 'ui_manifest',
          manifest: {
            pages: UI_PAGES.map(({ id, label }) => ({ id, label })),
            actions: UI_ACTIONS,
          },
        })
      )
      sendUiContext() // and what the screen shows right now
    }
    ws.onclose = () => {
      if (runningRef.current) setStatus('การเชื่อมต่อหลุด')
    }
    ws.onerror = () => setStatus('เชื่อมต่อไม่ได้')
    ws.onmessage = ev => {
      if (typeof ev.data !== 'string') {
        const type = pendingMetaRef.current?.content_type || 'audio/wav'
        queueRef.current.push(new Blob([ev.data], { type }))
        pendingMetaRef.current = null
        if (!playingRef.current) playNext()
        return
      }
      const m = JSON.parse(ev.data)
      if (m.type === 'transcript') {
        addMsg('user', m.text)
        setMascot('thinking')
      } else if (m.type === 'audio') {
        pendingMetaRef.current = m
        rememberBotText(String(m.text || '')) // fingerprint source per chunk
      } else if (m.type === 'assistant_text') {
        addMsg('bot', m.text)
        rememberBotText(String(m.text || ''))
      } else if (m.type === 'status') {
        if (m.state) setMascot(m.state)
        if (m.state === 'searching') setStatus('🔎 กำลังค้นข้อมูล…')
        if (m.state === 'thinking') setStatus('🤔 กำลังคิด…')
      } else if (m.type === 'done') {
        if (!playingRef.current && runningRef.current) {
          setStatus('ฟังอยู่…')
          setMascot('listening')
        }
      } else if (m.type === 'agent_note') {
        // In-page agent step transparency: narration/questions, spoken AND
        // visible — audio-only left the widget blank while the loop ran.
        addMsg('sys', `🤖 ${m.text}`)
      } else if (m.type === 'ui_action') executeUiAction(m)
      else if (m.type === 'ui_scan') sendInventory()
      else if (agentBridgeRef.current?.handleFrame(m)) {
        /* agent_* frames handled by the page-actuator bridge */
      } else if (m.type === 'voice_mode') {
        const on = m.mode === 'secretary'
        setSecretary(on)
        // Dictation lands in the chat — make sure the caller is looking at it.
        if (on && !window.location.pathname.startsWith('/home')) {
          addMsg('sys', '🖱 ไปหน้าแชท (โหมดเลขาพิมพ์ลงแชท)')
          router.push('/home')
        }
      } else if (m.type === 'error') addMsg('sys', `⚠ ${m.message}`)
    }

    // Browser STT with the echo mute-guard (see prototype bench).
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (SR) {
      const recog = new SR()
      recogRef.current = recog
      recog.lang = 'th-TH'
      recog.continuous = true
      recog.interimResults = true
      recog.maxAlternatives = 3 // runner-up hypotheses rescue garbled commands
      recog.onresult = (ev: any) => {
        if (playingRef.current || micMutedRef.current || Date.now() < muteUntilRef.current) return
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const result = ev.results[i]
          if (!result.isFinal) continue
          const alternatives = Array.from({ length: result.length }, (_, k) =>
            String(result[k]?.transcript || '')
          )
          const heard = pickUtterance(
            alternatives,
            UI_PAGES.map(p => p.label)
          )
          if (!heard || isEchoOfBot(heard)) continue // our own TTS leaking back in
          sendText(heard)
        }
      }
      recog.onend = () => {
        // Stay silent while the bot speaks, the mic is muted, or permission was
        // denied (restarting on `not-allowed` is an infinite loop); playback-end
        // and un-mute schedule the restart otherwise.
        if (
          runningRef.current &&
          recogRef.current &&
          !playingRef.current &&
          !micMutedRef.current &&
          !micDeniedRef.current
        )
          recog.start()
      }
      recog.onerror = (e: any) => {
        // Permission denied / blocked: stop the restart loop and tell the caller
        // they can still type. Everything else is transient (log it, keep going).
        if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
          if (!micDeniedRef.current) {
            micDeniedRef.current = true
            setStatus('🎤 ไมค์ถูกบล็อก — พิมพ์คุยแทนได้')
            addMsg('sys', '⚠ ไมค์ถูกบล็อก/ไม่ได้รับอนุญาต — พิมพ์คุยแทนได้')
          }
          return
        }
        if (e.error !== 'no-speech') console.warn('speech:', e.error)
      }
      recog.start()
    } else {
      addMsg('sys', '⚠ เบราว์เซอร์นี้ไม่มี Web Speech — พิมพ์คุยแทนได้')
    }
  }, [
    addMsg,
    executeUiAction,
    isEchoOfBot,
    playNext,
    rememberBotText,
    router,
    sendText,
    sendUiContext,
    setMascot,
  ])

  useEffect(() => hangUp, [hangUp]) // teardown on unmount

  return (
    <>
      {/* floating call button */}
      {!mounted && (
        <button
          onClick={() => void startCall()}
          title="โทรคุยกับ DeepTutor"
          aria-label="เริ่มสายสนทนาเสียง"
          style={{
            position: 'fixed',
            right: 24,
            bottom: 24,
            zIndex: 60,
            width: 56,
            height: 56,
            borderRadius: '50%',
            border: 'none',
            cursor: 'pointer',
            background: '#22c55e',
            color: '#fff',
            fontSize: 24,
            boxShadow: '0 4px 18px rgba(34,197,94,.45)',
          }}
        >
          📞
        </button>
      )}

      {/* floating mascot layer — sits over the page at the call-button corner
          (Botnoi-widget style): transparent scene, page stays interactive */}
      {mounted && (
        <div
          ref={panelRef}
          style={{
            position: 'fixed',
            right: 20,
            bottom: 20,
            zIndex: 70,
            width: 330,
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
            opacity: visible ? 1 : 0,
            transform: visible ? 'translateY(0)' : 'translateY(24px)',
            transition: `opacity ${FADE_MS}ms ease, transform ${FADE_MS}ms ease`,
            pointerEvents: visible ? 'auto' : 'none',
          }}
        >
          {/* mascot: transparent canvas, half-size */}
          <div style={{ position: 'relative', height: 240, pointerEvents: 'none' }}>
            <canvas
              ref={canvasRef}
              style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
            />
            <div
              style={{
                position: 'absolute',
                top: 6,
                left: 8,
                display: 'flex',
                gap: 6,
              }}
            >
              <div
                style={{
                  fontSize: 11.5,
                  padding: '3px 10px',
                  borderRadius: 999,
                  background: 'rgba(15,25,50,.75)',
                  border: '1px solid rgba(120,160,240,.3)',
                  color: '#cfe0ff',
                  backdropFilter: 'blur(6px)',
                }}
              >
                {status}
              </div>
              {secretary && (
                <div
                  style={{
                    fontSize: 11.5,
                    padding: '3px 10px',
                    borderRadius: 999,
                    background: 'rgba(120,60,10,.8)',
                    border: '1px solid rgba(250,190,90,.5)',
                    color: '#ffe2b0',
                    backdropFilter: 'blur(6px)',
                  }}
                >
                  📝 โหมดเลขา
                </div>
              )}
            </div>
          </div>

          {/* compact chat/control panel */}
          <div
            style={{
              background: 'rgba(12,18,34,.88)',
              border: '1px solid rgba(120,160,240,.22)',
              borderRadius: 14,
              padding: 10,
              backdropFilter: 'blur(10px)',
              display: 'flex',
              flexDirection: 'column',
              gap: 6,
            }}
          >
            <div
              style={{
                maxHeight: 130,
                overflowY: 'auto',
                display: 'flex',
                flexDirection: 'column',
                gap: 4,
              }}
            >
              {log.map((m, i) => (
                <div
                  key={i}
                  style={{
                    alignSelf:
                      m.who === 'user' ? 'flex-end' : m.who === 'bot' ? 'flex-start' : 'center',
                    background:
                      m.who === 'user'
                        ? 'rgba(37,74,150,.9)'
                        : m.who === 'bot'
                          ? 'rgba(31,41,55,.9)'
                          : 'rgba(90,60,140,.7)',
                    color: '#e8eefb',
                    borderRadius: 9,
                    padding: '5px 10px',
                    fontSize: 12.5,
                    maxWidth: '85%',
                  }}
                >
                  {m.text}
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <input
                value={typed}
                onChange={e => setTyped(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') {
                    sendText(typed)
                    setTyped('')
                  }
                }}
                placeholder="พิมพ์แทรก/ทดสอบโดยไม่ใช้ไมค์…"
                style={{
                  flex: 1,
                  minWidth: 0,
                  padding: '7px 10px',
                  borderRadius: 9,
                  fontSize: 12.5,
                  border: '1px solid rgba(120,160,240,.3)',
                  background: 'rgba(10,20,40,.7)',
                  color: '#dbe7ff',
                }}
              />
              <button
                onClick={toggleMute}
                aria-label={micMuted ? 'เปิดไมค์' : 'ปิดไมค์'}
                aria-pressed={micMuted}
                title={
                  micMuted
                    ? 'ไมค์ปิดอยู่ — กดเพื่อเปิด'
                    : 'ปิดไมค์ (พิมพ์ทดสอบได้โดยไม่มีเสียงรบกวน)'
                }
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: '50%',
                  border: 'none',
                  cursor: 'pointer',
                  background: micMuted ? '#f59e0b' : 'rgba(90,110,160,.55)',
                  color: '#fff',
                  fontSize: 15,
                  flexShrink: 0,
                }}
              >
                {micMuted ? '🔇' : '🎤'}
              </button>
              <button
                onClick={hangUp}
                aria-label="วางสาย"
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: '50%',
                  border: 'none',
                  cursor: 'pointer',
                  background: '#ef4444',
                  color: '#fff',
                  fontSize: 15,
                  flexShrink: 0,
                }}
              >
                ⏹
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
