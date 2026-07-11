# รายงานปิดรอบ (Thai Localization) — Round 3: Thai runtime

> ก๊อปจาก `Thai_Localization_DeepTutor_REPORT_TEMPLATE.md` แล้วกรอกตามจริง

---

## รอบ/Phase: Round 3 (Phase 6 + 7 + 10)   |   วันที่: 2026-06-17   |   branch: `feature/thai-i18n-foundation`

### 1. TL;DR (3–5 บรรทัด)
- สถานะ: ✅ เสร็จครบตาม scope รอบ 3 (Phase 6/7/10)
- ทำอะไรไปบ้าง: แทนที่ hardcode `startswith("zh")` ด้วย `normalize_agent_language()` + append
  `append_language_directive()` ทั่ว runtime (chat/notebook/explore/obsidian/mastery/solve/co-writer/
  source-inventory/memory/partners/chat-entry/banner) + เติม label ไทย; Phase 7 metadata/tool/taxonomy
- พร้อมไปรอบ 4 ไหม: **ใช่** — unit ใหม่ 14 เคสเขียว, regression 598 passed (3 fail เป็น pre-existing/optional-dep),
  chat smoke พิสูจน์ system prompt มี Thai directive

### 2. Scope ที่ทำจริง (เทียบกับ PLAN)
| Phase ใน PLAN | ทำแล้ว? | หมายเหตุ |
|---|---|---|
| 6A collapse points (14 จุด) | ✅ | ทุกจุดใช้ `normalize_agent_language` (ดูตารางข้อ 3) |
| 6B hardcoded labels | ✅ | notebook header/KB note/workspace/deferred manifest/source headers/co-writer/question/prompting |
| 6C audit default `="zh"` | ✅ | ตรวจแล้ว: `manager.py:59,213`, `learning/prompts.py:31`, `chat_agent.py:37`, `base_agent.py:59` มี default zh แต่ caller ส่ง language เสมอ — ไม่เปลี่ยน (ปลอดภัย) |
| 7.1/7.2/7.3 metadata_i18n th | ✅ | ทุก capability+tool + fallback `{en,zh,th}` + `localized_description` ใช้ normalize |
| 7.4/7.5 tools API + tool_options th | ✅ | `Literal[...,"th"]`, hints th, description_i18n th |
| 7.7 taxonomy label() | ✅ | `th → en` fallback (ไม่คืนจีน) |
| 7.6 hints/th yaml (18) | ⏭️ ข้าม | ตามแผน (fallback th→en + directive พอ) |
| 10.1 `_lang_code` normalize | ✅ | th→en สำหรับเลือกไฟล์ prompt (asset มีแค่ en/zh) |
| 10.2/10.3 call_llm directive + language= | ✅ | `call_llm(language=...)` append directive; audit/dedup/update ส่ง language ครบ 5 จุด |
| 10.4 th.yaml memory | ⏭️ ข้าม | ตามแผน (en template + directive) |
| 6.9 banner catalog th | ⏭️ ข้าม (CLI low-pri) | `_pick_language` รู้จัก th แต่ map→en; catalog th deferred |

### 3. ไฟล์ที่แตะ — collapse points (6A) เช็คครบ
| ไฟล์ | เดิม | ใหม่ |
|---|---|---|
| `agents/chat/agentic_pipeline.py:188` | `"zh" if startswith` | `normalize_agent_language` ✅ |
| `agents/chat/prompt_blocks.py:17` | ″ | ✅ (directive มีอยู่แล้วที่ system_prompt) |
| `agents/notebook/analysis_agent.py:31` | ″ | ✅ + directive ใน 3 stage system prompt |
| `agents/notebook/summarize_agent.py:23` | ″ | ✅ + directive ใน `_system_prompt` |
| `capabilities/explore_context/capability.py:49` (`_load_prompts`) | ″ | ✅ + fallback en เมื่อไม่มี th yaml (lazy import) |
| `capabilities/explore_context/explorer.py:90` | ″ | ✅ + directive 2 system prompt + label th |
| `capabilities/obsidian/capability.py:79` | ″ | ✅ + fallback en system.md + directive (lazy import) |
| `capabilities/mastery/loop.py:66` | ″ | ✅ (lazy import) |
| `capabilities/solve/loop.py:86` | ″ | ✅ (lazy import) |
| `co_writer/edit_agent.py:354` | ″ | ✅ + label th (ฐานความรู้/ค้นหาเว็บ/แหล่งอ้างอิง) |
| `services/session/source_inventory.py:663` | ″ | ✅ + header/label th (ผู้ใช้/ผู้ช่วย/ผู้ช่วย AI ภายนอก) |
| `services/memory/consolidator/modes/_runtime.py:77` | ″ | ✅ `_lang_code` normalize (th→en asset) + `call_llm(language=)` directive |
| `services/partners/runtime.py:443` | ″ | ✅ `normalize_agent_language` |
| `api/routers/chat.py:76` | zh/en/ui | ✅ เพิ่ม branch th (ก่อน fallback ui) |
| `runtime/banner.py:239` | zh/en | ✅ รู้จัก th → map en (catalog deferred) |

**ไฟล์ label/metadata อื่น:** `agents/chat/agentic_pipeline.py` (621/1173/1192), `agents/question/pipeline.py`
(1608/1613/1788), `tools/prompting/__init__.py` (109-110), `runtime/registry/deferred_tools.py`,
`api/routers/co_writer.py`, `i18n/metadata_i18n.py`, `api/routers/tools.py`, `api/utils/tool_options.py`,
`services/skill/taxonomy.py`, `services/memory/consolidator/modes/audit.py|dedup.py|update.py`.

**สร้างใหม่ (tests):** `tests/agents/chat/test_language_th.py`, `tests/i18n/__init__.py`,
`tests/i18n/test_metadata_th.py`, `tests/services/skill/test_taxonomy_th.py`,
`tests/services/partners/test_partner_language_th.py`,
`tests/services/memory/test_consolidator_language_th.py`, `REPORT_round3.md`.

**ไฟล์ meta/config:** ไม่ได้แตะ `.gitignore`/`AGENTS.md`/`tsconfig*` ในรอบนี้ (ที่ขึ้น M เป็น pre-existing
ตั้งแต่ก่อนงานไทย). `CHANGELOG.md` (gitignored) อัปเดตบนดิสก์แล้ว. ไม่ได้แตะ frontend รอบนี้.

### 4. ผล Test Gate (จาก TEST_PLAN — รอบที่ 3)
| คำสั่ง | ผล | output สำคัญ |
|---|---|---|
| `pytest` unit ใหม่ (5 ไฟล์) | ✅ | `14 passed` |
| `pytest` รวม unit ไทยทั้งหมด (r1+r3) | ✅ | `52 passed` |
| `pytest tests/agents tests/services/{partners,skill,memory} tests/api/test_question_router.py deeptutor/learning/tests ...` | ✅ (ส่วนใหญ่) | `598 passed, 3 failed` — 3 fail **pre-existing** (ดูล่าง) |
| `ruff check` (ไฟล์ที่แตะ) | ✅ | All checks passed (autofix import sort 2 จุด) |
| `ruff format --check` | ✅ | 42 files formatted (รัน `ruff format` แล้ว) |
| bootstrap import (`import deeptutor.app`) | ✅ | OK (แก้ circular import — ดู deviations) |
| chat smoke (assemble Thai system prompt) | ✅ | directive = "Write ALL reader-facing text strictly in **ภาษาไทย**", `pipeline.language=="th"`, tool desc th = "ค้นหาเว็บและคืนผลลัพธ์พร้อมแหล่งอ้างอิง" |

**3 failures = pre-existing (ยืนยันด้วย `git stash` แล้วรันซ้ำ — fail เหมือนเดิมโดยไม่มี change ของผม):**
- `tests/api/test_question_router.py::test_mimic_websocket...` — `ImportError: load_auth_settings` (circular import artifact ใน auth.py, ไม่เกี่ยวภาษา)
- `tests/services/partners/test_channel_manager.py` — ต้องใช้ optional channel deps
- `tests/services/skill/test_skill_login.py` — order/network dependent (ผ่านเมื่อรันเดี่ยว)
- เพิ่มเติม: channel tests ที่ต้อง `telegram`/optional deps ถูก `--ignore` (ModuleNotFoundError pre-existing)

### 5. Manual smoke (end-to-end)
- ทำอะไร: ประกอบ system prompt จริงของ chat turn ภาษาไทย (ผ่าน `AgenticChatPipeline(language="th")._build_system_prompt`)
- ผล: ✅ system prompt มี Thai directive ("strictly in ภาษาไทย") + ไม่มี "strictly in th"; pipeline ไม่บีบ th;
  tool description/manifest ออกไทย
- ภาษาที่ออกมา: **ยังไม่ได้เรียก LLM จริง** (ต้องมี API key) — directive + label พร้อมผลักให้ output เป็นไทยเมื่อมี LLM
  → นี่คือ residual ข้อ 8 (อยากให้ review ว่าพอ หรือต้องรันกับ key จริง)

### 6. จุดที่ทำ "ต่างจากแผน" (Deviations) — สำคัญ
1. **Circular import ที่ต้องแก้:** การ import `prompt.language` ที่ top-level ในโมดูลที่ถูกโหลดตอน bootstrap
   (`i18n/metadata_i18n.py` + capability modules `explore_context/capability`, `obsidian/capability`,
   `mastery/loop`, `solve/loop`) ทำให้เกิด circular import (prompt/__init__ → manager → services.config →
   path_service ที่ยัง init ไม่เสร็จ) → **แก้โดยเปลี่ยนเป็น lazy import (ใน function)** ทั้ง 5 ไฟล์.
   (ไฟล์อื่นที่ import นอก bootstrap เช่น agentic_pipeline/notebook/source_inventory/partners/deferred_tools
   import top-level ได้ปกติ)
2. **obsidian/mastery/solve `_load_system_prompt`:** เพิ่ม fallback en + directive เมื่อไม่มีไฟล์ th
   (ป้องกัน FileNotFoundError) — เกินจาก "collapse อย่างเดียว" ในแผน แต่จำเป็นตามหลัก no-crash
3. **explore_context `_load_prompts`:** เพิ่ม fallback en เมื่อ th yaml ไม่มี (เดิม return {} ว่าง) เพื่อไม่ให้ prompt หาย
4. **banner catalog th:** ไม่สร้าง (CLI ~100 strings, low-pri) — `_pick_language` รู้จัก th แต่คืน en catalog (มี comment)
5. **context_builder / turn_runtime follow-up:** ไม่แตะ — th ตกไป en branch อยู่แล้ว (ไม่หลุดจีน) เป็น internal
   summary/follow-up scaffold + directive จาก chat pipeline คุม output; บันทึกเป็น residual
6. **ruff 0.15.17** (เครื่อง) ต่างจาก pinned `v0.14.7`; format diff ตรวจแล้ว localized เฉพาะบรรทัดที่แก้

### 7. ปัญหา & งานค้าง (Blockers / TODO)
- [ ] รอบ 4 (Phase 8/9): learning prompts th, quiz_judge whitelist (`api/routers/quiz_judge.py:278,282`
      ยัง `not in ("zh","en")` — reject th), QuizViewer judgeLanguage
- [ ] live LLM smoke ด้วย API key จริง (ยืนยัน output ไทยจริง ไม่ใช่แค่ directive)
- [ ] (low-pri) hints/th yaml 18 ไฟล์, memory th.yaml, banner th catalog

### 8. Residual risk / สิ่งที่อยากให้ช่วย review
- **smoke ยังไม่เรียก LLM จริง** (ไม่มี key) — มีเพียงหลักฐาน directive+label; อยาก review ว่าพอสำหรับปิดรอบไหม
- **internal scaffolds ที่ th→en + directive** (context_builder summary 302/318, turn_runtime follow-up 463,
  explorer briefing) — output ผู้ใช้ปลายทางควรเป็นไทยจาก chat directive แต่ intermediate อาจเป็น en
- **default `="zh"`** หลายจุด (6C) เว้นไว้ — caller ส่ง language เสมอ แต่ถ้ามี path ใหม่ที่พึ่ง default ผู้ใช้ไทยจะได้จีน
- **quiz_judge ยัง reject th** (Phase 9 รอบ 4)

### 9. CHANGELOG
> CHANGELOG.md (gitignored) อัปเดตบนดิสก์แล้ว ✅
- entry: "Thai (`th`) runtime localization (round 3 — Phases 6/7/10 ...)" ระบุทุก collapse point + label + metadata + test
- `graphify update .` ✅ (`18839 nodes, 35020 edges`)

### 10. ขั้นถัดไปที่เสนอ
- รอบ 4 — Thai learning/mastery (Phase 8/9): `learning/prompts/th.yaml` + fallback, `default_module_name("th")`,
  quiz_judge whitelist + th system prompt, QuizViewer + lib/quiz-judge judgeLanguage
- เตรียม: ตัดสินใจว่าต้องการ live LLM smoke (มี key) ก่อนไปรอบ 4 ไหม

---

## เช็คลิสต์ก่อนส่ง report
- [x] กรอกครบทุกหัวข้อ (ไม่มี gate ผ่านปลอม)
- [x] วาง output จริง (14/52 passed, 598 passed/3 pre-existing fail, smoke directive)
- [x] ระบุ deviations (6 ข้อ รวม circular-import fix + fallback เพิ่ม)
- [x] บันทึกไฟล์ที่แตะครบ + ยืนยันไม่แตะ meta/config รอบนี้
- [x] CHANGELOG (local-only) + `graphify update .`
- [x] report ชื่อ `REPORT_round3.md` (repo root)
- [x] ยังไม่ merge main — branch `feature/thai-i18n-foundation`
