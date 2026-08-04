# REPORT — In-Page Agent, Phases A–D + Live Hardening (2026-07-10 → 07-11)

> Closes the build rounds of `PLAN_inpage_agent_parity.md` Phases A–D on branch
> `feat/voice-web-integration`. Phase E (head-to-head eval vs page-agent) is the
> only remaining phase; branch `page-agent-clean-eval` stays frozen as its test
> bed. Per fork policy §1: this is the durable, committed record.

## What was built

เป้าหมาย: สร้าง in-page agent (observe→think→act) ของเราเอง แทนการพึ่ง
Alibaba page-agent เป็น dependency — สมองอยู่ server (บังคับ trust model ได้จริง,
voice-native), มือ-ตาอยู่ browser ต่อยอด dom_tree ที่ vendor ไว้

### Phase B — สมอง (`deeptutor/services/voice_realtime/agent/`) — `9b87f91e`

`loop.py` (reflection-only history, DOM สดทุก step, budget 15 / delay 0.8s,
abort), `macro_tool.py` (แคตตาล็อก 7 actions + validation), `fixer.py`
(autoFixer ครบ 6 heuristics), `prompt.py` (voice-first, สองภาษา),
`observations.py` (URL change / wait / budget `<sys>` notes), `llm.py`
(`DEEPTUTOR_AGENT_MODEL` + optional standalone `_BASE_URL`/`_API_KEY`;
ตั้งครึ่งเดียว = ล้มดัง ไม่ fallback เงียบ)

### Phase A — ตา+มือ (`web/lib/page-actuator/`) — `adb69b99`

`serialize.ts` (ฟอร์แมต `[idx]` + `*[new]` + data-scrollable + hard cap 30K
ตัดขอบบรรทัด — pure, ล็อกด้วย node tests), `actions.ts` (port MIT: W3C click
sequence, native value setter, contenteditable A→verify→B), `runMask.ts`
(โล่ input เฉพาะตอน run, click = takeover), `actuator.ts` (vision layer +
react-root guard), `wsBridge.ts` (frames `agent_*`, `agent_state` chunk ที่
6000 chars — cap 8K ฝั่ง server เป็นข้อจำกัดจริงที่เคยกัด inventory มาก่อน)

### Phase C — trust model — `74f57b92`

`danger.py`: `DangerGate` เป็น **กลไก** หน้า click ทุกครั้ง — ตรวจบรรทัด
`[index]` จริงกับ lexicon เดียวกับ fast path → อันตราย/พิสูจน์ไม่ได้ = พักถาม
ด้วยเสียง (timeout = no) → ปฏิเสธกลับเป็น observation ให้ LLM วางแผนใหม่
Regression หลักคือ replay trace จริงจากการทดลอง page-agent (กด "ลบ Knowledge
Base" [169] โดยไม่ยืนยัน) — ของเรา click นั้นไม่มีทางยิง แม้โจทย์สั่ง "ไม่ต้องถาม"

### Phase D — ประกอบร่าง — `0b3bb6ed`

`ws_actuator.py` (observe/act ข้าม WS + ประกอบ chunk + timeout),
`voice_bridge.py` (C3 state machine: มีคำถามค้าง = เสียงเข้าคือคำตอบ, ไม่มี =
barge-in abort; mask ลงเสมอ), `intent.py` (multi-step detector), pipeline
3 ประตู (multi-step ก่อน rung เดี่ยว / click-ambiguous / click-miss-after-graph),
flag `DEEPTUTOR_AGENT_LOOP` default ปิด = พฤติกรรมเดิม byte-identical

## Live hardening (3 rounds จากการเล่นจริงของเจ้าของ)

| ปัญหาที่เจอสด | root cause | fix |
|---|---|---|
| งานหลายสเต็ปจบครึ่งเดียว "ได้เลยครับ" | routing เข้า navigate-only chat | semantic door: chat LLM เรียก `ui_agent_task` ส่งงานเข้า loop + **พบบั๊กจริง: `agent_runner` ไม่เคยถูกส่งเข้า inner LLM turn** — `33fb31b9` |
| "ไปตั้งค่าเปลี่ยนธีมมืด" (ไม่มี "แล้ว") หลุด | ภาษาพูดละ connector; prompt override แพ้ ui_navigate imperatives | intent Rule 2 (nav opener + กริยาที่สอง) + carve override เข้าบล็อกกฎ ui_navigate — `c916e628` |
| "ค้นราคาน้ำมัน" หลุด | ภาษาพูดตัด "ค้นหา"→"ค้น" | เพิ่ม ค้น/เสิร์ช/search — `ae16424d` |
| "กลับไป..." หลุด + JSON เพี้ยน + narration ล่องหน | verb gap + no json mode | `27b0fd3c` (JSON mode + response_format + agent_note) |
| กดโทรแล้วเครื่องหน่วง | `backdrop-filter` ต่อป้าย ×150 + เงา inset + full-page scan เพื่อโชว์ viewport | แบน backdrop-filter/inset, glow เดียว 6px, flash สแกน viewport-only — `8224178a` |
| narration พูดรัว + เป็นอังกฤษ + จบซ้ำสองรอบ | พูดทุก step; schema ไม่ระบุภาษา | step = โน้ตเงียบ, พูดเฉพาะคำถาม+สรุปจบครั้งเดียว, ภาษาบังคับใน schema — `0557c3f2` |
| 429 ค้างหลายนาที | retry 9× ทบ RPM (free tier 5 RPM; page-agent retry 2×) | `max_retries=1` fail-fast — `70935e29` |
| UX เสริม | — | neon restyle `dcaf4a66`, soft fade `5574cf84`, eyes-open flash `43e697b4`, upstream log `7b6588fa` |

## Deviations from plan (ทั้งหมดมีเหตุจากโค้ด/การใช้จริง)

1. **B3**: JSON-contract + fixer เป็นเส้นหลัก แทน native forced tool_choice —
   `services.llm.complete()` คืน text เท่านั้น; เสริม `response_format=json_object`
2. **D0**: flag เป็น env (`DEEPTUTOR_AGENT_LOOP`) แทน settings key — สวิตช์บอร์ด
   เดียวกับ config agent ที่เป็น env อยู่แล้ว
3. **D2**: เพิ่มประตู semantic (`ui_agent_task`) ที่แผนเดิมทำเป็น lexical อย่างเดียว —
   บทเรียนสด: ดักคำไม่มีวัน converge; แต่ก็พบว่า**ประตู semantic แข็งแรงตามคุณภาพ
   โมเดล routing** (Groq gpt-oss-120b เมิน override 2 ครั้ง) — deterministic ยังเป็น
   เส้นหลักที่ไว้ใจได้
4. **C4**: "คุมความถี่ narration" กลายเป็น "ไม่พูดเลยระหว่าง step" ตาม verdict จริง
5. **C1**: danger ตรวจจาก `extract_element_line` ฝั่ง server แทนส่ง elementTextMap
   ข้าม WS — ผลเท่ากัน frame น้อยกว่า

## State at close

- เทสต์: voice suite **408**, web node **197**, ruff/tsc/eslint เขียว
- Flag ปิด = เสียงเดิมทุกประการ (พิสูจน์ด้วย suite เดิมผ่านไม่แตะ)
- Live: งาน "ค้นราคาทอง" วิ่งจบจริง end-to-end (5 steps, คำตอบถูก); อุปสรรค
  ที่เหลือเป็นเรื่อง quota free tier ไม่ใช่โค้ด
- ค้างโดยรู้ตัว: `actions.ts` ไม่มีเทสต์อัตโนมัติ (ไม่มี jsdom; พิสูจน์ผ่าน live),
  multi-tab / per-page instructions = non-goal

## Next: Phase E (เฟสเดียวที่เหลือ)

ชุดโจทย์ ~10 ข้อ รันชน page-agent จริงบน `page-agent-clean-eval` เก็บ
success/steps/tokens/เวลา → REPORT → ตัดสินชะตา `ui_graph.py` (D4)
เงื่อนไข: quota Gemini reset หรือใช้ NVIDIA key / เปิด billing (Tier 1 = 150-300 RPM,
3.5 Flash $1.50/$9.00 ต่อ 1M tokens ≈ ฿3-4 ต่องาน)
