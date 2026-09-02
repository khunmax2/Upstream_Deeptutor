#!/usr/bin/env bash
# รันสิ่งที่ CI (.github/workflows/tests.yml) รัน — ก่อน push
#
#   ./scripts/precheck.sh          # ตรวจครบ
#   ./scripts/precheck.sh --fast   # ข้าม node tests (เร็วขึ้นมาก)
#
# เขียวหมด = push ได้ค่อนข้างมั่นใจ. ข้อจำกัดที่ปิดไม่ได้ในเครื่อง อ่านท้ายไฟล์
#
# ไม่ต้อง activate venv ก่อน — สคริปต์เรียก .venv/bin/ ตรง ๆ ให้เอง
set -uo pipefail
cd "$(dirname "$0")/.."

# เรียกเครื่องมือ Python จาก venv ตรง ๆ แทนที่จะพึ่ง PATH: shell ที่ยังไม่ได้
# activate จะไม่เจอ ruff เลย (command not found) และจะไปเจอ pytest ของ system
# Python แทน ซึ่งไม่มี deps ของโปรเจกต์ — ผลคือสคริปต์รายงานว่า ruff/pytest ล้ม
# ทั้งที่โค้ดไม่ได้พัง เป็นสัญญาณลวงที่แย่กว่าไม่มี gate เลย.
# เคารพ VIRTUAL_ENV ถ้ามี (เผื่อใครใช้ venv คนละที่) ไม่งั้น default เป็น .venv
VENV_BIN="${VIRTUAL_ENV:-$PWD/.venv}/bin"
for _tool in ruff pytest; do
  if [[ ! -x "$VENV_BIN/$_tool" ]]; then
    printf '\033[31m❌ ไม่พบ %s ใน %s\033[0m\n' "$_tool" "$VENV_BIN"
    printf 'สคริปต์นี้ต้องใช้ venv ของโปรเจกต์. สร้าง/ติดตั้งด้วย:\n'
    printf '  python -m venv .venv && .venv/bin/pip install -e ".[all]"\n'
    exit 1
  fi
done

# ...และวาง venv ไว้หน้า PATH ด้วย: การเรียก binary ตรง ๆ คุมได้แค่โพรเซสที่เรา
# สั่งเอง แต่เทสต์บางตัว (tests/services/sandbox) spawn โพรเซสลูกที่ต้องหา
# `python` จาก PATH เอง — ถ้าไม่ทำ ลูกจะตายด้วย exit 127 (command not found)
# เฉพาะตอนที่ยังไม่ได้ activate ซึ่งก็เป็นสัญญาณลวงอีกแบบ
export PATH="$VENV_BIN:$PATH"

FAST=0; [[ "${1:-}" == "--fast" ]] && FAST=1
FAILED=()
run() {  # run <ชื่อ> <คำสั่ง...>
  local name="$1"; shift
  printf '\n\033[1m── %s\033[0m\n' "$name"
  if "$@"; then printf '\033[32m   ✅ %s\033[0m\n' "$name"
  else printf '\033[31m   ❌ %s\033[0m\n' "$name"; FAILED+=("$name"); fi
}

# pytest ต้องรันบน config แบบเดียวกับ CI ("Create minimal runtime config" ใน
# tests.yml) ไม่ใช่ config ใช้งานจริงของเรา — ไม่งั้นได้ผลลวง 16 ตัว: config จริง
# ตั้ง logging.level=INFO + console_output=true ทำให้ log ปนลง stdout จนเทสต์ที่
# parse stdout ของ subprocess พัง และ CORS/allow-origins ที่เราตั้งไว้ก็ไม่ตรงกับ
# ที่เทสต์คาด. DEEPTUTOR_HOME ย้าย data root ได้ทั้งก้อน จึงแยกได้โดยไม่แตะของจริง.
CI_HOME="$(mktemp -d)"
trap 'rm -rf "$CI_HOME"' EXIT
mkdir -p "$CI_HOME/data/user/settings"
cat > "$CI_HOME/data/user/settings/main.yaml" <<'YAML'
system:
  language: en
logging:
  level: WARNING
YAML
cp tests/fixtures/ci_model_catalog.json "$CI_HOME/data/user/settings/model_catalog.json"

# ── Python (job: lint + python-tests) ───────────────────────────
run "ruff check"        "$VENV_BIN/ruff" check .
run "ruff format"       "$VENV_BIN/ruff" format --check .
run "pytest"            env DEEPTUTOR_HOME="$CI_HOME" "$VENV_BIN/pytest" -q tests deeptutor/learning/tests

# ── Frontend (job: web-tests) ───────────────────────────────────
if [[ $FAST -eq 0 ]]; then
  run "node tests"      bash -c 'cd web && npm run test:node'
  run "eslint"          bash -c 'cd web && npx eslint .'
else
  echo -e "\n   ⏭  ข้าม node tests + eslint (--fast)"
fi

# ── สรุป ────────────────────────────────────────────────────────
printf '\n\033[1m════ สรุป ════\033[0m\n'
if [[ ${#FAILED[@]} -eq 0 ]]; then
  printf '\033[32m✅ ผ่านหมด — push ได้\033[0m\n'
  exit 0
fi
printf '\033[31m❌ ไม่ผ่าน: %s\033[0m\n' "${FAILED[*]}"
printf '\n\033[33mถ้า pytest ล้มตอน collect เพราะ ModuleNotFoundError\033[0m\n'
printf '(telegram / slack_sdk / zulip / …) แปลว่า .venv ขาด optional deps ที่ CI\n'
printf 'ติดตั้ง — ไม่ใช่โค้ดพัง แก้ครั้งเดียวจบด้วย:\n'
printf '  pip install -r requirements/partners.txt\n'
exit 1

# ── สิ่งที่สคริปต์นี้ตรวจแทน CI ไม่ได้ ──────────────────────────
# 1. CI รัน Python 3.11/3.12/3.13/3.14 — เครื่องคุณมีเวอร์ชันเดียว
#    (โค้ดที่พังเฉพาะเวอร์ชันเก่ากว่าจะหลุดไป)
# 2. CI รัน `npm ci --legacy-peer-deps` จาก lockfile สะอาด — เครื่องคุณใช้
#    node_modules ที่มีอยู่ (dependency drift จะไม่ถูกจับ)
# 3. job "import-check" ติดตั้งแค่ requirements/server.txt แล้วลอง import
#    — จับ import ที่เผลอพึ่ง optional dep ซึ่งเครื่องคุณมีครบอยู่แล้ว
# 4. workflow "Repository Hygiene" (scripts/check_repo_hygiene.py) ไม่ได้รันที่นี่
