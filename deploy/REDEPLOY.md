# REDEPLOY — ตั้ง Deeptutor ใหม่จาก upstream ให้เสิร์ฟใต้ subpath

เอกสารนี้เขียนไว้สำหรับ **การ deploy ใหม่จาก clone สด** (ไม่ใช่การ merge)
เพราะโค้ด fork ห่างจาก upstream มากจน merge เสี่ยงกว่าแปะใหม่

อ้างอิง patch ต้นฉบับ: `deploy/patches/*.patch` (ใช้เป็น reference — apply ตรง ๆ ไม่ได้
เพราะ upstream ย้ายไฟล์ไปแล้ว) และไฟล์ที่ยกไปได้ทั้งดุ้นใน `deploy/patches/verbatim/`

สถานะที่สำรวจไว้: merge-base 2026-07-01 → upstream 2026-09-04 (~940 commits)

---

## 0. ตรวจก่อนเริ่ม

- [ ] CI ของ upstream เขียวที่ commit เป้าหมาย — **pin commit นั้น** อย่าใช้ HEAD สด
- [ ] backup: `_deeptutor_backup/data-full-*.tar.gz` (ทำผ่าน container เพราะ settings 6 ไฟล์เป็น mode 600 ของ UID 1000)
- [ ] rollback image: `upstream_deeptutor-deeptutor:pre-sync-20260904`
- [ ] rollback git tag: `deploy-working-v1.4.15`

## 1. ของเดิมห้ามแตะ

ตัวเก่ารันคู่ไปก่อนจนกว่าตัวใหม่จะเขียว — `/deepwitya` ต้องให้บริการได้ตลอด
ตัวใหม่ใช้ path + port แยกคนละชุด

| | เดิม | ใหม่ (เสนอ) |
|---|---|---|
| subpath | `/deepwitya` | `/deepwitya2` |
| frontend | 10310 | 10320 |
| backend | 8001 | 8002 |
| pocketbase | 8090 | 8091 |

(สำรวจแล้ว 10320 / 10321 / 8002 / 8091 ว่างทั้งหมด ณ 2026-09-04)

⚠️ **`container_name` ในไฟล์ base ถูก hardcode** (`deeptutor`, `pocketbase`,
`deeptutor-redis`, `deeptutor-sandbox-runner`) — compose project แยกกันไม่ช่วย
เพราะชื่อคอนเทนเนอร์เป็น global ต้อง override ทุกตัวใน localhost.yml ไม่งั้น
ชนกับ stack เดิมที่รันอยู่ ตรวจก่อน build เสมอด้วย:
```
python3 scripts/docker_compose.py -f docker-compose.yml \
  -f deploy/docker-compose.localhost.yml config | grep -E 'container_name|published|name:'
```

---

## 2. Patch ที่ต้องแปะใหม่ทุกครั้ง

upstream **ไม่มี basePath native** — ยืนยันแล้ว ต้องทำเองทั้งหมด

### 2.1 `web/next.config.js` — เพิ่ม basePath block
helper ที่ patch พึ่ง (`firstNonEmpty`, `SYSTEM_SETTINGS`) **ยังอยู่ครบในโค้ดใหม่** →
ยกบล็อกจาก patch 0001 มาวางได้เลย ต้องได้ทั้ง:
- `const BASE_PATH = firstNonEmpty(process.env.NEXT_PUBLIC_BASE_PATH, SYSTEM_SETTINGS.base_path, "")`
- ใส่ `NEXT_PUBLIC_BASE_PATH: BASE_PATH` ใน `env`
- `...(BASE_PATH ? { basePath: BASE_PATH, assetPrefix: BASE_PATH } : {})`

### 2.2 `web/shared/api/client.ts` — ⚠️ ไฟล์ย้ายแล้ว จุดที่พลาดง่ายที่สุด
เดิม `apiUrl`/`wsUrl` อยู่ใน `web/lib/api.ts` — **ตอนนี้ `web/lib/api.ts` เหลือแค่
`export * from "@/shared/api/client"`** ถ้า merge จะไม่ conflict แต่ patch หายเงียบ

ในโค้ดใหม่ทั้งสองฟังก์ชันเป็น pass-through:
```ts
export function apiUrl(path: string): string { return path; }
export function wsUrl(path: string): string { return path; }
```
→ ให้ prepend `BASE_PATH` ตรงนี้ (import จาก `basePath.ts`) จุดเดียวจบ

### 2.3 `web/lib/basePath.ts` — ไฟล์ใหม่ ยกไปทั้งดุ้น
upstream ไม่เคยแตะ → copy จาก `deploy/patches/verbatim/basePath.ts`
(เช็ค import alias ให้ตรง convention `@/shared/...` ของโค้ดใหม่)

### 2.4 `asset()` wrappers — basePath ไม่ prefix ให้ raw img / next-image / favicon
**ห้ามลอกรายชื่อไฟล์จากรอบก่อน — ต้อง grep ใหม่ทุกครั้ง** รอบ v1.6.4 เจอ 9 ไฟล์
(รอบก่อนมี 5) เพราะ upstream เพิ่ม dashboard / agent icons เข้ามา

grep ที่ใช้หา:
```
grep -rnE '(src|href|url)[=:]\s*["'"'"'`]/(([a-zA-Z0-9_-]+\.(png|jpg|svg|ico|webp))|(icons?|images?|logos?|assets|anima|agent-icons|provider-icons|knowledge-engine-icons)/)' --include='*.tsx' web/
```

ไฟล์ที่แก้จริงใน v1.6.4:
| ไฟล์ | แก้อะไร |
|---|---|
| `web/app/layout.tsx` | metadata icons 3 url (favicon 16/32 + apple-touch) |
| `web/components/layout/AppShell.tsx` | logo.png, banner.png |
| `web/components/sidebar/SidebarShell.tsx` | logo.png ×2, banner.png |
| `web/components/chat/home/SessionLoadingView.tsx` | logo_black.png |
| `web/features/chat/components/ChatWorkspace.tsx` | logo_black.png |
| `web/components/common/ProviderIcon.tsx` | template `/provider-icons/${spec.file}` |
| `web/components/dashboard/LearnerAnimaPanel.tsx` | /anima/reviews-clipboard.png |
| `web/components/knowledge/KnowledgeEngineIcon.tsx` | **จุดคอขวด** `src={source}` — ครอบที่เดียวคุมทั้ง map 10 entry |
| `web/components/agents/agent-icons.tsx` | **จุดคอขวด** `href={src}` ใน `OfficialAssetGlyph` — คุม call site ทั้งหมด |

สองไฟล์ท้ายมีจุดคอขวดจุดเดียว **อย่าไปครอบที่ call site** จะกลายเป็นครอบซ้ำ

### 2.4b `wsUrl()` — call site ที่ข้าม helper (ทำให้แชทพัง)
`asset()` ไม่พอ ต้องกวาด **path ที่ฝังดิบ ไม่ผ่าน `apiUrl`/`wsUrl`** ด้วย:
```
grep -rnE '\burl:\s*["'"'"'`]/(ws|api)|new WebSocket\(["'"'"'`]/' --include='*.ts' --include='*.tsx' web/
```
ใน v1.6.4 เจอ **1 จุด** และมันทำให้แชทใช้ไม่ได้ทั้งระบบ:

`web/features/chat/transport/TurnRuntimeClient.ts` มี default `url: "/ws"` ฝังไว้ตรง ๆ
→ เบราว์เซอร์เปิด `wss://<host>/ws` **นอก basePath** → nginx ส่งเข้า catch-all `/`
แทนที่จะเข้าแอปเรา → แชทตายด้วยข้อความ "การเชื่อมต่อหลุด" โดย request
**ไม่เคยไปถึง FastAPI เลย** (ยืนยันได้จาก log ที่ไม่มี WS จาก IP ผู้ใช้)
แก้เป็น `url: wsUrl("/ws")`

หมายเหตุ: v1.4.15 ลงทะเบียน WS ที่ `prefix="/api/v1"` (path `/api/v1/ws`) แต่ v1.6.4
ตัด prefix ออกเหลือ `/ws` — เป็นสาเหตุที่ปัญหานี้ไม่เคยโผล่ในรอบก่อน

**วิธีตรวจ WS ให้ถูก:** curl ต้องบังคับ `--http1.1` เพราะ HTTP/2 ไม่รองรับ
`Upgrade:` header จะได้ 404 หลอก ๆ ที่ไม่ใช่ปัญหาจริง
ผลที่ถูกต้องคือ **403** (ไม่มี cookie) เท่ากับยิงตรง backend

⚠️ `web/app/(workspace)/home/[[...sessionId]]/page.tsx` ของรอบก่อน **ถูกลบแล้ว**
route ใหม่คือ `web/app/(workspace)/chat/[sessionId]/page.tsx` (asset ย้ายไปอยู่ที่
`features/chat/components/ChatWorkspace.tsx` แทน)

### 2.5 `Dockerfile` — build arg
```dockerfile
ARG NEXT_PUBLIC_BASE_PATH=""
ENV NEXT_PUBLIC_BASE_PATH=${NEXT_PUBLIC_BASE_PATH}
```
ต้องอยู่ใน stage `frontend-builder` **ก่อน** `npm run build` เพราะ Next บด basePath
ตอน build เปลี่ยน runtime ไม่ได้
⚠️ upstream แก้ COPY เป็น `COPY --chown=deeptutor:deeptutor --from=frontend-builder /app/web ./web` — ยืนยันตำแหน่ง ARG ใหม่ทุกครั้ง

### 2.5b ตั้งค่า runtime ที่ต้องยกมาด้วย (เกือบลืม)
- `DEEPTUTOR_EMBEDDING_TIMEOUT: "600"` ใน service `deeptutor` — bge-m3 บน CPU
  ~6s/chunk, batch 10 chunk (~58s) ชน default timeout 60s ตอน index เอกสารจริง
- `data/user/settings/system.json`: `next_public_api_base_external` และ
  `next_public_api_base` ต้องเป็น **ค่าว่าง** ตั้งแต่ v1.4.15 เป็นต้นมา ไม่งั้น
  in-container proxy จะยิงออกนอกแล้ววน
- `data/user/settings/integrations.json`: `pocketbase_url` ว่าง = ไม่เปิดใช้
  PocketBase (ใช้ SQLite fallback) — ของเดิมตั้งไว้แบบนี้
- port มาจาก `system.json` (`backend_port`/`frontend_port`) และ
  `integrations.json` (`pocketbase_port`) ผ่าน wrapper ที่เขียน `docker.env`

### 2.6 compose override + nginx — ยกไปทั้งดุ้น
`deploy/patches/verbatim/docker-compose.localhost.yml` และ
`nginx-deepwitya.locations.conf` (แก้ port/path ตามตาราง §1)

---

## 3. Patch ที่ **ทิ้งได้แล้ว** — อย่าแปะซ้ำ

- **LLM `aclose` (commit 44bda81d)** — upstream ทำเองแล้ว:
  `deeptutor/services/llm/provider_core/base.py:125` + เรียกจาก `provider_factory.py`
  โซน LLM ถูกรื้อ 3,154 บรรทัด ดันของเก่าเข้าไปมีแต่พัง

---

## 4. ของใหม่ใน upstream ที่ต้องรับมือ

### 4.1 Redis — service ใหม่ บังคับโดยปริยาย
upstream เพิ่ม `deeptutor-redis` (`redis:7.4-alpine`, volume `./data/redis`)
และ `deeptutor` มี `depends_on: redis: condition: service_healthy`
→ **ไม่มี redis = คอนเทนเนอร์ไม่ start** ถึงแม้ค่า default ของ turn coordination
จะเป็น `memory` (ไม่ได้ใช้ redis จริง) ก็ตาม → ปล่อยรันไปเลย ง่ายสุด

### 4.2 `web/proxy.ts` เปลี่ยนโครง
- ใช้ `resolveBackendApiBase()` จาก `web/lib/backend-runtime-config` แทน env ตรง ๆ
- default เปลี่ยนเป็น `127.0.0.1` แทน `localhost` (dual-stack fix — ตรงกับที่เราต้องการอยู่แล้ว)
- route ใหม่ `isCodexCallbackPath` / `isRetiredPagePath` → ตรวจว่าทำงานถูกใต้ basePath

### 4.3 config layer ถูกรื้อใหญ่
`settings_spec.py` (+697 ใหม่ทั้งไฟล์), `runtime_settings.py` (+481),
`model_catalog.py` (+398), `provider_runtime.py` (+455), `embedding_endpoint.py` (+163)
→ ตั้งค่าใหม่จากศูนย์ปลอดภัยกว่าเอา `data/user/settings/*.json` เก่าไปทับ

---

## 5. ข้อมูลที่ยก / ไม่ยก

**ไม่ต้องยก** — ข้อมูล user ระบบเก่า (ตัดสินใจ 2026-09-04): pocketbase, sessions, memory

**ควรยก** (ไม่ใช่ข้อมูล user แต่เสียเวลาทำใหม่):
- `data/ollama` (1.1 GB, มี `bge-m3:latest`) → copy volume ไม่ต้อง pull ใหม่
- credential ใน settings เดิม — ไฟล์ที่มี key/token/secret:
  `auth.json`, `model_catalog.json`, `document_parsing.json`, `pageindex.json`
  → **ดึงเฉพาะค่า credential** ไปกรอกใน UI ตัวใหม่ อย่า copy ทั้งไฟล์ (schema เปลี่ยน)

---

## 6. Gotchas ของเครื่องนี้ (เจอมาแล้ว ต้องเจออีก)

- **Perms — กับดักใหญ่สุด อ่านให้ครบ**: container รันเป็น UID 1000 และ chown
  `/app/data` ตอน start ส่วน wrapper รันเป็น `search` (1006) บน host
  **บน deploy สดปี v1.6.4 พบว่า container สร้าง `data/user` เป็น 700 และ
  `data/user/settings` เป็น 700 ด้วย → host เข้าไม่ถึงแม้แต่จะ `ls`**

  **⚠️ ต้องทำซ้ำก่อน `up -d` / `--build` ทุกครั้ง** — file mode (644/666) รอด แต่
  **directory mode ถูกรีเซ็ตกลับเป็น 700 ทุกครั้งที่คอนเทนเนอร์ start/restart**
  (โค้ด multi-user เรียก `os.chmod(path, stat.S_IRWXU)` ดู `deeptutor/multi_user/paths.py`)
  อาการ: `python3 scripts/docker_compose.py ... --build` ตายคาที่
  `PermissionError: '/…/data/user/settings'` **ก่อน build จะเริ่มด้วยซ้ำ**
  (log สั้นมาก ไม่มีบรรทัด DONE/CACHED เลย) — เจอจริงตอนแก้ WS fix

  ทางเลี่ยงถาวร: ข้าม wrapper ไปเลย เรียก `docker compose` ตรง ๆ พร้อม
  `--env-file data/user/settings/docker.env` (ไฟล์นั้นเป็น 666 host อ่านได้เสมอ)
  wrapper มีหน้าที่แค่ generate ไฟล์นี้จาก JSON เท่านั้น

  ต้องเปิดสิทธิ์ให้ครบ **ทั้ง directory และไฟล์** มิฉะนั้น wrapper จะ fallback เงียบ ๆ:
  ```
  docker exec <c> chmod 775 /app/data/user /app/data/user/settings
  docker exec <c> chmod 644 /app/data/user/settings/system.json \
                            /app/data/user/settings/integrations.json
  docker exec <c> chmod 666 /app/data/user/settings/docker.env
  ```
  - `system.json` อ่านไม่ได้ → frontend_port fallback 3782 → เข้าเว็บไม่ได้
  - **`integrations.json` อ่านไม่ได้ → pocketbase_port fallback 8090** ← ตัวนี้ร้าย
    เพราะ 8090 คือพอร์ตของ stack เดิม ทำให้ `up -d` ล้มด้วย
    "Bind for 0.0.0.0:8090 failed: port is already allocated" ตอนรันคู่กัน
    (ของเดิมปลอดภัย แค่ตัวใหม่ start ไม่ขึ้น)
  - `docker.env` โดน chown ตอน **restart** → `PermissionError` restart ไม่ผ่าน
    แก้ถาวร: `chmod 666` (666 รอดจาก chown, `write_text` คงโหมดไว้)
  - อาการร่วม: wrapper **ไม่ error** มันพิมพ์ค่าที่ fallback ออกมาเฉย ๆ
    ให้ดูบรรทัด `Docker settings: backend=… frontend=… pocketbase=…` ทุกครั้ง
    ว่าตรงกับที่ตั้งใจไหม
- **AppArmor**: kernel 6.8.0-63 + Docker 29 → `no-new-privileges:true` ทำให้
  sandbox-runner execve EPERM → override ต้องมี `no-new-privileges:false`
- ใช้ **`python3`** เท่านั้น (ไม่มี `python` บนเครื่องนี้)
- start/restart:
  `python3 scripts/docker_compose.py -f docker-compose.yml -f deploy/docker-compose.localhost.yml up -d`

---

## 6b. เปิด multi-user (auth) — **ไม่ต้อง build ใหม่**

`DEEPTUTOR_AUTH_ENABLED` ถูกอ่าน **ตอน request time** โดย middleware (`web/proxy.ts`)
ไม่ได้ inline เข้า browser bundle (ดู comment ใน `runtime_settings.py`) ส่วนฝั่ง client
เรียนรู้สถานะจาก `fetchAuthStatus()` → `setRuntimeAuthEnabled()` ตอน runtime เช่นกัน
→ **แก้ config แล้ว restart คอนเทนเนอร์ พอ**

```
docker exec <c> python3 -c "
import json; p='/app/data/user/settings/auth.json'
d=json.load(open(p)); d['enabled']=True; d['cookie_secure']=True
json.dump(d,open(p,'w'),indent=2)"
docker restart <c>
```

- `cookie_secure=True` ใช้ได้เพราะ path นี้บังคับ HTTPS แล้ว **แต่ถ้าเข้าตรงพอร์ต
  (http://host:10320) จะ login ไม่ได้** — ต้องเข้าผ่าน nginx เท่านั้น
- **`docker compose up -d` เฉย ๆ ไม่พอ** ถ้าไฟล์ compose ไม่เปลี่ยน compose จะขึ้น
  "Running" แล้วไม่ recreate → env เดิมค้าง ต้อง `docker restart` ตรง ๆ
- ตรวจว่าติดจริงที่ **API ไม่ใช่ `docker exec env`** (exec เห็นแค่ env ตอนสร้าง
  คอนเทนเนอร์ ไม่เห็นตัวที่ entrypoint export ให้ลูก):
  `curl .../api/auth/status` ต้องได้ `"enabled":true`
  และ log ต้องขึ้น `📌 Auth enabled: true`
- ผู้ใช้คนแรก: `/register` เปิดให้สมัครได้ **เฉพาะตอน user store ว่าง** คนแรกเป็น admin
  หลังจากนั้นปิด — admin ต้องสร้างคนอื่นผ่าน `POST /api/auth/users`
  เช็คสถานะ: `curl .../api/auth/is_first_user`
- **อย่าเปิด PocketBase ถ้าจะใช้ multi-user** — โค้ดระบุว่า PocketBase deployment
  เป็น single-user และจะปิด self-registration (`pocketbase_url` ต้องว่าง = SQLite)
- หน้า `/` (basePath root พอดี) ตอบ 200 ไม่เด้ง login — ปกติ ไม่ใช่ช่องโหว่
  เพราะไม่มี `web/app/page.tsx` มันคือ shell เปล่า ทุก route จริงเด้ง 307 ไป
  `/login?next=…` และ API ตอบ 401

## 7. เกณฑ์ตัดสินว่าเขียว (ก่อนสลับ nginx)

- [ ] `curl -sL http://localhost/deepwitya2` → 200
- [ ] `curl http://localhost/deepwitya2/api/v1/auth/status` → JSON (ไม่ใช่ HTML 404)
- [ ] เปิดหน้าเว็บแล้ว **ไม่มี asset 404** ใน devtools (ตัวชี้วัดว่า `asset()` ครบ)
- [ ] embedding: เรียก `http://ollama:11434/api/embed` จากใน container → ได้ vector 1024 มิติ
- [ ] chat จบ 1 รอบ + RAG retrieve ได้จริง
- [ ] คอนเทนเนอร์ทุกตัว healthy และ `RestartCount = 0` หลังผ่านไป 30 นาที

เขียวครบ → สลับ nginx `/deepwitya` ไปชี้ตัวใหม่ → เฝ้า 1-2 วัน → ค่อยลบตัวเก่า
