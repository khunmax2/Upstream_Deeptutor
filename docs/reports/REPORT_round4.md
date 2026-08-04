# รายงานปิดรอบ (Thai Localization) — Round 4: Thai learning / mastery / quiz

> ก๊อปจาก `Thai_Localization_DeepTutor_REPORT_TEMPLATE.md` แล้วกรอกตามจริง

---

## รอบ/Phase: Round 4 (Phase 8 + 9)   |   วันที่: 2026-06-17   |   branch: `feature/thai-i18n-foundation`

### 1. TL;DR (3–5 บรรทัด)
- สถานะ: ✅ เสร็จครบตาม scope รอบ 4 (Phase 8/9)
- ทำอะไรไปบ้าง: สร้าง `learning/prompts/th.yaml` parity 100% กับ en, แก้ loader fallback `th→["th","en"]`,
  `default_module_name("th")` = "โมดูล N", quiz_judge รับ th (2 จุด) + append directive, QuizViewer ส่ง th
- พร้อมไป Phase 11 (optional quality) ไหม: **ใช่** — learning 205 passed, unit ใหม่เขียว, tsc/build ผ่าน,
  smoke prompt ไทยถูกต้อง

### 2. Scope ที่ทำจริง (เทียบกับ PLAN)
| Phase ใน PLAN | ทำแล้ว? | หมายเหตุ |
|---|---|---|
| 8.1 th.yaml (7 section) | ✅ | parity 15/15 leaf keys เท่า en, placeholder ตรงทุกตัว |
| 8.2 loader candidates th | ✅ | `th→["th","en"]`, `zh→["zh","en"]`, else `["en","zh"]` |
| 8.3 default_module_name("th") | ✅ | = "โมดูล {index}" (จาก th.yaml) |
| 8.4 mastery/solve asset | ✅ ยืนยัน | รอบ 3 collapse + fallback en + lazy import แล้ว — ไม่ crash เมื่อไม่มี th |
| 9.1 quiz_judge whitelist (2 จุด) | ✅ | `("zh","en")` → `("zh","en","th")` ทั้งบรรทัด 278 และ 282 |
| 9.2 judge th feedback | ✅ | เลือก append `append_language_directive` กับ en prompt (ไม่เพิ่ม th system prompt — consistent กับ runtime) |
| 9.3 QuizViewer.tsx judgeLanguage | ✅ | `zh/th/en` (type `lib/quiz-judge.ts` ขยาย th แล้วรอบ 2) |

### 3. ไฟล์ที่แตะ
**แก้ไข:**
- `deeptutor/learning/prompts.py` — loader candidates รองรับ th (เลิก coerce th→zh)
- `deeptutor/api/routers/quiz_judge.py` — whitelist +th (2 จุด) + import & append `append_language_directive`
  เมื่อไม่มี native judge prompt (th)
- `web/components/quiz/QuizViewer.tsx` — `judgeLanguage` รองรับ th

**สร้างใหม่:**
- `deeptutor/learning/prompts/th.yaml` — Thai Mastery Path prompts (parity en)
- `tests/learning/__init__.py`, `tests/learning/test_prompts_th.py`
- `tests/api/test_quiz_judge_th.py`
- `REPORT_round4.md`

**ไฟล์ meta/config:** ไม่ได้แตะ `.gitignore`/`AGENTS.md`/`tsconfig*` รอบนี้ (M ที่ค้างเป็น pre-existing).
`CHANGELOG.md` (gitignored) อัปเดตบนดิสก์. `web/next-env.d.ts` ถูก build สร้างใหม่ → `git checkout` revert แล้ว.

### 4. ผล Test Gate (จาก TEST_PLAN — รอบที่ 4)
| คำสั่ง | ผล | output สำคัญ |
|---|---|---|
| `pytest deeptutor/learning/tests tests/learning tests/api/test_quiz_judge_th.py` | ✅ | `205 passed` |
| `pytest` round-4 unit เดี่ยว | ✅ | `7 passed` (test_prompts_th 5 + test_quiz_judge_th 3 → รวม 7 หลัง dedup) |
| focused regression (learning+api+prompt+i18n+skill+chat th) | ✅ | `253 passed` |
| `ruff check` / `format --check` (ไฟล์ที่แตะ) | ✅ | All checks passed (autofix import sort + format 1 ไฟล์) |
| `npx tsc --noEmit` (web) | ✅ | `TSC=0` |
| `npm run build` (web) | ✅ | `✓ Compiled successfully in 10.4s`, `BUILD=0` |

**th.yaml parity (ตรวจด้วยสคริปต์ + ใน test):**
- leaf keys: en 15 / th 15 — missing 0, extra 0
- placeholder: `{knowledge_point}`, `{knowledge_points}`, `{records_json}`, `{index}` ตรงทุก key (0 mismatch)
- JSON ตัวอย่างใน system prompt (single-brace) และ notebook.user (double-brace `{{ }}`) คงรูปแบบเดิม

### 5. Manual smoke (Phase 8/9)
- Guided Learning (assemble prompts, ไม่เรียก LLM — ไม่มี key):
  - `default_module_name("th", 3)` → **"โมดูล 3"** ✅ (ไม่ใช่ "模块 3")
  - `diagnostic.system` (th) → "คุณคือผู้เชี่ยวชาญด้านการวินิจฉัยการเรียนรู้…" ✅
  - `explain.user` → "อธิบายจุดความรู้นี้: {knowledge_point}" (placeholder คงอยู่) ✅
  - `notebook_generation_prompts("th", ...)` → user มีข้อมูล records + JSON `{"modules"...}` ถูกต้อง ✅
  - candidates th → โหลด th.yaml จริง (ไม่ fallback zh) ✅
- Quiz judge: th อยู่ใน whitelist ✅; judge prompt (th) = en + directive "strictly in **ภาษาไทย**" ✅
- หมายเหตุ: **ยังไม่ได้เรียก LLM จริง** (ต้องมี API key) — มีหลักฐาน prompt/directive พร้อมผลักให้ output เป็นไทย

### 6. จุดที่ทำ "ต่างจากแผน" (Deviations)
1. **quiz_judge: เลือก append directive แทนเพิ่ม `_JUDGE_SYSTEM_PROMPTS["th"]`** — ตามที่แผนแนะนำ
   (consistent กับ runtime อื่น), append เฉพาะภาษาที่ไม่มี native prompt (th) เพื่อไม่เปลี่ยน byte output ของ zh/en
2. **`tests/learning/` เป็น dir ใหม่** — แผนระบุ path `tests/learning/test_prompts_th.py` แต่ learning tests เดิมอยู่
   `deeptutor/learning/tests/`; สร้าง `tests/learning/` ใหม่ + `__init__.py` (pytest testpaths ครอบ `tests/`)
3. **`_build_judge_user_prompt` ยังเป็น zh/en** (th→en branch) — label คำถาม/เฉลยใน user prompt เป็น en สำหรับ th
   แต่ feedback ออกไทยจาก directive; เป็น input framing ไม่ใช่ output ผู้ใช้ (เว้นไว้ตั้งใจ)
4. **quiz_judge smoke เป็น unit ของ building blocks** (whitelist + directive) ไม่ใช่ WS integration เต็ม
   เพราะ endpoint เป็น authenticated WebSocket + LLM stream (mock หนัก) — บันทึกใน test docstring

### 7. ปัญหา & งานค้าง (Blockers / TODO)
- [ ] live LLM smoke ด้วย API key จริง (guided learning flow + quiz feedback ออกไทยจริง end-to-end)
- [ ] Phase 11 (optional quality): prompt ไทยคุณภาพสูง question/book/visualize/math/explore
- [ ] Phase 14 final QA + Maintenance/Upstream Sync (พักไว้)

### 8. Residual risk / สิ่งที่อยากให้ช่วย review
- **ยังไม่เรียก LLM จริง** — เหมือนรอบ 3; มี prompt/directive ครบ แต่ output จริงต้องมี key
- **คุณภาพคำแปล th.yaml** — แปลโดย AI เน้นถูกต้อง+คงโครงสร้าง/placeholder; ควร review โดยเจ้าของภาษา
  (โดยเฉพาะศัพท์ feynman = "ไฟน์แมน", knowledge point = "จุดความรู้")
- **judge user prompt label** เป็น en สำหรับ th (input framing) — ถ้าต้องการ th เต็มค่อยเพิ่มทีหลัง
- 3 pre-existing fails จากรอบ  3 (load_auth_settings / optional channel deps / skill_login) ยังคงอยู่ ไม่เกี่ยวรอบนี้

### 9. CHANGELOG
> CHANGELOG.md (gitignored) อัปเดตบนดิสก์แล้ว ✅
- entry: "Thai (`th`) learning & quiz localization (round 4 — Phases 8/9 ...)" ระบุ th.yaml parity, loader fix,
  default_module_name, quiz_judge whitelist+directive, QuizViewer, tests
- `graphify update .` ✅

### 10. ขั้นถัดไปที่เสนอ
- Phase 11 (optional): prompt ไทยคุณภาพสูงต่อ capability (question → book → visualize → math → explore)
- หรือ Phase 14 final QA: รัน full `pytest` + `npm run i18n:check` + build + live smoke ด้วย key แล้วปิดงาน
- ตัดสินใจ: ต้องการ live LLM smoke ก่อนไป Phase 11 ไหม

---

## เช็คลิสต์ก่อนส่ง report
- [x] กรอกครบทุกหัวข้อ (ไม่มี gate ผ่านปลอม)
- [x] วาง output จริง (205/253 passed, parity 15/15, smoke "โมดูล 3" + judge directive)
- [x] ระบุ deviations (4 ข้อ)
- [x] บันทึกไฟล์ที่แตะครบ + ยืนยันไม่แตะ meta/config (next-env revert แล้ว)
- [x] CHANGELOG (local-only) + `graphify update .`
- [x] report ชื่อ `REPORT_round4.md` (repo root)
- [x] ยังไม่ merge main — branch `feature/thai-i18n-foundation`
