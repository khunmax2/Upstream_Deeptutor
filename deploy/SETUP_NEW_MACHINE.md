# ตั้งระบบบนเครื่องใหม่ — DeepWitya + Course Studio

เอกสารของ fork นี้ แยกจาก `README.md`, `DEPLOY.md`, `CONTAINERIZATION.md` ของ upstream
ซึ่งพูดถึง DeepTutor เปล่า ๆ ไม่รู้จัก Course Studio, gatekeeper, basePath `/deepwitya`
หรือกฎ Python 3.13 ของ fork นี้

**ทุกตัวเลขและทุกคำสั่งในนี้วัดจริงบนเครื่องปัจจุบันเมื่อ 2026-10-02** ไม่ได้เขียนจากความจำ
ที่ไหนบอกว่า "ต้องได้ X" คือเคยรันแล้วได้ X จริง

---

## 0. สรุปก่อน: ต้อง clone กี่ repo

**ถ้าจะแค่รันระบบ — `git clone` repo เดียวพอ** คือ repo นี้

| ส่วน | มาจากไหน | ต้อง clone ไหม |
|---|---|---|
| DeepWitya (backend + web) | build จาก repo นี้ | repo นี้ |
| **Course Studio** | **image สำเร็จรูปจาก ghcr** `ghcr.io/khunmax2/deepwitya-studio` | **ไม่ต้อง** |
| gatekeeper | `node:22-alpine` + mount โฟลเดอร์ `deploy/openmaic-gatekeeper/` ของ repo นี้ | ไม่ต้อง (ไม่ได้ build) |
| postgres / redis / pocketbase | image สาธารณะ | ไม่ต้อง |

image ของ studio **ดึงได้แบบไม่ต้อง `docker login`** (ตรวจแล้ว: ขอ anonymous token จาก ghcr
ได้ 200 และอ่าน manifest ของ digest ที่ pin ไว้ได้ 200) ดังนั้นเครื่องใหม่ไม่ต้องมีบัญชี
GitHub หรือ token อะไรทั้งนั้น

**repo ที่สอง (`OpenMAIC`) ต้องการก็ต่อเมื่อจะ _แก้_ ตัว studio** แล้ว build image ใหม่
การใช้งาน การ deploy และการทดสอบทั้งหมดไม่ต้องใช้มันเลย — ดู §7

---

## 1. สิ่งที่ต้องมีบนเครื่อง

| | เวอร์ชัน | หมายเหตุ |
|---|---|---|
| Docker Desktop (หรือ engine + compose v2) | — | เส้นทาง A |
| Python | **3.13** | เส้นทาง B — **ห้าม 3.14** |
| Node | 22 | เฉพาะตอนพัฒนา `web/` นอก Docker |
| ดิสก์ | ~25 GB | image + build cache |

> **ทำไมห้าม Python 3.14** — ไม่ใช่เรื่องความเข้ากันได้ แต่มันทำ RAG หาย **เงียบ ๆ**:
> `graphrag` ติดตั้งไม่ได้เลย (ทุก release cap `Requires-Python <3.14`, และ
> `pip install -e ".[graphrag]"` ตอบ exit 0 โดยไม่ลงอะไรเพราะ extra ถูก marker กัน)
> และ BM25 hybrid retrieval ถอยไปเป็น vector-only ทั้งคู่ไม่มี error ตอนติดตั้ง
> รายละเอียดใน `CLAUDE.md` และ `CHANGES.md` entry 2026-09-05
> (image Docker ใช้ Python 3.11 ภายใน ไม่เกี่ยวกับ venv ของเครื่อง)

---

## 2. เส้นทาง A — รันด้วย Docker (เหมือน host)

### 2.1 clone

```bash
git clone https://github.com/khunmax2/Upstream_Deeptutor.git
cd Upstream_Deeptutor
```

> **clone ที่มีอยู่แล้วห้าม `git pull`** — ประวัติของ `main` ถูก rewrite เมื่อ 2026-09-09
> ใช้ `git fetch origin && git reset --hard origin/main` (ดู `CLAUDE.md`)

### 2.2 สร้าง `deploy/production.env` — ขั้นที่ข้ามไม่ได้

compose **ปฏิเสธที่จะเริ่ม** ถ้าไม่มีสองค่านี้ ไม่ใช่พังเงียบ มันบอกชื่อตัวแปรมาเลย

```bash
cp deploy/production.env.example deploy/production.env
```

แล้วแก้สองบรรทัด:

- `OPENMAIC_IMAGE` — **คัดลอกจาก `deploy/openmaic-patches/openmaic-pin.json`**
  (เอา `image.ref` ส่วนก่อน `:` ต่อด้วย `@` แล้วตามด้วย `image.digest`)
  ต้องเป็น **digest** ไม่ใช่ tag ไฟล์ pin คือแหล่งความจริงเดียว ไม่ต้องเดา:

  ```bash
  python -c "import json;d=json.load(open('deploy/openmaic-patches/openmaic-pin.json'))['image'];print('OPENMAIC_IMAGE='+d['ref'].split(':')[0]+'@'+d['digest'])"
  ```

- `OPENMAIC_POSTGRES_PASSWORD` — เครื่องใหม่ที่เริ่ม DB เปล่า **สุ่มใหม่ได้เลย**
  `openssl rand -hex 24`
  **ยกเว้น**กรณีเดียว: ถ้าจะกู้ volume postgres ของ studio จากเครื่องเก่า ต้องใช้รหัส **เดิม**
  เพราะ postgres อ่านรหัสตอนสร้าง volume ครั้งแรกเท่านั้น

ไฟล์นี้ถูก gitignore (`*.env`) จึงไม่ติดไปกับ clone — ดู §6

### 2.3 ขึ้น stack

```bash
docker compose --env-file deploy/production.env \
  -f docker-compose.yml \
  -f deploy/docker-compose.openmaic.yml \
  -f deploy/docker-compose.uat.yml \
  up -d --build
```

ครั้งแรกใช้เวลาประมาณ 10–20 นาที (build image + pull studio)

**ต้องได้ 8 container healthy**: `deeptutor`, `deeptutor-redis`, `deeptutor-sandbox-runner`,
`pocketbase`, `deeptutor-openmaic`, `deeptutor-openmaic-postgres`,
`deeptutor-openmaic-gatekeeper`, `deeptutor-uat-nginx`

### 2.4 พอร์ต

| พอร์ต | อะไร |
|---|---|
| **8080** | nginx — **ใช้อันนี้** ทั้ง DeepWitya และ studio อยู่หลัง origin เดียว |
| 3782 | Next.js ตรง ๆ (studio เข้าไม่ได้ทางนี้ — เคยเข้าใจผิดมาแล้ว) |
| 8001 | FastAPI ตรง ๆ |
| 10330 | gatekeeper (ผูก `127.0.0.1` เท่านั้น — **ห้ามเปิดออกนอก** จะ spoof header ได้) |
| 8090 | pocketbase |

เปิด **http://localhost:8080/deepwitya**

### 2.5 ตรวจว่าขึ้นถูก

```bash
curl -s http://localhost:8080/deepwitya/api/auth/status
curl -s -o /dev/null -w 'studio -> %{http_code}\n' http://localhost:8080/deepwitya/course-studio
curl -s -o /dev/null -w 'school -> %{http_code}\n' http://localhost:8080/deepwitya/api/multi-user/school/classrooms
```

ต้องได้ `"enabled":true` · `307` · `401` (401 คือ "ต้องล็อกอิน" = router ขึ้นแล้ว;
ถ้าได้ 404 แปลว่า image เก่ากว่าโค้ด)

---

## 3. เส้นทาง B — รันจาก source (ไม่ใช้ Docker)

ได้เฉพาะ DeepWitya — **ไม่มี Course Studio** เพราะ studio เป็น image แยก

```bash
python3.13 -m venv .venv        # หรือ uv venv --python 3.13 .venv
pip install -e ".[all]"
deeptutor start                 # backend + frontend
```

---

## 4. ครั้งแรกที่รัน: อะไรถูกสร้างให้ อะไรต้องกรอกเอง

`data/` ไม่อยู่ใน git (ทั้ง upstream และ fork นี้) clone ใหม่จึงไม่มี ไม่ใช่ปัญหา —
**entrypoint ของ container และ `deeptutor start` เรียก `init_user_directories()` ให้เอง**

วัดจริงบน home เปล่า: สร้าง **17 ไฟล์** — `main.yaml`, `interface.json`, `auth.json`,
`system.json`, `model_catalog.json`, `agents.yaml`, `integrations.json`, การตั้งค่า RAG
(`graphrag`, `lightrag`, `lightrag_server`, `llamaindex`, `pageindex`,
`document_parsing`, `ima`) และ persona 3 ตัว (`peer`, `research-assistant`, `teacher`)

**ระบบจึงทำงานได้เหมือนเครื่องนี้ทุกอย่าง** ที่หายไปคือ *ข้อมูลที่ผู้ใช้สร้างขึ้น* เท่านั้น

สิ่งที่ต้องทำเองหลังรันครั้งแรก:

1. **สมัครบัญชีแรก** — การสมัครเองเปิดได้**ก่อนมีแอดมินคนแรกเท่านั้น** หลังจากนั้น
   ปิดทันที (`"Self-registration is closed"`) บัญชีแรกจึงได้ role `admin` และเป็น
   เจ้าของ `data/` ส่วนใครเป็น *primary* admin เป็นไปตามกฎใน `CLAUDE.md`:
   บัญชี bootstrap ใน `auth.json` ถ้ามีรหัสผ่าน มิฉะนั้นคือบัญชีที่บันทึกใน
   `primary_admin.json` และเปลี่ยนได้ด้วยคำสั่ง `primary_admin handover` เท่านั้น
2. **ใส่ API key** ที่หน้า Settings — เครื่องนี้มีอยู่ 5 ตัว: llm, embedding, search, tts, stt
   (key ไม่อยู่ใน git และไม่มีทางกู้จาก repo ต้องเอามาจากผู้ให้บริการหรือสำรองของเก่า)
3. ภาษาเริ่มต้นเป็น **ไทย** (`DEFAULT_INTERFACE_SETTINGS["language"] = "th"` ของ fork นี้)

---

## 5. pytest บนเครื่องใหม่ — กับดักเดียวที่มี

**`pytest` ไม่เรียก `init_user_directories()`** ดังนั้น clone ใหม่ที่ยังไม่เคยรันแอป
จะเจอ error นี้ (วัดจริง):

```
FileNotFoundError: Configuration file not found: main.yaml
  (expected under …/data/user/settings)
```

ไม่ใช่บั๊ก แต่ไม่มีที่ไหนเขียนไว้ก่อนหน้านี้ CI เลี่ยงด้วยการเขียนไฟล์เองใน workflow

**วิธีแก้ เลือกอันใดอันหนึ่ง:**

```bash
# ก. ให้โค้ดของแอปสร้างให้ (ตรงกับที่ container ทำ) — ทดสอบแล้วว่า pytest ผ่านทันทีหลังรัน
python -c "from deeptutor.services.setup import init_user_directories; init_user_directories()"

# ข. หรือเขียนเท่าที่ CI ใช้
mkdir -p data/user/settings
printf 'system:\n  language: en\nlogging:\n  level: WARNING\n' > data/user/settings/main.yaml
cp tests/fixtures/ci_model_catalog.json data/user/settings/model_catalog.json
```

แล้วรัน:

```bash
pytest -q tests deeptutor/learning/tests
```

**บน Windows** ต้องชี้ temp ไปที่อื่น ไม่งั้น ACL ค้างที่ `%TEMP%\pytest-of-<user>`
ทำให้ test 2,600+ ตัว ERROR ตั้งแต่ setup:

```bash
PYTEST_DEBUG_TEMPROOT=./.pytest-tmp pytest -q tests deeptutor/learning/tests
```

ที่เหลือ ~58–84 ตัวแดงบน Windows เป็น baseline ของแพลตฟอร์ม (sandbox argv exec,
macOS launcher, websocket timing) ไม่ใช่ regression — CI รัน Linux ไม่เจอ

> อยากรัน test โดยไม่แตะ `data/` จริง ให้ตั้ง `DEEPTUTOR_HOME=<ที่อื่น>`
> **ระวัง**: `init_user_directories(project_root)` **ละเลย argument ที่ส่งไป**
> (เขียนไว้ในโค้ดว่า "kept for API compatibility") มันอ่าน `DEEPTUTOR_HOME` เท่านั้น
> ส่ง path เข้าไปแล้วคิดว่าปลอดภัยคือเข้าใจผิด — มันจะไปทำงานกับ `data/` จริง

---

## 6. อะไรไม่อยู่ใน git และแปลว่าอะไรตอนย้ายเครื่อง

| ไม่อยู่ใน git | ผลตอนย้าย |
|---|---|
| **`data/`** (93 MB บนเครื่องนี้) | บัญชี, grants, **API key 5 ตัว**, ประวัติแชต, pocketbase, pet, memory, KB — หายหมด ระบบยังทำงานปกติ แต่เริ่มจากศูนย์ |
| **`deploy/production.env`** | stack ไม่ขึ้นจนกว่าจะสร้างใหม่ (§2.2) — error ชัด ไม่เงียบ |
| `.claude/launch.json` | สร้างใหม่อัตโนมัติ ไม่มีโค้ดอ้างถึง |
| `data/user/settings/docker.env` | `scripts/docker_compose.py` generate ให้ |
| `.mypy_cache`, `.next*`, `egg-info`, `tsbuildinfo` | regenerate |

**ถ้าอยากยกของเดิมไปด้วย** (เครื่องเก่ายังอยู่):

```bash
docker compose stop deeptutor                      # ให้ sqlite เขียนจบก่อน
tar -czf deeptutor-dev-backup.tar.gz data deploy/production.env
```

กู้คืนด้วยการแตกไฟล์ที่ root ของ clone ใหม่ **ก่อน** `compose up` ครั้งแรก
ถ้าจะยกฐานข้อมูล studio มาด้วย ใช้ `deploy/backup-studio.sh` และต้องเอารหัส
postgres เดิมมาด้วย (§2.2)

---

## 7. repo ที่สอง — ต้องเมื่อไร

`OpenMAIC` (remote `new` = `khunmax2/Ups_openMAIC`) คือ source ของ Course Studio
**ต้องการก็ต่อเมื่อจะแก้ตัว studio เอง** ไม่ใช่ตอนรันหรือ deploy

ความสัมพันธ์ตอนรัน: ทั้งสองเป็น **คนละแอป** ที่นั่งข้างกัน ไม่ใช่โมดูลเดียวกัน
(ADR-0005 "course studio as a sibling application") DeepWitya คุม `/deepwitya`,
studio คุม `/deepwitya/studio`, nginx route ตาม prefix ที่ยาวกว่า และ gatekeeper
เป็นตัวบอก studio ว่าใครล็อกอินอยู่ โดยอ่านจาก `/api/auth/status` ของ DeepWitya
แล้วใส่ header `x-deeptutor-owner` / `x-deeptutor-role` / `x-deeptutor-primary`
(มันจะ **ลบ** header พวกนี้ที่ client ส่งมาเองทิ้งก่อนเสมอ)

วางไว้ **ข้าง ๆ** repo นี้ เพราะเครื่องมือ default เป็น `../OpenMAIC`:

```bash
cd ..
git clone https://github.com/khunmax2/Ups_openMAIC.git OpenMAIC
cd Upstream_Deeptutor
python deploy/openmaic-patches/check_openmaic_contract.py --openmaic ../OpenMAIC
```

วงจรเวลาจะเปลี่ยน studio: แก้ใน OpenMAIC → PR → merge → รัน workflow
`studio-image.yml` ให้ publish image → อัปเดต `openmaic-pin.json` (ref + digest)
ใน repo นี้ผ่าน PR → แก้ `OPENMAIC_IMAGE` ใน `deploy/production.env` → recreate
เฉพาะ service `openmaic` อ่าน `deploy/GO-LIVE.md` §11 ก่อนทำกับ host

---

## 8. เช็กลิสต์ว่าเครื่องใหม่พร้อม

- [ ] `git log --oneline -1` ตรงกับ `origin/main`
- [ ] `deploy/production.env` มีสองบรรทัด และ `OPENMAIC_IMAGE` เป็น `@sha256:` ไม่ใช่ tag
- [ ] 8 container healthy
- [ ] `http://localhost:8080/deepwitya/api/auth/status` → `"enabled":true`
- [ ] studio → `307`, school route → `401` (ไม่ใช่ 404)
- [ ] สมัครบัญชีแรกได้ และมันเป็น primary admin
- [ ] ใส่ API key แล้วคุยกับติวเตอร์ได้
- [ ] `init_user_directories()` หนึ่งครั้ง แล้ว `pytest -q tests/multi_user` ผ่าน
- [ ] `ruff check .` และ `ruff format --check .` ผ่าน

---

## อ่านต่อ

| ไฟล์ | เมื่อไร |
|---|---|
| `CLAUDE.md` | กฎของ fork — อ่านก่อนแก้โค้ด |
| `AGENTS.md` | สถาปัตยกรรม |
| `deploy/GO-LIVE.md` | runbook ของ host; §11 คือการอัปเดตหลัง go-live |
| `deploy/REDEPLOY.md` | กับดักของ host จากยุค `/deepwitya2` |
| `deploy/probes/README.md` | เครื่องมือวินิจฉัยตอน turn ค้างหรือสงสัยสิทธิ์ของ studio |
| `docs/adr/0005-course-studio-sibling-application.md` | ทำไม studio ถึงเป็นแอปข้าง ๆ |
