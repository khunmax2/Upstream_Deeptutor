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
[Browser] mic → VAD → STT ─┐
   กล่องพิมพ์ใน call widget ─┼─WS(voice)─▶ [Backend]  ← ทั้งพูดและพิมพ์-ใน-widget เข้าเส้นเดียวกัน
   (type_text = browser STT)┘             pipeline.run_text_turn (ตัวจัดเส้นทาง turn)
                                            1) pre-gates (stop / dictation / pending)
                                            2) free fast-path (keyword จับ nav/click — 0 token)
                                            3) graph plan / confirm-ask (ui_graph)
                                            4) ★ intent classifier → { chat | ui_task | unclear }  ← A1 (flagged)
                                                 ├ unclear → ขอให้พูดใหม่ (ไม่แตะ RAG/loop)
                                                 ├ ui_task → in-page agent loop (observe→think→act)
                                                 │            └ ★ hard grounding: เช็ค landed route
                                                 │               vs target ที่ task ระบุ ก่อนอ้าง success
                                                 └ chat   → ★ kb_router (flagged) → { meta | unrelated | content }
                                                              ├ meta      → ตอบจาก KB manifest (ไม่ต้อง RAG)
                                                              ├ unrelated → ChatOrchestrator, RAG ปิด (knowledge_bases=[])
                                                              └ content   → ChatOrchestrator (RAG/tools ปกติ)
                                            → per-sentence TTS ──WS──▶ [Browser] ลำโพง + mascot
```

**การตัดสินใจดีไซน์**: งานเสียงเป็น *realtime I/O layer แยกต่างหาก* ไม่ใช่ Partners
channel — เรียก `ChatOrchestrator` ตรงๆ (ข้าม `MessageBus` แบบ turn-based) เพื่อให้
stream token เข้า per-sentence TTS และรองรับ barge-in ได้ โค้ดทั้งหมดเป็น additive/isolated

**สองเส้นตาม surface/WebSocket (สำคัญเวลา debug "ทำไมไม่ผ่าน guard")**: input จาก
**call widget** — ทั้งพูด (`handle_utterance` → server STT) และพิมพ์ในกล่องของ widget
(`{type:"user_text"}` → `handle_text`, browser STT) — วิ่งเข้า **voice pipeline** (ได้ rung
fast-path/classifier/kb_router/loop ครบ) ส่วน **กล่องแชตหลักหน้าโฮม** วิ่งเข้า
`ChatOrchestrator` ตรงๆ **ไม่ผ่าน rung เหล่านี้** — เส้นแยกกันที่ surface/WS ไม่ใช่เสียง-vs-พิมพ์

---

## 1) Backend — pipeline หลัก  `deeptutor/services/voice_realtime/`

| ไฟล์ | หน้าที่ |
|---|---|
| `pipeline.py` | **หัวใจ** — ตัวจัดเส้นทาง turn (`run_text_turn`): ladder pre-gates → fast-path → graph → classifier → kb_router → chat/loop |
| `intent_classifier.py` | **(A1)** ตัวจำแนกความหมาย `chat` / `ui_task` / `unclear` เป็น router หลัก (`unclear` = พูดมั่ว/ขาด → ขอพูดใหม่ ไม่แตะ RAG; คุมด้วย flag `DEEPTUTOR_VOICE_CLASSIFIER`) |
| `kb_router.py` | **(ใหม่, layer-2)** สำหรับ turn `chat`: ตัดสินจาก KB manifest ว่า `meta` (ถามเรื่องคลัง→ตอบจาก manifest) / `unrelated` (ปิด RAG) / `content` (RAG ปกติ) — กัน always-RAG (flag `DEEPTUTOR_VOICE_KB_ROUTING`) |
| `session.py` | สถานะต่อ 1 สาย (dictation mode, pending click/confirm ฯลฯ); `handle_utterance` (server STT) + `handle_text` (browser STT / พิมพ์ใน widget) → บรรจบที่ `run_text_turn` |
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
| `loop.py` | `InPageAgentLoop` — ตัวขับ observe→think→act; ก่อนอ้าง `done.success` ทำ **hard grounding** (issue 01): เทียบ landed URL vs target ที่ task ระบุ, ไม่ตรง→บังคับ `success=false` (`stopped_reason="grounding_miss"`) |
| `route_grounding.py` | **(ใหม่, issue 01)** แหล่ง truth อิสระ: `resolve_target_route(task)` (deterministic, exact/substring + length tie-break, ambiguous/non-nav→`None`), `landed_path`, `path_satisfies` (sibling-safe) |
| `route_manifest.json` | **(ใหม่)** route→aliases ที่ curate (seed จาก `web/lib/settings-nav.ts`+UI_PAGES) — แยกจาก `ui_graph.json` (คนละบทบาท: อันนี้ grounding, ui_graph คือ open_path whitelist); parity-tested ที่ `web/tests/voice-route-manifest-parity.test.ts` |
| `llm.py` | `think()` เรียก LLM + log token usage; env helpers (`hard_grounding_enabled`, step_delay/max_steps override, binding) |
| `prompt.py` | system prompt ของ loop |
| `intent.py` | free short-circuit: คำสั่งนี้ควรเข้า loop ไหม (Phase D2) |
| `fixer.py` | ทำ action JSON เละๆ จาก LLM ให้เข้ารูป (7 heuristics) |
| `danger.py` | `DangerGate` (`pre_act`) — ด่านความปลอดภัยจริง (danger words + `is_expensive_commit`) |
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
  `test_kb_router`, `test_ui_control`, `agent/test_loop`, `agent/test_route_grounding`, `agent/test_danger`,
  `test_fixer`, `test_llm_scope`, `test_voice_bridge`, `test_wiring` ฯลฯ
- **Node**: `web/tests/voice-*.test.ts` (รวม `voice-graph-parity`, `voice-route-manifest-parity`,
  `voice-manifest-parity`), `web/tests/page-actuator-serialize.test.ts`

## 7) Config + docs

| path | หน้าที่ |
|---|---|
| `.env.agent` (ตัวอย่าง: `.env.agent.example`) | env ของ loop + classifier (`DEEPTUTOR_VOICE_CLASSIFIER*`, `DEEPTUTOR_AGENT_*`) — **มี API key, gitignored** |
| loop tuning (env) | `DEEPTUTOR_AGENT_STEP_DELAY` / `DEEPTUTOR_AGENT_MAX_STEPS` — ปรับ latency/step budget ได้ต่อ deployment (ว่าง = default 0.8s / 15 step) |
| feature flags (env) | `DEEPTUTOR_VOICE_CLASSIFIER` (เปิด A1 router), `DEEPTUTOR_VOICE_KB_ROUTING` (เปิด layer-2 kb_router), `DEEPTUTOR_AGENT_HARD_GROUNDING` (**เปิด default**; ตั้ง 0/false เพื่อ rollback เป็น prompt-only) |
| provider binding (env) | `DEEPTUTOR_AGENT_BINDING` / `DEEPTUTOR_VOICE_CLASSIFIER_BINDING` — บังคับ provider spec ตาม endpoint (เช่น `openai` สำหรับ Groq) กัน model-name misroute; ว่าง = infer ตามชื่อโมเดล (Gemini ไม่กระทบ) |
| Settings > Voice (ในแอป) | LLM/STT/TTS ของ "สายปกติ" — คนละที่กับ env ของ loop/classifier |
| `docs/issues/voice-intent-classifier/PRD.md` | ดีไซน์ A1 (classifier เป็น router หลัก) |
| `docs/issues/kb-content-routing/PRD.md` | ดีไซน์ layer-2 KB routing (`unclear` bucket + kb_router meta/unrelated/content) |
| `docs/issues/inpage-agent-grounding/` | ช่องโหว่ grounding ของ loop จากการทดสอบสด (issues 01 hard-grounding **เสร็จ** / 02 serialize labels / 03 form-commit) |
| `docs/issues/llm-provider-adaptation/PRD.md` | ปรับ LLM param ตาม provider (part 1 + endpoint binding เสร็จ; thinking-disable ค้าง) |
| `docs/reports/REPORT_voice_*.md` · `docs/planning/DESIGN_voice_grounding.md` | รายงาน/ดีไซน์ย้อนหลัง |

---

## backlog ที่ค้าง (ณ 2026-07-13)

- **live full-path e2e (grounding 01 + 03)** — mechanism ทั้งคู่เสร็จ+unit-tested แล้ว เหลือ replay สดให้เห็น/ได้ยิน (issue-01 landing ผิด→ได้ยิน honest miss; issue-03 ask→fill→stop-at-commit) — ติด full-tier model 503 (รอคลาย หรือ pro/Groq)
- **thinking-disable Gemini** (provider-adaptation part 2 ที่เหลือ) — gemini flash พ่น reasoning นำหน้า JSON ทำ fixer พังแม้ `reasoning_effort=minimal`
- **page-agent E4 column** — harness พร้อม แต่ page-agent hang ตอน observe หลัง nav ต้องรันผ่าน dev mount
- **Gemini context caching** — วัด cost/latency ของ implicit caching ให้ loop (รอ billing)

> **เสร็จแล้ว (อ้างอิง)**: inpage-agent-grounding 01 (hard grounding, deterministic-tested) + 02 (serialize accessible-name) + 03 gap1/2 (expensive-commit gate + wired harness); KB-aware routing 3 phase; A1 classifier; provider-adaptation part 1 + endpoint binding — ดู `CHANGES.md`
