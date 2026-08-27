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

> หมายเหตุภาษา: ตอบภาษาตาม config `language` ของ partner — เลือกได้ที่หน้า
> Configure → "ภาษาที่ตอบกลับ" (มี English / 中文 / ไทย ตั้งแต่ 2026-08-26)
>
> ⚠️ ตัวเลือก **"อัตโนมัติ"** ไม่ใช่การตรวจจับภาษา — ค่าว่างถูกแปลงเป็น `en` แล้ว
> ระบบสั่ง prompt ว่า *"Do NOT switch languages"* ถ้าพิมพ์ไทยแล้วบอทตอบไทย
> นั่นคือโมเดลฝืนคำสั่งเอง ไม่ใช่ฟีเจอร์ — เปลี่ยนโมเดลหรือพิมพ์ปนอังกฤษเมื่อไหร่
> อาจกลับไปตอบอังกฤษ **อยากได้ไทยแน่นอนต้องเลือก "ไทย" ตรงๆ**
> (โหมด "ตอบตามภาษา user" จริงๆ ยังเป็นงานค้าง)

---

## ทำไมต้องใช้ cloudflared (และบน server จริงต้องทำยังไง)

**มี 2 เหตุผล ไม่ใช่แค่ HTTPS:**

1. **LINE เข้าถึง `localhost` ของเราไม่ได้** ← เหตุผลหลัก
   DeepTutor เปิด webhook ที่ `localhost:3979` บนเครื่องเรา แต่ LINE ยิงมาจาก
   อินเทอร์เน็ต เครื่องเราอยู่หลัง NAT ไม่มี public IP — ต่อให้ติดตั้ง HTTPS เองได้
   LINE ก็ยังหาเครื่องเราไม่เจอ **นี่คือเหตุผลที่ต้องมี tunnel**

2. **LINE บังคับ HTTPS** — ไม่รับ webhook ที่เป็น `http://`
   และ LINE channel ของ DeepTutor เปิดเป็น `ThreadingHTTPServer` ธรรมดา
   (`line.py`) **ไม่มี TLS** — `LineConfig` ไม่มีฟิลด์ `ssl`/`cert`/`key` เลย
   แปลว่ามันพูด HTTP ได้อย่างเดียว ไม่ว่าจะรันที่ไหน

cloudflared เลยทำให้ทั้งสองอย่าง: เปิด public URL + รองรับ HTTPS จริง
(ใบรับรองถูกต้องจาก Cloudflare) แล้วต่อเข้า HTTP ภายในเครื่อง

### ย้ายขึ้น server จริงแล้วเปลี่ยนอะไรบ้าง

ย้ายขึ้น server แก้ได้แค่**ข้อ 1** — **ข้อ 2 ยังอยู่** ยังต้องมีตัวกลางแปลง
HTTPS → HTTP อยู่ดี แค่เปลี่ยนจาก cloudflared เป็น reverse proxy ถาวร

| | ตอนนี้ (local) | บน server จริง |
|---|---|---|
| ให้ LINE เข้าถึงได้ | cloudflared quick tunnel | public IP + DNS |
| HTTPS | cloudflared ทำให้ | Caddy + Let's Encrypt |
| URL | **เปลี่ยนทุกครั้ง** ต้อง Verify ใหม่ | **คงที่** ตั้งครั้งเดียวจบ |
| ต้องเปิด terminal ค้าง | ต้อง | ไม่ต้อง |

repo มีตัวอย่างพร้อมใช้แล้วที่ `deploy/Caddyfile.example` (ครอบ LINE ไว้ด้วย):

```
line.example.com {
	reverse_proxy deeptutor:3979
}
```

คู่กับ `deploy/docker-compose.caddy.yml` — ต้องมีโดเมนของตัวเอง, ตั้ง DNS A record
ของ `app.` / `api.` / `line.<โดเมน>` ชี้มาที่ server และเปิดพอร์ต 80/443 ให้ Caddy
ขอใบรับรองได้

> เกร็ด: quick tunnel สุ่ม subdomain ใหม่ทุกรอบ ซึ่งเป็นต้นเหตุเดียวกับที่ทำให้ MCP
> server ที่ตั้ง URL เป็น `trycloudflare.com` ตายเมื่อปิด tunnel — ย้ายขึ้นโดเมนถาวร
> แก้ทั้ง LINE และ MCP พร้อมกัน

---

## อ้างอิงเร็ว

- พอร์ต LINE webhook: **3979** · path: **/line/webhook** (มาจาก `LineConfig` ใน `line.py`)
- ไฟล์ config: `data/partners/lineme/config.yaml` → ใต้ `channels.line:`
  (เก็บ secret/token ที่นี่ ไฟล์นี้ถูก gitignore — ไม่ขึ้น repo)
- **แก้ผ่านหน้า Configure ในเว็บ = มีผลทันที ไม่ต้องรีสตาร์ท**
  - *tool / โมเดล / ภาษา* — runner อ่าน config object เดียวกันทุกเทิร์น
    (ดูคอมเมนต์ใน `update_partner()` ที่ `api/routers/partners.py`)
  - *channel (token / `allow_from`)* — `PATCH` เรียก `reload_channels()` ให้เอง
    listener สะดุดแค่แป๊บเดียว ไม่ต้องปิดทั้งเซิร์ฟเวอร์
  - **แต่ถ้าแก้ `config.yaml` ด้วยมือ ต้องรีสตาร์ท** เพราะไฟล์ถูกอ่านตอน start
    เท่านั้น (และถ้า partner ยังรันอยู่ ค่าใน RAM จะเขียนทับไฟล์ตอนปิดเซิร์ฟเวอร์)
- OA: DeepWitya (`@149bktca`) · partner: `lineme`
- **`allow_from: ['*']` = เปิดให้ทุกคนที่แอด OA คุยได้** ภายใต้ API key ก้อนเดียวกัน
  แต่ละคนได้ session แยก (`line_<userId>.jsonl`) อ่านของกันไม่ได้ — อย่างไรก็ตาม
  partner ที่ `builtin_tools: None` จะเปิด tool ครบรวม `exec` (รัน shell) และ `cron`
  ให้คนแปลกหน้าด้วย และ memory tool (`partner_read` เห็น shared memory ของเจ้าของ)
  **ปิดไม่ได้** ถ้ายังเป็น dev ควรใส่ userId ตัวเองแทน `'*'`

## ลำดับปิดงาน
ปิด Terminal B (DeepTutor) → ปิด Terminal A (tunnel) ได้เลย
ครั้งหน้าเริ่มข้อ 1 ใหม่ (URL จะเปลี่ยน ต้อง Verify ใหม่)
