"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { fetchPetState, type PetState } from "@/lib/pet-api";

/**
 * Learner Anima — the learning companion, rendered on its own top-level page.
 *
 * The SERVER is authoritative: hunger/happy/exp/level/sick are derived from real
 * `LearningProgress` (mastery gate + lazy decay) by `deeptutor.pet` and pulled
 * here every few seconds. This component NEVER computes those numbers — it is a
 * pure renderer, so the whole UI is a replaceable "mask" over the bridge.
 *
 * Everything the canvas does on its own (wander, blink, walk-to-bowl, particles)
 * is *cosmetic*, triggered by observing deltas between two server states:
 *   exp up / hunger down  -> run to the bowl and eat
 *   level up              -> golden sparkles
 *   sick true -> false    -> heal hearts
 *
 * Art is high-DPI + anti-aliased (a cozy-room illustration, not pixel art). The
 * standalone design workspace is `docs/issues/anima-habitat/preview.html` — tweak
 * the look there first, then port here.
 */

const POLL_MS = 4000;
const LW = 800; // logical drawing width
const LH = 520; // logical drawing height
const FLOOR = 196; // wall/floor boundary
const BOWL_PT = { x: 620, y: 388 };

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
  blink: number;
  blinkT: number;
  glow: number;
};
type Mood = { hunger: number; happy: number; sick: boolean };
type Part = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  kind: string;
};

const C = {
  wall1: "#efdcb8",
  wall2: "#e2c99c",
  wainscot: "#d9c096",
  wainDk: "#b89a6f",
  floor1: "#c68d57",
  floor2: "#bb8049",
  grout: "rgba(120,78,42,.45)",
  plankHi: "rgba(255,232,190,.20)",
  rug1: "#7aa593",
  rug2: "#5f8a77",
  rug3: "#9ac1b0",
  rugEdge: "#4c6f60",
  wood: "#946139",
  woodDk: "#6f4526",
  leaf: "#5cae72",
  leafDk: "#3a8c57",
  leafHi: "#84cf95",
  pot: "#c9743f",
  potDk: "#9e5629",
  bedFrame: "#7c4f2e",
  quilt: "#e6c091",
  quilt2: "#f0d8b1",
  pillow: "#f6ecd6",
  lampPole: "#7b7f96",
  body1: "#8fe0c8",
  body2: "#63c3a7",
  bodyHi: "#c3f1e2",
  cream: "#fcf5e2",
  eye: "#2b2740",
  white: "#ffffff",
  cheek: "#ff9db0",
  bowl: "#9dc0dc",
  bowlDk: "#6a97bf",
  kib: "#c98a4e",
  frameW: "#7c4f2e",
  sky: "#bcd9ea",
  hill: "#8fc08f",
  sun: "#ffe08a",
};

type Ctx = CanvasRenderingContext2D;
const rr = (
  ctx: Ctx,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) => {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
};
function shadow(
  ctx: Ctx,
  cx: number,
  cy: number,
  rx: number,
  ry: number,
  a: number,
) {
  const g = ctx.createRadialGradient(cx, cy, 1, cx, cy, rx);
  g.addColorStop(0, `rgba(24,14,32,${a})`);
  g.addColorStop(1, "rgba(24,14,32,0)");
  ctx.save();
  ctx.translate(cx, cy);
  ctx.scale(1, ry / rx);
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(0, 0, rx, 0, 7);
  ctx.fill();
  ctx.restore();
}

// --- room -------------------------------------------------------------------
function drawWall(ctx: Ctx) {
  const g = ctx.createLinearGradient(0, 0, 0, FLOOR);
  g.addColorStop(0, C.wall1);
  g.addColorStop(1, C.wall2);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, LW, FLOOR);
  ctx.fillStyle = C.wainscot;
  ctx.fillRect(0, FLOOR - 54, LW, 54);
  ctx.fillStyle = C.wainDk;
  ctx.fillRect(0, FLOOR - 54, LW, 3);
  ctx.fillStyle = "rgba(255,255,255,.25)";
  ctx.fillRect(0, FLOOR - 51, LW, 2);
  ctx.strokeStyle = "rgba(120,95,60,.30)";
  ctx.lineWidth = 2;
  for (let x = 40; x < LW; x += 96) {
    rr(ctx, x, FLOOR - 44, 64, 34, 4);
    ctx.stroke();
  }
  ctx.fillStyle = C.wainDk;
  ctx.fillRect(0, FLOOR - 8, LW, 8);
  ctx.fillStyle = "rgba(0,0,0,.12)";
  ctx.fillRect(0, FLOOR, LW, 6);
}
function drawFloor(ctx: Ctx) {
  ctx.fillStyle = C.floor1;
  ctx.fillRect(0, FLOOR, LW, LH - FLOOR);
  for (let y = FLOOR, r = 0; y < LH; y += 30, r++) {
    ctx.fillStyle = r % 2 ? C.floor2 : C.floor1;
    ctx.fillRect(0, y, LW, 30);
    ctx.strokeStyle = C.grout;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, y + 0.5);
    ctx.lineTo(LW, y + 0.5);
    ctx.stroke();
    ctx.strokeStyle = C.plankHi;
    ctx.beginPath();
    ctx.moveTo(0, y + 2.5);
    ctx.lineTo(LW, y + 2.5);
    ctx.stroke();
    ctx.strokeStyle = "rgba(110,69,38,.35)";
    ctx.lineWidth = 2;
    for (let x = r % 2 ? 90 : 250; x < LW; x += 300) {
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x, y + 30);
      ctx.stroke();
    }
  }
  const g = ctx.createRadialGradient(560, 250, 30, 560, 330, 460);
  g.addColorStop(0, "rgba(255,214,140,.16)");
  g.addColorStop(1, "transparent");
  ctx.fillStyle = g;
  ctx.fillRect(0, FLOOR, LW, LH - FLOOR);
}
function drawRug(ctx: Ctx) {
  ctx.save();
  ctx.translate(390, 380);
  ctx.scale(1, 0.52);
  const rings: [number, string][] = [
    [210, C.rugEdge],
    [200, C.rug1],
    [172, C.rug2],
    [150, C.rug1],
    [120, C.rug2],
  ];
  for (const [r, col] of rings) {
    ctx.fillStyle = col;
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, 7);
    ctx.fill();
  }
  ctx.fillStyle = C.rug3;
  for (let a = 0; a < 7; a += Math.PI / 4) {
    ctx.beginPath();
    ctx.arc(Math.cos(a) * 135, Math.sin(a) * 135, 9, 0, 7);
    ctx.fill();
  }
  ctx.beginPath();
  ctx.arc(0, 0, 16, 0, 7);
  ctx.fill();
  ctx.restore();
}

// --- furniture --------------------------------------------------------------
function bookshelf(ctx: Ctx, x: number, y: number) {
  const w = 150;
  const h = 128;
  shadow(ctx, x + w / 2, y + h + 6, w / 1.7, 16, 0.3);
  ctx.fillStyle = C.woodDk;
  rr(ctx, x, y, w, h, 8);
  ctx.fill();
  ctx.fillStyle = C.wood;
  rr(ctx, x + 4, y + 4, w - 8, h - 8, 6);
  ctx.fill();
  ctx.fillStyle = "rgba(255,255,255,.10)";
  rr(ctx, x + 4, y + 4, w - 8, 6, 3);
  ctx.fill();
  const spines = [
    "#c0504d",
    "#4f81bd",
    "#9bbb59",
    "#e0a030",
    "#8064a2",
    "#4bacc6",
    "#d98a5a",
  ];
  for (let s = 0; s < 3; s++) {
    const sy = y + 12 + s * 38;
    const sh = 30;
    for (let bx = x + 12, i = 0; bx < x + w - 14; i++) {
      const bw = 9 + ((i * 7) % 9);
      ctx.fillStyle = spines[(s * 3 + i) % spines.length];
      if (i % 5 === 4) {
        ctx.save();
        ctx.translate(bx + bw / 2, sy + sh);
        ctx.rotate(-0.12);
        rr(ctx, -bw / 2, -sh, bw, sh, 2);
        ctx.fill();
        ctx.restore();
      } else {
        rr(ctx, bx, sy, bw, sh, 2);
        ctx.fill();
        ctx.fillStyle = "rgba(255,255,255,.22)";
        ctx.fillRect(bx, sy, bw, 3);
      }
      bx += bw + 3;
    }
    ctx.fillStyle = C.woodDk;
    ctx.fillRect(x + 8, sy + sh + 2, w - 16, 5);
  }
}
function plant(ctx: Ctx, x: number, y: number, s: number) {
  shadow(ctx, x, y + 40 * s, 34 * s, 12 * s, 0.28);
  ctx.fillStyle = C.potDk;
  rr(ctx, x - 22 * s, y + 12 * s, 44 * s, 30 * s, 6 * s);
  ctx.fill();
  ctx.fillStyle = C.pot;
  rr(ctx, x - 20 * s, y + 12 * s, 40 * s, 26 * s, 5 * s);
  ctx.fill();
  ctx.fillStyle = "rgba(255,255,255,.18)";
  rr(ctx, x - 20 * s, y + 12 * s, 40 * s, 6 * s, 3 * s);
  ctx.fill();
  const leaves: [number, number][] = [
    [0, -34],
    [-18, -18],
    [18, -18],
    [-10, -4],
    [10, -4],
    [0, -16],
  ];
  ctx.fillStyle = C.leafDk;
  for (const [lx, ly] of leaves) {
    ctx.beginPath();
    ctx.ellipse(x + lx * s, y + ly * s, 15 * s, 22 * s, lx * 0.03, 0, 7);
    ctx.fill();
  }
  ctx.fillStyle = C.leaf;
  for (const [lx, ly] of leaves) {
    ctx.beginPath();
    ctx.ellipse(x + lx * s, y + ly * s - 2, 12 * s, 18 * s, lx * 0.03, 0, 7);
    ctx.fill();
  }
  ctx.fillStyle = C.leafHi;
  for (const [lx, ly] of leaves) {
    ctx.beginPath();
    ctx.ellipse(x + lx * s - 3, y + ly * s - 6, 5 * s, 8 * s, lx * 0.03, 0, 7);
    ctx.fill();
  }
}
function lamp(ctx: Ctx, x: number, y: number) {
  const g = ctx.createRadialGradient(x, y + 20, 8, x, y + 110, 170);
  g.addColorStop(0, "rgba(255,214,140,.5)");
  g.addColorStop(1, "transparent");
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(x, y + 90, 170, 0, 7);
  ctx.fill();
  shadow(ctx, x, y + 150, 34, 12, 0.3);
  ctx.fillStyle = C.lampPole;
  ctx.fillRect(x - 3, y + 30, 6, 122);
  rr(ctx, x - 22, y + 150, 44, 8, 4);
  ctx.fill();
  ctx.fillStyle = C.sun;
  ctx.beginPath();
  ctx.moveTo(x - 30, y + 34);
  ctx.lineTo(x + 30, y + 34);
  ctx.lineTo(x + 22, y - 2);
  ctx.lineTo(x - 22, y - 2);
  ctx.closePath();
  ctx.fill();
  ctx.fillStyle = "rgba(255,255,255,.4)";
  ctx.beginPath();
  ctx.moveTo(x - 22, y - 2);
  ctx.lineTo(x + 22, y - 2);
  ctx.lineTo(x + 18, y + 8);
  ctx.lineTo(x - 18, y + 8);
  ctx.closePath();
  ctx.fill();
}
function bed(ctx: Ctx, x: number, y: number) {
  shadow(ctx, x, y + 26, 80, 22, 0.3);
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(1, 0.6);
  ctx.fillStyle = C.bedFrame;
  ctx.beginPath();
  ctx.arc(0, 0, 78, 0, 7);
  ctx.fill();
  ctx.fillStyle = C.quilt;
  ctx.beginPath();
  ctx.arc(0, 4, 66, 0, 7);
  ctx.fill();
  ctx.fillStyle = C.quilt2;
  ctx.beginPath();
  ctx.arc(6, -6, 44, 0, 7);
  ctx.fill();
  ctx.restore();
  ctx.fillStyle = C.pillow;
  rr(ctx, x - 30, y - 16, 60, 26, 12);
  ctx.fill();
  ctx.fillStyle = "rgba(255,255,255,.5)";
  rr(ctx, x - 26, y - 13, 52, 8, 6);
  ctx.fill();
}
function bowl(ctx: Ctx, x: number, y: number) {
  shadow(ctx, x, y + 8, 36, 12, 0.3);
  ctx.fillStyle = C.bowlDk;
  ctx.beginPath();
  ctx.ellipse(x, y, 34, 15, 0, 0, 7);
  ctx.fill();
  ctx.fillStyle = C.bowl;
  ctx.beginPath();
  ctx.ellipse(x, y - 3, 32, 13, 0, 0, 7);
  ctx.fill();
  ctx.fillStyle = "rgba(0,0,0,.14)";
  ctx.beginPath();
  ctx.ellipse(x, y - 3, 24, 9, 0, 0, 7);
  ctx.fill();
  ctx.fillStyle = C.kib;
  for (const [dx, dy] of [
    [-12, -2],
    [-2, -6],
    [10, -3],
    [-6, 3],
    [6, 3],
    [0, 0],
  ]) {
    ctx.beginPath();
    ctx.arc(x + dx, y - 4 + dy, 4, 0, 7);
    ctx.fill();
  }
}
function wallFrame(ctx: Ctx, x: number, y: number) {
  ctx.fillStyle = C.frameW;
  rr(ctx, x, y, 92, 66, 6);
  ctx.fill();
  ctx.fillStyle = C.sky;
  rr(ctx, x + 7, y + 7, 78, 52, 3);
  ctx.fill();
  ctx.fillStyle = C.sun;
  ctx.beginPath();
  ctx.arc(x + 66, y + 22, 9, 0, 7);
  ctx.fill();
  ctx.fillStyle = C.hill;
  ctx.beginPath();
  ctx.moveTo(x + 7, y + 59);
  ctx.quadraticCurveTo(x + 40, y + 30, x + 85, y + 59);
  ctx.fill();
}
function drawRoom(ctx: Ctx) {
  drawWall(ctx);
  drawFloor(ctx);
  wallFrame(ctx, 354, 40);
  drawRug(ctx);
  bookshelf(ctx, 40, FLOOR - 120);
  plant(ctx, 240, FLOOR - 30, 1);
  lamp(ctx, 600, 44);
  bed(ctx, 120, 430);
  bowl(ctx, 628, 388);
  plant(ctx, 700, 452, 1.25);
}

// --- creature ---------------------------------------------------------------
function drawPet(ctx: Ctx, pet: Cosmetic, mood: Mood) {
  const walking = pet.act === "walk" || pet.act === "seekfood";
  const bob = walking
    ? Math.sin(pet.anim * 11) * 5
    : Math.sin(pet.anim * 3) * 3.4;
  const squash = walking
    ? Math.sin(pet.anim * 11) * 0.05
    : Math.sin(pet.anim * 3) * 0.02;
  const hop = pet.hop > 0 ? -Math.sin(pet.hop * Math.PI) * 30 : 0;
  const R = 46;
  const cx = pet.x;
  const cy = pet.y - R + bob + hop;

  shadow(ctx, pet.x, pet.y + 4, 48, 15, 0.32);

  pet.glow += ((mood.sick ? 0.25 : 0.4 + mood.happy / 260) - pet.glow) * 0.05;
  const aura = ctx.createRadialGradient(cx, cy, 8, cx, cy, 70);
  aura.addColorStop(
    0,
    `rgba(${mood.sick ? "150,190,175" : "140,240,200"},${0.28 * pet.glow})`,
  );
  aura.addColorStop(1, "transparent");
  ctx.fillStyle = aura;
  ctx.beginPath();
  ctx.arc(cx, cy, 70, 0, 7);
  ctx.fill();

  ctx.save();
  ctx.translate(cx, cy);
  ctx.scale(pet.dir * (1 - squash), 1 + squash);

  const b1 = mood.sick ? "#a9bfb2" : C.body1;
  const b2 = mood.sick ? "#7f978a" : C.body2;
  const bh = mood.sick ? "#c8d6cd" : C.bodyHi;
  // ears
  ctx.fillStyle = b2;
  for (const sx of [-1, 1]) {
    ctx.beginPath();
    ctx.moveTo(sx * 20, -R * 0.7);
    ctx.quadraticCurveTo(sx * 40, -R * 1.25, sx * 14, -R * 0.95);
    ctx.quadraticCurveTo(sx * 6, -R * 0.78, sx * 20, -R * 0.7);
    ctx.fill();
  }
  ctx.fillStyle = C.cheek;
  for (const sx of [-1, 1]) {
    ctx.beginPath();
    ctx.ellipse(sx * 24, -R * 0.98, 4, 6, 0, 0, 7);
    ctx.fill();
  }
  // body
  const bg = ctx.createRadialGradient(-14, -16, 6, 0, 0, R + 6);
  bg.addColorStop(0, bh);
  bg.addColorStop(0.5, b1);
  bg.addColorStop(1, b2);
  ctx.fillStyle = bg;
  ctx.beginPath();
  ctx.ellipse(0, 0, R, R * 0.92, 0, 0, 7);
  ctx.fill();
  // belly
  ctx.fillStyle = C.cream;
  ctx.beginPath();
  ctx.ellipse(0, 14, R * 0.62, R * 0.6, 0, 0, 7);
  ctx.fill();
  // cheeks
  ctx.fillStyle = C.cheek;
  ctx.globalAlpha = 0.85;
  ctx.beginPath();
  ctx.ellipse(-26, 6, 9, 7, 0, 0, 7);
  ctx.fill();
  ctx.beginPath();
  ctx.ellipse(26, 6, 9, 7, 0, 0, 7);
  ctx.fill();
  ctx.globalAlpha = 1;
  // eyes
  if (pet.blink > 0) {
    ctx.strokeStyle = C.eye;
    ctx.lineWidth = 3;
    ctx.lineCap = "round";
    for (const sx of [-1, 1]) {
      ctx.beginPath();
      ctx.moveTo(sx * 18 - 7, -4);
      ctx.quadraticCurveTo(sx * 18, 1, sx * 18 + 7, -4);
      ctx.stroke();
    }
  } else {
    for (const sx of [-1, 1]) {
      ctx.fillStyle = C.white;
      ctx.beginPath();
      ctx.ellipse(sx * 18, -4, 10, 12, 0, 0, 7);
      ctx.fill();
      ctx.fillStyle = C.eye;
      ctx.beginPath();
      ctx.ellipse(sx * 18 + sx * 2, -1, 6, 8, 0, 0, 7);
      ctx.fill();
      ctx.fillStyle = C.white;
      ctx.beginPath();
      ctx.arc(sx * 18 - 1, -6, 2.6, 0, 7);
      ctx.fill();
    }
  }
  // mouth
  ctx.strokeStyle = C.eye;
  ctx.lineWidth = 2.4;
  ctx.lineCap = "round";
  if (pet.act === "eat") {
    ctx.fillStyle = "#7a3b46";
    ctx.beginPath();
    ctx.ellipse(0, 16, 5, 6, 0, 0, 7);
    ctx.fill();
  } else if (mood.sick) {
    ctx.beginPath();
    ctx.moveTo(-7, 18);
    ctx.quadraticCurveTo(0, 13, 7, 18);
    ctx.stroke();
  } else {
    ctx.beginPath();
    ctx.moveTo(-8, 13);
    ctx.quadraticCurveTo(0, 21, 8, 13);
    ctx.stroke();
  }
  // feet
  ctx.fillStyle = b2;
  ctx.beginPath();
  ctx.ellipse(-16, R * 0.82, 10, 6, 0, 0, 7);
  ctx.fill();
  ctx.beginPath();
  ctx.ellipse(16, R * 0.82, 10, 6, 0, 0, 7);
  ctx.fill();
  ctx.restore();

  if (mood.sick) {
    ctx.fillStyle = "#ff6b8a";
    ctx.font = "bold 22px system-ui, sans-serif";
    ctx.fillText("✚", cx + 40, cy - 34);
  }
}

// --- particles --------------------------------------------------------------
function star(ctx: Ctx, x: number, y: number, r: number) {
  ctx.beginPath();
  for (let i = 0; i < 10; i++) {
    const a = (i * Math.PI) / 5 - Math.PI / 2;
    const rr2 = i % 2 ? r : r / 2.3;
    if (i) ctx.lineTo(x + Math.cos(a) * rr2, y + Math.sin(a) * rr2);
    else ctx.moveTo(x + Math.cos(a) * rr2, y + Math.sin(a) * rr2);
  }
  ctx.closePath();
  ctx.fill();
}
function heart(ctx: Ctx, x: number, y: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x, y + r);
  ctx.bezierCurveTo(
    x - r * 1.5,
    y - r * 0.4,
    x - r * 0.4,
    y - r * 1.3,
    x,
    y - r * 0.4,
  );
  ctx.bezierCurveTo(
    x + r * 0.4,
    y - r * 1.3,
    x + r * 1.5,
    y - r * 0.4,
    x,
    y + r,
  );
  ctx.fill();
}
function drawParts(ctx: Ctx, parts: Part[], dt: number): Part[] {
  for (const p of parts) {
    p.x += p.vx * dt;
    p.y += p.vy * dt;
    p.vy += 90 * dt;
    p.life -= dt * 0.85;
  }
  const alive = parts.filter((p) => p.life > 0);
  for (const p of alive) {
    ctx.globalAlpha = Math.max(0, p.life);
    if (p.kind === "level") {
      ctx.fillStyle = "#ffd76a";
      star(ctx, p.x, p.y, 9);
    } else if (p.kind === "heal") {
      ctx.fillStyle = "#ff9db0";
      heart(ctx, p.x, p.y, 8);
    } else {
      ctx.fillStyle = "#c98a4e";
      ctx.beginPath();
      ctx.arc(p.x, p.y, 4, 0, 7);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }
  return alive;
}

function drawLighting(ctx: Ctx, mood: Mood, night: boolean) {
  if (night) {
    // Dark theme = evening in the room: a cool multiply pass dims everything,
    // then the floor lamp re-lights its corner so it reads as "lamp on at
    // night", not a gray filter over a daytime scene.
    ctx.globalCompositeOperation = "multiply";
    ctx.fillStyle = "#8b87b8";
    ctx.fillRect(0, 0, LW, LH);
    ctx.globalCompositeOperation = "source-over";
    const lampGlow = ctx.createRadialGradient(600, 120, 16, 600, 175, 280);
    lampGlow.addColorStop(0, "rgba(255,206,120,.42)");
    lampGlow.addColorStop(1, "rgba(255,206,120,0)");
    ctx.fillStyle = lampGlow;
    ctx.fillRect(0, 0, LW, LH);
  }
  const v = ctx.createRadialGradient(LW / 2, LH / 2, 180, LW / 2, LH / 2, 560);
  v.addColorStop(0, "transparent");
  v.addColorStop(1, night ? "rgba(8,6,18,.55)" : "rgba(10,6,20,.4)");
  ctx.fillStyle = v;
  ctx.fillRect(0, 0, LW, LH);
  if (mood.sick) {
    ctx.fillStyle = "rgba(90,120,110,.14)";
    ctx.fillRect(0, 0, LW, LH);
  } else if (!night) {
    ctx.fillStyle = `rgba(255,190,120,${0.04 + 0.05 * (mood.happy / 100)})`;
    ctx.fillRect(0, 0, LW, LH);
  }
}

/**
 * The habitat canvas — a PURE renderer. It shows the cozy room + creature and
 * plays cosmetic reactions (run-to-bowl, level sparkles, heal hearts) fired by
 * deltas between server states. It never computes pet stats.
 *
 * Two modes: pass `controlledState` and the parent owns fetching (the dashboard
 * polls one aggregate endpoint and feeds state in); pass nothing and the canvas
 * polls `fetchPetState` itself. Either way it renders only the stage — the
 * surrounding status/mastery cards live in the page.
 */
export default function PetHabitat({
  controlledState,
  offline = false,
}: {
  controlledState?: PetState | null;
  offline?: boolean;
} = {}) {
  const { t } = useTranslation();
  const controlled = controlledState !== undefined;
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [selfFailed, setSelfFailed] = useState(false);
  const failed = controlled ? offline : selfFailed;

  const stateRef = useRef<PetState | null>(null);
  const prevRef = useRef<PetState | null>(null);
  // Dark theme (incl. glass) renders the room at night — read from the <html>
  // class the app's ThemeScript maintains, kept in a ref for the draw loop.
  const darkRef = useRef(false);
  const partsRef = useRef<Part[]>([]);
  const redrawRef = useRef<(() => void) | null>(null);
  const petRef = useRef<Cosmetic>({
    x: LW / 2,
    y: 380,
    tx: LW / 2,
    ty: 380,
    dir: 1,
    anim: 0,
    act: "idle",
    actT: 0,
    hop: 0,
    blink: 0,
    blinkT: 2.5,
    glow: 0.6,
  });

  const spawn = useCallback((kind: string) => {
    const pet = petRef.current;
    const n = kind === "level" ? 18 : kind === "heal" ? 12 : 8;
    for (let i = 0; i < n; i++)
      partsRef.current.push({
        x: pet.x + (Math.random() * 60 - 30),
        y: pet.y - 40,
        vx: (Math.random() * 2 - 1) * 40,
        vy: -(60 + Math.random() * 90),
        life: 1,
        kind,
      });
  }, []);

  /** Observe a new server state and fire the cosmetic reactions it implies. */
  const observe = useCallback(
    (next: PetState) => {
      const prev = prevRef.current;
      const pet = petRef.current;
      if (prev) {
        if (next.exp > prev.exp || next.hunger < prev.hunger - 0.5) {
          pet.tx = BOWL_PT.x;
          pet.ty = BOWL_PT.y;
          pet.act = "seekfood";
          pet.actT = 0;
        }
        if (next.level > prev.level) spawn("level");
        if (prev.sick && !next.sick) spawn("heal");
      }
      prevRef.current = next;
      stateRef.current = next;
      redrawRef.current?.(); // reduced-motion mode redraws on state change
    },
    [spawn],
  );

  // --- state source ---------------------------------------------------------
  // Uncontrolled: poll the bridge directly. Controlled: the parent (the dashboard)
  // owns the fetch and feeds `controlledState` in — one poller for the whole page.
  useEffect(() => {
    if (controlled) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await fetchPetState();
        if (!cancelled) {
          observe(next);
          setSelfFailed(false);
        }
      } catch {
        if (!cancelled) setSelfFailed(true);
      }
    };
    poll();
    const id = window.setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [controlled, observe]);

  useEffect(() => {
    if (controlled && controlledState) observe(controlledState);
  }, [controlled, controlledState, observe]);

  // --- cosmetic render loop -------------------------------------------------
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const reduced =
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

    const fit = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const cssW = canvas.clientWidth || 700;
      const cssH = (cssW * LH) / LW;
      canvas.style.height = `${cssH}px`;
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);
      ctx.setTransform(canvas.width / LW, 0, 0, canvas.width / LW, 0, 0);
      ctx.imageSmoothingEnabled = true;
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(canvas);

    // Track theme switches live so the room darkens/brightens immediately
    // (and reduced-motion mode repaints its single frame).
    const readTheme = () => {
      darkRef.current = document.documentElement.classList.contains("dark");
    };
    readTheme();
    const themeObserver = new MutationObserver(() => {
      readTheme();
      redrawRef.current?.();
    });
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });

    let raf = 0;
    let last = performance.now();
    let running = true;

    const mood = (): Mood => {
      const s = stateRef.current;
      return {
        hunger: s?.hunger ?? 0,
        happy: s?.happy ?? 80,
        sick: s?.sick ?? false,
      };
    };

    const frame = (now: number) => {
      const dt = reduced ? 0 : Math.min(0.05, (now - last) / 1000);
      last = now;
      const pet = petRef.current;

      if (!reduced) {
        pet.blinkT -= dt;
        if (pet.blinkT <= 0) {
          pet.blink = 0.13;
          pet.blinkT = 2 + Math.random() * 3.5;
        }
        if (pet.blink > 0) pet.blink -= dt;

        const dx = pet.tx - pet.x;
        const dy = pet.ty - pet.y;
        const d = Math.hypot(dx, dy);
        if (d > 4) {
          if (pet.act === "idle") pet.act = "walk";
          const sp = 78 * (pet.act === "seekfood" ? 1.7 : 1);
          pet.x += (dx / d) * sp * dt;
          pet.y += (dy / d) * sp * dt;
          if (Math.abs(dx) > 2) pet.dir = dx > 0 ? 1 : -1;
          pet.anim += dt;
        } else {
          if (pet.act === "seekfood") {
            pet.act = "eat";
            pet.actT = 0;
          } else if (pet.act === "walk") pet.act = "idle";
          pet.anim += dt * 0.5;
        }
        pet.actT += dt;
        if (pet.act === "eat" && pet.actT > 1.2) {
          pet.act = "idle";
          pet.hop = 1;
          if (partsRef.current.length < 40) spawn("crumb");
        }
        if (pet.act === "idle" && pet.actT > 1.8 + Math.random() * 2.4) {
          pet.tx = 110 + Math.random() * (LW - 220);
          pet.ty = FLOOR + 70 + Math.random() * (LH - FLOOR - 120);
          pet.act = "walk";
          pet.actT = 0;
        }
        if (pet.hop > 0) {
          pet.hop -= dt * 1.7;
          if (pet.hop < 0) pet.hop = 0;
        }
      }

      const m = mood();
      ctx.clearRect(0, 0, LW, LH);
      drawRoom(ctx);
      drawPet(ctx, pet, m);
      if (!reduced) partsRef.current = drawParts(ctx, partsRef.current, dt);
      drawLighting(ctx, m, darkRef.current);

      if (running && !reduced) raf = window.requestAnimationFrame(frame);
    };

    // reduced-motion: draw a single calm frame; redraw only when state changes.
    redrawRef.current = () => frame(performance.now());
    if (reduced) frame(last);
    else raf = window.requestAnimationFrame(frame);

    // pause the loop while the tab is hidden (saves CPU/battery).
    const onVis = () => {
      if (reduced) return;
      if (document.hidden) {
        running = false;
        window.cancelAnimationFrame(raf);
      } else if (!running) {
        running = true;
        last = performance.now();
        raf = window.requestAnimationFrame(frame);
      }
    };
    document.addEventListener("visibilitychange", onVis);

    return () => {
      running = false;
      window.cancelAnimationFrame(raf);
      ro.disconnect();
      themeObserver.disconnect();
      document.removeEventListener("visibilitychange", onVis);
      redrawRef.current = null;
    };
  }, [spawn]);

  return (
    <div className="relative h-full w-full bg-[#1f1c1a]">
      <canvas ref={canvasRef} className="block h-auto w-full" />
      {failed && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/60 text-xs text-white/80">
          {t("Companion offline")}
        </div>
      )}
    </div>
  );
}
