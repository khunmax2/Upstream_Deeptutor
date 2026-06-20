# REPORT — LINE channel: empty `allowFrom` ทำให้ backend ล่มทั้งตัว

วันที่: 2026-06-20
สถานะ: รายงานปัญหา (ยังไม่แก้โค้ด) — เอาไปคุยใน Cowork ก่อน
Branch: `feature/LINE_Integration`

---

## 1. อาการที่เจอ

ระหว่างกำลัง **ลองตั้งค่า** LINE channel (ยังไม่ได้ใส่ allowlist ใด ๆ) สั่ง `deeptutor start`
แล้ว backend crash ทันทีตอน startup ด้วย exit code 3:

```
SystemExit: Error: "line" has empty allowFrom (denies all).
Set ["*"] to allow everyone, or add specific user IDs.

ERROR:    Application startup failed. Exiting.
...
RuntimeError: Backend exited with code 3
```

Frontend ขึ้นได้ปกติ แต่ backend ตาย → ใช้งานอะไรไม่ได้เลย

---

## 2. Root cause

ปัญหาไม่ใช่ว่า "ผู้ใช้ตั้งค่าผิด" แต่เป็นว่า **default config ที่ระบบสร้างให้เอง ไปชน guard ที่
escalate เป็น fatal crash ของทั้ง process**

### ลำดับเหตุการณ์

1. เปิด LINE channel → config ถูกเขียนด้วยค่า default `allow_from: []`
   - มาจาก Pydantic field default: `allow_from: list[str] = Field(default_factory=list)`
     ที่ [`deeptutor/partners/channels/line.py:104`](deeptutor/partners/channels/line.py:104)
   - ไฟล์จริงที่เจอ: [`data/partners/lineme/config.yaml:5`](data/partners/lineme/config.yaml) → `allow_from: []`
2. `deeptutor start` → FastAPI lifespan → `auto_start_partners()`
   ([`deeptutor/api/main.py:149`](deeptutor/api/main.py))
3. → `start_partner()` → `_build_channel_manager()` → `ChannelManager.__init__()`
   → `_init_channels()` → `_validate_allow_from()`
4. `_validate_allow_from()` เจอ `allow_from == []` → `raise SystemExit(...)`
   ([`deeptutor/partners/channels/manager.py:108-114`](deeptutor/partners/channels/manager.py:108))
5. `SystemExit` ใน lifespan → **Application startup failed** → backend process ตายทั้งตัว

### จุดสำคัญ: มี 2 เลเยอร์ที่จัดการ `allow_from` ว่าง แต่ไม่สอดคล้องกัน

| เลเยอร์ | ตำแหน่ง | พฤติกรรมเมื่อ `allow_from == []` | ผลกระทบ |
|--------|---------|--------------------------------|---------|
| **Runtime guard** | [`base.py:116-124`](deeptutor/partners/channels/base.py:116) `is_allowed()` | log warning + ปฏิเสธข้อความนั้น (return False) | นุ่มนวล, ปลอดภัย ✅ |
| **Startup validator** | [`manager.py:108-114`](deeptutor/partners/channels/manager.py:108) `_validate_allow_from()` | `raise SystemExit` | ฆ่า backend ทั้ง process ❌ |

Runtime layer ปฏิเสธข้อความจาก sender ที่ไม่ได้รับอนุญาตอยู่แล้ว (deny-by-default ทำงานถูก)
ดังนั้น startup validator ที่ escalate เป็น `SystemExit` จึง **เกินจำเป็น** — channel ออปชัน
เดียวที่ตั้งค่าไม่ครบ ไม่ควรทำให้ทั้งระบบ (รวม capability/ช่องทางอื่น) บูตไม่ขึ้น

> หมายเหตุ: `_validate_allow_from` มาตั้งแต่ commit `da106191` (production IM infra)
> ไม่ใช่โค้ดที่ฟอร์กเพิ่งเพิ่ม — เป็นพฤติกรรม upstream

---

## 3. ผลกระทบ / ความรุนแรง

- **UX**: กับดักตอน onboarding — แค่ "ลองเปิด" channel แล้วรีสตาร์ท = backend ทั้งตัวบูตไม่ขึ้น
  ข้อความ error อยู่ใน backend log ที่ผู้ใช้ทั่วไปอาจไม่ทันสังเกต (เห็นแต่ "Backend exited code 3")
- **Blast radius**: ไม่ได้กระทบแค่ LINE — channel ใด ๆ (Telegram, Slack, Discord, ฯลฯ) ที่
  เปิดโดยยังไม่ตั้ง `allow_from` ก็ทำให้ backend ล่มเหมือนกัน เพราะ default เป็น `[]` ทั้งหมด
  (ดู grep: ทุก channel ใช้ `Field(default_factory=list)`)
- **Security**: ไม่มีช่องโหว่ — deny-by-default ถูกต้องแล้ว ปัญหาอยู่ที่ "วิธีบังคับ" ไม่ใช่ "นโยบาย"

### เรื่อง credentials (ตรวจแล้ว — ปลอดภัย)

ไฟล์ [`data/partners/lineme/config.yaml`](data/partners/lineme/config.yaml) มี
`channel_access_token` / `channel_secret` เป็น plaintext แต่ตรวจแล้วไฟล์ **ถูก gitignore และ
ไม่ได้ถูก git track** → ไม่หลุดขึ้น repo ไม่ต้อง rotate

---

## 4. แนวทางแก้ (เสนอเพื่อถกใน Cowork)

### ตัวเลือก A — Graceful degradation (แนะนำ) ⭐

เปลี่ยน `_validate_allow_from()` ไม่ให้ `SystemExit` แต่ให้ **ข้าม/ปิดเฉพาะ channel ที่ตั้งค่า
ไม่ครบ** แล้ว log error ชัด ๆ ที่บอกวิธีแก้

- **ข้อดี**: channel เดียวพังไม่ลากทั้ง backend ล่ม; channel อื่น + capability ยังทำงาน;
  runtime guard ก็ deny ให้อยู่แล้ว
- **ข้อเสีย**: ถ้าใครตั้งใจให้ "config ผิด = ต้องหยุด" จะหายไป (แก้ด้วยการ log ระดับ ERROR ที่เด่นพอ)
- **กระทบไฟล์ upstream** 1 จุด ([`manager.py`](deeptutor/partners/channels/manager.py)) →
  ต้องบันทึก CHANGES.md ตามฟอร์กโพลิซี §1
- ร่างแนวทาง:
  ```python
  def _validate_allow_from(self) -> None:
      for name in list(self.channels):
          ch = self.channels[name]
          if getattr(ch.config, "allow_from", None) == []:
              _logger().error(
                  '{} channel disabled: empty allowFrom (denies all). '
                  'Set ["*"] to allow everyone, or add specific user IDs.',
                  name,
              )
              del self.channels[name]   # ปิดเฉพาะตัวนี้ ไม่ crash ทั้ง backend
  ```

### ตัวเลือก B — แก้ default ตอนสร้าง config ไม่ให้ออกมาว่าง

ตอน scaffold/บันทึก config ผ่าน UI ให้ค่าเริ่มต้นเป็นสถานะที่ "valid แต่ปลอดภัย"
เช่น `enabled: false` จนกว่าจะตั้ง `allow_from`, หรือบังคับให้ UI กรอก allowlist ก่อนเปิด channel

- **ข้อดี**: แก้ที่ต้นทาง ผู้ใช้ไม่มีทางได้ config พังตั้งแต่แรก
- **ข้อเสีย**: ต้องแตะทั้งฝั่ง UI (agents-config) และตัว writer ของ partner config; ขอบเขตกว้างกว่า
- เหมาะทำ **ควบคู่** กับ A (A กัน crash, B กันไม่ให้เกิดตั้งแต่แรก)

### ตัวเลือก C — ไม่แตะโค้ด แค่ทำ docs/UX

เพิ่มคำอธิบายใน UI ว่าต้องตั้ง `allow_from` ก่อนเปิด channel + ข้อความ error ที่อ่านง่ายขึ้น

- **ข้อดี**: ไม่กระทบ upstream เลย mergeable ที่สุด
- **ข้อเสีย**: ไม่แก้ root cause — กับดัก crash ยังอยู่

### Quick fix ที่ทำไปแล้ว (workaround ชั่วคราว)

ตั้ง [`data/partners/lineme/config.yaml`](data/partners/lineme/config.yaml) เป็น:
```yaml
    allow_from:
    - '*'
```
→ backend boot ได้แล้ว **แต่** `['*']` = อนุญาตทุกคนที่หา bot เจอใน LINE คุยได้
ใช้เทสต์ DM MVP พอได้ แต่ก่อนใช้จริงควรเปลี่ยนเป็น LINE userId เฉพาะ

---

## 5. ข้อเสนอแนะ

- **ระยะสั้น**: ทำ **ตัวเลือก A** — ค่าใช้จ่ายต่ำ, กันกับดักได้ทันที, สอดคล้องกับ runtime guard ที่มีอยู่
- **ระยะกลาง**: ทำ **ตัวเลือก B** ฝั่ง UI เพื่อกันไม่ให้เกิด config พังตั้งแต่ต้นทาง
- เปลี่ยน workaround `['*']` กลับเป็น allowlist เฉพาะก่อน deploy จริง

---

## 6. Fix applied — 2026-06-20 (Option A)

ทำตาม **ตัวเลือก A (graceful degrade)** แล้ว แยกเป็น commit เดี่ยว generic เพื่อ cherry-pick
ขึ้น branch สะอาดสำหรับ upstream PR (`channels/manager.py` ของฟอร์ก == upstream, pristine)

### Diff (surgical)

`deeptutor/partners/channels/manager.py` — `_validate_allow_from()`:
เปลี่ยนจาก `raise SystemExit` → log ERROR + `del self.channels[name]` (ปิดเฉพาะ channel นั้น)

```python
def _validate_allow_from(self) -> None:
    # An enabled channel with empty allowFrom denies all senders. Disable
    # just that channel (and log why) instead of aborting the whole
    # process, so one misconfigured channel can't take the backend down.
    for name in list(self.channels):  # snapshot — we mutate during the loop
        if getattr(self.channels[name].config, "allow_from", None) == []:
            _logger().error(
                "{} channel disabled: empty allowFrom (denies all). "
                'Set ["*"] to allow everyone, or add specific user IDs.',
                name,
            )
            del self.channels[name]
```

- ไม่แตะ `_init_channels` (ยังเรียก `_validate_allow_from()` ที่ท้าย method เหมือนเดิม)
- deny-by-default ยังอยู่ครบ: runtime `BaseChannel.is_allowed` (base.py:116) ปฏิเสธทุก sender
  เมื่อ allowlist ว่างอยู่แล้ว — fix นี้แค่กันไม่ให้ "startup escalate เป็น process kill"

### Tests

เพิ่ม `tests/services/partners/test_channel_manager.py::TestValidateAllowFrom`:
- `test_empty_allow_from_disables_only_that_channel` — channel ที่ `allow_from=[]` หายจาก
  `manager.channels`, channel ที่ตั้งถูก (`["*"]`) ยังอยู่, **ไม่ raise** (ยืนยัน "1 ตัวพังไม่ลากตัวอื่น")
- `test_valid_channels_are_left_intact` — channel ที่ allowlist ถูกต้องไม่ถูกแตะ

ไม่มี test เดิมที่ assert `SystemExit` บน validator (ตรวจแล้ว — ไม่ต้องแก้ของเดิม)

### ผลรัน

- `pytest tests/services/partners/` → **370 passed, 3 failed**
  - 3 ที่ fail เป็น **pre-existing** จาก optional deps ที่ไม่ได้ติดตั้ง (`telegram`, `slack_sdk`,
    `PyJWT[crypto]`) — ยืนยันด้วยการ stash การแก้แล้วรันบน HEAD ก็ fail เหมือนเดิม ไม่เกี่ยวกับ fix นี้
  - 2 test ใหม่ของ fix นี้ผ่านทั้งคู่
- `ruff check` + `ruff format` → ผ่าน (format จัด string quote ให้เล็กน้อย)

### Closeout

- `FORK_TOUCHPOINTS.txt` — เพิ่ม `deeptutor/partners/channels/manager.py` พร้อมหมายเหตุ
  "upstream bugfix; candidate for upstream PR — remove once merged"
- `CHANGES.md` — เพิ่ม section ใหม่ "Upstream bug fixes"

### ขั้นต่อไป (แยก action — ทำหลัง fork fix เขียว)

Cherry-pick commit นี้ขึ้น branch สะอาดจาก `upstream/main` แล้วเปิด PR → `HKUDS/DeepTutor:main`
(คำอธิบาย PR เป็น generic: อาการ → root cause → fix; ไม่พูดถึงฟอร์ก/LINE/Thai)
