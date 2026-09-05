#!/usr/bin/env bash
# ============================================
# Wire /deepwitya2 into the host nginx.  Run with sudo:
#     sudo bash deploy/apply-nginx-deepwitya2.sh
#
# What it does
#   1. backs up both shared config files (timestamped, next to the originals)
#   2. writes TWO snippet files that this project owns outright
#   3. adds ONE include line to each shared file (the only shared-file change)
#   4. runs `nginx -t`; on ANY failure it restores the backups and exits
#      WITHOUT ever reloading, so the running nginx keeps its current config
#   5. reloads nginx only after the test passes
#
# Idempotent: re-running detects the include lines and makes no second change.
# Reversible: sudo bash deploy/apply-nginx-deepwitya2.sh --revert
# ============================================
set -euo pipefail

SSL=/etc/nginx/sites-available/sansarnnews-ssl   # :443, server_name 203.185.144.41
HTTP=/etc/nginx/sites-available/ade              # :80,  server_name _
SNIP_SSL=/etc/nginx/snippets/deepwitya2.conf
SNIP_HTTP=/etc/nginx/snippets/deepwitya2-redirect.conf
STAMP=$(date +%Y%m%d-%H%M%S)

[ "$(id -u)" -eq 0 ] || { echo "ต้องรันด้วย sudo" >&2; exit 1; }

backup() { cp -a "$1" "$1.bak-$STAMP"; echo "  backup: $1.bak-$STAMP"; }

restore() {
  echo "!! nginx -t ไม่ผ่าน — คืนค่าเดิมทั้งหมด" >&2
  [ -f "$SSL.bak-$STAMP" ]  && mv -f "$SSL.bak-$STAMP"  "$SSL"
  [ -f "$HTTP.bak-$STAMP" ] && mv -f "$HTTP.bak-$STAMP" "$HTTP"
  rm -f "$SNIP_SSL" "$SNIP_HTTP"
  echo "   คืนค่าเรียบร้อย nginx ยังใช้ config เดิมอยู่ (ไม่เคย reload)" >&2
  exit 1
}

if [ "${1:-}" = "--revert" ]; then
  python3 - "$SSL" "$HTTP" <<'PY'
import re, sys
for f in sys.argv[1:]:
    s = open(f).read()
    s = re.sub(
        r'\n *# DeepTutor v2[^\n]*\n *include /etc/nginx/snippets/deepwitya2[a-z-]*\.conf;\n',
        '\n', s)
    open(f, 'w').write(s)
    print("  cleaned", f)
PY
  rm -f "$SNIP_SSL" "$SNIP_HTTP"
  nginx -t && systemctl reload nginx && echo "revert เรียบร้อย"
  exit 0
fi

echo "== 1. backup =="
backup "$SSL"
backup "$HTTP"

echo "== 2. เขียน snippet (ไฟล์ของโปรเจคนี้เอง) =="
cat > "$SNIP_SSL" <<'CONF'
# DeepTutor v2 — frontend behind basePath=/deepwitya2
# Owned by /home/search/Thoughtmind/Upstream_Deeptutor_v2
#
# NO trailing slash on proxy_pass: Next.js basePath needs the prefix preserved,
# or /deepwitya2/_next/... resolves to nothing.
location /deepwitya2 {
    proxy_pass http://127.0.0.1:10320;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
CONF

cat > "$SNIP_HTTP" <<'CONF'
# DeepTutor v2 — force HTTPS for THIS PATH ONLY
# Owned by /home/search/Thoughtmind/Upstream_Deeptutor_v2
#
# Same per-location redirect pattern already used by /research-helper and
# /sansarn-research-helper in this file.
#
# Deliberately NO HSTS header: HSTS is per-HOST, not per-path, so adding it here
# would force every path on this IP to HTTPS in visitors' browsers — including
# other projects that may still need plain HTTP.
location /deepwitya2 {
    return 301 https://$host$request_uri;
}
CONF
echo "  wrote $SNIP_SSL"
echo "  wrote $SNIP_HTTP"

echo "== 3. เพิ่ม include อย่างละ 1 บรรทัด =="
python3 - "$SSL" "$HTTP" <<'PY'
import sys

def insert_before_last_brace(path, comment, include):
    s = open(path).read()
    if "deepwitya2" in s:
        print(f"  ข้าม {path} (มี deepwitya2 อยู่แล้ว)")
        return
    i = s.rstrip().rfind("}")
    assert i != -1, f"{path}: หา closing brace ไม่เจอ"
    block = f"\n    {comment}\n    include {include};\n"
    open(path, "w").write(s[:i] + block + s[i:])
    print(f"  แก้ {path} (+3 บรรทัด)")

insert_before_last_brace(
    sys.argv[1],
    "# DeepTutor v2 — see Upstream_Deeptutor_v2/deploy/apply-nginx-deepwitya2.sh",
    "/etc/nginx/snippets/deepwitya2.conf")
insert_before_last_brace(
    sys.argv[2],
    "# DeepTutor v2 — see Upstream_Deeptutor_v2/deploy/apply-nginx-deepwitya2.sh",
    "/etc/nginx/snippets/deepwitya2-redirect.conf")
PY

echo "== 4. nginx -t =="
nginx -t || restore

echo "== 5. reload =="
systemctl reload nginx
echo
echo "เสร็จ — ลองเปิด https://203.185.144.41/deepwitya2"
