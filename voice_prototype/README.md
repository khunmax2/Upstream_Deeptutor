# DeepTutor Voice Call — หน้าโทรคุย (call.html)

หน้าเว็บสำหรับ **โทรคุยเสียงกับ DeepTutor** (Mic → STT → ChatOrchestrator → TTS →
ลำโพง) พร้อม mascot 3D ที่ขยับปากตามเสียงจริง โฟลเดอร์นี้เหลือแค่ **static host
บางๆ** — ตัว pipeline จริงทั้งหมดอยู่ฝั่ง production ใน
`deeptutor/services/voice_realtime/` + `deeptutor/api/routers/voice_realtime.py`

```
Browser (call.html: mic + VAD + barge-in + mascot 3D)
   │  WebSocket
   ▼
DeepTutor  ws://localhost:8011/api/v1/voice/ws
   │  STT (Settings > Voice) → ChatOrchestrator (RAG/tools) → per-sentence TTS
   ▼
เสียงตอบกลับ streaming ทีละประโยค (+ filler "ขอค้นข้อมูลสักครู่" ตอนใช้ tool)
```

server.py ในโฟลเดอร์นี้มีหน้าที่เดียว: เสิร์ฟ `static/call.html` จาก origin
`http://localhost` (เบราว์เซอร์ไม่ยอมให้หน้า `file://` ใช้ไมค์)

## วิธีรัน

```bash
# 1) รัน DeepTutor (สมอง + STT/TTS ตาม Settings > Voice)
deeptutor serve --port 8011

# 2) รันหน้า call
cd voice_prototype
pip install -r requirements.txt   # แค่ fastapi + uvicorn
python server.py                  # default 127.0.0.1:8800
```

เปิด **Chrome** ที่ `http://127.0.0.1:8800/` → กด "📞 เริ่มสาย" → อนุญาตไมค์ → พูดไทยได้เลย
(ถ้า DeepTutor รันพอร์ตอื่น: `http://127.0.0.1:8800/?port=NNNN`)

- โหมดไมค์ **browser** — Web Speech API ถอดเสียงฝั่งเบราว์เซอร์ (ไม่ต้องมี STT provider)
- โหมดไมค์ **server STT** — อัดเสียงส่งไปถอดที่ DeepTutor (ใช้ provider ใน Settings)
- พิมพ์ในช่องล่างแล้ว Enter = ทดสอบโดยไม่ใช้ไมค์
- พูดดังระหว่างบอทพูด = แทรก (barge-in)

## config

`.env` มีแค่ `HOST` / `PORT` ของ static host — LLM / STT / TTS ตั้งใน DeepTutor
(Settings > Voice) ไม่ใช่ที่นี่

## ประวัติ

เดิมโฟลเดอร์นี้เป็น prototype แบบ standalone (pipeline STT→LLM→TTS ของตัวเอง +
หน้า `/mvp`, `/`) — ถูกถอดออกหลังงานย้ายเข้า production layer แล้ว ดูบันทึกใน
`CHANGES.md` ส่วน "Voice call (realtime)"
