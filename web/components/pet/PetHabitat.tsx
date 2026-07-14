"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { fetchPetState, type PetState } from "@/lib/pet-api";

/**
 * Anima Habitat — the learning companion, rendered beside the Mastery Path map.
 *
 * The SERVER is authoritative: hunger/happy/exp/level/sick are derived from real
 * `LearningProgress` (mastery gate + lazy decay) by `deeptutor.pet` and pulled
 * here every few seconds. This component NEVER computes those numbers — it is a
 * pure renderer, so the whole UI is a replaceable "mask" over the bridge.
 *
 * Everything the canvas does on its own (wander, bob, walk-to-bowl, motes) is
 * *cosmetic*, triggered by observing deltas between two server states:
 *   exp up / hunger down  -> run to the bowl and eat
 *   level up              -> hop + rising motes
 *   sick true -> false    -> heal sparkle
 */

const POLL_MS = 4000;
const W = 320;
const H = 208;
const TILE = 16;

type Cosmetic = {
  x: number;
  y: number;
  tx: number;
  ty: number;
  dir: number;
  anim: number;
  act: "idle" | "walk" | "seekfood" | "eat";
  actT: number;
  hop: number;
  glow: number;
};

type Mote = { x: number; y: number; life: number; vy: number };

const PAL: Record<string, string | null> = {
  ".": null,
  k: "#1a1636",
  o: "#0d0b22",
  v: "#b98cff",
  V: "#caa6ff",
  c: "#f4ecff",
  e: "#12143a",
  w: "#57e0ff",
  b: "#8a5a3c",
  B: "#a97045",
  g: "#4a3d86",
  p: "#3ecb7a",
  P: "#2ba05e",
  a: "#ffcf6b",
  y: "#ffe6a6",
  n: "#5a4a86",
  N: "#7a68a8",
  q: "#57e0ff",
  Q: "#2a6bd6",
};

const PET_SPRITE = [
  "....oooo....",
  "..oovvvvoo..",
  ".ovVVVVVVo..",
  ".ovVeweVwo..",
  ".ovVeweVwo..",
  ".ovVVVVVVo..",
  ".ovccccccvo.",
  ".ovccVVccvo.",
  "..ovccccvo..",
  "...ovccvo...",
  "..o.ovvo.o..",
  "..o......o..",
];
const BOOKSHELF = [
  "gggggggggg",
  "gBbBbBbBBg",
  "gggggggggg",
  "gBBbBbBbBg",
  "gggggggggg",
];
const NEST = [
  "..nNNNNn..",
  ".nNnnnnNn.",
  "nNnnnnnnNn",
  "nNnnnnnnNn",
  ".nNnnnnNn.",
  "..nNNNNn..",
];
const BOWL = ["........", "..aaaa..", ".ayyyya.", "aayyyyaa", ".aaaaaa."];
const PLANT = ["..pp..", ".pPPp.", "pPppPp", ".pPPp.", "..bb..", "..bb.."];
const PORTAL = [
  "..QQQQ..",
  ".QqqqqQ.",
  "QqQQQQqQ",
  "QqQwwQqQ",
  "QqQQQQqQ",
  ".QqqqqQ.",
  "..QQQQ..",
];

const BOWL_SPOT = { tx: 16, ty: 11 };
const FURNITURE: { rows: string[]; x: number; y: number; s: number }[] = [
  { rows: BOOKSHELF, x: 1, y: 1, s: 2 },
  { rows: PORTAL, x: 16, y: 1, s: 2 },
  { rows: NEST, x: 1, y: 9, s: 2 },
  { rows: BOWL, x: 15, y: 10, s: 2 },
  { rows: PLANT, x: 9, y: 1, s: 2 },
  { rows: PLANT, x: 12, y: 11, s: 2 },
];

function drawSprite(
  ctx: CanvasRenderingContext2D,
  rows: string[],
  px: number,
  py: number,
  s: number,
) {
  for (let y = 0; y < rows.length; y++) {
    const row = rows[y];
    for (let x = 0; x < row.length; x++) {
      const color = PAL[row[x]];
      if (!color) continue;
      ctx.fillStyle = color;
      ctx.fillRect(px + x * s, py + y * s, s, s);
    }
  }
}

export default function PetHabitat({
  pathId,
  tr,
}: {
  pathId: string;
  tr: (cn: string, en: string) => string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [state, setState] = useState<PetState | null>(null);
  const [failed, setFailed] = useState(false);

  // Latest server state, readable from the animation loop without restarting it.
  const stateRef = useRef<PetState | null>(null);
  const prevRef = useRef<PetState | null>(null);
  const cosmeticRef = useRef<Cosmetic>({
    x: W / 2,
    y: H / 2,
    tx: W / 2,
    ty: H / 2,
    dir: 1,
    anim: 0,
    act: "idle",
    actT: 0,
    hop: 0,
    glow: 0.6,
  });
  const motesRef = useRef<Mote[]>([]);

  /** Observe a new server state and fire the cosmetic reactions it implies. */
  const onServerState = useCallback((next: PetState) => {
    const prev = prevRef.current;
    const pet = cosmeticRef.current;

    if (prev) {
      const fed = next.exp > prev.exp || next.hunger < prev.hunger - 0.5;
      if (fed) {
        pet.tx = BOWL_SPOT.tx * TILE;
        pet.ty = BOWL_SPOT.ty * TILE;
        pet.act = "seekfood";
        pet.actT = 0;
      }
      const leveled = next.level > prev.level;
      const healed = prev.sick && !next.sick;
      if (leveled || healed) {
        pet.hop = 1;
        for (let i = 0; i < 10; i++) {
          motesRef.current.push({
            x: pet.x + (Math.random() * 20 - 10),
            y: pet.y,
            life: 1,
            vy: 20 + Math.random() * 20,
          });
        }
      }
    }

    prevRef.current = next;
    stateRef.current = next;
    setState(next);
    setFailed(false);
  }, []);

  // --- poll the bridge (the only source of truth) ---------------------------
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await fetchPetState(pathId);
        if (!cancelled) onServerState(next);
      } catch {
        if (!cancelled) setFailed(true);
      }
    };
    poll();
    const id = window.setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [pathId, onServerState]);

  // --- cosmetic render loop -------------------------------------------------
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.imageSmoothingEnabled = false;

    let raf = 0;
    let last = performance.now();

    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const pet = cosmeticRef.current;
      const server = stateRef.current;
      const sick = server?.sick ?? false;
      const hunger = server?.hunger ?? 0;
      const happy = server?.happy ?? 80;

      // wander AI (cosmetic only — never touches server numbers)
      const dx = pet.tx - pet.x;
      const dy = pet.ty - pet.y;
      const dist = Math.hypot(dx, dy);
      if (dist > 2) {
        if (pet.act === "idle") pet.act = "walk";
        const speed = 22 * (pet.act === "seekfood" ? 1.5 : 1);
        pet.x += (dx / dist) * speed * dt;
        pet.y += (dy / dist) * speed * dt;
        if (Math.abs(dx) > 1) pet.dir = dx > 0 ? 1 : -1;
        pet.anim += dt;
      } else {
        if (pet.act === "seekfood") {
          pet.act = "eat";
          pet.actT = 0;
        } else if (pet.act === "walk") {
          pet.act = "idle";
        }
        pet.anim += dt * 0.5;
      }
      pet.actT += dt;
      if (pet.act === "eat" && pet.actT > 1.1) {
        pet.act = "idle";
        pet.hop = 1;
        pet.actT = 0;
      }
      if (pet.act === "idle" && pet.actT > 1.6 + Math.random() * 2) {
        pet.tx = 40 + Math.random() * (W - 80);
        pet.ty = 44 + Math.random() * (H - 80);
        pet.act = "walk";
        pet.actT = 0;
      }
      // a hungry pet drifts toward the bowl on its own
      if (hunger > 70 && pet.act === "idle" && Math.random() < 0.01) {
        pet.tx = BOWL_SPOT.tx * TILE;
        pet.ty = BOWL_SPOT.ty * TILE;
      }

      // floor
      const cols = W / TILE;
      const rows = H / TILE;
      for (let y = 0; y < rows; y++) {
        for (let x = 0; x < cols; x++) {
          const edge = x === 0 || y === 0 || x === cols - 1 || y === rows - 1;
          ctx.fillStyle = edge
            ? y === 0
              ? "#4a3d86"
              : "#3a2f6b"
            : (x + y) % 2
              ? "#23244f"
              : "#282a58";
          ctx.fillRect(x * TILE, y * TILE, TILE, TILE);
        }
      }
      const rug = ctx.createRadialGradient(W / 2, H / 2, 10, W / 2, H / 2, 120);
      rug.addColorStop(0, "rgba(87,224,255,.06)");
      rug.addColorStop(1, "transparent");
      ctx.fillStyle = rug;
      ctx.fillRect(0, 0, W, H);

      // furniture
      for (const f of FURNITURE) {
        drawSprite(ctx, f.rows, f.x * TILE, f.y * TILE, f.s);
      }

      // pet glow — mood comes from SERVER happy/sick
      pet.glow += ((sick ? 0.25 : 0.4 + happy / 250) - pet.glow) * 0.05;
      const glow = ctx.createRadialGradient(
        pet.x,
        pet.y + 6,
        2,
        pet.x,
        pet.y + 6,
        26,
      );
      glow.addColorStop(
        0,
        `rgba(${sick ? "255,107,138" : "255,207,107"},${0.35 * pet.glow})`,
      );
      glow.addColorStop(1, "transparent");
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.ellipse(pet.x, pet.y + 8, 24, 12, 0, 0, 7);
      ctx.fill();

      // pet sprite
      const bob =
        pet.act === "walk" || pet.act === "seekfood"
          ? Math.sin(pet.anim * 10) * 1.2
          : Math.sin(pet.anim * 3) * 0.8;
      const hop = pet.hop > 0 ? -Math.sin(pet.hop * Math.PI) * 6 : 0;
      const px = Math.round(pet.x - 12);
      const py = Math.round(pet.y - 14 + bob + hop);
      ctx.save();
      if (pet.dir < 0) {
        ctx.translate(px + 24, 0);
        ctx.scale(-1, 1);
        drawSprite(ctx, PET_SPRITE, 0, py, 2);
      } else {
        drawSprite(ctx, PET_SPRITE, px, py, 2);
      }
      ctx.restore();
      if (sick) {
        ctx.fillStyle = "#ff6b8a";
        ctx.font = "9px monospace";
        ctx.fillText("✚", pet.x + 10, py - 2);
      }
      if (pet.hop > 0) {
        pet.hop -= dt * 1.8;
        if (pet.hop < 0) pet.hop = 0;
      }

      // motes
      const motes = motesRef.current;
      for (const m of motes) {
        m.y -= m.vy * dt;
        m.life -= dt * 0.8;
      }
      motesRef.current = motes.filter((m) => m.life > 0);
      for (const m of motesRef.current) {
        ctx.fillStyle = `rgba(185,140,255,${m.life})`;
        ctx.fillRect(m.x, m.y, 2, 2);
      }

      raf = window.requestAnimationFrame(tick);
    };

    raf = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(raf);
  }, []);

  const expPct = state ? (state.exp / state.expToNext) * 100 : 0;

  return (
    <div className="rounded-lg border border-[var(--border)] overflow-hidden">
      <div className="flex flex-col sm:flex-row">
        {/* Stage */}
        <div className="relative bg-[#05060f] sm:w-[60%]">
          <canvas
            ref={canvasRef}
            width={W}
            height={H}
            className="block w-full h-auto [image-rendering:pixelated]"
          />
          {failed && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/60 text-xs text-white/80">
              {tr("无法连接到伙伴", "Companion offline")}
            </div>
          )}
        </div>

        {/* Stats — straight from the server, never computed here */}
        <div className="flex-1 p-3 space-y-2.5">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm font-medium text-[var(--foreground)]">
                {state?.name ?? "—"}
                {state?.sick && (
                  <span className="ml-1.5 text-xs text-red-500">
                    {tr("生病了", "sick")}
                  </span>
                )}
              </div>
              <div className="text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">
                {`${state?.element ?? ""} ${tr("元素精灵", "anima")}`}
              </div>
            </div>
            <div className="text-xs font-medium text-amber-500">
              {`${tr("等级", "Lv.")} ${state?.level ?? 1}`}
            </div>
          </div>

          <Bar
            label={tr("饥饿", "Hunger")}
            value={state?.hunger ?? 0}
            text={`${Math.round(state?.hunger ?? 0)}%`}
            className="bg-orange-500"
          />
          <Bar
            label={tr("快乐", "Happiness")}
            value={state?.happy ?? 0}
            text={`${Math.round(state?.happy ?? 0)}%`}
            className="bg-emerald-500"
          />
          <Bar
            label={tr("知识", "Knowledge")}
            value={expPct}
            text={`${Math.round(state?.exp ?? 0)} / ${state?.expToNext ?? 100}`}
            className="bg-violet-500"
          />

          <p className="pt-0.5 text-[10px] leading-relaxed text-[var(--muted-foreground)]">
            {tr(
              "答对测验喂养它：真正掌握一个知识点才会长大。",
              "Feed it by answering quizzes — it only grows when you truly master an objective.",
            )}
          </p>
        </div>
      </div>
    </div>
  );
}

function Bar({
  label,
  value,
  text,
  className,
}: {
  label: string;
  value: number;
  text: string;
  className: string;
}) {
  return (
    <div>
      <div className="flex justify-between text-[10px] text-[var(--muted-foreground)]">
        <span>{label}</span>
        <span>{text}</span>
      </div>
      <div className="mt-1 h-1.5 w-full rounded-full bg-[var(--accent)] overflow-hidden">
        <div
          className={`h-full transition-all duration-500 ${className}`}
          style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
        />
      </div>
    </div>
  );
}
