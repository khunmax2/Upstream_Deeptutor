#!/usr/bin/env bash
set -euo pipefail
OURS="${1:-main}"; TARGET="${2:-upstream/main}"
git fetch upstream -q
MB=$(git merge-base "$OURS" "$TARGET")        # จุด fork ร่วม → ดู "เฉพาะของใหม่ upstream"
echo "## merge-base = $MB"
echo "## upstream เปลี่ยนอะไรบ้าง (stat)"; git diff --stat "$MB..$TARGET" | tail -1
echo "## collision (เราแก้ใน main ∩ upstream แก้)"
git diff --name-only "$MB..$TARGET" | sort | comm -12 FORK_TOUCHPOINTS.txt -
echo "## Tier-1 pillars touched"
git diff --name-only "$MB..$TARGET" | grep -Ef <(printf '%s\n' \
  'services/prompt/language.py' 'services/prompt/manager.py' 'core/i18n.py' \
  'config/loader.py' 'i18n/init.ts' 'app-shell-storage.ts') || echo "  (none ✅)"
echo "## en/app.json new keys (บวก)"; git diff "$MB..$TARGET" -- web/locales/en/app.json | grep -cE '^\+\s*"' || true
echo "## new language-gates introduced by upstream"
git diff "$MB..$TARGET" | grep -E '^\+' | grep -E 'startswith\("zh"\)|== "zh"|Literal\["(en|zh)"' || echo "  (none ✅)"
echo "## ไฟล์ไทยที่ upstream ลบ/ย้าย"
git diff --name-status "$MB..$TARGET" | grep -E '^[DR]' | grep -Ff FORK_TOUCHPOINTS.txt || echo "  (none ✅)"
