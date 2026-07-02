# Voice Call Prototype (standalone)

พิสูจน์ pipeline **Mic → STT → LLM → TTS → ลำโพง** แบบ realtime-ish โดยยังไม่ผูกเข้า
DeepTutor เต็มตัว ทุกไฟล์อยู่นอก package `deeptutor/` (merge กับ upstream ไม่ชน)

```
Browser (mic + energy-VAD endpointing + barge-in)
   │  ส่ง 1 utterance (webm) ต่อรอบ ผ่าน WebSocket
   ▼
server.py  ──►  STT (Groq Whisper)  ──►  LLM (OpenAI-compatible, stream)
                                              │ token-by-token
                                              ▼
                                   SentenceChunker  ──►  TTS ต่อประโยค
                                              │
                                              ▼  ส่ง mp3 กลับทันทีประโยคแรก
                                          ลำโพง
```

แนวคิดหลัก: **เริ่มพูดประโยคแรกตั้งแต่ LLM ยังพิมพ์ไม่จบ** (per-sentence TTS) →
รู้สึกเหมือนโทรคุย ไม่ใช่อัดแล้วรอ

## 🚀 MVP — เล่นได้จริงเร็วสุด (ไม่ต้องมี key STT/TTS)

โหมดนี้ให้ **เบราว์เซอร์ทำ STT/TTS เอง** (Web Speech API, ภาษาไทย) — ต้องมีแค่ DeepTutor
endpoint เป็นสมอง ไม่ต้องมี Groq/TokenMind/อะไรทั้งนั้น

```bash
cd voice_prototype
pip install -r requirements.txt
# ตั้ง .env ให้ LLM_BASE_URL/LLM_MODEL ชี้ DeepTutor OpenAI-compatible wrap ของคุณ
set -a; source .env; set +a
python server.py
```

เปิด **Chrome/Edge** ที่ `http://127.0.0.1:8800/mvp` → กด "เริ่มสนทนา" → อนุญาตไมค์ → พูดไทยได้เลย
ระบบถอดเสียง → ส่งเข้า DeepTutor (stream) → พูดตอบกลับทีละประโยค. ใส่หูฟังแล้วติ๊ก
"โหมดหูฟัง" เพื่อพูดแทรก (barge-in). พอ key TokenMind มา ค่อยสลับไปโหมด server-side ด้านล่าง

---

## ติดตั้ง (โหมดเต็ม: server-side STT/TTS)

```bash
cd voice_prototype
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # แล้วกรอกคีย์
```

`.env` ที่ต้องกรอก:
- `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` — ชี้ไป DeepTutor wrap (OpenAI-compatible)
- `GROQ_API_KEY` — STT (สมัครฟรีที่ console.groq.com)
- `TTS_BACKEND` + คีย์ของ backend นั้น (`openai` / `elevenlabs` / `botnoi`)

## รัน

```bash
set -a; source .env; set +a        # โหลด env เข้า shell
python server.py                   # เปิด http://127.0.0.1:8800
```

เปิดเบราว์เซอร์ → กด **เริ่มสนทนา** → อนุญาตไมค์ → พูดภาษาไทย หยุดพูด ~0.7s
ระบบจะถอดเสียง ส่งเข้า LLM แล้วพูดตอบกลับ. พูดแทรกระหว่างมันตอบได้ (barge-in หยุดเสียงเดิม)

แถบบนจะโชว์ latency แต่ละ stage: **STT · LLM TTFT · TTS ประโยคแรก · เสียงแรก · รวม**

## ทดสอบโดยไม่มีไมค์

```bash
# ครึ่ง LLM+TTS กับ endpoint จริง (วัด latency จริง)
python selftest.py "อธิบายทฤษฎีบทพีทาโกรัสสั้นๆ"

# logic ล้วน ไม่ต่อเน็ต (chunker + คุณสมบัติ flush ประโยคแรกก่อนจบ)
python tests/test_pipeline.py
```

## ขอบเขต prototype นี้ (รู้ไว้ก่อน)
- STT เป็น **batch-on-endpoint** (อัดจบประโยคแล้วส่ง) ไม่ใช่ streaming STT — Phase 2
- transport เป็น **WebSocket** ตามที่ตกลง — WebRTC (`aiortc`) ไว้ Phase 2 เมื่อลงมือถือ/เน็ตเสีย
- TTS ยิงทีละประโยค (per-sentence) — provider-agnostic; ElevenLabs streaming จริงไว้ทีหลัง
- BOTNOI adapter ใส่ไว้แบบ best-effort — **ต้องเช็ค endpoint/field กับ docs ปัจจุบันก่อนใช้จริง**
- ยังไม่ผูก `ChatOrchestrator` — ใช้ OpenAI-compatible endpoint ตรงๆ (ตามแผน Step 3)

## map ไป production (Step 2 architecture)
| ไฟล์ prototype | จะกลายเป็น |
|---|---|
| `server.py` (WS) | `deeptutor/api/routers/voice_realtime.py` |
| `pipeline.py` | `deeptutor/services/voice_realtime/{pipeline,chunker}.py` |
| stage STT/TTS | reuse `deeptutor/services/voice/` adapters (+ BOTNOI/ElevenLabs ใหม่) |
| client VAD/barge-in | ฝั่ง `web/` |
