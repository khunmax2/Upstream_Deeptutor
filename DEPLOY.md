# DEPLOY.md — DeepTutor (fork) Production Deployment Guide

คู่มือติดตั้ง DeepTutor fork (`khunmax2/Upstream_Deeptutor`) บนเซิร์ฟเวอร์ใหม่
แบบ **Docker Compose production** พร้อม **LINE webhook** (Caddy reverse proxy + TLS อัตโนมัติ)

> เขียนให้ทั้งคนและ **Claude CLI / coding agent** ทำตามได้ทีละขั้นแบบ copy-paste
> ทุกที่ที่เขียน `example.com`, `<...>`, `REPLACE_WITH_...` = ค่าที่ต้องแทนด้วยของจริง

---

## 0. ภาพรวมสถาปัตยกรรมที่จะติดตั้ง

ทุกอย่างรันใน Docker Compose บนเซิร์ฟเวอร์เดียว:

| Service | ที่มา | พอร์ต (ใน container) | หน้าที่ |
|---|---|---|---|
| `deeptutor` | build จาก `Dockerfile` (target `production`) | `8001` backend, `3782` frontend, `3979` LINE webhook | แอปหลัก (FastAPI + Next.js + partner channels) |
| `sandbox-runner` | build จาก `Dockerfile.runner` | `8900` (internal only) | รันโค้ดที่โมเดลสร้าง แบบแยก container (office skills) |
| `pocketbase` | image `ghcr.io/muchobien/pocketbase` | `8090` | auth/storage sidecar (optional) |
| `caddy` | image `caddy:2` (overlay file) | `80`, `443` | reverse proxy + TLS (Let's Encrypt) |

**Routing สาธารณะ** (ผ่าน Caddy):

```
https://app.<domain>   ->  deeptutor:3782   (Web UI)
https://api.<domain>   ->  deeptutor:8001   (backend — เบราว์เซอร์เรียกตรง)
https://line.<domain>  ->  deeptutor:3979   (LINE webhook -> /line/webhook)
```

> **จุดที่พลาดบ่อยที่สุด:** เบราว์เซอร์โหลด Web UI แล้ว **เรียก backend ตรงๆ** ที่
> `next_public_api_base_external` — ไม่มี proxy ภายใน. ดังนั้น `api.<domain>` ต้อง
> เข้าถึงได้จากอินเทอร์เน็ต ไม่ใช่แค่ `app.<domain>`. ถ้าตั้งผิด หน้าเว็บโหลดได้
> แต่ Settings ขึ้น "Backend unreachable".

> **LINE listener (3979)** ถูกสตาร์ทอยู่ "ข้างใน" container `deeptutor` โดย
> partner auto-start ([api/main.py](deeptutor/api/main.py)) — Caddy เข้าถึงผ่าน
> docker network จึง **ไม่ต้อง publish 3979 ออก host**. Dockerfile EXPOSE แค่
> 8001/3782 ก็ไม่เป็นไร เพราะ Caddy คุยกันใน network เดียวกัน.

---

## 1. Prerequisites (เตรียมก่อน)

### 1.1 เซิร์ฟเวอร์
- Linux x86_64 หรือ arm64 (Ubuntu 22.04+ แนะนำ)
- RAM **≥ 4 GB** (8 GB ถ้าจะใช้ RAG/KB หนักๆ), ดิสก์ว่าง ≥ 20 GB
- เปิดพอร์ตขาเข้า **80** และ **443** จากอินเทอร์เน็ต (สำหรับ Caddy + TLS + LINE)

### 1.2 ซอฟต์แวร์บนเซิร์ฟเวอร์
ตรวจ/ติดตั้ง:

```bash
docker --version          # ต้องมี Docker Engine 24+
docker compose version    # ต้องมี Compose v2
git --version
python3 --version         # ใช้รัน scripts/docker_compose.py (3.8+ พอ)
```

ถ้ายังไม่มี Docker (Ubuntu/Debian):

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # แล้ว logout/login ใหม่ ให้ใช้ docker ไม่ต้อง sudo
```

### 1.3 โดเมน + DNS (จำเป็นสำหรับ LINE/TLS)
สร้าง DNS **A record** (และ AAAA ถ้ามี IPv6) ชี้มาที่ IP เซิร์ฟเวอร์ ทั้ง 3 ชื่อ:

```
app.example.com    A   <SERVER_PUBLIC_IP>
api.example.com    A   <SERVER_PUBLIC_IP>
line.example.com   A   <SERVER_PUBLIC_IP>
```

ตรวจว่า resolve ถูก ก่อนไปต่อ:

```bash
dig +short app.example.com api.example.com line.example.com
```

### 1.4 ข้อมูลที่ต้องมีในมือ
- **API key ของ LLM provider** (เช่น OpenAI / Anthropic / OpenRouter / หรือ endpoint local) + ชื่อ model
- (ถ้าทำ LINE) จาก https://developers.line.biz/console/ :
  - **Channel secret** (Basic settings, hex 32 ตัว)
  - **Channel access token** (Messaging API → Issue, ยาว ~170 ตัว)
  - **LINE userId ของตัวเอง** (สำหรับ allowlist; ดูวิธีหาในข้อ 6.4)

---

## 2. ดึงโค้ดจาก GitHub

```bash
# เลือก path ที่จะวางโปรเจค เช่น /opt
cd /opt
git clone https://github.com/khunmax2/Upstream_Deeptutor.git deeptutor
cd deeptutor

# ติดตั้ง production บน main (หลัง merge LINE เข้า main แล้ว)
git checkout main
git pull --ff-only
```

> ทั้งโฟลเดอร์ `data/` ถูก gitignore — fresh clone จะ **ไม่มี** settings/secrets ใดๆ
> เราจะสร้างขึ้นในขั้นถัดไป. ข้อมูลทั้งหมด (settings, API keys, KB, memory, partners,
> logs) จะถูก persist ใน `./data` ที่ mount เข้า container.

---

## 3. ตั้งค่า runtime settings (สำคัญสำหรับ remote server)

settings อยู่ใต้ `data/user/settings/`. container สร้าง default ให้เองตอน boot แรก
**แต่** บน remote server ต้องตั้ง `next_public_api_base_external` + `cors_origins`
**ก่อน** start ไม่งั้นเบราว์เซอร์เรียก backend ไม่เจอ.

```bash
mkdir -p data/user/settings
cp deploy/settings/system.json.example data/user/settings/system.json
```

แก้ `data/user/settings/system.json` แทนค่า domain จริง:

```json
{
  "version": 1,
  "backend_port": 8001,
  "frontend_port": 3782,
  "next_public_api_base_external": "https://api.example.com",
  "next_public_api_base": "",
  "cors_origin": "",
  "cors_origins": ["https://app.example.com"],
  "disable_ssl_verify": false,
  "chat_attachment_dir": "",
  "sandbox_allow_subprocess": true
}
```

> `scripts/docker_compose.py` อ่าน `backend_port`/`frontend_port` จากไฟล์นี้เพื่อ
> map พอร์ต host. ปล่อยเป็น 8001/3782 ได้ (Caddy คุยใน network ภายใน ไม่ชนกัน).
> เก็บ `cors_origins` ให้ตรง origin ของ Web UI เป๊ะ (ต้องมี `https://app.example.com`).

**ตั้งค่า LLM provider (เลือก 1 ใน 2 วิธี):**

- **วิธี A (แนะนำ, ง่ายสุด):** ข้ามไปก่อน แล้วไปตั้งใน Web UI หลัง start —
  เปิด `https://app.example.com` → **Settings → Models** → Add provider
  (Base URL / API key / model) → Save.
- **วิธี B (headless/pre-seed):** ถ้ามี `model_catalog.json` ที่ใช้งานได้จากเครื่องอื่น
  ก๊อปวางที่ `data/user/settings/model_catalog.json` ก่อน start. (schema ซับซ้อน —
  อย่าเขียนมือ ใช้ของที่ export มาแล้ว หรือใช้วิธี A.)

---

## 4. (ถ้าทำ LINE) เตรียม Caddy + partner config

ข้ามทั้งข้อ 4 ได้ถ้ายังไม่ทำ LINE → ไปข้อ 5 (ดูหมายเหตุท้ายข้อ 5 สำหรับโหมดไม่มี Caddy)

### 4.1 Caddyfile

```bash
cp deploy/Caddyfile.example deploy/Caddyfile
```

แก้ `deploy/Caddyfile`: เปลี่ยน `example.com` → โดเมนจริง และ `you@example.com` → อีเมลจริง

### 4.2 LINE partner config

```bash
mkdir -p data/partners/lineme
cp deploy/settings/partner-line-config.yaml.example data/partners/lineme/config.yaml
```

แก้ `data/partners/lineme/config.yaml`:
- `channel_secret`, `channel_access_token` = ค่าจริงจาก LINE console
- `allow_from` = ใส่ LINE userId ของตัวเอง (ดูข้อ 6.4); ใช้ `'*'` เฉพาะตอนเทสสั้นๆ

> ทั้ง `deploy/Caddyfile` และ `data/partners/lineme/config.yaml` ถูก gitignore
> (อยู่ใต้ `data/` หรือเป็นไฟล์ที่ไม่ commit) — secrets ไม่ขึ้น repo.

---

## 5. Build + Start

### 5.1 พร้อม LINE/Caddy (โหมดเต็ม)

```bash
python scripts/docker_compose.py \
  -f docker-compose.yml \
  -f deploy/docker-compose.caddy.yml \
  up -d --build
```

### 5.2 ไม่มี LINE/Caddy (Web app อย่างเดียว)

```bash
python scripts/docker_compose.py -f docker-compose.yml up -d --build
```

> ในโหมดนี้ Web UI/backend จะอยู่บนพอร์ต host 3782/8001 (ตาม system.json).
> ถ้าจะเข้าจากเครื่องอื่นต้องเปิดพอร์ตเหล่านี้และตั้ง `next_public_api_base_external`
> เป็น `http://<SERVER_IP>:8001` แทน (ไม่มี TLS). แนะนำใช้โหมด 5.1 กับ Caddy บน
> production มากกว่า.

ครั้งแรก build ใช้เวลาหลายนาที (มี Rust toolchain + npm). ดู progress ด้วย:

```bash
docker compose ps
docker compose logs -f deeptutor
```

---

## 6. ตรวจสอบหลังติดตั้ง

### 6.1 Health
```bash
docker compose ps                    # ทุก service ต้อง healthy
docker compose logs deeptutor | grep -i "Backend Port"
```

### 6.2 Web UI
เปิด `https://app.example.com` → ต้องเห็นหน้า DeepTutor. ไป **Settings** —
ถ้าไม่ขึ้น "Backend unreachable" แปลว่า `api.example.com` + CORS ถูกต้อง.

### 6.3 LINE listener ขึ้นไหม
```bash
docker compose logs deeptutor | grep -i "LINE webhook listening"
# คาดหวัง: LINE webhook listening on http://0.0.0.0:3979/line/webhook
```

### 6.4 ตั้ง Webhook ฝั่ง LINE + หา userId
1. LINE Developers Console → Channel → **Messaging API**
2. Webhook URL = `https://line.example.com/line/webhook` → **Verify** (ต้องขึ้น Success)
3. เปิด **Use webhook** = ON; ปิด **Auto-reply / Greeting** (กันตอบทับ)
4. **หา userId ของตัวเอง:** ทักข้อความหา OA 1 ครั้ง แล้วดู log:
   ```bash
   docker compose logs deeptutor | grep -i "userId\|allow_from\|denied"
   ```
   เอา userId ที่เห็นไปใส่ `allow_from` ใน `data/partners/lineme/config.yaml`
   แล้ว **restart** (ข้อ 7.1). ทักใหม่ → บอทต้องตอบ.

---

## 7. งานดูแลระบบ (Operations)

### 7.1 Restart (จำเป็นทุกครั้งที่แก้ settings/partner config — อ่านตอน start เท่านั้น)
```bash
python scripts/docker_compose.py -f docker-compose.yml -f deploy/docker-compose.caddy.yml restart deeptutor
# หรือ restart ทั้ง stack:
python scripts/docker_compose.py -f docker-compose.yml -f deploy/docker-compose.caddy.yml up -d
```

### 7.2 อัปเดตเวอร์ชัน (pull โค้ดใหม่ + rebuild)
```bash
cd /opt/deeptutor
git pull --ff-only
python scripts/docker_compose.py -f docker-compose.yml -f deploy/docker-compose.caddy.yml up -d --build
```

### 7.3 Logs
```bash
docker compose logs -f deeptutor          # แอปหลัก (backend + frontend + LINE)
docker compose logs -f caddy              # TLS / reverse proxy
# log ไฟล์ภายใน: data/user/logs/ai_tutor_*.log
```

### 7.4 Backup / Restore
ทุกอย่างที่ต้องสำรองอยู่ใน `./data` ต้นไม้เดียว:
```bash
docker compose down
tar czf deeptutor-data-$(date +%F).tar.gz data/
# restore: แตกไฟล์ทับ ./data แล้ว up ใหม่
```
รวม: settings + API keys (`data/user/settings`), KB, memory, partner config + sessions
(`data/partners`), accounts/audit (`data/system`), TLS certs (`data/caddy`).

### 7.5 Stop / ลบ
```bash
docker compose down            # หยุด (data ยังอยู่)
docker compose down -v         # หยุด + ลบ named volumes (ระวัง: data/ เป็น bind mount จะไม่โดน)
```

---

## 8. Troubleshooting (จาก runbook จริงของ fork)

| อาการ | สาเหตุ | แก้ |
|---|---|---|
| หน้าเว็บโหลดได้ แต่ Settings = "Backend unreachable" | `next_public_api_base_external` ผิด/ว่าง หรือ `api.<domain>` เข้าไม่ถึง | ตั้งเป็น `https://api.<domain>` ใน system.json + เช็ค DNS/Caddy ของ api. |
| CORS error ใน console เบราว์เซอร์ | `cors_origins` ไม่ตรง origin ของ UI | ใส่ `https://app.<domain>` เป๊ะ แล้ว restart |
| Caddy ขอ cert ไม่ได้ / 526 | DNS ยังไม่ชี้มา หรือ 80/443 ปิด | ตรวจ `dig`, เปิด firewall 80+443, ดู `docker compose logs caddy` |
| LINE Verify = **404** | URL ขาด path | ต้องลงท้าย `/line/webhook` เป๊ะ |
| LINE Verify = **401** (signature) | `channel_secret` ผิดช่อง | secret = Basic settings (hex 32) ไม่ใช่ access token |
| Verify ผ่าน แต่บอทไม่ตอบ + 401 ตอน reply | `channel_access_token` ผิด/สลับช่อง | token = Messaging API → Issue (~170 ตัว) |
| Verify ผ่าน แต่บอทเงียบทุกคน | `allow_from` ว่าง = deny ทุกคน | ใส่ userId ตัวเอง หรือ `'*'` (เทสเท่านั้น) แล้ว restart |
| Verify ได้ **502/530** | container ไม่ healthy / LINE channel ไม่ขึ้น | เช็ค `docker compose ps` + log "listening" |
| บอทตอบ แต่ LINE ตอบทับ | OA auto-reply/greeting เปิดอยู่ | ปิดทั้งคู่ใน OA Manager |
| แก้ config แล้วไม่มีผล | config อ่านตอน start เท่านั้น | **restart `deeptutor`** เสมอ (ข้อ 7.1) |

---

## 9. หมายเหตุความปลอดภัย

- **Secrets ไม่อยู่ใน git:** ทั้ง `data/` ถูก gitignore. API keys / LINE token อยู่
  เฉพาะบนเซิร์ฟเวอร์ใน `data/user/settings` และ `data/partners`. ห้าม commit.
- **Sandbox sidecar:** โหมด compose route การรันโค้ดที่โมเดลสร้างไปที่
  `sandbox-runner` (container แยก สิทธิ์ต่ำ อ่าน-only rootfs) ผ่าน
  `DEEPTUTOR_SANDBOX_RUNNER_URL` — ตัวแอปหลักไม่รันโค้ด untrusted เอง.
- **allow_from:** บน production อย่าใช้ `'*'` ค้างไว้ — จำกัด userId ที่อนุญาต.
- **Caddy TLS:** cert/ACME state อยู่ใน `data/caddy` — รวมใน backup, อย่าลบ.

---

## 10. Checklist สำหรับ Claude CLI (ทำตามลำดับ)

```
[ ] 1. ติดตั้ง docker + compose + git (ข้อ 1.2)
[ ] 2. สร้าง DNS A records app./api./line.<domain> -> server IP (ข้อ 1.3) + dig ผ่าน
[ ] 3. เปิด firewall 80 + 443
[ ] 4. git clone + checkout main (ข้อ 2)
[ ] 5. cp deploy/settings/system.json.example -> data/user/settings/system.json + แก้ domain (ข้อ 3)
[ ] 6. (LINE) cp Caddyfile.example -> deploy/Caddyfile + แก้ domain/email (ข้อ 4.1)
[ ] 7. (LINE) cp partner-line-config.yaml.example -> data/partners/lineme/config.yaml + ใส่ secret/token (ข้อ 4.2)
[ ] 8. python scripts/docker_compose.py -f docker-compose.yml -f deploy/docker-compose.caddy.yml up -d --build (ข้อ 5.1)
[ ] 9. docker compose ps = healthy ทั้งหมด + เปิด https://app.<domain> (ข้อ 6)
[ ] 10. ตั้ง LLM provider ใน Settings -> Models (ข้อ 3 วิธี A)
[ ] 11. (LINE) Verify webhook + ใส่ userId ใน allow_from + restart (ข้อ 6.4)
```
