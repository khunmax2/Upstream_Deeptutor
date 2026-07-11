# รายงานปิดรอบ (Thai Localization) — Round 2: Thai UI parity

> ก๊อปจาก `Thai_Localization_DeepTutor_REPORT_TEMPLATE.md` แล้วกรอกตามจริง

---

## รอบ/Phase: Round 2 (Phase 2 + 3)   |   วันที่: 2026-06-17   |   branch: `feature/thai-i18n-foundation` (ทำต่อจากรอบ 1 ไม่ได้แตก branch ใหม่)

### 1. TL;DR (3–5 บรรทัด)
- สถานะ: ✅ เสร็จครบตาม scope รอบ 2
- ทำอะไรไปบ้าง: เติม `th/app.json` ให้ parity 100% กับ en (เพิ่ม 590 key แปลไทย, ลบ stale 43),
  parity `common.json` ทั้ง en/zh/th, generalize parity script ให้ loop ทุก locale,
  เพิ่ม `th` ใน settings-nav/tools/dashboard/book creator/quiz-judge/shared/SettingsContext
  + อัปเดต 3 settings renderer ให้ render ไทยจริง
- พร้อมไปรอบ 3 ไหม: **ใช่** — `i18n:parity` (gate หลัก) ผ่าน 0 missing, tsc/build/test:node เขียวทั้งหมด

### 2. Scope ที่ทำจริง (เทียบกับ PLAN)
| Phase ใน PLAN | ทำแล้ว? | หมายเหตุ |
|---|---|---|
| 2.1 th/app.json parity | ✅ | 2067 → 2614 keys (เพิ่ม 590, ลบ stale 43) = เท่า en |
| 2.2 th/common.json parity | ✅ | th มี 7 keys = en (หลังเพิ่ม language.thai ใน en) |
| 2.3 language.thai ใน en/zh common.json | ✅ | เก็บงานค้างรอบ 1 |
| 2.4 i18n_parity.mjs loop ทุก locale | ✅ | baseline = en, auto-detect ทุกโฟลเดอร์ใน locales/ |
| 3.1 settings-nav.ts Lang + th | ✅ | `Lang` += th; เติม th ทุก label/blurb/HUB/crumb |
| 3.2 tools/page.tsx (zh→map, CAPABILITY_LABELS, coming soon) | ✅ | `const zh` → `pick(en,zh,th)`; CAPABILITY_LABELS += th; "เร็วๆ นี้" 2 จุด |
| 3.3 SettingsContext model prefix | ✅ | map `{en,zh,th}` → "โมเดล "; สอดคล้องกับ `defaultModelLabel` (รอบ 1) |
| 3.4 shared.tsx type + locale | ✅ | `th-TH`; Thai ใช้ branch ไม่ uppercase (เหมือน CJK) |
| 3.5 SpaceDashboard Lang + th | ✅ | type + ทุก literal + `tr` รองรับ th |
| 3.6 BookCreator dropdown | ✅ | cast += th + `<option value="th">ไทย` |
| 3.7 quiz-judge.ts type | ✅ | `"zh"|"en"` → += th |

### 3. ไฟล์ที่แตะ
**แก้ไข (locale / scripts):**
- `web/locales/th/app.json` — เพิ่ม 590 คำแปลไทย, ลบ 43 stale, เรียง key ตาม en (2614)
- `web/locales/th/common.json` — (seed รอบ 1; parity แล้วกับ en)
- `web/locales/en/common.json`, `web/locales/zh/common.json` — เพิ่ม `language.thai`
- `web/scripts/i18n_parity.mjs` — loop ทุก locale เทียบ en เป็น baseline

**แก้ไข (Phase 3 ตามลิสต์):**
- `web/lib/settings-nav.ts` — `Lang` += th + เติม th ทุก label/blurb
- `web/app/(utility)/settings/tools/page.tsx` — `pick(en,zh,th)`, CAPABILITY_LABELS += th, coming soon th
- `web/components/settings/SettingsContext.tsx` — model prefix map (+ th "โมเดล ")
- `web/components/settings/shared.tsx` — `formatContextWindowUpdatedAt`/`labelClass` += th
- `web/components/space/SpaceDashboard.tsx` — `Lang` + literals + `tr` += th
- `web/app/(workspace)/book/components/BookCreator.tsx` — book-language dropdown += th
- `web/lib/quiz-judge.ts` — `QuizJudgeRequest.language` += th

**แก้ไข (นอกลิสต์ — จำเป็นเพื่อให้ Thai labels render จริง + กัน tsc พัง — ดูข้อ 6):**
- `web/components/settings/SettingsHub.tsx` — `tr` รองรับ th + 6 inline Lang literal += th
- `web/components/settings/SettingsBreadcrumb.tsx` — `tr` รองรับ th
- `web/components/settings/SettingsSectionGrid.tsx` — `tr` รองรับ th + 2 inline literal (configured/not set) += th

**สร้างใหม่:** `REPORT_round2.md`

**ไฟล์ meta ที่ยังขึ้น `M` แต่ไม่ใช่ของรอบนี้/รอบก่อน (pre-existing ตั้งแต่ก่อนเริ่มงานไทย):**
- `.gitignore` — pre-existing (ถูกแก้ก่อนเริ่มรอบ 1; เป็นตัวที่ทำให้ CHANGELOG.md/CLAUDE.md กลายเป็น gitignored)
- `AGENTS.md` — pre-existing (ถูกแก้ก่อนเริ่มรอบ 1) **ผมไม่ได้แก้ทั้งสองไฟล์นี้** — บันทึกไว้ตามคำเตือนรอบ 1

> หมายเหตุ: `web/next-env.d.ts` ถูก build สร้างใหม่ทุกครั้ง → revert กลับด้วย `git checkout` แล้ว (build artifact ไม่ commit)

### 4. ผล Test Gate (จาก TEST_PLAN — รอบที่ 2)

| คำสั่ง | ผล | หมายเหตุ / output สำคัญ |
|---|---|---|
| `npm run i18n:parity` (GATE หลัก) | ✅ | `[i18n:parity] OK (locales checked vs en: th, zh)` — th **0 missing / 0 extra** |
| `npm run i18n:audit` | ✅ (exit 0) | informational; warnings เป็น hardcoded string เดิม (มีอยู่ก่อนแล้ว ทั้ง en/zh) ไม่ใช่ key gap |
| `npx tsc --noEmit` | ✅ | `TSC_REAL_EXIT=0` |
| `npm run build` | ✅ | `✓ Compiled successfully in 10.6s`, `BUILD=0` (settings subpages prerender ครบ) |
| `npm run test:node` | ✅ | `tests 133 / pass 133 / fail 0` (รวม normalize-language รอบ 1) |

**parity ก่อน/หลัง:** th `app.json` 2067 → **2614** keys (= en 2614), missing **590 → 0**, stale **43 → 0**.
common.json: en/zh/th ทั้งหมด 7 keys ตรงกัน.

**คุณภาพการแปล (self-check ด้วยสคริปต์):**
- coverage: 590/590 key แปลครบ (0 uncovered)
- placeholder integrity: ตรวจ `{{...}}` ทุก key — **0 mismatch** (ทุก placeholder ใน en ปรากฏใน th ครบ)
- product/tech names (API, MinerU, PDF, CLI, BM25, GraphRAG, PageIndex, Docling, markitdown,
  FastAPI, Next.js, Obsidian, Feishu/Telegram/Slack, Claude Code/Codex, SVG/PNG ฯลฯ) + path/code คงเดิม

### 5. Manual smoke (Phase 2/3)
- ทำอะไร: **ไม่ได้รันเบราว์เซอร์แบบ interactive** (ไม่มี GUI/Playwright ในรอบนี้) — ใช้หลักฐาน static แทน:
  - `npm run build` prerender ทุก settings subpage (`/settings/{appearance,network,models,llm,embedding,
    search,tts,stt,image,video,tools,mcp,capabilities,memory,...}`) + space/* + book สำเร็จ
  - `i18n:parity` = 0 missing → **เป็นไปไม่ได้ที่ key string จะโชว์ raw key** (เช่น `guidedLearning.xxx`)
    เพราะ th มีครบทุก key และ `fallbackLng:"en"` รองรับส่วนที่ไม่ใช่ keyed
- ผล: ผ่านตามหลักฐาน static; **ยังไม่ได้แนบ screenshot การ render ไทยจริง** (ดู residual risk)
- ภาษาที่ออกมา: คาดว่าไทยครบในส่วน keyed + settings-nav/dashboard/tools (เพราะ renderer เลือก th แล้ว)

### 6. จุดที่ทำ "ต่างจากแผน" (Deviations) — สำคัญ
1. **แตะ 3 ไฟล์นอกลิสต์ Phase 3** (`SettingsHub.tsx`, `SettingsBreadcrumb.tsx`, `SettingsSectionGrid.tsx`):
   ไฟล์เหล่านี้ consume `Lang` จาก settings-nav ผ่าน `tr = (l) => zh ? l.zh : l.en` (binary)
   - **ทำไม:** ถ้าไม่แก้ การเติม th ใน settings-nav จะ "มองไม่เห็น" (th user เห็น en) + มี inline
     `Lang` literal ใน 2 ไฟล์นี้ที่ทำให้ **tsc พัง** หลังเปลี่ยน type เป็น require `th`
   - **กระทบ phase อื่นไหม:** ไม่ — เป็น render layer ของ settings เท่านั้น
2. **เพิ่ม inline Lang literal += th หลายจุดใน SettingsHub** (Settings/Tour/API/local/“configured”) —
   จำเป็นเพราะ type `Lang` บังคับ field th (ถ้าไม่เติม tsc พัง)
3. **`labelClass` ให้ Thai ใช้ branch เดียวกับ CJK** (ไม่ uppercase/ไม่ letter-spacing) ตามข้อควรระวังใน PLAN 1.5
4. **th/app.json: ทุก key แปลใหม่ 100%** — repo เก่าให้คำแปล reuse ได้ **0 key** (en ของ v1.4.6 เป็น
   flat English-string keys เวอร์ชันใหม่ที่ไม่ตรงกับ key เก่าเลย) จึงแปลใหม่ทั้ง 590 (บันทึกไว้เพราะ
   PLAN 2.1 คาดว่าจะ reuse จากเก่าได้บางส่วน)
5. **Manual smoke ใช้หลักฐาน static** (ไม่มี browser interactive) — ดูข้อ 8

### 7. ปัญหา & งานค้าง (Blockers / TODO)
- [ ] แนบ screenshot การ render ไทยจริงของ settings/dashboard/book (ต้องมี dev server + browser)
- [ ] รอบ 3: backend runtime (chat pipeline, explorer, obsidian, partners, metadata i18n, quiz_judge whitelist)
- [ ] คำแปลไทยบางคำเป็นศัพท์เทคนิคทับศัพท์ (embedding, ชังก์, เวกเตอร์) — review โดยเจ้าของภาษา/โดเมนได้

### 8. Residual risk / สิ่งที่อยากให้ช่วย review
- **ยังไม่มี screenshot ยืนยันการ render** — static gate ผ่านหมดแต่ไม่ได้เห็นด้วยตา; ถ้าต้องการ ผมรัน
  `npm run dev` + เปิดหน้าให้ได้ในรอบถัดไป
- **คุณภาพคำแปล 590 key**: แปลโดย AI เน้นความถูกต้อง/เป็นธรรมชาติ + คงศัพท์เทคนิค — ควร review สุ่มบางหมวด
  (โดยเฉพาะ Knowledge Center / RAG / MinerU ที่ศัพท์เทคนิคเยอะ)
- **จุด binary zh/en ที่ยังเหลือโดยตั้งใจ** (scope รอบ 3+): runtime/agent backend, hardcoded label นอก settings
- `i18n:audit` ยังมี hardcoded UI literal เดิม (เช่น placeholder "gpt-4o", aria-label "DeepTutor") — มีมาก่อน
  หน้านี้แล้วทั้ง en/zh ไม่ใช่งานไทย จึงไม่แก้ในรอบนี้

### 9. CHANGELOG
> CHANGELOG.md ตอนนี้ **gitignored** (จาก `.gitignore` ที่ถูกแก้ก่อนรอบ 1) — อัปเดตบนดิสก์แล้ว ✅ (จะไม่เข้า git ตามที่ผู้ใช้ตัดสินใจ)
- entry ที่เพิ่ม (ใต้ `## [Unreleased] > ### Added`): "Thai (`th`) UI localization (round 2 — Phases 2/3 ...)"
  ระบุ parity 2614 keys, 590 แปลใหม่, 43 stale, parity script, และทุกไฟล์ Phase 3 + 3 renderer
- `graphify update .` ✅ (`18715 nodes, 34864 edges` — graph.json + GRAPH_REPORT.md อัปเดต)

### 10. ขั้นถัดไปที่เสนอ
- รอบถัดไป: **Round 3 — Thai runtime** (Phase 6/7/10): chat pipeline ไม่บีบ th, explorer/obsidian/partners,
  metadata i18n, quiz_judge API whitelist, source/context labels
- เตรียม/ตัดสินใจก่อน: ต้องการ screenshot ยืนยัน Thai UI ของรอบ 2 ก่อนไปรอบ 3 ไหม

---

## เช็คลิสต์ก่อนส่ง report
- [x] กรอกครบทุกหัวข้อ (ไม่มี gate ผ่านปลอม)
- [x] วาง output จริงของ gate (parity OK 0 missing / tsc 0 / build OK / 133 node tests)
- [x] ระบุ deviations ตรง ๆ (5 ข้อ รวม 3 ไฟล์นอกลิสต์)
- [x] บันทึกไฟล์ meta ที่ขึ้น M ทุกไฟล์ (`.gitignore`, `AGENTS.md` = pre-existing ไม่ใช่ของผม; `next-env.d.ts` = revert แล้ว)
- [x] อัปเดต CHANGELOG.md (local-only) + `graphify update .`
- [x] ไฟล์ report ชื่อ `REPORT_round2.md` (repo root)
- [x] ยังไม่ merge เข้า main — อยู่บน `feature/thai-i18n-foundation` รอ review
