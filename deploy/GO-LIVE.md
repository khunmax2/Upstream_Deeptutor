# GO-LIVE — DeepWitya + Course Studio ขึ้น `/deepwitya` บน 203.185.144.41

> **ทำแล้ว — cutover 2026-09-12 00:10 (เวลา host)** จาก tag `golive-2026-09-11` = `main` `b119ee12c`,
> studio image `ghcr.io/khunmax2/deepwitya-studio@sha256:4f54b507…4dee6d` (fork `d5585dd3`)
> ยืนยันจากภายนอก: `/deepwitya` = stack ใหม่, `/deepwitya/studio` → gatekeeper 401, `http://` → 301
> ค้าง: §8 (ลบ v1 หลัง 7 วัน → **2026-09-19**), image provider ใน studio Settings ชี้ endpoint ที่ host เข้าไม่ถึง
> เอกสารนี้เก็บไว้เป็น runbook สำหรับรอบหน้า — สิ่งที่พบระหว่างทางถูกใส่กลับเข้าไปแล้ว (ดู "บทเรียน" ท้ายไฟล์)

runbook สำหรับวัน go-live เขียนคู่กับ `deploy/REDEPLOY.md` (ซึ่งเล่าวิธีตั้ง
stack `/deepwitya2` ที่ validate มาแล้ว) และ `docs/adr/0005-course-studio-sibling-application.md`
(ทำไม studio ถึงเป็น sibling app ที่ pull image ตาม digest)

**หลักคิด:** ไม่มีขั้นไหนที่แตะ `/deepwitya` บน :443 จนกว่าจะถึง §5 และขั้น §5
ย้อนกลับได้ในไม่กี่วินาทีด้วยคำสั่งเดียว (§7) stack เก่า (v1) ไม่ถูกลบจนกว่าจะเฝ้าครบ 7 วัน

## ภาพรวม — ก่อน / หลัง

| | ตอนนี้ | หลัง go-live |
|---|---|---|
| `/deepwitya` (:443) | v1 เก่า, frontend `10310` | **stack ใหม่**, frontend `10320` |
| `/deepwitya/studio` | ไม่มี | gatekeeper `10330` → studio (image ตาม digest) |
| `/deepwitya2` | stack v1.6.x ที่ validate | **ปิด** (location ถูกถอด) |
| DeepWitya image | build จาก `main` เดิม, base path `/deepwitya2` | build จาก tag go-live, base path **`/deepwitya`** |
| container | `deeptutor2`, `pocketbase2`, `deeptutor2-redis`, `deeptutor2-sandbox-runner`, `deeptutor2-ollama` | เดิมทั้งหมด + `deeptutor-openmaic`, `deeptutor-openmaic-gatekeeper`, `deeptutor-openmaic-postgres` |
| `data/` ของ DeepWitya | ของ stack `/deepwitya2` | **ใช้ต่อที่เดิม** (user, settings, sessions ที่ validate มาแล้ว) |
| ฐานข้อมูล studio | — | **สร้างใหม่** (ไม่ยกจาก UAT — ดู §1.3) |

stack ใหม่คือ stack `/deepwitya2` ที่ **rebuild ในที่** (ชื่อ container, port,
`data/` เดิม) ด้วย overlay `deploy/docker-compose.production.yml` แทน
`docker-compose.localhost.yml` — ต่างกันแค่ base path ที่ bake ลง image, สองบรรทัดที่
ต่อแอปเข้ากับ studio และ service ของ studio อีก 3 ตัว

ราคาที่ต้องรู้: **ตั้งแต่ขั้น §3.4 (rebuild) `/deepwitya2` จะใช้ไม่ได้** เพราะ image
ถูก bake ใหม่เป็น `/deepwitya` — ไม่กระทบ `/deepwitya` ตัวจริง (v1) ที่ยังให้บริการอยู่

**ต้องสั่งหยุด stack เก่าก่อนไหม — ไม่ต้อง ทั้งสองตัว:**

| stack | ต้องทำอะไร | ทำไม |
|---|---|---|
| `/deepwitya2` (`deeptutor2`, …) | **ไม่ต้องหยุด** — §3.4 `up -d --build` recreate container ชุดเดิมให้เอง | มันคือ stack ใหม่นั่นแหละ แค่ build ใหม่ในที่ |
| `/deepwitya` v1 (port 10310) | **ไม่ต้องหยุด** — ปล่อยรันไว้ | คือทางถอย §7.1 (สลับ nginx กลับใน 5 วินาที) ลบทีหลังใน §8 เมื่อพอใจแล้ว — หรือเร็วกว่านั้นถ้าไม่อยากเก็บ แต่ต้องรู้ว่าลบแล้วทางถอยแบบทันทีหายไปด้วย |

ข้อมูลผู้ใช้ในทั้งสอง stack เป็นของทดสอบ **ไม่ยกอะไรทั้งนั้น** สิ่งเดียวที่มีค่าคือ config
การ deploy ซึ่งอยู่ใน `data/user/settings/` ของ `/deepwitya2` (port, `auth.json` ที่เปิด
multi-user, บัญชี admin, credential ของ model) และมันอยู่ที่เดิมอยู่แล้วเพราะ rebuild ในที่

---

## 0. วัดก่อน อย่าเดา (บน host)

ทั้งหมดนี้ต้องตอบได้ก่อนเริ่ม §3 — ถ้าค่าใดไม่ตรงกับตาราง ให้หยุดแล้วปรับ runbook
ไม่ใช่ปรับ host

```bash
# stack ที่รันอยู่ + port ที่ publish — กรองด้วย label ของ compose project เสมอ ไม่ใช่ prefix ชื่อ
# (v1 ก็ชื่อขึ้นต้น deeptutor เหมือนกัน; ชื่อ project = ชื่อโฟลเดอร์ checkout)
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'
docker ps --filter label=com.docker.compose.project=upstream_deeptutor_v2 --format '{{.Names}}\t{{.Status}}'

# nginx: /deepwitya ชี้ไปไหน (คาดว่า 10310) และ /deepwitya2 (คาดว่า 10320)
sudo nginx -T 2>/dev/null | grep -nE 'location /deepwitya|proxy_pass http://127.0.0.1:10[0-9]+' 

# checkout บน host: อยู่ที่ไหน branch อะไร สะอาดไหม
cd /home/search/Thoughtmind/Upstream_Deeptutor_v2 && git status --short | head && git log --oneline -1

# port ที่ docker.env สร้างไว้ (คาด 8002 / 10320 / 8091)
cat data/user/settings/docker.env

# compose รองรับ --env-file ซ้ำสองไฟล์ (ต้อง >= 2.24)
docker compose version

# ดิสก์ — วันนี้เครื่อง dev เต็มจน docker daemon ตายกลางทาง อย่าให้ host ซ้ำรอย
df -h / && docker system df
```

- [ ] `/deepwitya` → `10310` (v1) — ถ้าเป็นเลขอื่น ใช้เลขนั้นแทนใน §5
      วัดได้ 2026-09-11: `10310` **ทั้ง :443 และ :80** — :80 เป็น `proxy_pass` ไม่ใช่ redirect
      cutover จึงเพิ่ม `return 301` ไป https ในบล็อก :80 (stack ใหม่ตั้ง cookie `Secure`,
      login ผ่าน http ไม่ติด — REDEPLOY §6b) ดู §5
- [ ] `/deepwitya2` → `10320` และ container `deeptutor2` รันอยู่ healthy
- [ ] checkout สะอาด: `git status --short` ว่าง — `M` ห้ามมี; `??` (untracked) ให้ย้ายออกไป
      `../_deeptutor_backup/` ก่อน เพื่อให้ checkout ตรง tag เป๊ะ (วัดได้ 2026-09-11:
      `deploy/uat_scene_content.py` จาก session ทดสอบก่อนหน้า — ไม่กระทบ build แต่ย้ายออก)
- [ ] container studio **ชุดเก่า** บน host: `deeptutor-openmaic` (build เอง, ไม่มี healthcheck) และ
      `deeptutor-openmaic-gatekeeper` (`127.0.0.1:10331`) มาจาก integration รอบก่อนใน compose
      project เดียวกัน (`upstream_deeptutor_v2`) — **ปกติ** §3.4 จะ recreate สองตัวนี้ในที่จาก image
      ตาม digest และสร้าง `deeptutor-openmaic-postgres` เพิ่ม ถ้า `up` ตอบ
      `container name … already in use` แปลว่ามาจากคนละ project → หยุด รายงาน
- [ ] `docker compose version` ≥ 2.24
- [ ] ดิสก์ว่าง ≥ 20 GB (build DeepWitya ใช้ ~5 GB, studio image ~1 GB, postgres เริ่มที่ไม่กี่ร้อย MB)
- [ ] port `10330` ว่าง: `ss -ltnp | grep 10330` ต้องว่าง
- [ ] port สำหรับ preview (§4) ว่าง **บน host**: `ss -ltnp | grep -E ':(8443|9443)\s'` — วัดได้ 2026-09-11:
      **8443 บน host เป็นของ Kong 3.9.1 (gateway ของแอปอื่น)** → ใช้ `9443` ใน §4
      `nginx -t` ไม่ bind จึงไม่เตือน; port ชนจะรู้ตอน reload ว่า bind ล้ม แล้ว nginx ใช้ config เดิมต่อเงียบ ๆ
      script ตรวจให้แล้ว แต่วัดไว้ก่อนดีกว่า

---

## 1. ทำล่วงหน้าจากเครื่อง dev (ไม่ต้องเข้า host)

### 1.1 `feat/course-studio → main`

PR #69 merge แล้ว 2026-09-11 (`main` = `931431e97`) และ tag แล้ว — คำสั่งไว้อ้างอิงถ้าต้องทำรอบหน้า:

```bash
git tag -a golive-2026-09-11 -m "Course studio go-live" origin/main && git push origin golive-2026-09-11
```

host จะ checkout **tag** นี้ ไม่ใช่ `main` สด — สิ่งที่ deploy ต้องชี้ได้ว่าคือ commit ไหน

### 1.2 publish studio image แล้วบันทึก digest ลง pin

ADR-0005: deploy **pull** image ตาม digest ไม่ build บน host workflow
`.github/workflows/studio-image.yml` build จาก commit ที่ pin ไว้ใน
`deploy/openmaic-patches/openmaic-pin.json` ด้วย build arg จาก `deploy/build-studio.sh`
(ที่เดียวที่ค่าอยู่) แล้ว push ไป `ghcr.io/khunmax2/deepwitya-studio`

```bash
gh workflow run studio-image.yml --repo khunmax2/Upstream_Deeptutor --ref main
gh run watch --repo khunmax2/Upstream_Deeptutor   # ~10 นาที; job summary พิมพ์ digest
```

แล้ว:

- [ ] package `deepwitya-studio` บน GitHub → Package settings → **Change visibility → Public**
      (ครั้งแรกที่ push GHCR ตั้งเป็น private; repo ทั้งสองเป็น public อยู่แล้ว image
      ไม่มี secret — ถ้าอยากเก็บ private ต้อง `docker login ghcr.io` บน host ด้วย PAT read:packages)
- [x] บันทึก `image.ref` / `image.digest` / `built: true` ลง pin — ทำแล้ว 2026-09-11:
      `ghcr.io/khunmax2/deepwitya-studio@sha256:4f54b507257fdd8453495ac2bd7206ed8a1e59f79b473c67489b05765f4dee6d`
- [ ] ทดสอบ pull จากเครื่อง dev: `docker pull ghcr.io/khunmax2/deepwitya-studio@sha256:<digest>`
      แล้ว `docker run --rm --entrypoint sh <ref> -c 'grep -rl /deepwitya/studio/_next .next/server/app | wc -l'` ต้อง > 0

### 1.3 ข้อมูล — ตัดสินใจแล้ว (2026-09-11): ไม่ยกข้อมูลผู้ใช้ใด ๆ

ทั้ง v1 และ `/deepwitya2` เป็นระบบทดสอบ ข้อมูลผู้ใช้ในนั้นไม่มีค่า สิ่งที่มีค่าคือ **config การ deploy** เท่านั้น

| ข้อมูล | ตัดสินใจ | หมายเหตุ |
|---|---|---|
| `data/user/settings/` ของ `/deepwitya2` (port, `auth.json`, บัญชี admin, credential ของ model) | **ใช้ต่อ** — อยู่ที่เดิมเพราะ rebuild ในที่ | นี่คือ "ข้อมูล deploy" ที่ต้องเก็บ; §2 backup ไว้เผื่อ |
| session / เอกสาร / ผู้ใช้ทดสอบใน `/deepwitya2` | ปล่อยไว้ ไม่แตะ ไม่ยก | ติดมากับ `data/` เดิม ไม่เป็นไร ลบทีหลังได้ |
| ทุกอย่างใน v1 (`/deepwitya` เดิม) | **ทิ้ง** ตอน §8 | ไม่มีอะไรต้องยก |
| ฐานข้อมูล studio | **สร้างใหม่** | คอร์ส UAT บนเครื่อง dev เป็นของทดลอง; key ใน studio กรอกใหม่ใน Settings (admin แชร์ให้ทุกบัญชีได้จากเมนูบน key) |
| `data/ollama` (bge-m3 1.1 GB) | อยู่ที่เดิม | ไม่ต้อง pull ใหม่ |

---

## 2. Backup (บน host, ก่อนแตะอะไร)

```bash
cd /home/search/Thoughtmind/Upstream_Deeptutor_v2
mkdir -p ../_deeptutor_backup

# data/ ผ่าน container เพราะ settings เป็น 600 ของ UID 1000 (REDEPLOY §0)
docker exec deeptutor2 tar -C /app -czf - data | cat > ../_deeptutor_backup/data-pre-golive-$(date +%Y%m%d).tar.gz
ls -la ../_deeptutor_backup/

# image ปัจจุบันของ stack /deepwitya2 — ทางถอยแบบไม่ต้อง build (§7.3)
# ชื่อ image ขึ้นกับ project name ของ compose (ชื่อโฟลเดอร์) — อ่านจาก container ไม่เดา
IMG=$(docker inspect deeptutor2 --format '{{.Config.Image}}'); echo "$IMG"
docker tag "$IMG" "${IMG%%:*}:pre-golive-$(date +%Y%m%d)"

# commit ที่รันอยู่ก่อน go-live
git rev-parse HEAD > ../_deeptutor_backup/pre-golive-commit.txt
```

- [ ] tarball มีขนาดสมเหตุสมผล (`tar -tzf ... | head`)
- [ ] `docker images "${IMG%%:*}"` เห็น tag `pre-golive-*`

---

## 3. เตรียม stack ใหม่ (บน host — ยังไม่แตะ nginx :443)

### 3.1 checkout tag

```bash
git fetch origin --tags
git checkout golive-2026-09-11
git log --oneline -1          # ต้องเป็น commit ที่ PR ใน §1.1 merge
```

### 3.2 secrets ของ studio

```bash
cp deploy/production.env.example deploy/production.env
openssl rand -hex 24          # → OPENMAIC_POSTGRES_PASSWORD
nano deploy/production.env    # ใส่ OPENMAIC_IMAGE=ghcr.io/khunmax2/deepwitya-studio@sha256:<digest จาก pin> และรหัสผ่าน
chmod 600 deploy/production.env
```

- [ ] `OPENMAIC_IMAGE` ลงท้าย `@sha256:` + digest **ตรงกับ pin** ไม่ใช่ tag

### 3.3 กับดัก permission (REDEPLOY §6 — ต้องทำก่อน build ทุกครั้ง **และซ้ำหลัง container restart ทุกครั้ง**)

directory mode ถูก reset เป็น 700 ทุกครั้งที่ container start — รวมถึง restart ที่เกิดจาก §3.4 รอบที่ล้ม
อาการ: `docker compose … config` ตอบ `permission denied` ที่ `docker.env` → กลับมาทำข้อนี้ใหม่ (ไม่ใช้ sudo)
บรรทัด `chmod 666 docker.env` ในทางปฏิบัติเป็น no-op (container เขียนไฟล์นี้เป็น 666 อยู่แล้ว) เก็บไว้เผื่อ:

```bash
docker exec deeptutor2 chmod 775 /app/data/user /app/data/user/settings
docker exec deeptutor2 chmod 644 /app/data/user/settings/system.json /app/data/user/settings/integrations.json
docker exec deeptutor2 chmod 666 /app/data/user/settings/docker.env
```

### 3.4 build + up (จุดที่ `/deepwitya2` หยุดให้บริการ)

```bash
docker compose -f docker-compose.yml \
               -f deploy/docker-compose.openmaic.yml \
               -f deploy/docker-compose.production.yml \
               --env-file data/user/settings/docker.env \
               --env-file deploy/production.env \
               up -d --build 2>&1 | tee ../_deeptutor_backup/golive-build-$(date +%Y%m%d-%H%M).log
```

ลำดับไฟล์สำคัญ: `production.yml` ต้องอยู่ **ท้ายสุด** (มันตั้ง `LOGIN_URL` ทับค่าว่างของ overlay studio)

สิ่งที่เกิด: build DeepWitya ใหม่ด้วย `NEXT_PUBLIC_BASE_PATH=/deepwitya` (~8–12 นาที),
pull studio ตาม digest, สร้าง postgres ใหม่ (volume `<project>_openmaic-postgres` — ดู `docker volume ls | grep openmaic`),
start gatekeeper **หลัง** studio healthy (`depends_on: service_healthy` — healthcheck ของ studio
เพิ่ง fix ให้ใช้ `node` แทน `wget` ที่ไม่มีใน image; ก่อนหน้านี้ gatekeeper จะไม่ start เลยบน `compose up` สด)

```bash
docker ps --format '{{.Names}}\t{{.Status}}' | sort
```

- [ ] 8 container `healthy` (deeptutor2, pocketbase2, redis, sandbox-runner, ollama, openmaic, gatekeeper, postgres)
      — ถ้า `deeptutor-openmaic` ค้าง `starting` เกิน 2 นาที ดู `docker logs deeptutor-openmaic`
      ถ้า `deeptutor-openmaic-postgres` เป็น `Restarting (255)` และ log ขึ้น
      `exec /usr/local/bin/docker-entrypoint.sh: operation not permitted` = quirk
      `no-new-privileges` ของ host นี้ (REDEPLOY §6) overlay production ปลดให้ studio ทั้ง 3 ตัวแล้ว
      ตั้งแต่ 2026-09-11 — ถ้ายังเจอ แปลว่า checkout ไม่ใช่ tag ล่าสุด
      ถ้าเห็น `EACCES` ที่ `/app/data`: volume `<project>_openmaic-data` มีอยู่ก่อนจาก image รุ่นเก่า
      (studio รันเป็น uid 1001) → `docker run --rm -v <project>_openmaic-data:/d alpine chown -R 1001:1001 /d`
      แล้ว `docker restart deeptutor-openmaic`; volume ที่สร้างใหม่ไม่เจอปัญหานี้
- [ ] `curl -s http://127.0.0.1:10330/__gatekeeper/health` → `{"ok":true...}`
- [ ] `curl -sI http://127.0.0.1:10320/deepwitya/login | head -1` → `200` (หรือ `307`)
- [ ] `curl -s http://127.0.0.1:10320/deepwitya/api/auth/status` → JSON มี `"enabled":true`
- [ ] `curl -s http://127.0.0.1:10330/deepwitya/studio/api/health` → `401` และ body บอกให้ไป
      `/deepwitya/login` (ไม่มี cookie = gatekeeper กัน; มันตอบ 401 พร้อมข้อความ ไม่ redirect)
- [ ] `docker logs deeptutor2 2>&1 | grep -i "auth enabled"` → `true`

---

## 4. ทดสอบของจริงก่อนสลับ (preview ผ่าน SSH tunnel)

base path ถูก bake ไว้ที่ `/deepwitya` ดังนั้น stack ใหม่ทดสอบได้ที่ path นั้นเท่านั้น —
แต่ `/deepwitya` บน :443 ยังเป็นของ v1 วิธีแก้: nginx server อีกตัวบน **loopback
127.0.0.1:8443** ใช้ cert เดิม (ไม่ต้องเปิด firewall) แล้วเข้าผ่าน SSH tunnel

บน host (พอร์ตที่สองคือพอร์ต preview บน host — ต้องว่าง ดู §0; script ปฏิเสธถ้าไม่ว่าง
และยืนยันหลัง reload ว่า nginx ฟังจริง):
```bash
sudo bash deploy/apply-nginx-golive.sh --preview 10320 9443
```

บนเครื่องคุณ (**ไม่ใช่ใน host**) — เปิด PowerShell ใหม่ ปล่อยค้างไว้ตลอดการทดสอบ
(เลขซ้ายคือพอร์ตบนเครื่องคุณ เลือกที่ว่าง — 2026-09-11 เครื่อง dev มี IDE ใช้ 8443 อยู่ จึงใช้ 18443):
```bash
ssh -L 18443:127.0.0.1:9443 search@203.185.144.41
```
แล้วเปิด **https://localhost:18443/deepwitya** (เบราว์เซอร์เตือน cert ไม่ตรงชื่อ — กดผ่าน,
cert ออกให้ IP ไม่ใช่ localhost; `cookie_secure` ยังใช้ได้เพราะเป็น https)

ก่อนเริ่ม checklist ยืนยันว่าถึงตัวจริง: `curl -k -sI https://localhost:18443/deepwitya/api/auth/status`
ต้องได้ `Server: nginx` และ body มี `"enabled":true` — ถ้าได้ `Server: kong` หรือกล่อง Basic auth
ของเบราว์เซอร์ = ปลายท่อเป็นของแอปอื่น (พอร์ตชน) ไม่ใช่ stack เรา

- [ ] login admin ได้ (cookie ติด, ไม่เด้งกลับ login)
- [ ] แชท 1 รอบจบ, RAG ค้นเอกสารได้ (ถ้ามีเอกสารใน stack เดิม)
- [ ] devtools → Network ไม่มี asset `404` (ตัวชี้ว่า base path ครบทุกจุด)
- [ ] เมนู **Course Studio** เปิด iframe ได้ ไม่ใช่หน้า "ไม่ได้เชื่อมต่อ"
- [ ] ใน studio: Settings → กรอก API key 1 provider → **บันทึกแล้ว refresh ยังเป็น mask** (key อยู่ server)
- [ ] สร้างคอร์สภาษาไทยสั้น ๆ 1 คอร์ส (3 ฉาก มี simulation 1) → ปุ่มใน simulation เป็นไทย
- [ ] login เป็นบัญชี preset `learner` → เมนู studio ไม่โชว์ และเข้า
      `https://localhost:8443/deepwitya/course-studio` ตรง ๆ ได้หน้า "ไม่ใช่ส่วนหนึ่งของบัญชีนี้"
- [ ] status code ของ path เรา — **gatekeeper ไม่ log รายคำขอ** (มีแค่ banner ตอน boot) ต้องอ่านจาก
      nginx access log ซึ่งเป็น `640 www-data:adm` → คนรัน sudo เอง:
      `sudo awk '$7 ~ /deepwitya/ {print $9}' /var/log/nginx/access.log | sort | uniq -c`
      403 ต้องเท่ากับจำนวนครั้งที่ learner ลอง, ไม่มี 502
- [ ] `docker ps` ทุกตัวยัง healthy และ `docker inspect deeptutor2 --format '{{.RestartCount}}'` = 0

ถ้าข้อใดไม่ผ่าน: **ยังไม่ได้แตะ production เลย** แก้แล้ว `up -d --build` ซ้ำ §3.4 ได้ตามสบาย

---

## 5. Cutover (จุดเดียวที่แตะ `/deepwitya` จริง — ~5 วินาที)

```bash
sudo bash deploy/apply-nginx-golive.sh --cutover 10310 10320
```

script: ตรวจว่า `location /deepwitya` บน :443 ชี้ไป `10310` จริง (ไม่ตรง = หยุด ไม่แตะอะไร) →
backup ทั้งสองไฟล์ → :443 เปลี่ยน port ใน block `/deepwitya` **บรรทัดเดียว** + เพิ่ม
`include /etc/nginx/snippets/deepwitya-studio.conf` (location `/deepwitya/studio` → 10330)
→ :80 เพิ่ม `return 301 https://…` เป็นบรรทัดแรกของ block `/deepwitya` (proxy_pass เดิม
ทิ้งไว้ — `return` ทำงานใน rewrite phase ก่อน proxy เสมอ; block ที่ redirect อยู่แล้วไม่แตะ)
→ `nginx -t` (ไม่ผ่าน = คืน backup อัตโนมัติ ไม่ reload) → reload

จากเครื่องคุณ (ไม่ผ่าน tunnel):

- [ ] `curl -sIL https://203.185.144.41/deepwitya | grep -E "HTTP|location"` → 200 (หรือ 307 ไป `/deepwitya/login`)
- [ ] `curl -sI http://203.185.144.41/deepwitya | grep -E "HTTP|location"` → `301` `location: https://…/deepwitya`
- [ ] `curl -s https://203.185.144.41/deepwitya/studio/api/health` → `401` + ข้อความชี้ไป `/deepwitya/login`
- [ ] เบราว์เซอร์ปกติ: login → แชท → studio → เหมือน §4
- [ ] ผู้ใช้ที่ login ค้างจาก v1 จะโดนเด้ง login ใหม่ (token คนละ `auth_secret`) — ปกติ บอกผู้ใช้ล่วงหน้า

ถอด `/deepwitya2` (ตอนนี้ตอบ 404 อยู่แล้วเพราะ image bake เป็น `/deepwitya`) และ preview
(**ต้องถอด** — ไฟล์ preview ที่ค้างจะทำให้ reload ครั้งหน้าพยายาม bind พอร์ตนั้นอีก):

```bash
sudo bash deploy/apply-nginx-deepwitya2.sh --revert
sudo bash deploy/apply-nginx-golive.sh --remove-preview
```

---

## 6. เฝ้า

- 30 นาทีแรก: `docker ps` (กรอง label) ทุก 10 นาที, `RestartCount` = 0 ทั้ง 8, `docker logs --since 10m deeptutor-openmaic | grep -ciE "error|unhandled"`;
  status code จาก nginx access log (sudo — ดู §4) ไม่มี 502
- 24 ชั่วโมง: `docker logs deeptutor-openmaic --since 24h | grep -iE "error|unhandled" | head`
- 7 วัน: ยังไม่ลบ stack v1 (§8)

---

## 7. Rollback — เลือกตามอาการ

### 7.1 stack ใหม่พัง, v1 ยังดี → คืน nginx (วินาที)

```bash
sudo bash deploy/apply-nginx-golive.sh --revert
```
`/deepwitya` กลับไป `10310` (v1 ยังรันอยู่ตลอด ไม่เคยถูกหยุด), include studio ถูกถอด,
`return 301` บน :80 ถูกถอด — ไฟล์ทั้งสองกลับเหมือนก่อน cutover ทุก byte
ผู้ใช้กลับไปเห็นระบบเดิมทันที ข้อมูลใน v1 ไม่เคยถูกแตะ

### 7.2 เฉพาะ studio พัง, DeepWitya ดี → หยุดแค่ studio

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.openmaic.yml -f deploy/docker-compose.production.yml \
  --env-file data/user/settings/docker.env --env-file deploy/production.env stop openmaic gatekeeper
```
DeepWitya ทำงานต่อ เมนู Course Studio ขึ้น "ไม่ได้เชื่อมต่อ" (ออกแบบไว้ให้เป็นแบบนี้)
ไม่มี image studio ก่อนหน้าให้ถอย (นี่คือ publish ครั้งแรก) — pin เดิม `05c86fd2` build
ได้จาก workflow เดียวกันถ้าต้องการ แต่ image `d5585dd3` ผ่าน UAT มาแล้วทั้งชุด

### 7.3 อยากได้ v1.6.x กลับที่ `/deepwitya2` (ช้ากว่า — ไม่น่าต้องใช้)

image ก่อน go-live ถูก bake เป็น `/deepwitya2` อยู่แล้ว ไม่ต้อง build:
```bash
IMG=$(docker inspect deeptutor2 --format '{{.Config.Image}}')
docker tag "${IMG%%:*}:pre-golive-<date>" "$IMG"
docker compose -f docker-compose.yml -f deploy/docker-compose.localhost.yml \
  --env-file data/user/settings/docker.env up -d --no-build
sudo bash deploy/apply-nginx-deepwitya2.sh
```
(ทำ §7.1 ก่อนเสมอ เพื่อให้ `/deepwitya` กลับเป็น v1 ระหว่างนี้)

### 7.4 ข้อมูล DeepWitya เสีย (ไม่น่าเกิด — schema additive)

```bash
docker compose ... stop deeptutor
docker run --rm -v "$PWD:/w" -w /w alpine sh -c 'rm -rf data && tar -xzf ../_deeptutor_backup/data-pre-golive-<date>.tar.gz'
docker compose ... up -d
```

---

## 8. หลังเฝ้าครบ 7 วัน

- [ ] หา stack v1: `docker ps --format '{{.Names}}\t{{.Ports}}' | grep 10310` แล้วดู
      `docker inspect <c> --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'`
      → `cd` ไปที่นั่น → `docker compose down` (**ไม่ใส่ `-v`** — volume/`data/` ของ v1 เก็บไว้อีก 30 วัน)
- [ ] `docker image prune` เฉพาะ dangling; **อย่า** `system prune -a` (ลบ `pre-golive-*` ทิ้ง)
- [ ] ลบ `location /deepwitya2` ที่ :80 ถ้ายังเหลือ (`apply-nginx-deepwitya2.sh --revert` ทำให้แล้ว)
- [ ] `CHANGES.md` บันทึกวันที่ go-live + commit + digest

---

## 9. วิธีสั่ง Claude วัน go-live

ระบบเป็นสอง repo (DeepWitya นี้ + fork OpenMAIC) แต่วัน go-live **ใช้ repo นี้ repo เดียว**:
studio มาเป็น image ตาม digest ใน pin แล้ว ไม่ต้องแตะ fork

**ที่ไหน:** host ไม่มี Claude — เลือกอย่างใดอย่างหนึ่ง

| แบบ | วิธี | ข้อควรรู้ |
|---|---|---|
| ก. รัน Claude Code บนเครื่องคุณใน `D:/Vscode/Upstream_Deeptutor` ให้มันคุย host ผ่าน `ssh` | ต้องมี key auth ไป host แล้ว (`ssh <user>@203.185.144.41 true` ต้องผ่านโดยไม่ถามรหัส) — Claude กรอกรหัสผ่าน/passphrase ให้ไม่ได้ | `sudo` บน host ต้องไม่ถามรหัส (`NOPASSWD`) สำหรับ `nginx -t`, `systemctl reload nginx` หรือคุณรันขั้น `sudo` เอง |
| ข. ติดตั้ง Claude Code บน host แล้วรันใน `/home/search/Thoughtmind/Upstream_Deeptutor_v2` **(ใช้จริง 2026-09-11)** | เห็นทุกอย่างตรง ๆ ไม่ต้องผ่าน ssh; วัดค่า/วินิจฉัยได้ดีมาก | **sudo ใช้ไม่ได้** (`sudo -n true` → password required, ไม่มี TTY) — ทุกขั้น sudo คนพิมพ์เองในหน้าต่าง host แล้ววาง output ให้ Claude; ต้อง `git fetch` ให้ checkout มี `deploy/GO-LIVE.md` ก่อน |

รูปแบบที่ใช้จริง 2026-09-11: Claude บน host (ข.) วัด/ตรวจ/รายงาน → คนวาง output ให้ Claude อีกตัวบนเครื่อง dev ที่ถือ repo →
ตัวนั้นแก้ runbook/script เป็น PR → merge → ย้าย tag → host `git fetch origin --force --tags && git checkout golive-…` →
ทำต่อ tag ย้ายทั้งหมด 4 ครั้งในคืนเดียว (#71 digest, #72 :80 redirect, #73 no-new-privileges, #74 preview port) — ปกติ
ไม่ใช่ความผิดพลาด: กติกา "แก้ runbook ไม่แก้ host" ทำงานได้จริงเพราะ tag ย้ายได้

**prompt ที่ paste ได้เลย** (แบบ ก. ให้เติมบรรทัดแรก; แบบ ข. ตัดออก):

```
host คือ 203.185.144.41 เข้าด้วย ssh <user>@203.185.144.41 (key auth ตั้งไว้แล้ว) repo บน host อยู่ที่ /home/search/Thoughtmind/Upstream_Deeptutor_v2

วันนี้ go-live ตาม deploy/GO-LIVE.md อ่านทั้งไฟล์ก่อน แล้วทำตามลำดับ §0 → §2 → §3 → §4 → §5 → §6 ทีละหัวข้อ
กติกา:
1. §0 ต้องรายงานค่าที่วัดได้จริงทุกข้อก่อนทำอย่างอื่น ถ้าค่าใดไม่ตรงตารางใน runbook ให้หยุดแล้วเสนอแก้ runbook ไม่ใช่แก้ host
2. ห้ามข้าม checklist ข้อใด ถ้าข้อไหนไม่ผ่านให้หยุดและบอก ห้ามแก้แล้วไปต่อเอง
3. ขั้นที่ใช้ sudo (§4, §5, §7, การอ่าน access log) เธอรันไม่ได้ — session ไม่มี TTY กรอกรหัสไม่ได้ ให้พิมพ์คำสั่งมาให้ฉันรันเองในหน้าต่าง host แล้วรอฉันวาง output กลับ
4. §5 (cutover) ทำเมื่อฉันสั่ง "cutover" เท่านั้น
5. ถ้าอะไรพังหลัง §5 ให้ทำ §7.1 ทันทีแล้วค่อยมาวิเคราะห์
6. ข้อมูลผู้ใช้ในทั้งสอง stack เป็นของทดสอบ ไม่ต้องยก ไม่ต้องถาม (§1.3)
สถานะที่ทำไว้แล้ว: main มี tag golive-<วันที่>, studio image publish แล้ว digest อยู่ใน deploy/openmaic-patches/openmaic-pin.json
```

**ก่อนถึงวันนั้น สิ่งที่ต้องเป็นจริง (ไม่งั้น Claude จะติดตั้งแต่ §1):**
- [ ] PR `feat/course-studio → main` merge แล้ว + tag `golive-<วันที่>` push แล้ว
- [ ] workflow `studio-image.yml` รันบน `main` แล้ว, package ตั้ง Public, digest บันทึกใน pin และ merge แล้ว
- [ ] ssh key ไป host ใช้ได้ (แบบ ก.) หรือ Claude Code อยู่บน host (แบบ ข.)

## 10. สิ่งที่รู้ว่ายังไม่ได้ทำ (ไม่ใช่ blocker — ตัดสินใจไว้แล้ว)

- CSP ของ studio ไม่มี `frame-ancestors` ที่กว้างกว่า `'self'` — ถูกต้องสำหรับ origin เดียว (T12 ใน threat model เป็นเรื่อง header อื่น ยังค้าง)
- ลบบัญชี DeepWitya แล้วข้อมูลใน studio ของ owner นั้นยังอยู่ — script reconcile อยู่ใน backlog
- key ใน `studio_credential` ไม่ได้เข้ารหัสที่ disk (postgres volume บน host เดียวกัน สิทธิ์ root) — backlog
- prompt ฝั่ง TS (`lib/chat/pi/prompts.ts`, PBL instructor) ยังมีตัวอย่างจีน — ไม่กระทบ course ปกติ

---

## บทเรียนจากรอบ 2026-09-11 (ใส่กลับเข้า runbook ข้างบนแล้ว — นี่คือสรุป)

| เจอ | อาการ | แก้ที่ |
|---|---|---|
| `:80 /deepwitya` เป็น `proxy_pass` ไม่ใช่ redirect | ถ้า swap port ตาม cutover เดิม login ผ่าน http จะวนเพราะ cookie `Secure` | script: :80 เพิ่ม `return 301` แทน swap (#72) |
| `no-new-privileges:true` บน studio 3 ตัว | postgres `Restarting (255)` `exec docker-entrypoint.sh: operation not permitted`; studio/gatekeeper ไม่เคย start | overlay production ปลดให้ 3 ตัวเหมือน sandbox-runner (#73) — host นี้เท่านั้น |
| host 8443 = supabase-kong (`0.0.0.0:8443` ครอบ loopback) | preview `nginx -t` ผ่าน, reload "สำเร็จ" แต่ bind ล้มเงียบ; เบราว์เซอร์ได้ Basic auth ของ Kong; ไฟล์ค้างทำให้ reload ครั้งถัดไป (cutover) จะล้มด้วย และ `systemctl restart nginx` จะล่มทั้งเครื่อง | script: พอร์ต preview เป็นพารามิเตอร์ + ตรวจว่างก่อน + ยืนยัน listener หลัง reload + cutover ปฏิเสธ preview ค้าง (#74); §0 วัดพอร์ต preview |
| เครื่อง dev 8443 = Antigravity IDE | tunnel bind ไม่ได้ เบราว์เซอร์ไปโดน IDE | tunnel ใช้ 18443 ฝั่ง dev |
| ssh tunnel เก่ายังค้าง | 18443 ยังชี้ 8443 หลังแก้ฝั่ง host แล้ว | ปิด process ssh เก่าก่อนเปิดใหม่ — ตรวจด้วย `netstat -ano` หา 18443 แล้ว `Get-CimInstance Win32_Process` ดู command line ของ pid นั้น |
| gatekeeper ไม่ log รายคำขอ | นับ status code จาก `docker logs` ไม่ได้ | ใช้ nginx access log (sudo) |
| §3.3 ต้องรันซ้ำ | container restart จาก §3.4 ที่ล้ม reset dir เป็น 700 → `compose config` อ่าน `docker.env` ไม่ได้ | §3.3 ระบุ "ซ้ำหลัง restart" |
| Claude บน host ไม่มี sudo | ทุกขั้น nginx/sudo คนต้องพิมพ์เอง | §9 |
| image provider `custom-image` ต่อไม่ติดจาก host | ImageGeneration `fetch failed` ใน 200 ms; TTS custom ใช้ได้ | ไม่ใช่ของ go-live — แก้ URL ใน studio Settings |

