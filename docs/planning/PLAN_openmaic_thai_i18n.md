# แผน: ภาษาไทยสำหรับ OpenMAIC (ส่งขึ้น upstream THU-MAIC)

> สถานะ (2026-09-06): **PR 1 และ PR 2 ทำเสร็จแล้ว รอการตัดสินใจว่าจะส่ง upstream
> หรือไม่** งานอยู่ใน `deploy/openmaic-patches/` — ยังไม่ push และยังไม่ส่งใคร
> ตัวเลขทุกตัวในเอกสารนี้วัดจากซอร์สจริงของ `D:\Vscode\OpenMAIC` (commit
> `d4ef5faa`) ไม่ใช่การประมาณ
>
> - **PR 2 (locale)** — แปล 1,689/1,800 คีย์ ที่เหลือคือ endonym 108 ตัวกับ
>   `null` 3 ตัวที่ไม่มีอะไรให้แปล ผ่าน `check-i18n-keys.mjs` ของ upstream เอง
> - **PR 1 (ฟอนต์)** — `0002-thai-script-support.patch` ครอบทั้ง UI และ video export
> - **เฟส 3 (workbench overlay 247 คีย์)** — ยังไม่ทำ ไม่บล็อกอะไร
> เจ้าของ: Attapon · ผู้ช่วยวิเคราะห์: Claude
> ซอร์สอ้างอิง: [THU-MAIC/OpenMAIC](https://github.com/THU-MAIC/OpenMAIC) (MIT)
> งานที่เกี่ยวข้อง: `feat/openmaic-embed` (ฝัง OpenMAIC ที่ `/maic`) —
> ดู [`docs/reports/REPORT_openmaic_embed_L1.md`](../reports/REPORT_openmaic_embed_L1.md)
> และ [`deploy/OPENMAIC_EMBED.md`](../../deploy/OPENMAIC_EMBED.md)

---

## 0. ทำไมแผนนี้ถึงมีอยู่

เราฝัง OpenMAIC เข้ามาเป็นเมนู "Course Studio" ที่ `/maic` แล้ว แต่ **OpenMAIC ไม่มี
ภาษาไทยเลย** — มี 12 locale (`ar-SA de-DE en-US es-MX fr-FR ja-JP ko-KR pt-BR ru-RU
vi-VN zh-CN zh-TW`) ไม่มีไทย ผู้ใช้ที่เลือกภาษาไทยใน DeepTutor กดเมนูนี้แล้วเจอ
อังกฤษล้วน

คำถามที่ตามมาคือ **จะแปลที่ไหน** และเรามีบทเรียนของตัวเองอยู่แล้ว: ภาษาไทยของ
DeepTutor เกิดจาก commit `8360f589` ของฟอร์คนี้เอง ไม่เคยส่งขึ้น HKUDS ผลคือทุกวันนี้
`CLAUDE.md` ต้องเขียนเตือนว่า upstream sync เป็น **"merge-with-conflicts ไม่ใช่
fast-forward"** และต้องมีคู่มือ sync ทั้งชุดใน `docs/planning/upstream-sync/`
แค่เพราะเรื่องนี้

**ถ้าแปล OpenMAIC ในสำเนาของเรา เราจะสร้างกับดักเดียวกันขึ้นมาอีกที่หนึ่ง**

เอกสารนี้จึงตั้งอยู่บนสมมติฐานว่า **เป้าหมายคือส่งขึ้น upstream** และวางแผนให้ PR
มีโอกาส merge สูงที่สุด

> **จังหวะสำคัญ:** งาน `feat/openmaic-embed` ที่เพิ่งทำ **ไม่ได้แก้ไฟล์ของ OpenMAIC
> เลยแม้แต่ไฟล์เดียว** สำเนาของเรายังสะอาด 100% ถ้าปล่อยให้มีการแก้ไฟล์ในนั้นก่อน
> ด้วยเหตุผลอื่นใด มันจะกลายเป็นฟอร์คที่สองทันที และแผนนี้จะแพงขึ้นทั้งแผน

---

## 1. ปริมาณงาน (วัดจริง)

| ไฟล์ | คีย์ | คำ | ตัวอักษร |
|---|---|---|---|
| `lib/i18n/locales/en-US.json` | 1,800 (string 1,797) | **6,429** | 40,474 |
| workbench (baseline = `workbenchEn` ใน `lib/i18n/workbench.ts`) | 247 | — | — |

ความยาวเฉลี่ย 22.5 ตัวอักษร ยาวสุด 197 — ส่วนใหญ่เป็น label/ปุ่ม ไม่ใช่ prose ยาว

### 1.1 งานกระจุกอยู่ไหน (28 section)

```
settings     715   <- 40% ของทั้งหมด — กลไกล้วน วิจารณญาณต่ำ
edit         329
pbl          191
generation   109
workspace     86
export        54
classroom     48   <- ส่วนที่ต้องใช้วิจารณญาณ กลับเล็ก
chat          34
toolbar       31
quiz          27
roundtable    23
actions       21
proMode       16
import / whiteboard / stage / media / agentBar / ... ที่เหลือ
```

ข้อสังเกตสำหรับการวางแรง: **40% แรกเป็นแผงตั้งค่า** ซึ่งแปลเร็วและตรวจง่าย
ส่วนที่ต้องใช้ความคิดจริง (`classroom`, `agentBar`, `chat`, `home`) รวมกันไม่ถึง 10%

---

## 2. ความยากที่แท้จริง — ไม่ได้อยู่ที่ปริมาณ

- **106 คีย์มี interpolation `{{...}}`** ตัวแปรต่างกัน 41 ตัว
  (`count` 34 ครั้ง, `name` 16, `total` 9, `n` 8, `error` 6, `title` 5, `max` 4, `type` 3, ...)
  `TRANSLATION_GUIDE.md` สั่งชัด: **ห้ามลบหรือเปลี่ยนชื่อตัวแปร** โค้ดอ้างอิงอยู่
- **3 คีย์เป็น plural form** — ไทยไม่ผันพจน์ ข้อนี้แทบฟรี (ต่างจาก ru-RU / ar-SA ที่หนัก)
- **31 ค่ายาวเกิน 100 ตัวอักษร** — เป็นคำอธิบาย/คำเตือน ต้องอ่านบริบทก่อนแปล
- **6 คีย์มี "design intent"** ที่ upstream เขียนกำกับไว้เอง แปลตรงตัวถือว่าผิด:

  | คีย์ | ข้อกำหนด |
  |---|---|
  | `home.greetingWithName` | เป็น **call-to-action** ไม่ใช่คำทักทาย (กดแล้วเปิดช่องแก้ชื่อเล่น) ต้องมี `{{name}}` และห้ามแปลเหลือแค่ "ยินดีต้อนรับ" |
  | `profile.defaultNickname` | คำอบอุ่น เป็นกลางทางเพศ และสื่อว่า "นี่คือ placeholder ไปแก้ได้" — EN ใช้ "Learner", ZH ใช้ "同学" ห้ามใช้คำเย็นชาแบบ "ผู้ใช้" หรือทางการแบบ "นักเรียน" |
  | `profile.bioPlaceholder` | ต้องบอกใบ้ว่า bio ถูกส่งให้ AI ครูใช้ปรับบทเรียน — อธิบาย *ทำไม* ถึงควรกรอก |
  | `generation.textTruncated` / `imageTruncated` | toast เตือนทางเทคนิค สั้นและตรงไปตรงมา มี `{{n}}` / `{{total}}` + `{{max}}` |
  | `agentBar.readyToLearn` | ประโยคปลุกอารมณ์ก่อนเข้าเรียน ต้อง "ชวน" ไม่ใช่ "สั่ง" |
  | `settings.agentsCollaboratingCount` | เป็น status label ไม่ใช่ปุ่ม มี `{{count}}` |

---

## 3. รูปร่าง PR จริง — วัดจาก vi-VN (#1025)

commit `8db87855` "feat(i18n): add Vietnamese (vi-VN) locale" แตะแค่ **6 ไฟล์ 1,838 บรรทัด**:

```
lib/i18n/locales/vi-VN.json             +1827   ตัวงาน
lib/i18n/locales.ts                        +1   { code, label, shortLabel }
lib/video-export-app/cover-config.ts       +2   import + map entry
tests/video-export/cover-config.test.ts    +5   CTA 3 ประโยค
README.md / README-zh.md                   +6
```

**workbench ไม่ได้อยู่ใน PR นั้น** — มาทีหลังเป็น PR แยก และคีย์ที่ยังไม่แปลจะ
fall back เป็นอังกฤษที่อ่านรู้เรื่อง (ไม่ใช่ `workbench.tool.label.x`) เพราะ
`workbenchResourceFor` merge ทับ English เสมอ **แปลว่าทำเป็นเฟสหลังได้อย่างปลอดภัย**

### 3.1 Gate ที่ต้องผ่าน

- `npm run check:i18n-keys` — บังคับคีย์ตรงกับ `en-US.json` เป๊ะ, ห้าม array,
  ห้าม object ว่าง
- `tests/workbench/workbench-i18n.test.ts` — คุมรูปร่าง overlay ทั้ง 10 ภาษา (เฟส 3)
- `tests/video-export/cover-config.test.ts` — ต้องเพิ่ม CTA 3 ประโยคของไทย

---

## 4. สองอย่างที่ไทยต้องทำเพิ่ม แต่ vi-VN ไม่ต้อง

### 4.1 ฟอนต์ไทย — แก้ข้อมูลจากฉบับแรก

> **แก้ข้อมูล (2026-09-06):** ฉบับแรกเขียนว่า *"เขาเพิ่มฟอนต์แยกต่อ script ทุกภาษา
> ที่ไม่ใช่ละติน (zh→noto-sans-sc, ko→noto-sans-kr, ar→noto-sans-arabic)"* —
> **ไม่จริง** ฟอนต์เหล่านั้นไม่ได้เข้า UI chrome: `app/editor-fonts.ts` ถูกโหลด
> โดย `lib/edit/preload-editor.ts` เท่านั้น คือเป็นฟอนต์สำหรับ*เนื้อหาในสไลด์*
> ส่วนอีกชุดใช้ตอน video export ข้อความ UI ภาษาจีน เกาหลี และอาหรับ **ตกไปใช้
> ฟอนต์ OS เหมือนกันหมด** ไทยจึงไม่ได้แย่กว่าภาษาอื่น

สภาพจริง แยกเป็นสามเส้นทาง:

| | UI chrome | ฟอนต์ในสไลด์ | video export (MP4) |
|---|---|---|---|
| latin, cyrillic, greek, vietnamese | **Inter** OK | — | `noto-script-fonts` OK |
| จีน, เกาหลี | ฟอนต์ OS | `editor-fonts.ts` OK | `noto-cjk` OK |
| อาหรับ | ฟอนต์ OS | — | `noto-script-fonts` OK |
| **ไทย** | ฟอนต์ OS | ไม่มี | **ไม่มีเลย** |

งานฟอนต์จึงมีน้ำหนักไม่เท่ากันสองชิ้น:

**(ก) video export — บั๊กจริง** ทั้ง `generate-video-export-noto-cjk.mjs` (sc/kr)
และ `generate-video-export-noto-script-fonts.mjs` (cyrillic/arabic) ไม่มีไทย
MP4 ที่ export ออกมาเป็นกล่องสี่เหลี่ยม ไม่ใช่แค่คนละฟอนต์

**(ข) UI chrome — เป็นการเพิ่ม ไม่ใช่การแก้** ไทยเรนเดอร์ด้วยฟอนต์ OS เหมือนจีน
กับเกาหลีเป็นอยู่ทุกวันนี้ ถ้า bundle ให้ไทย ไทยจะดีกว่าจีนซึ่งเป็น locale ปริยาย
ของเขา — upstream มีสิทธิ์ถามว่าทำไมทำให้ภาษาเดียว

**ทั้งสองข้อทำเสร็จแล้ว** ใน `deploy/openmaic-patches/0002-thai-script-support.patch`
ใช้ `@fontsource/noto-sans-thai` (ยืนยันแล้วว่า `@fontsource/noto-sans` มี subset
cyrillic/devanagari/greek/latin/vietnamese **ไม่มี thai**) โหลดผ่าน `400.css` /
`700.css` ที่มี `unicode-range` ต่อ subset — วิธีเดียวกับที่ `layout.tsx` อธิบาย
ไว้เองว่าทำไมถึงเลิกใช้ `next/font`

วัดผลบน dev server จริง: จาก 6 faces ที่ประกาศ โหลดมา 2 (ไทย 400 และ 700) ส่วน
latin / latin-ext ไม่ถูกดึงเลย และ `document.fonts.check(..., 'ก')` = true ขณะที่
เช็คด้วย 'A' = false

### 4.2 ฟอนต์สำหรับ video export

`scripts/generate-video-export-noto-script-fonts.mjs` มี registry ต่อ script ที่
ตอนนี้ครอบคลุมแค่ `cyrillic` กับ `arabic` (ปรากฏเป็น literal list 3 จุดในไฟล์)
แล้ว generate ออกมาเป็น `noto-script-font-assets.ts`

ต้องเพิ่ม entry ของไทย + รัน `npm run gen:video-export-noto-script-fonts`
ไม่งั้น **MP4 ที่ export ออกมาจะเรนเดอร์ไทยเป็นสี่เหลี่ยมเปล่า**

### 4.3 ข่าวดี — สองเรื่องที่ไม่ต้องทำอะไร

- **การตัดคำ:** `components/workbench/chat/workbench-chat.css:335` ใช้
  `word-break: normal` ซึ่งถูกต้องสำหรับไทยอยู่แล้ว (เบราว์เซอร์ตัดคำไทยด้วย
  dictionary เมื่อเป็น `normal`) ไม่มี `break-all` ให้ต้องไปแก้
- **ทิศทางข้อความ:** ไม่พบ machinery จัดการ RTL ต่อ locale — ไทยเป็น LTR
  จึงไม่กระทบ

---

## 5. แผนเป็นเฟส

### PR 1 — รองรับอักษรไทย (ฟอนต์)

**ทำไมแยก:** reviewer ที่ THU-MAIC ตัดสินคุณภาพคำแปลไทยไม่ได้ แต่ตัดสินงานฟอนต์ได้
ถ้ารวมเป็น PR เดียวแล้วเขาลังเลกับคำแปล งานฟอนต์จะติดร่างแหไปด้วย และถ้า PR 1 ค้าง
PR 2 ก็ยัง merge ได้ แค่เรนเดอร์ด้วยฟอนต์ fallback ไปก่อน

- เพิ่ม `@fontsource/noto-sans-thai` ใน `package.json`
- ต่อเข้า font stack ของ UI (`app/layout.tsx` / `app/globals.css`)
- เพิ่ม entry ไทยใน `scripts/generate-video-export-noto-script-fonts.mjs`
  แล้ว regenerate assets
- **เกณฑ์ผ่าน:** ข้อความไทยตัวอย่างเรนเดอร์ด้วย Noto Sans Thai ทั้งใน UI และใน MP4
  ที่ export บนเครื่องที่ *ไม่มี* ฟอนต์ไทยติดตั้งใน OS
- **ประเมิน:** 0.5 วัน · ทำได้ทันทีโดยไม่ต้องรอคำแปล

### PR 2 — locale `th-TH`

เดินตามรอย vi-VN เป๊ะ:

- `lib/i18n/locales/th-TH.json` (1,800 คีย์)
- `lib/i18n/locales.ts` — `{ code: 'th-TH', label: 'ไทย', shortLabel: 'TH' }`
- `lib/video-export-app/cover-config.ts` + `tests/video-export/cover-config.test.ts`
- README ทั้งสองไฟล์
- **เกณฑ์ผ่าน:** `npm run check:i18n-keys` เขียว · ตัวแปร interpolation ครบทั้ง
  106 คีย์ · 6 คีย์ design-intent ผ่านการรีวิวโดยคนที่อ่านคู่มือแล้ว
- **ประเมิน:** 3.5–5.5 วัน (แปล 3–5 + ตรวจ interpolation / design-intent 0.5)

### PR 3 — workbench overlay (เฟสหลัง)

- `lib/i18n/workbench-locales/th-TH.json` (247 คีย์) + import ใน `workbench.ts`
- **เกณฑ์ผ่าน:** `tests/workbench/workbench-i18n.test.ts` เขียว
- **ประเมิน:** 1 วัน · เลื่อนได้ ไม่บล็อกอะไร (fall back เป็นอังกฤษที่อ่านรู้เรื่อง)

**รวมเฟส 1–2: ~1 สัปดาห์**

---

## 6. ถ้า upstream ไม่รับ

ความเสี่ยงต่ำ — เขามี 12 ภาษาอยู่แล้ว มี `TRANSLATION_GUIDE.md` ที่เขียนขั้นตอน
เพิ่มภาษาไว้ชัดเจน 3 ข้อ และเพิ่งรับ vi-VN เข้าไป แต่ถ้าค้างหรือถูกปฏิเสธจริง:

1. **เก็บงานไว้เป็น patch แยก** อย่าแก้ไฟล์ในสำเนาโดยตรง — ทำเป็นไฟล์ patch ที่
   apply ได้ในขั้นตอน build ของเรา เพื่อให้ยัง `git pull` จาก THU-MAIC ได้สะอาด
2. บันทึกใน `CHANGES.md` และเขียนขั้นตอน re-apply ไว้ เหมือนที่ทำกับ
   `docs/planning/upstream-sync/` ของ DeepTutor
3. ยอมรับว่าเราจะมี upstream สองตัวที่ต้อง re-apply ทุกครั้ง — ซึ่งคือสิ่งที่
   แผนนี้ทั้งแผนพยายามหลีกเลี่ยง

---

## 7. ลำดับการตัดสินใจ

1. ยืนยันว่าจะส่ง upstream (ไม่ใช่แปลในสำเนา) — **ตัดสินใจก่อนแตะโค้ด OpenMAIC ใดๆ**
2. ทำ PR 1 (ฟอนต์) ได้ทันที ไม่ต้องรออะไร
3. หา/จัดคนแปล 6,429 คำ แล้วทำ PR 2
4. PR 3 เมื่อว่าง
