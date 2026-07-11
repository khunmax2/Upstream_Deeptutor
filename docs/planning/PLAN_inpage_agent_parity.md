# แผน: สร้าง in-page agent ของเราเอง (reverse-engineering page-agent → ออกแบบใหม่เป็นงานของเรา)

> สถานะ: ร่างแผน (2026-07-10) · เจ้าของ: Attapon · ผู้ช่วยวิเคราะห์: Claude
> ซอร์สอ้างอิง: `~/Project/antigravity/page-agent` (MIT, Alibaba) — อ่านครบทั้ง core ~3,600 บรรทัด
> งานของเราที่จะยกระดับ: `feat/voice-web-integration` (`deeptutor/services/voice_realtime/`)

---

## 0. ทำไมแผนนี้ถึงมีอยู่

ผลการทดลองบน branch `page-agent-clean-eval` สรุปได้ว่า page-agent (เมื่อได้โมเดลแรงพอ)
ทำได้ทุกอย่างที่เราวางแผนไว้ใน DESIGN_voice_grounding Phase C: นำทางหลายสเต็ปข้ามหน้า,
แก้ทางเองเมื่อหลง, verify หลังทุก action, ทำงานกับ UI ไทยได้ และเข้าใจคำสั่งซับซ้อน
("ไปที่ศูนย์ความรู้ → เลือก kb → ตั้งค่า → กดลบแต่อย่ายืนยัน")

ทางเลือกคือ (ก) เสียบ page-agent เป็น dependency หรือ (ข) **เข้าใจมันให้ทะลุ แล้วสร้างของเราเอง**
เจ้าของโปรเจคเลือก (ข) — เหตุผล: เป็นงานของตัวเอง, ควบคุมได้ทั้ง stack, ผสาน trust model
กับ voice ได้ลึกกว่า, และสมองไปอยู่ฝั่ง server ได้ (กุญแจสู่ endgame: universal voice connector)

เอกสารนี้คือ (1) กายวิภาคของ page-agent ทุกสเต็ปจากซอร์สจริง (2) ช่องว่างเทียบกับงานเรา
(3) แผนสร้างเป็นเฟส พร้อมเกณฑ์ผ่านและกลยุทธ์ทดสอบ

---

## 1. กายวิภาคของ page-agent (จากซอร์ส ไม่ใช่จากพฤติกรรม)

### 1.1 โครงใหญ่ — 4 ชิ้นแยกขาดกัน

```
┌─────────────────────────────────────────────────────────┐
│ Panel (ui/)              UI ลอย — ไม่จำเป็นต่อการทำงาน   │
├─────────────────────────────────────────────────────────┤
│ PageAgentCore (core/)    สมอง: ReAct loop + prompt +     │
│                          MacroTool + autoFixer           │
├─────────────────────────────────────────────────────────┤
│ LLM (llms/)              ท่อ OpenAI-compat: retry,       │
│                          forced tool_choice, customFetch │
├─────────────────────────────────────────────────────────┤
│ PageController           มือ+ตา: dom_tree → index map →  │
│ (page-controller/)       serialize; click/type/scroll    │
│                          "ไม่รู้จัก LLM เลย เทสได้เดี่ยวๆ" │
└─────────────────────────────────────────────────────────┘
```

ข้อสังเกตเชิงสถาปัตย์ที่ควรลอก: **PageController ไม่ import อะไรจาก core เลย** —
มันคือ library มือ+ตาล้วนๆ ที่เทสต์ได้โดยไม่มี LLM นี่คือเส้นแบ่ง (seam) ที่ทำให้
เราวางสมองไว้คนละ process (server) ได้โดยไม่ต้องออกแบบใหม่

### 1.2 The loop — หนึ่ง step ทำอะไรบ้าง (`PageAgentCore.ts:251-359`)

ทุก step คือ **observe → think → act** ครบวงจร โดย LLM ถูกเรียก **ครั้งเดียวต่อ step**:

1. **stepDelay** (`:260`) — หน่วง 0.4s (default) ให้ DOM นิ่งก่อนเริ่ม step ถัดไป
2. **Observe** (`:268`) — `getBrowserState()` สแกน DOM **ใหม่ทั้งหมดทุก step**
   (ไม่ diff, ไม่ cache) ได้ url/title/header/content/footer
3. **System observations** (`#handleObservations` `:538-577`) — ระบบแทรกข้อความ `<sys>`:
   - URL เปลี่ยน → "Page navigated to → {url}" + รอ 0.5s ให้หน้านิ่ง
   - รอสะสม ≥3s → เตือน "อย่า wait อีกถ้าไม่มีเหตุผล"
   - เหลือ 5 steps → เตือนให้เตรียมจบ; เหลือ 2 → "ต้องจบเดี๋ยวนี้"
4. **Assemble prompt** (`#assembleUserPrompt` `:579-647`) — โครงสร้าง:
   ```
   <instructions>       system + per-page (getPageInstructions(url)) + llms.txt
   <agent_state>        โจทย์ (ทวนทุก step!) + "Step N of 40" + เวลาปัจจุบัน
   <agent_history>      ต่อ step เก่า: evaluation / memory / next_goal / action result
                        ← ไม่มี DOM เก่า! ไม่มี error events!
   <browser_state>      DOM สดของ step นี้เท่านั้น
   ```
   **หัวใจการคุม context:** ประวัติเก็บแค่ "ความคิด+ผลลัพธ์" (ไม่กี่บรรทัด/step)
   ส่วน DOM เต็มมีเฉพาะปัจจุบัน → context โตช้ามาก แม้ 40 steps
5. **Think** (`:285`) — เรียก LLM ด้วย **MacroTool ตัวเดียว** ชื่อ `AgentOutput`
   (`#packMacroTool` `:386-470`): schema = `{evaluation_previous_goal, memory,
   next_goal, action: union(ทุก tool)}` บังคับด้วย `tool_choice: {name: AgentOutput}`
   + `parallel_tool_calls: false` (`OpenAIClient.ts:42-52`)
   → ได้ทั้ง reflection และ action ใน **หนึ่ง call เสมอ** ไม่มีทางได้ข้อความเปล่า
6. **autoFixer** (`utils/autoFixer.ts`) — ก่อน execute ซ่อมของเสียจากโมเดล 6 แบบ:
   JSON อยู่ใน content แทน tool_call / เรียก tool ตรงข้าม MacroTool / arguments
   ถูก stringify ซ้อนสองชั้น / ห่อ function wrapper / input เป็น primitive
   (`{"click_element_by_index": 2}` → `{index: 2}` โดยเดาจาก zod schema) /
   ไม่มี action เลย → fallback `wait 1s` — **นี่คือเหตุที่มันทนโมเดลอ่อนได้ระดับหนึ่ง**
7. **Act** — execute tool, จับเวลา, ผูกผล (สตริงเดียว มี ✅/❌ นำหน้า) เข้า history
8. **จบเมื่อ** action คือ `done {text, success}` หรือเกิน maxSteps (40) หรือถูก abort

### 1.3 ตา — DOM serialization (`dom/index.ts:193-463`)

- ฐานคือ `dom_tree` (สายเลือด browser-use — ตัวเดียวกับที่เรา vendor ไว้แล้ว)
  ให้ flat tree + `highlightIndex` เฉพาะ element ที่ interactive จริง
- แปลงเป็นบรรทัดละ element: `[12]<button aria-label=บันทึก>บันทึก />`
  - **indent = ลูกของ element ก่อนหน้า** (LLM เข้าใจโครงสร้างโดยไม่ต้องเห็น HTML)
  - **`*[12]` = element ที่เพิ่งโผล่ตั้งแต่ step ก่อน** (WeakMap cache `dom/index.ts:55,97-108`)
    → LLM รู้ทันทีว่า dropdown/modal เพิ่งเปิด
  - text ธรรมดา (ไม่ interactive) แสดงเป็นบรรทัดเปล่าไม่มี index
- attributes ถูกกรองเหลือ ~20 ตัวที่มีความหมาย (aria-*, role, placeholder, value…)
  ตัดค่าซ้ำ (เช่น aria-label ที่ตรงกับ text), ตัดยาวเกิน 20 ตัวอักษร
- container ที่ scroll ได้ติดป้าย `data-scrollable="top=…, bottom=…"` บอกระยะเหลือ
- header/footer บอกตำแหน่ง viewport: "… 300 pixels below - scroll to see more …"
- `viewportExpansion` default **-1 = ทั้งหน้า** (ไม่ใช่แค่ viewport)
- กัน React ครอบทั้งหน้าเป็นปุ่มยักษ์: `patches/react.ts` ติด
  `data-page-agent-not-interactive` ให้ #root/#app ฯลฯ

### 1.4 มือ — การกระทำ (`actions.ts`)

**แก้ข้อเข้าใจผิดที่เราเคยบันทึกไว้:** click **ไม่ได้**อาศัย `elementFromPoint` หา
เป้าหมาย — เป้าหมายมาจาก **reference ตรงใน selectorMap** (`getElementByIndex`)
`elementFromPoint` ใช้แค่ refine หา child ในสุด *ภายใน* element นั้น (`:86-91`)
และถ้า hit ออกนอก element ก็ fallback กลับมาที่ element เอง → ทนต่อ DOM ขยับ
กว่าที่เราเคยวิเคราะห์ (บันทึกแก้ไว้เพื่อความซื่อตรงของ record)

- **click** (`:64-126`): scrollIntoView → ยิงลำดับ event ตามสเปก W3C ครบ
  (pointerover/enter → mouseover/enter → pointerdown → mousedown → focus →
  pointerup → mouseup → `.click()`) — นี่คือเหตุที่ React/antd component ยอมรับ
- **input_text** (`:131-232`): input/textarea ใช้ **native value setter**
  (ทะลุ React controlled component) + dispatch `input` event;
  contenteditable มี Plan A (synthetic InputEvent) → verify → Plan B (execCommand)
- **select** (`:238-254`): จับคู่ข้อความ option → set value → dispatch change
- **scroll** (`:275-417`): เลื่อนทั้งหน้า หรือเลื่อน container ตาม index
  (ไต่หา scrollable ancestor สูงสุด 10 ชั้น) — ผลตอบเป็นข้อความบอกว่าถึงสุดหรือยัง

### 1.5 กลไกความปลอดภัย/ปฏิบัติการที่มี (และไม่มี)

มี: SimulatorMask บังหน้าจอกันมือคนชนระหว่างรัน (แต่ pass-through ชั่วคราวตอน
hit-test), abort signal ทะลุถึง fetch + tools, `stop()` ที่รอ run จบจริง,
`user_takeover` event, retry จำแนก retryable/ไม่ (`InvokeError`)

**ไม่มีเลย: ด่านยืนยัน action อันตราย** — trace "กดลบ KB" ของเราพิสูจน์แล้วว่า
มันกดปุ่มลบทันทีถ้าโจทย์สั่ง สิ่งเดียวที่กั้นคือ modal ของแอป → **ช่องที่เราเหนือกว่า
และต้องเป็นแกนของดีไซน์เรา**

### 1.6 จุดต่อขยาย (เผื่ออนาคตอยากรองรับ ecosystem เดียวกัน)

`customTools` (override/ลบ tool ด้วยชื่อ), `customSystemPrompt`,
`instructions.system` + `getPageInstructions(url)`, `transformPageContent`,
`transformRequestBody`, hooks `onBefore/AfterStep`, `onBefore/AfterTask`,
`onAskUser`, `pushObservation()`, events (`statuschange/historychange/activity`)

---

## 2. Gap analysis — เรามีอะไรแล้ว / ขาดอะไร

### เรามีและเหนือกว่า (อย่าทิ้ง)

| ของเรา (voice branch) | สถานะเทียบ page-agent |
|---|---|
| Danger rung — จับคำอันตราย **เป็นกลไก** + ยืนยันเสียง + `pending_click` | ไม่มีเลย |
| Fast path deterministic (`resolve_click_target`) ~ms, ฟรี, ทน STT garble 4 ชั้น | ทุก action ต้องจ่าย LLM call |
| หู+ปาก: STT ไทย, TTS ต่อประโยค, barge-in, echo guard | ไม่มี (มีแต่แผงพิมพ์) |
| สมองอยู่ server → ใช้ LLM stack/observability ของ DeepTutor ได้ | ล็อคใน browser |
| `ui_context` MutationObserver สตรีมสภาพหน้าให้ server ต่อเนื่อง | สแกนเป็นรอบเฉพาะตอน agent รัน |

### เราขาด (นี่คือสิ่งที่ต้องสร้าง)

1. **Loop** — ของเราตอนนี้คือ "หนึ่งคำสั่ง → หนึ่ง action" ไม่มี observe→think→act วนจนกว่างานเสร็จ
2. **Reflection memory มีโครงสร้าง** (evaluation/memory/next_goal ต่อ step) — สิ่งที่ทำให้แก้ทางเองได้
3. **DOM serialization แบบ index ทั้งหน้า** — เรามี dom_tree vendor แล้วแต่ยังใช้แบบ shallow;
   ยังไม่มี `*[new]` marker, data-scrollable, indent hierarchy, header/footer ตำแหน่ง
4. **มือครบชุด** — เรามีแค่ click; ขาด input_text (native setter), select, scroll ตาม index
5. **MacroTool + forced tool_choice** — บังคับให้ทุกคำตอบเป็น structured action เสมอ
6. **autoFixer** — ชั้นซ่อมคำตอบโมเดล (สำคัญมากถ้าอยากใช้โมเดลถูกลง)
7. **Step budget + system observations** — เตือนตัวเอง, ตรวจ URL เปลี่ยน, กัน wait วน
8. **`done` contract + `ask_user` escalation**

---

## 3. การออกแบบของเรา — ต่างจากเขาตรงไหนและทำไม

### 3.1 การตัดสินใจหลัก: **สมองอยู่ server (Python), มือ+ตาอยู่ browser (TS)**

```
Browser (web/)                          Server (deeptutor/)
┌──────────────────────┐   WebSocket   ┌─────────────────────────────┐
│ PageActuator (ใหม่)   │◄────────────►│ InPageAgentLoop (ใหม่)       │
│ = PageController ของ  │  observe/act │  observe → think → act loop  │
│   เราเอง:            │   frames      │  ├ MacroTool + reflection    │
│  - dom_tree (มีแล้ว)  │              │  ├ autoFixer (port)          │
│  - serialize [idx]    │              │  ├ danger rung ✋ (มีแล้ว!)   │
│  - click/type/select/ │              │  ├ fast path ⚡ (มีแล้ว!)     │
│    scroll (port)      │              │  └ voice: ask_user = พูด+ฟัง │
└──────────────────────┘              └─────────────────────────────┘
```

ทำไมไม่ทำใน browser ทั้งหมดแบบเขา:
- **trust model บังคับใช้ฝั่ง server ได้จริง** — browser JS ถูก bypass ได้ ด่านอันตราย
  ใน server bypass ไม่ได้ (บทเรียนเดียวกับ llm-proxy ที่ pin model ฝั่ง server)
- **voice pipeline ทั้งหมดอยู่ server อยู่แล้ว** — ask_user ผ่าน TTS/STT, narration
  ของ next_goal ออกลำโพง ได้ฟรีเพราะอยู่บ้านเดียวกัน
- **endgame**: universal connector ต้องมีสมองนอกหน้าเว็บอยู่แล้ว (ต่อไปมือจะเป็น
  extension/desktop ได้โดยสมองเดิม) — ตรงกับ [[voice-connector-to-computer-use]]
- ต้นทุนที่ยอมจ่าย: latency WS round-trip ต่อ action (~10-30ms ใน localhost —
  จิ๊บจ๊อยเทียบ LLM call หลักวินาที)

### 3.2 สิ่งที่ **ลอกแนวคิด** (ผ่านการพิสูจน์แล้ว ไม่ต้องเถียงใหม่)

1. ประวัติเก็บแค่ reflection+ผล ไม่เก็บ DOM เก่า; DOM สดทุก step
2. MacroTool เดียว + forced tool_choice + parallel=false
3. Serialization format `[idx]<tag attrs>text />` + indent + `*[new]` + data-scrollable
4. ลำดับ event click ตามสเปก + native value setter (port ตรงๆ พร้อม attribution MIT)
5. System observations (URL change / wait accumulation / budget warnings)
6. autoFixer ทุก heuristic
7. โจทย์ผู้ใช้ทวนซ้ำทุก step ใน `<agent_state>`

### 3.3 สิ่งที่ **ออกแบบเอง/ทำให้ดีกว่า** (ส่วนที่เป็น "งานของเรา" จริงๆ)

1. **Gated pipeline**: คำสั่งเข้า fast path ก่อนเสมอ → hit = จบใน ~ms ไม่จ่าย LLM;
   miss หรือเป็นงานหลายสเต็ป → เข้า loop (เขาไม่มีชั้นนี้ — ทุกอย่างจ่ายเต็ม)
2. **Danger rung ในตัว loop**: ก่อน execute action ประเภท click/input ทุกครั้ง
   server ตรวจ danger lexicon + verify element text → ถ้าอันตราย: **พักงาน**
   (ไม่ fail) → ถามยืนยันด้วยเสียง → คำตอบ "ใช่" ปลุก loop ต่อ; "ไม่" → ตัด action
   นี้ออกแล้วให้ LLM คิดใหม่พร้อม observation "user rejected the click"
3. **Voice-native**: `next_goal` ของทุก step = สคริปต์ narration ออก TTS
   (ผู้ใช้ *ได้ยิน* ว่า agent กำลังจะทำอะไร — barge-in ระหว่างพูด = abort ธรรมชาติ);
   `ask_user` = พูดคำถาม + เปิดไมค์รอคำตอบ ผ่าน STT guard ที่มีแล้ว
4. **ui_context ที่มีอยู่เป็น observation เสริม**: MutationObserver เราสตรีมอยู่แล้ว →
   ใช้ trigger "หน้าเปลี่ยนเอง" ระหว่างรอ (เขาต้อง poll เป็นรอบ)
5. **ภาษาไทยเป็น first-class**: system prompt สองภาษา, danger lexicon ไทย/อังกฤษ
   (มีแล้ว), ตัวอย่าง reasoning เป็นบริบทไทย

### 3.4 สัญญาระหว่างสองฝั่ง (WS protocol เพิ่มจากที่มี)

```jsonc
// server → browser
{ "type": "agent_observe" }                          // ขอ browser_state
{ "type": "agent_act", "action": "click",  "index": 12 }
{ "type": "agent_act", "action": "input",  "index": 3, "text": "..." }
{ "type": "agent_act", "action": "select", "index": 7, "option": "..." }
{ "type": "agent_act", "action": "scroll", "down": true, "pages": 0.5, "index": 9 }
// browser → server
{ "type": "agent_state",  "url": "...", "title": "...", "header": "...",
  "content": "[0]<a …", "footer": "..." }
{ "type": "agent_acted",  "ok": true, "message": "✅ Clicked element (...)" }
```

---

## 4. แผนงานเป็นเฟส

> หลักการทุกเฟส: ไฟล์ใหม่ล้วน (fork policy §3), มีเทสต์ก่อนถือว่าจบ, ปิดเฟสด้วย
> CHANGES.md + REPORT ตาม §1, `graphify update .` ตอนปิดงาน

### Phase A — มือ+ตา ฝั่ง browser (`web/lib/page-actuator/`)  ~3-4 วันงาน

สร้าง `PageActuator` (TS ใหม่, standalone เทสได้แบบเดียวกับ PageController):

- [ ] A1 `serialize.ts` — flatTreeToString ของเราเอง ต่อยอด dom_tree ที่ vendor ไว้:
      index, indent, attribute filter, `*[new]` (WeakMap), data-scrollable, header/footer
- [ ] A2 `actions.ts` — port click event-sequence / native value setter /
      select / scroll ตาม index (**คง copyright header MIT ของ Alibaba ในไฟล์ port**)
- [ ] A3 react-root guard + `data-deeptutor-not-interactive` blacklist
      (จำเป็น: หน้าเราเป็น React — ถ้าไม่ทำ ทั้งหน้าเป็นปุ่มเดียว)
- [ ] A4 ต่อ WS frames `agent_observe`/`agent_act`/`agent_state`/`agent_acted`
      เข้ากับ socket voice ที่มีอยู่ (ไฟล์ hook ใหม่ ไม่แตะของเดิม)
      ⚠️ **งบขนาด frame (ตรวจแล้วชนจริง)**: control frame ฝั่ง server มี cap
      (`MAX_MANIFEST_BYTES`, ~8K — `voice_realtime.py:121`) และ `pageInventory`
      เคยโดน server ปัดทั้ง frame มาแล้ว; `agent_state` ของหน้าจริงใหญ่กว่านั้น
      หลายเท่า → ต้องทำสองชั้น: (1) serializer มี hard cap ของตัวเอง
      (attr ≤20 ตัวอักษร ตามเขา + เพดานรวม ~30K chars พร้อมบรรทัด
      "…truncated, scroll for more") (2) ส่ง `agent_state` แบบ **chunked**
      (`seq`/`total` ประกอบกลับฝั่ง server) หรือแยก cap เฉพาะ frame ชนิดนี้
      — ตัดสินใจตอนทำ A4 แต่ห้ามเงียบ-ตัด-ทิ้งเหมือนเคสเก่า
- [ ] A5 run-mask + vision layer (แสดง "เห็นอะไร / กดอะไร" ระหว่าง loop รัน):
      - **บล็อก input คนจริง** เฉพาะช่วง loop รัน (แนว SimulatorMask — click/wheel/
        keydown กันหมด, pass-through ชั่วคราวตอน hit-test); คลิกบน mask หรือ
        พูดแทรก (barge-in) = user takeover → abort loop พร้อม push observation
      - **โชว์สิ่งที่ agent เห็น**: ตอน observe เปิด highlight ของ dom_tree engine
        ที่ vendor ไว้ (`doHighlightElements: true` + opacity ที่มองเห็น) — กรอบ +
        ป้าย [index] ทุก element ที่ถูก index ให้ผู้ใช้เห็นภาพเดียวกับ LLM;
        เคลียร์ด้วย cleanup ของ engine ทุกครั้งก่อน step ถัดไป
        (ทุกวันนี้เราเรียกแบบปิดไว้ใน `pageInventory.ts` — โหมด loop แค่เปิดสวิตช์)
      - **โชว์สิ่งที่กำลังจะกด**: `simulatorCursor` ไถลไปเป้าหมาย + `glowBox` เน้น
        element ที่ถูกเลือก ก่อนลงมือทุก action (มือที่มองเห็น — ของเดิมทั้งคู่)
      - mascot ตัวโทรของเดิมไม่เกี่ยวและไม่แตะ; single-action ของ fast path เดิม
        คงพฤติกรรมเดิม (ไม่มี mask ไม่มี highlight — เร็วเกินกว่าจะชนมือคน และ
        จอไม่ควรกระพริบกับคำสั่งง่าย)
- [ ] เทสต์: node test serialize (DOM จำลอง), เทสต์ actions บนหน้า fixture
- **เกณฑ์ผ่าน**: เปิดหน้า knowledge แล้วสั่ง observe ผ่าน WS ได้ browser_state
  ที่มี index ครบ; สั่ง click ตาม index แล้วปุ่มจริงทำงาน

### Phase B — สมอง ฝั่ง server (`deeptutor/services/voice_realtime/agent/`)  ~4-5 วันงาน

- [ ] B1 `loop.py` — `InPageAgentLoop`: state machine observe→think→act,
      history (reflection เท่านั้น), step budget, stepDelay, abort event
      — ค่า default จูนเพื่อ voice ไม่ใช่ลอกเขา: **maxSteps 15** (คนถือสายรอ
      ไม่ได้ 40 สเต็ป; config ได้ถึง 40), **stepDelay 0.8s** (บทเรียน suanrao
      บน DOM ที่ animation เยอะ — ของเขา default 0.4)
- [ ] B2 `prompt.py` — system prompt ของเราเอง (โครงจาก §1.2 แต่เขียนใหม่
      สองภาษา + กติกา voice) + assembler `<instructions>/<agent_state>/<agent_history>/<browser_state>`
- [ ] B3 `macro_tool.py` — JSON schema ของ AgentOutput (union ของ action ทั้งหมด),
      forced tool_choice, `parallel_tool_calls: false`
      — ตรวจแล้ว: stack เราส่ง kwargs ดิบถึง completion ได้ (precedent:
      `agents/chat/agent_loop.py:465` ตั้ง `tool_choice="auto"` อยู่แล้ว) จึงตั้ง
      named tool_choice ได้ตรงๆ; แต่ named choice ขึ้นกับ provider → ต้องมี
      **fallback อัตโนมัติ**: JSON-object mode + fixer (autoFixer รองรับ
      "JSON มาใน content" อยู่แล้ว — เส้นทางเดียวกัน)
- [ ] B4 `fixer.py` — port autoFixer ครบทุก heuristic + เทสต์ยิงเคสเสียจริง
      (มีตัวอย่างใน autoFixer.ts ครบแล้ว)
- [ ] B5 `observations.py` — URL change, wait accumulation, budget warnings
- [ ] B6 tools ฝั่ง server: `done/wait/ask_user/click/input/select/scroll`
      (execute = ส่ง WS frame รอ `agent_acted`)
- [ ] เทสต์: loop กับ browser ปลอม (fixture browser_state) — ไม่ต้องมี browser จริง
      ทดสอบ: จบงานเมื่อ done, budget หมด, autoFixer ซ่อม, abort กลางคัน
- **เกณฑ์ผ่าน**: โจทย์จำลอง 3 สเต็ป (นำทาง→กรอก→ยืนยัน) วิ่งจบบน fixture
- [ ] B7 **agent LLM scope** — ⚠️ แก้ข้ออ้างอิงเดิม: `LLM_PROXY_MODEL` อยู่บน
      branch ทดสอบเท่านั้น ไม่มีบน branch นี้ ต้องสร้างของตัวเอง: reuse pattern
      `set_scoped_llm_config` ที่ pipeline เสียงใช้อยู่แล้ว
      (`_enter_fast_voice_llm_scope`) + env/setting ใหม่ `DEEPTUTOR_AGENT_MODEL`
      (และ optional `_BASE_URL`/`_API_KEY` แบบเดียวกับที่ standalone proxy พิสูจน์
      แล้วว่าจำเป็น) — **บทเรียนที่จ่ายมาแล้ว: ห้าม tier lite กับ loop นี้เด็ดขาด**
      และห้าม fallback เงียบไปโมเดลแชท (ตั้งครึ่งเดียว = 503 บอกตรงๆ)

### Phase C — Trust model ในตัว loop (ของเราแท้ๆ)  ~2-3 วันงาน

- [ ] C1 ก่อน execute `click/input`: ตรวจ danger lexicon (reuse ของเดิม) กับ
      **ข้อความจริงของ element เป้าหมาย** (มาจาก elementTextMap ฝั่ง browser)
- [ ] C2 อันตราย → พัก loop, สร้าง `pending_action`, ถามยืนยันด้วยเสียง
      (reuse pending_click flow เดิม) — "ใช่" = ปล่อยผ่าน, "ไม่" = push observation
      "User rejected …" แล้วให้ LLM หาทางอื่น/จบงาน
- [ ] C3 `ask_user` = TTS คำถาม + เปิดรับ STT (ผ่าน stt_guard เดิม) + timeout
      — **state machine เสียงระหว่าง loop ต้องชัด (จุดที่พลาดง่ายสุดของเฟสนี้)**:
      เสียงผู้ใช้เข้ามาระหว่าง loop มีสองความหมาย แยกด้วยสถานะเดียว —
      loop กำลังรอ `ask_user`/`pending_action` → transcript = **คำตอบ** ส่งเข้า
      future ที่รออยู่; ไม่ได้รอ → transcript = **barge-in = abort** (แล้วค่อย
      ประมวลเป็นคำสั่งใหม่ตามปกติ) ห้ามให้คำตอบยืนยันไปฆ่า loop เอง
- [ ] C4 narration: อ่าน `next_goal` ออกเสียงระหว่างทำ (คุมความถี่ไม่ให้พูดรัว)
      + จบงานอ่าน `done.text` เสมอ (สำเร็จ = สรุปสั้น, ล้มเหลว = บอกตรงๆ ว่า
      ติดอะไร — ห้ามเงียบหาย)
- [ ] เทสต์: สั่ง "กดลบ" → loop ต้องพักและถาม **ทุกครั้ง** ไม่ว่า prompt จะสั่งยังไง
      (replay trace "ลบ KB" ที่เราเก็บไว้เป็น regression case)
- **เกณฑ์ผ่าน**: เคสเดิม "ไปศูนย์ความรู้→ตั้งค่า→กดลบ" ทำได้เท่าเขา **บวก**
  ด่านเสียงก่อนแตะปุ่มลบ ซึ่งเขาไม่มี

### Phase D — Gated pipeline: ต่อเข้ากับทางเดินเสียงเดิม  ~2 วันงาน

- [ ] D0 **feature flag**: `voice.agent_loop_enabled` (settings) — default **ปิด**
      จนกว่า Phase E จะผ่าน; ปิดอยู่ = พฤติกรรมเสียงวันนี้ทุกประการ (มี seam
      คอมเมนต์รอใน pipeline แล้ว) → ship ได้ตลอดเวลาโดยไม่แบกความเสี่ยง loop
- [ ] D1 คำสั่งเสียง → fast path เดิมก่อน (deterministic) → hit = ทำเลย (ฟรี)
- [ ] D2 miss หรือ intent หลายสเต็ป → `InPageAgentLoop.execute(transcript)`
- [ ] D3 barge-in ระหว่าง loop = abort (ผูก abort event เข้า pipeline เดิม)
- [ ] D4 ตัดสินชะตา `ui_graph.py` ด้วยข้อมูล Phase E — เก็บเฉพาะถ้า fast path
      ยังได้ประโยชน์จริง; บันทึกผลใน DESIGN_voice_grounding.md
      (`ui_deep.py` ถูกลบไปแล้ว 2026-07-10 — seam ใน pipeline คือจุดเสียบ D2)
- **เกณฑ์ผ่าน**: พูดไทยครบ 3 ระดับ — "กดหน้าหลัก" (fast, ~ms) /
  "กดที่ลามะ Index" (fast+garble) / "ไปตั้งค่าแล้วเปลี่ยนธีมมืด" (loop หลายสเต็ป)

### Phase E — วัดผลเทียบ page-agent ตรงๆ  ~1-2 วันงาน

- [ ] E1 ชุดโจทย์มาตรฐาน ~10 ข้อ (เก็บจากการทดลองรอบนี้): click ชื่อ garble,
      เปลี่ยนธีม, ค้นหา+เปิด RAG, ลบ-แต่-อย่ายืนยัน, งานที่ต้อง scroll, ฯลฯ
- [ ] E2 รันทั้งคู่บน branch นี้ (page-agent ยังอยู่ครบ) เก็บ: success rate,
      จำนวน steps, tokens, เวลา, จำนวนครั้งที่ต้องยืนยัน
- [ ] E3 REPORT สรุป → ถ้าของเราแพ้ข้อไหน กลับไปดูซอร์สเขาว่าเพราะกลไกใด
- **เกณฑ์ผ่านของทั้งโปรเจค**: success ≥ page-agent บนโจทย์ชุดเดียวกัน
  โดยมี (1) fast path ถูกกว่าใน task ง่าย (2) ด่านอันตรายทำงาน 100%

### ลำดับและการพึ่งพา

A กับ B ทำขนานกันได้ (B เทสต์บน fixture ไม่รอ A) → C ต่อจาก B → D ต่อจาก A+C → E ปิดท้าย
รวม ~2-3 สัปดาห์ทำงานจริง

---

## 5. ความเสี่ยงและการรับมือ

| ความเสี่ยง | รับมือ |
|---|---|
| ต้นทุน token (DOM ทั้งหน้าทุก step × โมเดลแรง) | fast path กันงานง่ายออกก่อน; วัดจริงใน Phase E; ถ้าแพง → viewport-only + scroll (เขา default ทั้งหน้า เราเลือกได้) |
| WS round-trip ทำ loop ช้า | จิ๊บจ๊อยเทียบ LLM call; วัดใน E |
| โมเดลอ่อนทำ loop เพี้ยน (บทเรียนตรงจากการทดลอง!) | autoFixer + config โมเดลแยกจากแชท + budget warnings |
| DOM serialize ของเราต่างจากเขา → พฤติกรรม LLM ต่าง | Phase A มี golden test เทียบ output กับของเขาบนหน้าเดียวกัน |
| `agent_state` ชน cap 8K ของ control frame (ชนจริงแน่ — inventory เคยโดนปัดทั้ง frame มาแล้ว) | A4: serializer hard cap + ส่งแบบ chunked/แยก cap; ห้ามเงียบ-ตัด-ทิ้ง |
| named tool_choice ไม่เวิร์กกับบาง provider | B3: fallback JSON-object mode + fixer โดยอัตโนมัติ |
| loop เสียระหว่างพัฒนา กระทบเสียงที่ใช้งานได้อยู่ | D0: flag ปิดเป็น default — เสียงวันนี้ไม่เปลี่ยนจนกว่า E ผ่าน |
| ภาระดูแลโค้ด port | port เฉพาะชั้นบาง (actions/serialize ~1,100 บรรทัด) สมองเขียนเองหมด |
| upstream sync ชนกัน | ไฟล์ใหม่ทั้งหมดใน dir ใหม่ 2 จุด (`web/lib/page-actuator/`, `services/voice_realtime/agent/`) |

## 6. ทรัพย์สินทางปัญญา

page-agent = MIT (Copyright Alibaba Group Holding Limited) → port/ดัดแปลงได้
โดยคง copyright notice ในไฟล์ที่ port ตรง (A2) และให้เครดิตใน NOTICE + CHANGES.md
แนวคิด/สถาปัตยกรรม (loop, reflection, MacroTool) ไม่ติดลิขสิทธิ์ — ส่วนสมอง
เราเขียนใหม่ทั้งหมดเป็นงานของเรา (สายเลือดเดียวกับ browser-use ที่เป็นแรงบันดาลใจของเขาอีกที)

## 7. สิ่งที่ตัดสินใจแล้ว / ยังไม่ตัดสินใจ

**ตัดสินใจแล้ว**: สมอง server / มือ browser · ลอก 7 กลไกใน §3.2 · trust model เป็นแกน ·
ไฟล์ใหม่ล้วน · โมเดล agent แยกจากโมเดลแชท

**ยังไม่ตัดสินใจ (รอข้อมูล)**: ชะตา ui_graph.py (D4) · viewport เต็มหน้า vs จำกัด (E) ·
จะ expose `execute_javascript` ไหม (เขาปิด default — เราน่าจะไม่เปิดเลย) ·
multi-tab (extension package ของเขามี TabsController — นอกขอบเขตรอบนี้)
