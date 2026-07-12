# งานเสียง DeepTutor — แผนที่ทั้งหมด (Voice feature map)

เอกสารนี้บอกว่า "ส่วนไหนของงานเสียงอยู่ตรงไหน" เพื่อให้หา/แก้ได้เร็ว โค้ดจริงกระจาย
อยู่หลายที่ในรีโป (backend pipeline, agent loop, API, frontend, eval, tests) — ตาราง
ข้างล่างรวมไว้ที่เดียว
_(อัปเดต 2026-07-13)_

> **หมายเหตุประวัติ**: เดิมมีโฟลเดอร์ `voice_prototype/` เป็น standalone bench
> (หน้า `call.html` ที่คุยตรงกับ WS) — ถูกลบเมื่อ 2026-07-13 หลังของดีย้ายเข้าแอปจริง
> หมดแล้ว (`VoiceCallWidget.tsx`) และงาน in-page agent ทั้งหมดรันบนแอป Next.js
> เท่านั้น ดูบันทึกใน `CHANGES.md`

---

## ภาพรวมการไหลของข้อมูล

```
[Browser] mic → VAD → STT ──WS──▶ [Backend]
                                     pipeline.run_text_turn (ตัวจัดเส้นทาง turn)
                                       1) pre-gates (stop / dictation / pending)
                                       2) free fast-path (keyword จับ nav/click — 0 token)
                                       3) ★ intent classifier  → { chat | ui_task }   ← A1 (flagged)
                                            ├ chat    → ChatOrchestrator (RAG/tools)
                                            └ ui_task → in-page agent loop (observe→think→act)
                                       → per-sentence TTS ──WS──▶ [Browser] ลำโพง + mascot
```

**การตัดสินใจดีไซน์**: งานเสียงเป็น *realtime I/O layer แยกต่างหาก* ไม่ใช่ Partners
channel — เรียก `ChatOrchestrator` ตรงๆ (ข้าม `MessageBus` แบบ turn-based) เพื่อให้
stream token เข้า per-sentence TTS และรองรับ barge-in ได้ โค้ดทั้งหมดเป็น additive/isolated

---

## 1) Backend — pipeline หลัก  `deeptutor/services/voice_realtime/`

| ไฟล์ | หน้าที่ |
|---|---|
| `pipeline.py` | **หัวใจ** — ตัวจัดเส้นทาง turn (`run_text_turn`): ladder pre-gates → fast-path → classifier → chat/loop |
| `intent_classifier.py` | **(ใหม่, A1)** ตัวจำแนกความหมาย `chat` vs `ui_task` เป็น router หลัก (คุมด้วย flag `DEEPTUTOR_VOICE_CLASSIFIER`) |
| `session.py` | สถานะต่อ 1 สาย (dictation mode, pending click/confirm ฯลฯ) |
| `ui_control.py` | keyword rungs สำหรับ nav/click แบบ deterministic (fast-path เดิม) |
| `ui_graph.py` / `ui_graph.json` | กราฟหน้า/ปุ่มที่นำทางได้ (ชะตากรรมรอสรุปใน D4) |
| `narration.py` | ประโยค filler/ให้กำลังใจตอนบอทเงียบ (เช่น "ขอค้นข้อมูลสักครู่") |
| `chunker.py` | ตัดข้อความเป็นประโยคเพื่อส่ง TTS ทีละประโยค |
| `stt_guard.py` | กรอง STT: bias คำศัพท์ + confidence + กัน hallucination |
| `vad.py` | ตัวช่วย voice-activity detection |

## 2) In-page agent loop  `deeptutor/services/voice_realtime/agent/`

สมองฝั่ง server ที่ขับ UI แบบ observe→think→act (คำสั่งหลายสเต็ป)

| ไฟล์ | หน้าที่ |
|---|---|
| `loop.py` | `InPageAgentLoop` — ตัวขับ observe→think→act |
| `llm.py` | `think()` เรียก LLM + log token usage (`complete_with_usage`) |
| `prompt.py` | system prompt ของ loop |
| `intent.py` | free short-circuit: คำสั่งนี้ควรเข้า loop ไหม (Phase D2) |
| `fixer.py` | ทำ action JSON เละๆ จาก LLM ให้เข้ารูป (7 heuristics) |
| `danger.py` | `DangerGate` (`pre_act`) — ด่านความปลอดภัยจริง |
| `macro_tool.py` | catalog + validation ของ action ตัวเดียวต่อ turn |
| `observations.py` | `<sys>` notes ที่ loop เขียนกลับให้ LLM |
| `types.py` | `BrowserState` / `ActResult` ฯลฯ |
| `ws_actuator.py` | `WsPageActuator` — ฝั่ง server ของ frame protocol |
| `voice_bridge.py` | `AgentVoiceBridge` — เชื่อม loop เข้ากับ turn เสียง 1 session |

## 3) API routers  `deeptutor/api/routers/`

| ไฟล์ | หน้าที่ |
|---|---|
| `voice_realtime.py` | WebSocket `/api/v1/voice/ws` — endpoint ของ "สายสด" (STT → orchestrator → per-sentence TTS) |
| `voice.py` | HTTP TTS/STT บางๆ (โครงสร้างพื้นฐานที่แชร์ทั้งระบบ) |

## 4) Frontend  `web/`

| path | หน้าที่ |
|---|---|
| `components/voice/VoiceCallWidget.tsx` | **UI สายจริงในแอป** (mic, VAD, barge-in, mascot 3D) — mount ที่ `web/app/layout.tsx` |
| `components/voice/VoiceActionBridge.tsx` | ต่อ agent act → หน้าเว็บ |
| `components/voice/pageContext.ts` | สร้าง context ของหน้า (ป้อน classifier/loop) |
| `components/voice/pageInventory.ts` | inventory ของ element บนหน้า |
| `components/voice/simulatorCursor.ts` | เคอร์เซอร์จำลองให้เห็นตอน act |
| `components/voice/speechAlternatives.ts` | จัดการ speech alternatives |
| `components/voice/dom_tree/{engine.ts,type.ts}` | เครื่องมือ serialize DOM tree |
| `hooks/useVoiceRecorder.ts` · `useVoiceAutoplay.ts` | อัดไมค์ + เล่นเสียงตอบอัตโนมัติ |
| `lib/page-actuator/` | **มือของ loop** ฝั่งเบราว์เซอร์ (ดูตารางย่อยข้างล่าง) |

`web/lib/page-actuator/`

| ไฟล์ | หน้าที่ |
|---|---|
| `serialize.ts` | serialize หน้า → element มี index (สายตาของ loop) |
| `actions.ts` | primitive: click / type / ฯลฯ |
| `actuator.ts` | จุดรวม actuator |
| `wsBridge.ts` | client ของ frame protocol (`agent_observe`/`agent_act`/`agent_state_chunk`) |
| `runMask.ts` · `neonHighlights.ts` | mask + ไฮไลต์ตอนทำงาน |

## 5) Eval  `eval/inpage_agent/`

head-to-head harness ของ loop บนแอปสด

| ไฟล์ | หน้าที่ |
|---|---|
| `browser_host.mjs` | Playwright + HTTP bridge (goto/observe/act/probe) — เปิด Chromium จริง |
| `run_ours.py` | รัน loop ผ่าน `HttpActuator` (resumable) |
| `run_voice_live.py` | **end-to-end**: transcript → classifier → ui_task → loop บนแอปสด (รับช่วง bench เดิม) |
| `run_pageagent.mjs` | คู่เทียบ page-agent (DEFERRED — hang ตอน observe หลัง nav) |
| `tasks.json` · `make_table.py` | ชุดงานมาตรฐาน + สรุปตาราง |

## 6) Tests

- **Python**: `tests/services/voice_realtime/` (+ `agent/`) — `test_pipeline`, `test_intent_classifier`,
  `test_ui_control`, `agent/test_loop`, `test_fixer`, `test_llm_scope`, `test_wiring` ฯลฯ
- **Node**: `web/tests/voice-*.test.ts`, `web/tests/page-actuator-serialize.test.ts`

## 7) Config + docs

| path | หน้าที่ |
|---|---|
| `.env.agent` (ตัวอย่าง: `.env.agent.example`) | env ของ loop + classifier (`DEEPTUTOR_VOICE_CLASSIFIER*`, `DEEPTUTOR_AGENT_*`) — **มี API key, gitignored** |
| Settings > Voice (ในแอป) | LLM/STT/TTS ของ "สายปกติ" — คนละที่กับ env ของ loop/classifier |
| `docs/issues/voice-intent-classifier/PRD.md` | ดีไซน์ A1 (classifier เป็น router หลัก) |
| `docs/issues/inpage-agent-grounding/` | ช่องโหว่ grounding ของ loop จากการทดสอบสด (issues 01/02) |
| `docs/issues/llm-provider-adaptation/PRD.md` | ปรับ LLM param ตาม provider (part 1 เสร็จ) |
| `docs/reports/REPORT_voice_*.md` · `docs/planning/DESIGN_voice_grounding.md` | รายงาน/ดีไซน์ย้อนหลัง |

---

## backlog ที่ค้าง (ณ 2026-07-13)

- **page-agent E4 column** — harness พร้อม แต่ page-agent hang ตอน observe หลัง nav ต้องรันผ่าน dev mount
- **provider-adaptation part 2** — config-source = settings+env (เตรียมพร้อม UI); part 1 (host-based reasoning drop) เสร็จแล้ว
- **inpage-agent-grounding** — (01) loop ต้อง verify ว่าถึงปลายทางที่ตั้งใจก่อนอ้าง success; (02) `serialize.ts` fallback ไป accessible name สำหรับลิงก์ไอคอนล้วน
- **Gemini context caching** — วัด cost/latency ของ implicit caching ให้ loop (รอ billing)
