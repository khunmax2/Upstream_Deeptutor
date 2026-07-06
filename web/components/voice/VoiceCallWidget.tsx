"use client";

// Voice call widget — floating call button + full-screen mascot overlay.
//
// Botnoi-WebAvatar-style presentation over DeepTutor's own realtime voice
// layer: pressing the call button fades the mascot overlay in, hanging up
// fades it out. The call itself is the same protocol as the prototype bench
// (`voice_prototype/static/call.html`): WebSocket `/api/v1/voice/ws` →
// ChatOrchestrator, browser Web-Speech STT with an echo mute-guard, per-
// sentence TTS audio streamed back, lip-sync driven by the real audio
// amplitude. Three.js is loaded from CDN on first open (no bundle dep).
//
// Fork-additive: new file; mounted with a one-line include in the workspace
// layout.

import { useCallback, useEffect, useRef, useState } from "react";
import { wsUrl } from "@/lib/api";

const THREE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js";
const FADE_MS = 500;

type MascotState = "idle" | "listening" | "thinking" | "speaking" | "searching";

interface MascotHandle {
  setState: (s: MascotState) => void;
  lipAttach: (el: HTMLAudioElement) => void;
  dispose: () => void;
}

let threePromise: Promise<any> | null = null;
function loadThree(): Promise<any> {
  const w = window as any;
  if (w.THREE) return Promise.resolve(w.THREE);
  if (!threePromise) {
    threePromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = THREE_CDN;
      s.async = true;
      s.onload = () => resolve((window as any).THREE);
      s.onerror = () => {
        threePromise = null;
        reject(new Error("โหลด three.js ไม่ได้"));
      };
      document.head.appendChild(s);
    });
  }
  return threePromise;
}

/** Build the 3D mascot on `canvas` (ported from the prototype call page). */
function initMascot(THREE: any, canvas: HTMLCanvasElement): MascotHandle {
  const V3 = (x: number, y: number, z: number) => new THREE.Vector3(x, y, z);
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x0e2350, 8, 18);
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
  camera.position.set(0, 1.75, 6.4);
  camera.lookAt(0, 1.3, 0);

  scene.add(new THREE.HemisphereLight(0x9fc0ff, 0x0a1730, 0.7));
  const key = new THREE.DirectionalLight(0xfff0d8, 1.0);
  key.position.set(3.5, 6.5, 4.5);
  key.castShadow = true;
  scene.add(key);
  const fill = new THREE.DirectionalLight(0x6fa0ff, 0.45);
  fill.position.set(-5, 3, 2);
  scene.add(fill);
  const rim = new THREE.DirectionalLight(0x4f8fff, 0.55);
  rim.position.set(0, 3, -5);
  scene.add(rim);
  const front = new THREE.PointLight(0xffffff, 0.3, 30);
  front.position.set(0, 2.2, 4.5);
  scene.add(front);

  const floor = new THREE.Mesh(
    new THREE.CircleGeometry(10, 64),
    new THREE.MeshStandardMaterial({ color: 0x0c1d40, roughness: 1 }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  scene.add(floor);
  const grid = new THREE.GridHelper(20, 40, 0x3a78d0, 0x1c3a66);
  grid.material.transparent = true;
  grid.material.opacity = 0.22;
  grid.position.y = 0.01;
  scene.add(grid);

  const M = (color: number, o: any = {}) =>
    new THREE.MeshStandardMaterial(Object.assign({ color, roughness: 0.7 }, o));
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
  };
  function mesh(geo: any, m: any, p = [0, 0, 0], r = [0, 0, 0]) {
    const e = new THREE.Mesh(geo, m);
    e.position.set(p[0], p[1], p[2]);
    e.rotation.set(r[0], r[1], r[2]);
    e.castShadow = true;
    e.receiveShadow = true;
    return e;
  }
  function tube(pts: number[][], radius: number, m: any) {
    const curve = new THREE.CatmullRomCurve3(pts.map((p) => V3(p[0], p[1], p[2])));
    const e = new THREE.Mesh(new THREE.TubeGeometry(curve, 56, radius, 12, false), m);
    e.castShadow = true;
    return e;
  }
  function extrudeShape(pts: number[][], depth: number, m: any, bevel: number) {
    const sh = new THREE.Shape();
    sh.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) sh.lineTo(pts[i][0], pts[i][1]);
    sh.closePath();
    const geo = new THREE.ExtrudeGeometry(sh, {
      depth,
      bevelEnabled: true,
      bevelThickness: bevel,
      bevelSize: bevel,
      bevelSegments: 2,
    });
    return mesh(geo, m);
  }

  const rocker = new THREE.Group();
  scene.add(rocker);
  const figure = new THREE.Group();
  rocker.add(figure);

  [-1, 1].forEach((s) => {
    figure.add(mesh(new THREE.CylinderGeometry(0.17, 0.15, 0.34, 24), mat.suit, [s * 0.18, 0.32, 0]));
    figure.add(mesh(new THREE.BoxGeometry(0.02, 0.3, 0.02), mat.suitDk, [s * 0.18, 0.32, 0.15]));
    const sh = new THREE.Group();
    sh.position.set(s * 0.18, 0, 0);
    sh.rotation.y = s * 0.12;
    const foot = mesh(new THREE.SphereGeometry(0.155, 30, 22), mat.gold, [0, 0.12, 0.12]);
    foot.scale.set(1.08, 0.98, 1.95);
    sh.add(foot);
    const heel = mesh(new THREE.SphereGeometry(0.13, 22, 18), mat.gold, [0, 0.13, -0.07]);
    heel.scale.set(1.0, 1.05, 1.0);
    sh.add(heel);
    sh.add(mesh(new THREE.SphereGeometry(0.018, 10, 8), mat.gold, [0, 0.2, 0.16]));
    figure.add(sh);
  });

  const torso = new THREE.Group();
  figure.add(torso);
  const bodyMesh = mesh(new THREE.SphereGeometry(0.42, 40, 30), mat.suit, [0, 0.78, 0]);
  bodyMesh.scale.set(1.06, 1.2, 0.86);
  torso.add(bodyMesh);
  torso.add(mesh(new THREE.CylinderGeometry(0.17, 0.19, 0.16, 22), mat.white, [0, 1.16, 0.02]));
  torso.add(mesh(new THREE.TorusGeometry(0.21, 0.07, 14, 30), mat.suit, [0, 1.11, 0], [Math.PI / 2, 0, 0]));
  const shirt = extrudeShape([[-0.12, 0.18], [0.12, 0.18], [0.0, -0.2]], 0.03, mat.shirt, 0.01);
  shirt.position.set(0, 0.92, 0.3);
  shirt.rotation.x = -0.12;
  torso.add(shirt);
  const lapelPts = [[0.0, 0.22], [0.05, 0.1], [0.11, 0.2], [0.17, 0.05], [0.13, -0.22], [0.0, -0.18]];
  const lapR = extrudeShape(lapelPts, 0.05, mat.lapel, 0.012);
  lapR.position.set(0.075, 0.9, 0.31);
  lapR.rotation.set(-0.12, -0.34, 0);
  torso.add(lapR);
  const lapL = extrudeShape(lapelPts.map((p) => [-p[0], p[1]]), 0.05, mat.lapel, 0.012);
  lapL.position.set(-0.075, 0.9, 0.31);
  lapL.rotation.set(-0.12, 0.34, 0);
  torso.add(lapL);
  [-1, 1].forEach((s) =>
    torso.add(mesh(new THREE.BoxGeometry(0.012, 0.4, 0.04), mat.suitDk, [s * 0.07, 0.9, 0.37], [0, 0, -s * 0.06])),
  );
  torso.add(mesh(new THREE.BoxGeometry(0.085, 0.085, 0.05), mat.tie, [0, 1.0, 0.42]));
  const blade = mesh(new THREE.CylinderGeometry(0.05, 0.085, 0.33, 4), mat.tie, [0, 0.79, 0.41]);
  blade.rotation.y = Math.PI / 4;
  torso.add(blade);
  torso.add(mesh(new THREE.SphereGeometry(0.022, 12, 10), mat.dark, [0, 0.55, 0.37]));
  torso.add(mesh(new THREE.BoxGeometry(0.07, 0.035, 0.02), mat.white, [-0.2, 0.9, 0.36], [0, 0, 0.12]));
  torso.add(mesh(new THREE.ConeGeometry(0.035, 0.06, 4), mat.gold, [0.17, 0.92, 0.4]));

  function arm(side: number) {
    const g = new THREE.Group();
    g.position.set(side * 0.4, 1.0, 0.0);
    const cap = mesh(new THREE.SphereGeometry(0.17, 26, 20), mat.suit, [0, 0, 0]);
    cap.scale.set(1, 0.88, 0.95);
    g.add(cap);
    g.add(mesh(new THREE.CylinderGeometry(0.15, 0.115, 0.42, 22), mat.suit, [0, -0.23, 0]));
    g.add(mesh(new THREE.CylinderGeometry(0.13, 0.125, 0.05, 22), mat.suit, [0, -0.44, 0]));
    const glove = mesh(new THREE.SphereGeometry(0.155, 26, 20), mat.blue, [0, -0.51, 0.02]);
    glove.scale.set(1, 1.05, 1);
    g.add(glove);
    g.add(mesh(new THREE.SphereGeometry(0.06, 16, 12), mat.blue, [side * -0.1, -0.47, 0.09]));
    g.rotation.z = side * 0.11;
    torso.add(g);
    return g;
  }
  const armL = arm(-1);
  const armR = arm(1);

  const head = new THREE.Group();
  head.position.set(0, 1.86, 0);
  figure.add(head);
  const shell = mesh(new THREE.SphereGeometry(0.62, 46, 36), mat.orange);
  shell.scale.set(1.0, 0.99, 0.9);
  head.add(shell);
  const facePanel = mesh(new THREE.SphereGeometry(0.45, 42, 32), mat.cream, [0, -0.02, 0.33]);
  facePanel.scale.set(0.94, 1.0, 0.52);
  head.add(facePanel);
  function eye(side: number) {
    const g = new THREE.Group();
    g.position.set(side * 0.19, 0.05, 0.5);
    const e = mesh(new THREE.SphereGeometry(0.12, 30, 24), mat.dark);
    e.scale.set(0.82, 1.3, 0.8);
    g.add(e);
    g.add(mesh(new THREE.SphereGeometry(0.032, 14, 12), mat.hi, [side * 0.04, 0.07, 0.09]));
    g.add(mesh(new THREE.SphereGeometry(0.016, 12, 10), mat.hi, [-side * 0.03, -0.03, 0.1]));
    head.add(g);
    return g;
  }
  const eyeL = eye(-1);
  const eyeR = eye(1);
  [-1, 1].forEach((s) => {
    const ch = mesh(new THREE.SphereGeometry(0.075, 18, 14), mat.cheek, [s * 0.27, -0.06, 0.46]);
    ch.scale.set(1, 0.7, 0.4);
    head.add(ch);
  });
  const mouth = mesh(new THREE.SphereGeometry(0.08, 28, 22), mat.mouth, [0, -0.23, 0.52]);
  head.add(mouth);
  const arcF = [[-0.43, 0.28, 0.3], [-0.24, 0.37, 0.45], [0, 0.4, 0.49], [0.24, 0.37, 0.45], [0.43, 0.28, 0.3]];
  head.add(tube(arcF, 0.075, mat.blue));
  head.add(tube(arcF.map(([x, y, z]) => [x, y + 0.005, z + 0.035]), 0.04, mat.blueLt));
  [-1, 1].forEach((s) => head.add(mesh(new THREE.SphereGeometry(0.085, 18, 14), mat.blue, [s * 0.43, 0.28, 0.3])));
  head.add(
    tube(
      [[-0.43, 0.28, 0.3], [-0.55, 0.3, -0.05], [-0.34, 0.4, -0.45], [0, 0.44, -0.55], [0.34, 0.4, -0.45], [0.55, 0.3, -0.05], [0.43, 0.28, 0.3]],
      0.045,
      mat.blueDk,
    ),
  );
  [-1, 1].forEach((s) => {
    head.add(mesh(new THREE.CylinderGeometry(0.17, 0.17, 0.16, 30), mat.orange, [s * 0.6, -0.02, 0], [0, 0, Math.PI / 2]));
    head.add(mesh(new THREE.TorusGeometry(0.12, 0.05, 14, 26), mat.dark, [s * 0.69, -0.02, 0], [0, Math.PI / 2, 0]));
    head.add(mesh(new THREE.CylinderGeometry(0.075, 0.075, 0.04, 22), mat.suitDk, [s * 0.71, -0.02, 0], [0, 0, Math.PI / 2]));
  });
  head.add(tube([[-0.6, 0.0, -0.02], [-0.45, 0.5, -0.06], [0, 0.66, -0.06], [0.45, 0.5, -0.06], [0.6, 0.0, -0.02]], 0.05, mat.suitDk));
  head.add(tube([[-0.62, -0.02, 0.06], [-0.5, -0.16, 0.42], [-0.25, -0.23, 0.55], [-0.08, -0.24, 0.57]], 0.02, mat.dark));
  head.add(mesh(new THREE.SphereGeometry(0.045, 16, 12), mat.blue, [-0.06, -0.24, 0.58]));

  // ── state + lip-sync ──
  let mascotState: MascotState = "idle";
  let mouthOpen = 0;
  const STATE_RIM: Record<MascotState, number> = {
    idle: 0x4f8fff,
    listening: 0x37d67a,
    thinking: 0xe0a53a,
    speaking: 0x59c2ff,
    searching: 0xa855f7,
  };
  const rimTarget = new THREE.Color(STATE_RIM.idle);

  let lipCtx: AudioContext | null = null;
  let lipAnalyser: AnalyserNode | null = null;
  let lipData: Uint8Array<ArrayBuffer> | null = null;
  function lipAttach(el: HTMLAudioElement) {
    try {
      if (!lipCtx) {
        lipCtx = new AudioContext();
        lipAnalyser = lipCtx.createAnalyser();
        lipAnalyser.fftSize = 256;
        lipData = new Uint8Array(lipAnalyser.fftSize);
        lipAnalyser.connect(lipCtx.destination);
      }
      if (lipCtx.state === "suspended") void lipCtx.resume();
      lipCtx.createMediaElementSource(el).connect(lipAnalyser!);
    } catch {
      /* element still plays to the default output if capture fails */
    }
  }
  function mouthFromAudio(): number {
    if (!lipAnalyser || !lipData) return 0;
    lipAnalyser.getByteTimeDomainData(lipData);
    let s = 0;
    for (const v of lipData) {
      const x = (v - 128) / 128;
      s += x * x;
    }
    return Math.min(1, Math.sqrt(s / lipData.length) * 3.4);
  }

  const clock = new THREE.Clock();
  let nextBlink = 2;
  let blinkAt = -1;
  let yaw = 0.3;
  let targetYaw = 0.3;
  let raf = 0;
  let disposed = false;
  function animate() {
    if (disposed) return;
    raf = requestAnimationFrame(animate);
    const t = clock.getElapsedTime();
    rocker.rotation.z = Math.sin(t * 1.0) * 0.06;
    rocker.rotation.x = Math.sin(t * 0.85 + 0.5) * 0.025;
    rocker.position.y = Math.abs(Math.sin(t * 1.0)) * 0.02;
    torso.scale.set(1, 1 + Math.sin(t * 1.7) * 0.012, 1);
    const perk = mascotState === "listening" ? 0.1 : mascotState === "thinking" ? -0.05 : 0;
    const tilt = mascotState === "thinking" ? 0.18 : 0;
    head.rotation.z = -Math.sin(t * 1.0) * 0.04 + tilt;
    head.rotation.y = Math.sin(t * 0.45) * 0.16;
    head.rotation.x = Math.sin(t * 0.9) * 0.03 - perk;
    armL.rotation.x = Math.sin(t * 1.0 + Math.PI) * 0.08;
    armR.rotation.x = Math.sin(t * 1.0) * 0.08;

    let es = 1;
    if (t > nextBlink && blinkAt < 0) {
      blinkAt = t;
      nextBlink = t + 2.5 + Math.random() * 3.5;
    }
    if (blinkAt >= 0) {
      const p = (t - blinkAt) / 0.16;
      if (p >= 1) blinkAt = -1;
      else es = 1 - Math.sin(p * Math.PI);
    }
    eyeL.scale.y = eyeR.scale.y = Math.max(0.05, es);

    let target = 0;
    if (mascotState === "speaking") target = mouthFromAudio();
    else if (mascotState === "listening") target = 0.05;
    mouthOpen += (target - mouthOpen) * 0.35;
    mouth.scale.set(1.5 - mouthOpen * 0.4, 0.4 + mouthOpen * 1.9, 0.9);

    rim.color.lerp(rimTarget, 0.06);
    targetYaw += (mascotState === "searching" ? 0.045 : 0.0014);
    yaw += (targetYaw - yaw) * 0.08;
    figure.rotation.y = yaw;
    renderer.render(scene, camera);
  }
  function resize() {
    const w = canvas.clientWidth || canvas.parentElement?.clientWidth || innerWidth;
    const h = canvas.clientHeight || canvas.parentElement?.clientHeight || innerHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h, false);
  }
  window.addEventListener("resize", resize);
  resize();
  animate();

  return {
    setState: (s: MascotState) => {
      mascotState = s;
      if (STATE_RIM[s] !== undefined) rimTarget.setHex(STATE_RIM[s]);
    },
    lipAttach,
    dispose: () => {
      disposed = true;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      if (lipCtx) void lipCtx.close();
      renderer.dispose();
    },
  };
}

interface LogMsg {
  who: "user" | "bot" | "sys";
  text: string;
}

export default function VoiceCallWidget() {
  const [mounted, setMounted] = useState(false); // overlay in the DOM
  const [visible, setVisible] = useState(false); // fade state (opacity)
  const [status, setStatus] = useState("กำลังเชื่อมต่อ…");
  const [log, setLog] = useState<LogMsg[]>([]);
  const [typed, setTyped] = useState("");

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const mascotRef = useRef<MascotHandle | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const recogRef = useRef<any>(null);
  const playingRef = useRef(false);
  const muteUntilRef = useRef(0);
  const playerRef = useRef<HTMLAudioElement | null>(null);
  const queueRef = useRef<Blob[]>([]);
  const pendingMetaRef = useRef<any>(null);
  const runningRef = useRef(false);

  const addMsg = useCallback((who: LogMsg["who"], text: string) => {
    setLog((l) => [...l.slice(-19), { who, text }]);
  }, []);

  const setMascot = useCallback((s: MascotState) => {
    mascotRef.current?.setState(s);
  }, []);

  const stopPlayback = useCallback(() => {
    queueRef.current = [];
    if (playerRef.current) {
      playerRef.current.pause();
      playerRef.current = null;
    }
    playingRef.current = false;
  }, []);

  // Self-continuing playback chain: `onended` must call the *current* playNext,
  // so the recursion goes through a ref (also keeps the hook deps acyclic).
  const playNextRef = useRef<() => void>(() => {});
  const playNext = useCallback(() => {
    const queue = queueRef.current;
    if (!queue.length) {
      playingRef.current = false;
      muteUntilRef.current = Date.now() + 800; // echo tail guard
      if (runningRef.current) {
        setStatus("ฟังอยู่…");
        setMascot("listening");
      }
      return;
    }
    playingRef.current = true;
    setMascot("speaking");
    setStatus("🔊 กำลังพูด");
    const player = new Audio(URL.createObjectURL(queue.shift()!));
    playerRef.current = player;
    mascotRef.current?.lipAttach(player);
    player.onended = () => playNextRef.current();
    player.onerror = () => playNextRef.current();
    void player.play().catch(() => playNextRef.current());
  }, [setMascot]);
  useEffect(() => {
    playNextRef.current = playNext;
  }, [playNext]);

  const bargeIn = useCallback(() => {
    if (playingRef.current && wsRef.current?.readyState === 1) {
      stopPlayback();
      wsRef.current.send(JSON.stringify({ type: "barge" }));
      if (runningRef.current) setMascot("listening");
    }
  }, [setMascot, stopPlayback]);

  const sendText = useCallback(
    (raw: string) => {
      const text = raw.trim();
      const ws = wsRef.current;
      if (!text || !ws || ws.readyState !== 1) return;
      bargeIn();
      addMsg("user", text);
      setMascot("thinking");
      ws.send(JSON.stringify({ type: "user_text", text }));
    },
    [addMsg, bargeIn, setMascot],
  );

  const hangUp = useCallback(() => {
    runningRef.current = false;
    if (recogRef.current) {
      recogRef.current.onend = null;
      recogRef.current.stop();
      recogRef.current = null;
    }
    stopPlayback();
    wsRef.current?.close();
    wsRef.current = null;
    setMascot("idle");
    setVisible(false); // fade out…
    window.setTimeout(() => {
      mascotRef.current?.dispose();
      mascotRef.current = null;
      setMounted(false); // …then unmount
      setLog([]);
    }, FADE_MS);
  }, [setMascot, stopPlayback]);

  const startCall = useCallback(async () => {
    setMounted(true);
    setStatus("กำลังเชื่อมต่อ…");
    runningRef.current = true;
    // Next frame: start the fade-in once the overlay is in the DOM.
    requestAnimationFrame(() => requestAnimationFrame(() => setVisible(true)));

    try {
      const THREE = await loadThree();
      if (!runningRef.current) return;
      if (canvasRef.current && !mascotRef.current) {
        mascotRef.current = initMascot(THREE, canvasRef.current);
      }
    } catch (e: any) {
      addMsg("sys", `⚠ ${e.message}`);
    }

    const ws = new WebSocket(wsUrl("/api/v1/voice/ws"));
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    ws.onopen = () => {
      setStatus("ฟังอยู่…");
      setMascot("listening");
    };
    ws.onclose = () => {
      if (runningRef.current) setStatus("การเชื่อมต่อหลุด");
    };
    ws.onerror = () => setStatus("เชื่อมต่อไม่ได้");
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") {
        const type = pendingMetaRef.current?.content_type || "audio/wav";
        queueRef.current.push(new Blob([ev.data], { type }));
        pendingMetaRef.current = null;
        if (!playingRef.current) playNext();
        return;
      }
      const m = JSON.parse(ev.data);
      if (m.type === "transcript") {
        addMsg("user", m.text);
        setMascot("thinking");
      } else if (m.type === "audio") pendingMetaRef.current = m;
      else if (m.type === "assistant_text") addMsg("bot", m.text);
      else if (m.type === "status") {
        if (m.state) setMascot(m.state);
        if (m.state === "searching") setStatus("🔎 กำลังค้นข้อมูล…");
        if (m.state === "thinking") setStatus("🤔 กำลังคิด…");
      } else if (m.type === "done") {
        if (!playingRef.current && runningRef.current) {
          setStatus("ฟังอยู่…");
          setMascot("listening");
        }
      } else if (m.type === "error") addMsg("sys", `⚠ ${m.message}`);
    };

    // Browser STT with the echo mute-guard (see prototype bench).
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (SR) {
      const recog = new SR();
      recogRef.current = recog;
      recog.lang = "th-TH";
      recog.continuous = true;
      recog.interimResults = true;
      recog.onresult = (ev: any) => {
        if (playingRef.current || Date.now() < muteUntilRef.current) return;
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          if (ev.results[i].isFinal) sendText(ev.results[i][0].transcript);
        }
      };
      recog.onend = () => {
        if (runningRef.current && recogRef.current) recog.start();
      };
      recog.onerror = (e: any) => {
        if (e.error !== "no-speech") console.warn("speech:", e.error);
      };
      recog.start();
    } else {
      addMsg("sys", "⚠ เบราว์เซอร์นี้ไม่มี Web Speech — พิมพ์คุยแทนได้");
    }
  }, [addMsg, playNext, sendText, setMascot]);

  useEffect(() => hangUp, [hangUp]); // teardown on unmount

  return (
    <>
      {/* floating call button */}
      {!mounted && (
        <button
          onClick={() => void startCall()}
          title="โทรคุยกับ DeepTutor"
          aria-label="เริ่มสายสนทนาเสียง"
          style={{
            position: "fixed",
            right: 24,
            bottom: 24,
            zIndex: 60,
            width: 56,
            height: 56,
            borderRadius: "50%",
            border: "none",
            cursor: "pointer",
            background: "#22c55e",
            color: "#fff",
            fontSize: 24,
            boxShadow: "0 4px 18px rgba(34,197,94,.45)",
          }}
        >
          📞
        </button>
      )}

      {/* fading mascot overlay */}
      {mounted && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 70,
            background: "linear-gradient(#081530, #143a72)",
            opacity: visible ? 1 : 0,
            transition: `opacity ${FADE_MS}ms ease`,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <canvas ref={canvasRef} style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} />

          <div style={{ position: "absolute", top: 18, left: 22, color: "#dbe7ff", pointerEvents: "none" }}>
            <b style={{ fontSize: 17 }}>☎️ DeepTutor Call</b>
            <div
              style={{
                marginTop: 8,
                fontSize: 12,
                padding: "4px 12px",
                borderRadius: 999,
                background: "rgba(20,40,80,.6)",
                border: "1px solid rgba(120,160,240,.25)",
                display: "inline-block",
              }}
            >
              {status}
            </div>
          </div>

          <div
            style={{
              position: "absolute",
              left: "50%",
              bottom: 22,
              transform: "translateX(-50%)",
              width: "min(620px, 92vw)",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <div style={{ maxHeight: "22vh", overflowY: "auto", display: "flex", flexDirection: "column", gap: 4 }}>
              {log.map((m, i) => (
                <div
                  key={i}
                  style={{
                    alignSelf: m.who === "user" ? "flex-end" : m.who === "bot" ? "flex-start" : "center",
                    background: m.who === "user" ? "rgba(37,74,150,.85)" : m.who === "bot" ? "rgba(31,41,55,.85)" : "rgba(90,60,140,.6)",
                    color: "#e8eefb",
                    borderRadius: 10,
                    padding: "6px 11px",
                    fontSize: 13.5,
                    maxWidth: "82%",
                  }}
                >
                  {m.text}
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    sendText(typed);
                    setTyped("");
                  }
                }}
                placeholder="พิมพ์แทรก/ทดสอบโดยไม่ใช้ไมค์…"
                style={{
                  flex: 1,
                  padding: "9px 12px",
                  borderRadius: 10,
                  border: "1px solid rgba(120,160,240,.3)",
                  background: "rgba(10,20,40,.7)",
                  color: "#dbe7ff",
                }}
              />
              <button
                onClick={hangUp}
                aria-label="วางสาย"
                style={{
                  width: 46,
                  height: 46,
                  borderRadius: "50%",
                  border: "none",
                  cursor: "pointer",
                  background: "#ef4444",
                  color: "#fff",
                  fontSize: 19,
                }}
              >
                ⏹
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
