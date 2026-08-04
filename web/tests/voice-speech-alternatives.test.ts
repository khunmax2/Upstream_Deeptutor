// N-best rescue (components/voice/speechAlternatives) — pure logic tests.
//
// The rule under test: rank #1 always wins EXCEPT when it fails the
// navigation-command shape while a lower-ranked alternative passes it —
// normal conversation must never be rewritten by a runner-up hypothesis.

import test from "node:test";
import assert from "node:assert/strict";

import { pickUtterance, labelTokens } from "../components/voice/speechAlternatives";

const LABELS = [
  "หน้าความจำ / หน่วยความจำ (memory)",
  "หน้า Knowledge Base (คลังความรู้/ศูนย์ความรู้/เอกสาร)",
  "หน้าตั้งค่า (settings)",
];

test("garbled top hypothesis loses to a nav-shaped runner-up", () => {
  const picked = pickUtterance(
    ["ไฟหน้าหน่วยความจำ", "ไปหน้าหน่วยความจำ"],
    LABELS,
  );
  assert.equal(picked, "ไปหน้าหน่วยความจำ");
});

test("normal conversation keeps rank #1 even when a runner-up looks nav-ish", () => {
  const picked = pickUtterance(
    ["วันนี้อากาศดีมาก", "ไปหน้าตั้งค่า"],
    LABELS,
  );
  assert.equal(picked, "วันนี้อากาศดีมาก");
});

test("nav-shaped rank #1 is never replaced", () => {
  const picked = pickUtterance(
    ["ไปหน้าตั้งค่า", "ไปหน้าความจำ"],
    LABELS,
  );
  assert.equal(picked, "ไปหน้าตั้งค่า");
});

test("runner-up must name a known page, not just sound like a command", () => {
  const picked = pickUtterance(
    ["ไฟหน้ารถเสีย", "ไปหน้าร้านค้า"], // ร้านค้า is not a manifest page
    LABELS,
  );
  assert.equal(picked, "ไฟหน้ารถเสีย");
});

test("handles empty and single-alternative input", () => {
  assert.equal(pickUtterance([], LABELS), "");
  assert.equal(pickUtterance(["  "], LABELS), "");
  assert.equal(pickUtterance(["สวัสดี"], LABELS), "สวัสดี");
});

test("labelTokens extracts aliases incl. หน้า-stripped forms", () => {
  const tokens = labelTokens(LABELS);
  assert.ok(tokens.includes("หน่วยความจำ"));
  assert.ok(tokens.includes("ความจำ")); // หน้าความจำ minus หน้า
  assert.ok(tokens.includes("ศูนย์ความรู้"));
  assert.ok(tokens.includes("knowledge"));
});

test("garbled mode command loses to a mode-shaped runner-up", () => {
  // The exact live garble: 'เปิดโหมดเลขา' heard as 'เปิดหมดเลยค่ะ' while the
  // correct phrase sat in hypothesis #2.
  const picked = pickUtterance(["เปิดหมดเลยค่ะ", "เปิดโหมดเลขา"], LABELS);
  assert.equal(picked, "เปิดโหมดเลขา");
  const exit = pickUtterance(["ปิดหมดเรขาค", "ปิดโหมดเลขา"], LABELS);
  assert.equal(exit, "ปิดโหมดเลขา");
});

test("mode-shaped rank #1 is never replaced", () => {
  const picked = pickUtterance(["เปิดโหมดเลขา", "เปิดโหมดพิมพ์"], LABELS);
  assert.equal(picked, "เปิดโหมดเลขา");
});

test("speech without mode fragments keeps rank #1 despite a mode runner-up", () => {
  const picked = pickUtterance(["วันนี้ไปเที่ยวมา", "เปิดโหมดเลขา"], LABELS);
  assert.equal(picked, "วันนี้ไปเที่ยวมา");
});

test("mode-adjacent chatter without a mode runner-up keeps rank #1", () => {
  const picked = pickUtterance(["ปิดไฟหมดเลยนะ", "ปิดไฟหมดแล้วนะ"], LABELS);
  assert.equal(picked, "ปิดไฟหมดเลยนะ");
});

test("normal conversation keeps rank #1 exactly (no rewriting)", () => {
  // The exact failure to prevent: a chat sentence replaced by hypothesis #2.
  const picked = pickUtterance(
    ["มาตรา 112 คืออะไร", "มาตรา 112 มีอะไร", "ไปหน้าตั้งค่า"],
    LABELS,
  );
  assert.equal(picked, "มาตรา 112 คืออะไร");
});
