# รายงานปิดรอบ (Thai Localization) — Round 1: Thai Foundation

> ก๊อปจาก `Thai_Localization_DeepTutor_REPORT_TEMPLATE.md` แล้วกรอกตามจริง

---

## รอบ/Phase: Round 1 (Phase 1 / 4 / 5)   |   วันที่: 2026-06-17   |   branch: `feature/thai-i18n-foundation`

### 1. TL;DR (3–5 บรรทัด)
- สถานะ: ✅ เสร็จครบตาม scope รอบ 1
- ทำอะไรไปบ้าง: เพิ่ม `th` เข้า frontend language plumbing (type/normalizer/lazy-load/selector/datetime),
  backend plumbing (`parse_language`, interface settings, settings API schema, core i18n),
  prompt manager + `normalize_agent_language()` + label "ภาษาไทย" + fallback `th→en`; seed locale ไทย;
  เพิ่ม unit test ครบทุก gate ของรอบ 1
- พร้อมไป phase ถัดไปไหม: **ใช่** — ทุก gate รอบ 1 เขียว (unit/tsc/build/regression) และเลือกไทยไม่ crash
  (fallback en ทำงาน เพราะ th locale ยังไม่ parity — เป็นงานรอบ 2)

### 2. Scope ที่ทำจริง (เทียบกับ PLAN)
| Phase ใน PLAN | ทำแล้ว? | หมายเหตุ |
|---|---|---|
| 1.1 ขยาย `AppLanguage` (2 ที่) | ✅ | `app-shell-storage.ts:3`, `i18n/init.ts:6` |
| 1.2 normalizeLanguage (2 ตัว) | ✅ | storage = exact `th`; init = `th`/`thai` |
| 1.3 lazy-load th/app.json | ✅ | เพิ่ม branch ใน `ensureLanguage` |
| 1.4 selector "ไทย" | ✅ | `appearance/page.tsx` ใช้ label map + key `language.thai` |
| 1.5 datetime `th→th-TH` | ✅ | `lib/datetime.ts` |
| 2 (seed only) | 🟡 | seed `th/app.json`+`common.json` จาก repo เก่า; **parity ยังไม่ทำ** (รอบ 2) |
| 4.1 `parse_language` | ✅ | + docstring `zh/en/th` |
| 4.2 `_normalize_language` | ✅ | interface_settings |
| 4.3 settings API schema | ✅ | `UISettings` + `LanguageUpdate` Literal มี `th` |
| 4.4 core i18n `_parse_language` | ✅ | `th` branch; `_MESSAGES["th"]` ยังไม่เพิ่ม (fallback en) |
| 5.1 `normalize_agent_language` | ✅ | + `__all__` |
| 5.2 label "ภาษาไทย" | ✅ | `_LANGUAGE_LABELS["th"]` |
| 5.4 prompt fallback `th→["th","en"]` | ✅ | `manager.py` |
| (เพิ่ม) en/zh `language.thai` key | ✅ | `web/locales/{en,zh}/app.json` |

### 3. ไฟล์ที่แตะ
**แก้ไข (frontend):**
- `web/context/app-shell-storage.ts` — `AppLanguage` += `"th"`; `normalizeLanguage` รองรับ `th`
- `web/i18n/init.ts` — `AppLanguage` += `"th"`; `normalizeLanguage` (`th`/`thai`); `ensureLanguage` lazy-load `th/app.json`
- `web/components/settings/SettingsContext.tsx` — `UiSettings["language"]` += `"th"`
- `web/lib/datetime.ts` — `Language` += `"th"`; `getLocale` `th→th-TH`
- `web/app/(utility)/settings/appearance/page.tsx` — selector array `["en","zh","th"]` + label map (key `language.thai`)
- `web/components/settings/ServiceConfigEditor.tsx` — `defaultModelLabel` รับ `th` → `"โมเดล {n}"` (กัน tsc พัง)
- `web/app/(utility)/settings/tools/page.tsx` — tool hints lookup fallback `th→en` (กัน tsc พัง)
- `web/locales/en/app.json`, `web/locales/zh/app.json` — เพิ่มคีย์ `language.thai`

**แก้ไข (backend):**
- `deeptutor/services/config/loader.py` — `parse_language` `th`/`thai`→`th` + docstring
- `deeptutor/services/settings/interface_settings.py` — `_normalize_language` `th`/`thai`→`th`
- `deeptutor/api/routers/settings.py` — `UISettings.language` & `LanguageUpdate.language` Literal += `"th"`
- `deeptutor/core/i18n.py` — `_parse_language` `th` branch (consume via `.get(lang,{})` → fallback en, no KeyError)
- `deeptutor/services/prompt/language.py` — `_LANGUAGE_LABELS["th"]="ภาษาไทย"`; `normalize_agent_language()`; `__all__`
- `deeptutor/services/prompt/manager.py` — `LANGUAGE_FALLBACKS["th"]=["th","en"]`

**สร้างใหม่:**
- `web/locales/th/app.json`, `web/locales/th/common.json` — seed จาก repo เก่า (`../../DeepTutor/web/locales/th/`)
- `tests/services/config/test_parse_language_th.py`
- `tests/api/test_settings_language_th.py`
- `tests/services/prompt/__init__.py`, `tests/services/prompt/test_language_th.py`
- `web/tests/normalize-language.test.ts`
- `REPORT_round1.md` (ไฟล์นี้)

**คำสั่ง git สรุป:** `git diff --stat` (16 ไฟล์แก้ + untracked ใหม่ตามด้านบน)

### 4. ผล Test Gate (จาก TEST_PLAN)

| คำสั่ง | ผล | หมายเหตุ / output สำคัญ |
|---|---|---|
| `pytest tests/services/config/test_parse_language_th.py tests/api/test_settings_language_th.py tests/services/prompt/test_language_th.py` | ✅ | `38 passed in 1.20s` |
| `pytest tests/multi_user/test_ui_language_scoping.py` (regression) | ✅ | `2 passed, 34 warnings in 0.30s` |
| `npx tsc --noEmit` (web) | ✅ | `TSC_EXIT=0` (หลังแก้ ServiceConfigEditor + tools/page) |
| `npm run test:node` (web) | ✅ | `tests 133 / pass 133 / fail 0` (รวม normalize-language ใหม่ 5 เคส) |
| `npm run build` (web) | ✅ | `✓ Compiled successfully in 9.9s`, `BUILD_EXIT=0` |

> หมายเหตุ test environment: venv ไม่มี `pytest` ติดมา ต้อง `pip install pytest pytest-asyncio` ก่อน (pytest 9.1.0).

รายละเอียด unit ใหม่ที่เพิ่ม:
- `test_parse_language_th.py` — `parse_language`/`_normalize_language` รองรับ `th`/`thai` (+ default zh/en คงเดิม)
- `test_settings_language_th.py` — `LanguageUpdate(language="th")`/`UISettings(language="th")` ผ่าน pydantic,
  reject `"xx"`, และ endpoint `update_language` persist `th` (monkeypatch load/save)
- `test_language_th.py` — `normalize_agent_language` ทุกเคส, `language_label("th")=="ภาษาไทย"`,
  `language_directive("th")` มี "ภาษาไทย" และ **ไม่มี** "strictly in th", `PromptManager.load_prompts(...,"th")` ไม่ throw
- `normalize-language.test.ts` — `normalizeLanguage` ของ `app-shell-storage` (canonical)

### 5. Manual smoke
- ทำอะไร: ไม่ได้คลิกจริงใน UI (ไม่มี dev server ในรอบนี้) — ตรวจผ่าน static gate แทน
- ผล: `npm run build` ผ่าน → route `/settings/appearance` prerender ได้; selector มี option `th` และ key `language.thai`
  มีครบใน en/zh/th จึงไม่โชว์ raw key
- ภาษาที่ออกมา: คาดว่าเลือก "ไทย" แล้ว UI ส่วนที่ th locale ยังขาด key จะ fallback en (เพราะ `fallbackLng:"en"`)
  → ไม่ขาวจอ/ไม่ crash (จะ verify ด้วยตาในรอบ 2 ตอนทำ parity)

### 6. จุดที่ทำ "ต่างจากแผน" (Deviations) — สำคัญ
1. **Frontend node test ใช้ `.ts` ไม่ใช่ `.mjs`** — TEST_PLAN ระบุ `web/scripts/__tests__/normalize-language.test.mjs`
   แต่ runner จริง (`scripts/run-node-tests.mjs`) คอมไพล์ `web/tests/**/*.ts` ด้วย `tsconfig.node-tests.json`
   แล้วรัน `.test.js` เท่านั้น — `.mjs` ใน `scripts/__tests__/` จะไม่ถูกเก็บ จึงสร้าง
   `web/tests/normalize-language.test.ts` ตาม convention จริงแทน
2. **ทดสอบเฉพาะ normalizer ของ `app-shell-storage` ใน node test (ไม่ใช่ทั้ง 2 ตัว)** —
   `i18n/init.ts` import `@/locales/*` (alias) และ pull `i18next`/`react-i18next` (ESM-only)
   เข้ามา ทำให้ cjs node-test runner โหลดไม่ได้ จึงไม่ import init.ts ใน test;
   การเปลี่ยน type ของ init.ts ครอบคลุมด้วย `tsc --noEmit` แทน (เลี่ยงแก้ shared `tsconfig.node-tests.json` ที่เสี่ยง)
3. **แตะ Phase 3 surfaces 2 จุดเพื่อกัน build พัง** — การขยาย `AppLanguage` ทำให้ `tsc` ฟ้องที่
   `ServiceConfigEditor.tsx` (`defaultModelLabel`) และ `tools/page.tsx` (`tool.hints[language]`)
   จึงแก้ขั้นต่ำ: `defaultModelLabel` เพิ่มสาขา th = "โมเดล {n}" (ตรงเจตนา Phase 3.3),
   tools hints fallback `th→en` (Phase 7 จะเติม th payload จริง) — ไม่กระทบ phase อื่น
4. **`th/app.json` ยัง seed (2067 keys) ไม่ parity กับ en (2614 keys)** — เป็นเจตนา: รอบ 1 แค่ให้ไม่พัง,
   parity เป็น gate ของรอบ 2 (Phase 2)

### 7. ปัญหา & งานค้าง (Blockers / TODO)
- [ ] รอบ 2: เติม `th/app.json` ให้ parity 100% + อัปเดต `i18n_parity.mjs` ให้ loop `th`
- [ ] รอบ 2: settings-nav, CAPABILITY_LABELS, SpaceDashboard, BookCreator dropdown, QuizViewer/quiz-judge type
- [ ] `deeptutor/core/i18n.py` ยังไม่มี `_MESSAGES["th"]` (ตอนนี้ backend API messages fallback en)
- [ ] `language.thai` ยังไม่มีใน `en/common.json`,`zh/common.json` (มีใน th/common.json) — เก็บตอนทำ common parity

### 8. Residual risk / สิ่งที่อยากให้ช่วย review
- จุดที่ใช้ fallback ชั่วคราว (ยังไม่ใช่ไทยแท้): tool hints (`th→en`), backend API messages (`_MESSAGES` ไม่มี th),
  prompt ทุก capability (ยังไม่มี `th/` yaml → ใช้ en + language directive)
- จุด `zh/en` hardcoded ที่ยังเหลือ **โดยตั้งใจ** (เป็น scope รอบ 3+): chat pipeline, explorer, obsidian,
  partner runtime, metadata i18n, quiz_judge whitelist, taxonomy `label()` ฯลฯ — ยังไม่แตะในรอบนี้
- อยาก review: วิธีจัดการ duplicate normalizer (storage exact-match vs init alias-match) — รอบนี้คงไว้ตามแผน
  แต่ storage normalizer ไม่รับ `"thai"`/`"TH"` (รับเฉพาะ `"th"`) ซึ่งโอเคเพราะอ่านจาก localStorage ที่เก็บ canonical code

### 9. CHANGELOG
> เพิ่ม entry ใต้ `## [Unreleased] > ### Added` แล้ว ✅
- entry: "Thai (`th`) language foundation (round 1 — Phases 1/4/5 ...)" ระบุไฟล์ frontend/backend ที่แตะ,
  locale seed, การ fallback en, และ test ใหม่ทั้ง 4 ไฟล์ (ดู `CHANGELOG.md`)
- รัน `graphify update .` แล้ว ✅ (`18667 nodes, 34817 edges` — graph.json + GRAPH_REPORT.md อัปเดต)

### 10. ขั้นถัดไปที่เสนอ
- รอบถัดไป: **Round 2 — Thai UI parity** (Phase 2 + 3): เติม th locale ให้ครบ, แก้ parity script,
  settings-nav/tools/dashboard/book creator/service editor, datetime/shared formatting
- ต้องตัดสินใจก่อน: จะให้ `i18n:parity` เป็น gate แข็ง (block) ทันทีในรอบ 2 ไหม (แนะนำ: ใช่)

---

## เช็คลิสต์ก่อนส่ง report
- [x] กรอกครบทุกหัวข้อ (ไม่มี gate ผ่านปลอม)
- [x] วาง output จริงของ test gate (38 passed / 133 node / build OK / tsc 0)
- [x] ระบุ deviations ตรง ๆ (4 ข้อ)
- [x] อัปเดต `CHANGELOG.md` + รัน `graphify update .`
- [x] ไฟล์ report ชื่อ `REPORT_round1.md` (อยู่ที่ repo root)
- [x] ยังไม่ merge เข้า main — อยู่บน branch `feature/thai-i18n-foundation` รอ review
