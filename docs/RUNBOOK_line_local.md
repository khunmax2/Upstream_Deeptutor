# RUNBOOK — รัน LINE bot บนเครื่อง local (กันลืม)

วิธีเปิด DeepTutor + cloudflared ให้ LINE OA เชื่อมได้ ทุกครั้งที่จะใช้งาน

> ⚠️ ความจริงที่ต้องจำ: **cloudflared quick tunnel ได้ URL ใหม่ทุกครั้งที่เปิด**
> → ปิด terminal tunnel เมื่อไหร่ ต้องเอา URL ใหม่ไปอัปเดตใน LINE + กด Verify ใหม่เสมอ

---

## ทุกครั้งที่จะเปิดใช้ (4 ขั้น เรียงตามนี้)

### 1. เปิด tunnel — Terminal A (เปิดค้างไว้ ห้ามปิด)
```bash
cloudflared tunnel --url http://localhost:3979
```
มองหาบรรทัด:
```
https://<สุ่มมาใหม่>.trycloudflare.com
```
ก๊อป URL นี้ไว้

### 2. อัปเดต Webhook ใน LINE + Verify
เอา URL จากข้อ 1 **ต่อ path ให้ครบ**:
```
https://<สุ่มมาใหม่>.trycloudflare.com/line/webhook
```
ใส่ที่ไหนก็ได้ 1 ใน 2:
- OA Manager → Messaging API → "ลิงก์ Webhook"
- Developers Console → ช่อง Webhook → กด **Verify**

ต้องขึ้น Success (ถ้า error ดูหัวข้อ "เช็คก่อนงง" ล่าง)

### 3. สตาร์ท DeepTutor — Terminal B
```bash
deeptutor start
```
รอจนเห็น log:
```
LINE webhook listening on http://0.0.0.0:3979/line/webhook
```
ถ้าไม่เห็นบรรทัดนี้ = channel LINE ไม่ขึ้น (ดู "เช็คก่อนงง")

### 4. ทดสอบ
ทักข้อความหา OA จากมือถือ → บอทต้องตอบ

---

## เช็คก่อนงง (ปัญหาที่เจอบ่อย)

| อาการ | สาเหตุ | แก้ |
|------|--------|-----|
| **Verify ได้ 404 Not Found** | URL ใน LINE ใส่ไม่ครบ path | ต้องลงท้าย `/line/webhook` เป๊ะ (ไม่ใช่แค่ host) |
| **Verify ได้ 401 (signature failed)** | `channel_secret` ผิดช่อง | secret = แท็บ Basic settings (hex 32 ตัว) ไม่ใช่ access token |
| **Verify ผ่าน แต่บอทไม่ตอบ + 401 ตอน reply** | `channel_access_token` ผิด/สลับช่อง | token = แท็บ Messaging API → Issue (ยาว ~170 ตัว) |
| **Verify ผ่าน แต่บอทเงียบทุกคน** | `allow_from` ว่าง = deny ทุกคน | ใส่ userId ตัวเอง หรือ `'*'` (เทสเท่านั้น) |
| **Verify ได้ 502/530** | DeepTutor ยังไม่รัน / channel ไม่ขึ้น | สตาร์ท DeepTutor + เช็ค log "listening" |
| **บอทตอบ แต่มี LINE ตอบทับ** | OA auto-reply / greeting เปิดอยู่ | ปิดทั้งคู่ใน OA Manager |

> หมายเหตุภาษา: ตอนนี้ตอบภาษาตาม config `language` (ล็อก `th` ไว้ชั่วคราว) — โหมด "ตอบตามภาษา user" ยังเป็นงานค้าง

---

## อ้างอิงเร็ว

- พอร์ต LINE webhook: **3979** · path: **/line/webhook** (มาจาก `LineConfig` ใน `line.py`)
- ไฟล์ config: `data/partners/lineme/config.yaml` → ใต้ `channels.line:`
  (เก็บ secret/token ที่นี่ ไฟล์นี้ถูก gitignore — ไม่ขึ้น repo)
- **แก้ config ใดๆ ต้องรีสตาร์ท DeepTutor** (อ่าน config ตอน start เท่านั้น)
- OA: DeepWitya (`@149bktca`) · partner: `lineme`

## ลำดับปิดงาน
ปิด Terminal B (DeepTutor) → ปิด Terminal A (tunnel) ได้เลย
ครั้งหน้าเริ่มข้อ 1 ใหม่ (URL จะเปลี่ยน ต้อง Verify ใหม่)
