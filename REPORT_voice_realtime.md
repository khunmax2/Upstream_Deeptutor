# รายงานปิดรอบ — Voice Call (Realtime) Production Integration

> prototype (`voice_prototype/`) → production realtime I/O layer ใน `deeptutor/`

---

## รอบ/Phase: Voice realtime integration | วันที่: 2026-06-30 | branch: `feat/voice-prototype`

### 1. TL;DR
- สถานะ: ✅ realtime voice layer ลงจริงใน `deeptutor/` แบบ **additive** ทั้งหมด —
  เพิ่มไฟล์ใหม่เป็นหลัก, แตะ upstream แค่ 2 ไฟล์ (registry dict + `main.py` 1 บรรทัด) + 1 catalog spec
- **หลักการที่รักษาไว้:** reuse `ChatOrchestrator.handle()` ตรง + consume `StreamBus` `CONTENT`
  tokens เอง (bypass partner `MessageBus`) → ได้ per-sentence TTS + barge-in. STT/TTS reuse
  facade `transcribe_audio` / `synthesize_speech` (catalog-driven) ตามที่ตกลง
- **ยังไม่ผูก** capability/partner ใหม่ — เป็น layer แยกตาม design
- 5 commits แบบ Conventional Commits + รอบนี้ปิดด้วย CHANGES.md + REPORT นี้

### 2. Scope ที่ทำจริง
- พอร์ต `SentenceChunker` → `deeptutor/services/voice_realtime/chunker.py`
- เพิ่ม ElevenLabs/BOTNOI TTS adapters (catalog-integrated)
- `pipeline.run_turn()` + `VoiceSession` (barge-in) + `vad.py` (shared constants)
- WebSocket `/api/v1/voice/ws` + wire ใน `main.py`
- เทสต์ครบทุกชั้น (chunker / pipeline CONTENT-gating / session barge-in / adapters / WS routing)

### 3. ไฟล์ที่แตะ
**เพิ่มใหม่ (source):**
- `deeptutor/services/voice_realtime/__init__.py`, `chunker.py`, `vad.py`, `pipeline.py`, `session.py`
- `deeptutor/services/voice/adapters/bespoke.py` (ElevenLabs + BOTNOI)
- `deeptutor/api/routers/voice_realtime.py`

**เพิ่มใหม่ (tests):**
- `tests/services/voice_realtime/test_chunker.py`, `test_pipeline.py`, `test_session.py`
- `tests/services/test_voice_bespoke.py`
- `tests/api/test_voice_realtime_ws.py`

**แก้ upstream (minimal, mergeable):**
- `deeptutor/services/voice/adapters/__init__.py` — register 2 adapter keys
- `deeptutor/services/config/provider_runtime.py` — เพิ่ม `elevenlabs` / `botnoi` ใน `TTS_PROVIDERS`
- `deeptutor/api/main.py` — 1 บรรทัด `include_router(voice_realtime.router, …)`

**เอกสาร:** `CHANGES.md` (extend Voice section), `REPORT_voice_realtime.md` (ใหม่)

**Working-tree (ไม่ commit):** จัด `ruff format` / import-order ให้ `voice_prototype/` เพื่อให้
`ruff check .` + `ruff format --check .` เขียวทั้ง repo (prototype ยัง uncommitted — ปล่อยไว้ให้
เจ้าของรอบ prototype commit เอง)

### 4. การออกแบบที่สำคัญ (decisions)
| จุด | เลือก | เหตุผล |
|---|---|---|
| STT/TTS | facade `transcribe_audio`/`synthesize_speech` | resolve config จาก admin catalog เหมือน REST `/voice`; Groq STT + OpenAI/Groq TTS ใช้ได้ทันที |
| ElevenLabs/BOTNOI | catalog-integrated | เลือกจาก Settings > Voice; แตะ upstream น้อยสุด (dict + spec) |
| พูดเฉพาะคำตอบสุดท้าย | gate `call_kind == "llm_final_response"` | กฎเดียวกับ `PartnerRunner` — ไม่พูด narration/tool rounds |
| barge-in | `VoiceSession` cancel in-flight task | utterance ใหม่/`barge` frame ยกเลิกเทิร์นทันที, ไม่ commit history |
| `vad.py` | thin shared constants | browser เป็นเจ้าของ VAD ใน MVP |

### 5. ผล Test Gate
| คำสั่ง | ผล | หมายเหตุ |
|---|---|---|
| `ruff check .` | ✅ | All checks passed (รวม prototype หลังจัด import) |
| `ruff format --check .` | ✅ | 912 files already formatted |
| `pytest` voice set (5 ไฟล์ใหม่ + voice เดิม) | ✅ | **46 passed** (chunker/pipeline/session/adapters/WS + regression voice เดิม) |
| `pre-commit run mypy` (source ใหม่) | ✅ | Passed (router อยู่ใน mypy-exclude เดิม) |
| app import + route wiring | ✅ | `/api/v1/voice/ws` ลง APIWebSocketRoute (lazy `_IncludedRouter` ของ FastAPI 0.138) |
| `graphify update .` | ✅ | 20801 nodes / 50440 edges (graphify-out gitignored) |

**หมายเหตุ — pre-commit `bandit`:** ❌ config error `Unknown test in profile: B104/B105` —
**pre-existing/version mismatch ทั้ง repo** (fail เหมือนกันบนไฟล์ upstream เดิม
`voice/adapters/openai_compat.py`) ไม่ใช่ regression ของรอบนี้

### 6. ที่เหลือ / Phase ถัดไป (ไม่อยู่ใน scope รอบนี้)
- ฝั่ง `web/`: ย้าย mic capture + VAD/barge-in client จาก prototype `static/index.html` เข้า Next.js
- streaming STT (ตอนนี้ batch-on-endpoint), WebRTC transport (ตอนนี้ WebSocket)
- ElevenLabs streaming TTS จริง, ตรวจ BOTNOI endpoint/field กับ docs ปัจจุบันก่อน production
- (ออปชัน) แก้ bandit profile config ที่ B104/B105 ให้ตรง version — เป็น repo-wide ไม่เกี่ยว voice
