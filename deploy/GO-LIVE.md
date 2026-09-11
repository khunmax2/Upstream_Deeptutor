# GO-LIVE — DeepWitya + Course Studio ขึ้น `/deepwitya` บน 203.185.144.41

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

---

## 0. วัดก่อน อย่าเดา (บน host)

ทั้งหมดนี้ต้องตอบได้ก่อนเริ่ม §3 — ถ้าค่าใดไม่ตรงกับตาราง ให้หยุดแล้วปรับ runbook
ไม่ใช่ปรับ host

```bash
# stack ที่รันอยู่ + port ที่ publish
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'

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
- [ ] `/deepwitya2` → `10320` และ container `deeptutor2` รันอยู่ healthy
- [ ] checkout สะอาด (ไม่มี `M` ค้าง) — ถ้ามี ให้ดูว่าเป็นอะไรก่อน `git stash`
- [ ] `docker compose version` ≥ 2.24
- [ ] ดิสก์ว่าง ≥ 20 GB (build DeepWitya ใช้ ~5 GB, studio image ~1 GB, postgres เริ่มที่ไม่กี่ร้อย MB)
- [ ] port `10330` ว่าง: `ss -ltnp | grep 10330` ต้องว่าง

---

## 1. ทำล่วงหน้าจากเครื่อง dev (ไม่ต้องเข้า host)

### 1.1 `feat/course-studio → main`

PR เดียว merge เมื่อ CI เขียว (88 commits, merge-tree สะอาด ณ 2026-09-11) แล้ว tag:

```bash
git tag -a golive-2026-09-13 -m "Course studio go-live" origin/main && git push origin golive-2026-09-13
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
- [ ] บันทึก `image.ref` / `image.digest` / `built: true` ลง pin (PR เล็ก) — deploy ต้อง
      **ปฏิเสธ digest ว่าง** ตาม comment ในไฟล์ pin
- [ ] ทดสอบ pull จากเครื่อง dev: `docker pull ghcr.io/khunmax2/deepwitya-studio@sha256:<digest>`
      แล้ว `docker run --rm --entrypoint sh <ref> -c 'grep -rl /deepwitya/studio/_next .next/server/app | wc -l'` ต้อง > 0

### 1.3 ตัดสินใจเรื่องข้อมูล

| ข้อมูล | ตัดสินใจ | เหตุผล |
|---|---|---|
| `data/` ของ DeepWitya (user, settings, sessions) | **ใช้ของ stack `/deepwitya2` ต่อ** | validate มาแล้ว, schema ของ `feat/course-studio` เป็น additive (เพิ่ม `auth_secret` ใน `users.json`) |
| ฐานข้อมูล studio (คอร์สที่สร้างตอน UAT) | **เริ่มใหม่** (แนะนำ) | ของ UAT เป็นของทดลอง; ยกมาต้อง `pg_dump` + `UPDATE` ที่อยู่ media ทุกแถวเพราะ origin ต่างกัน — ทำได้แต่ไม่คุ้ม |
| API key ใน studio (`studio_credential`) | **กรอกใหม่ใน Settings ของ studio** | key อยู่ฝั่ง server ต่อ owner; admin แชร์ให้ทุกบัญชีได้จากเมนูบน key |
| `data/ollama` (bge-m3 1.1 GB) | อยู่ที่เดิม | volume เดิมของ stack `/deepwitya2` |

ถ้าจะยกคอร์ส UAT จริง ๆ: `docker exec deeptutor-openmaic-postgres pg_dump -U openmaic openmaic > studio-uat.sql`
บนเครื่อง dev → restore บน host **ก่อน** studio ตัวใหม่ start ครั้งแรก → แล้วค่อยแก้ที่อยู่ media
(บันทึกไว้เป็น option ไม่ใช่แผน)

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
git checkout golive-2026-09-13
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

### 3.3 กับดัก permission (REDEPLOY §6 — ต้องทำก่อน build ทุกครั้ง)

directory mode ถูก reset เป็น 700 ทุกครั้งที่ container start:

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

บน host:
```bash
sudo bash deploy/apply-nginx-golive.sh --preview 10320
```

บนเครื่องคุณ:
```bash
ssh -L 8443:127.0.0.1:8443 <user>@203.185.144.41
```
แล้วเปิด **https://localhost:8443/deepwitya** (เบราว์เซอร์เตือน cert ไม่ตรงชื่อ — กดผ่าน,
cert ออกให้ IP ไม่ใช่ localhost; `cookie_secure` ยังใช้ได้เพราะเป็น https)

- [ ] login admin ได้ (cookie ติด, ไม่เด้งกลับ login)
- [ ] แชท 1 รอบจบ, RAG ค้นเอกสารได้ (ถ้ามีเอกสารใน stack เดิม)
- [ ] devtools → Network ไม่มี asset `404` (ตัวชี้ว่า base path ครบทุกจุด)
- [ ] เมนู **Course Studio** เปิด iframe ได้ ไม่ใช่หน้า "ไม่ได้เชื่อมต่อ"
- [ ] ใน studio: Settings → กรอก API key 1 provider → **บันทึกแล้ว refresh ยังเป็น mask** (key อยู่ server)
- [ ] สร้างคอร์สภาษาไทยสั้น ๆ 1 คอร์ส (3 ฉาก มี simulation 1) → ปุ่มใน simulation เป็นไทย
- [ ] login เป็นบัญชี preset `learner` → เมนู studio ไม่โชว์ และเข้า
      `https://localhost:8443/deepwitya/course-studio` ตรง ๆ ได้หน้า "ไม่ใช่ส่วนหนึ่งของบัญชีนี้"
- [ ] `docker logs deeptutor-openmaic-gatekeeper --since 10m | grep -c ' 403 '` เท่ากับจำนวนครั้งที่ learner ลอง ไม่มากกว่า
- [ ] `docker ps` ทุกตัวยัง healthy และ `docker inspect deeptutor2 --format '{{.RestartCount}}'` = 0

ถ้าข้อใดไม่ผ่าน: **ยังไม่ได้แตะ production เลย** แก้แล้ว `up -d --build` ซ้ำ §3.4 ได้ตามสบาย

---

## 5. Cutover (จุดเดียวที่แตะ `/deepwitya` จริง — ~5 วินาที)

```bash
sudo bash deploy/apply-nginx-golive.sh --cutover 10310 10320
```

script: ตรวจว่า `location /deepwitya` ชี้ไป `10310` จริง (ไม่ตรง = หยุด ไม่แตะอะไร) →
backup ทั้งสองไฟล์ → เปลี่ยน port ใน block `/deepwitya` **บรรทัดเดียว** → เพิ่ม
`include /etc/nginx/snippets/deepwitya-studio.conf` (location `/deepwitya/studio` → 10330)
→ `nginx -t` (ไม่ผ่าน = คืน backup อัตโนมัติ ไม่ reload) → reload

จากเครื่องคุณ (ไม่ผ่าน tunnel):

- [ ] `curl -sIL https://203.185.144.41/deepwitya | grep -E "HTTP|location"` → 200 (หรือ 307 ไป `/deepwitya/login`)
- [ ] `curl -s https://203.185.144.41/deepwitya/studio/api/health` → `401` + ข้อความชี้ไป `/deepwitya/login`
- [ ] เบราว์เซอร์ปกติ: login → แชท → studio → เหมือน §4
- [ ] ผู้ใช้ที่ login ค้างจาก v1 จะโดนเด้ง login ใหม่ (token คนละ `auth_secret`) — ปกติ บอกผู้ใช้ล่วงหน้า

ถอด `/deepwitya2` (ตอนนี้ตอบ 404 อยู่แล้วเพราะ image bake เป็น `/deepwitya`) และ preview:

```bash
sudo bash deploy/apply-nginx-deepwitya2.sh --revert
sudo bash deploy/apply-nginx-golive.sh --remove-preview
```

---

## 6. เฝ้า

- 30 นาทีแรก: `docker ps` ทุก 10 นาที, `RestartCount` = 0, `docker logs -f deeptutor-openmaic-gatekeeper` ดูว่า 200/302/403 สมเหตุสมผล ไม่มี 502
- 24 ชั่วโมง: `docker logs deeptutor-openmaic --since 24h | grep -iE "error|unhandled" | head`
- 7 วัน: ยังไม่ลบ stack v1 (§8)

---

## 7. Rollback — เลือกตามอาการ

### 7.1 stack ใหม่พัง, v1 ยังดี → คืน nginx (วินาที)

```bash
sudo bash deploy/apply-nginx-golive.sh --revert
```
`/deepwitya` กลับไป `10310` (v1 ยังรันอยู่ตลอด ไม่เคยถูกหยุด) และ include studio ถูกถอด
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

## 9. สิ่งที่รู้ว่ายังไม่ได้ทำ (ไม่ใช่ blocker — ตัดสินใจไว้แล้ว)

- CSP ของ studio ไม่มี `frame-ancestors` ที่กว้างกว่า `'self'` — ถูกต้องสำหรับ origin เดียว (T12 ใน threat model เป็นเรื่อง header อื่น ยังค้าง)
- ลบบัญชี DeepWitya แล้วข้อมูลใน studio ของ owner นั้นยังอยู่ — script reconcile อยู่ใน backlog
- key ใน `studio_credential` ไม่ได้เข้ารหัสที่ disk (postgres volume บน host เดียวกัน สิทธิ์ root) — backlog
- prompt ฝั่ง TS (`lib/chat/pi/prompts.ts`, PBL instructor) ยังมีตัวอย่างจีน — ไม่กระทบ course ปกติ
