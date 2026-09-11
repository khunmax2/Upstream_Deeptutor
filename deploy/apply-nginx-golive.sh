#!/usr/bin/env bash
# ============================================
# Go-live nginx changes for /deepwitya on the host — run with sudo.
#
#   sudo bash deploy/apply-nginx-golive.sh --preview [new-frontend-port] [preview-port]
#       A loopback-only HTTPS server on 127.0.0.1:<preview-port> (default
#       8443) that serves the NEW stack under /deepwitya, reusing the host
#       certificate. Nothing on :443 changes. Reach it from your machine
#       through an SSH tunnel (pick any free LOCAL port on the left):
#           ssh -L 18443:127.0.0.1:<preview-port> <user>@203.185.144.41
#           https://localhost:18443/deepwitya
#       This is the only way to exercise a stack whose base path is compiled
#       in: /deepwitya on :443 still belongs to the old stack until cutover.
#       The port must be free on the host: `nginx -t` does not bind, so a
#       taken port passes the test and then fails at reload -- nginx logs
#       `bind() ... failed (98: Address already in use)`, keeps the OLD
#       config, and every later reload (the cutover's included) fails the
#       same way while the file stays in sites-enabled. So this mode refuses
#       a taken port before writing anything, verifies the listener after
#       the reload, and --cutover refuses to run while a preview file exists
#       whose port nginx is not listening on. Measured 2026-09-11: 8443 on
#       the host belongs to a Kong gateway of another application.
#
#   sudo bash deploy/apply-nginx-golive.sh --cutover 10310 10320
#       On :443, `location /deepwitya` moves from the old frontend port to the
#       new one, and `location /deepwitya/studio` (→ gatekeeper 10330) is
#       included next to it. Longest prefix wins, so the studio location beats
#       /deepwitya without the /deepwitya block knowing. The old port is
#       recorded for --revert. On :80, `location /deepwitya` gets a
#       `return 301` to HTTPS as its first line if it proxies today (a block
#       that already redirects is left alone): the new stack sets a Secure
#       session cookie, so a login over plain HTTP never sticks. `return`
#       runs in nginx's rewrite phase, before proxy_pass, so the existing
#       proxy_pass line stays where it is and --revert removes one line.
#
#   sudo bash deploy/apply-nginx-golive.sh --revert [--force]
#       /deepwitya back to the recorded old port, studio include removed.
#       The old stack must still be running — nothing here starts it, and
#       it refuses to point /deepwitya at a port nothing listens on (the
#       state after the old stack is removed in GO-LIVE.md §8): that would
#       turn a working site into 502 in the name of a rollback. --force
#       overrides when you know something will listen there in a moment.
#
#   sudo bash deploy/apply-nginx-golive.sh --remove-preview
#       Drop the preview server after cutover.
#
# Every mode: backup both shared files (timestamped, next to the originals),
# edit, `nginx -t`; on ANY failure restore the backups and exit WITHOUT
# reloading, so the running nginx keeps its current config. Reload only after
# the test passes. Same pattern as apply-nginx-deepwitya2.sh.
#
# The shared files belong to other teams too (six other paths on this IP).
# The only edits made to them: on :443 one `include` line and one port number
# inside the `location /deepwitya` block; on :80 one `return 301` line inside
# that block. Everything else lives in files this project owns outright under
# /etc/nginx/snippets and sites-available.
# ============================================
set -euo pipefail

SSL=/etc/nginx/sites-available/sansarnnews-ssl   # :443, server_name 203.185.144.41
HTTP=/etc/nginx/sites-available/ade              # :80,  server_name _
SNIP_STUDIO=/etc/nginx/snippets/deepwitya-studio.conf
PREVIEW=/etc/nginx/sites-available/deepwitya-preview
PREVIEW_LINK=/etc/nginx/sites-enabled/deepwitya-preview
STATE=/etc/nginx/snippets/deepwitya-golive.state
GATEKEEPER_PORT=10330
PREVIEW_PORT="${PREVIEW_PORT:-8443}"
STAMP=$(date +%Y%m%d-%H%M%S)
CLEANUP_ON_FAIL=""

[ "$(id -u)" -eq 0 ] || { echo "ต้องรันด้วย sudo" >&2; exit 1; }

backup() { cp -a "$1" "$1.bak-$STAMP"; echo "  backup: $1.bak-$STAMP"; }

restore() {
  echo "!! nginx -t ไม่ผ่าน — คืนค่าเดิมทั้งหมด" >&2
  [ -f "$SSL.bak-$STAMP" ]  && mv -f "$SSL.bak-$STAMP"  "$SSL"
  [ -f "$HTTP.bak-$STAMP" ] && mv -f "$HTTP.bak-$STAMP" "$HTTP"
  # shellcheck disable=SC2086
  [ -n "$CLEANUP_ON_FAIL" ] && rm -f $CLEANUP_ON_FAIL
  echo "   คืนค่าเรียบร้อย nginx ยังใช้ config เดิมอยู่ (ไม่เคย reload)" >&2
  exit 1
}

test_and_reload() {
  echo "== nginx -t =="
  nginx -t || restore
  echo "== reload =="
  systemctl reload nginx
}

write_studio_snippet() {
  cat > "$SNIP_STUDIO" <<CONF
# DeepWitya — Course Studio behind its gatekeeper (ADR-0005)
# Owned by the DeepWitya checkout: deploy/apply-nginx-golive.sh
#
# Sits under /deepwitya on purpose: nginx picks the longest matching prefix,
# so this wins over \`location /deepwitya\` without that block knowing.
# The gatekeeper listens on loopback only and forwards to the studio after
# verifying the DeepWitya session cookie; a signed-out visitor is sent to
# /deepwitya/login by the gatekeeper itself.
#
# NO trailing slash on proxy_pass: the studio is built with
# basePath=/deepwitya/studio and needs the prefix preserved.
location /deepwitya/studio {
    proxy_pass http://127.0.0.1:${GATEKEEPER_PORT};
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_buffering off;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    client_max_body_size 200m;
}
CONF
  echo "  wrote $SNIP_STUDIO"
}

# Rewrite the port inside `location /deepwitya {` only. With no destination
# it only reports. Refuses anything but exactly one proxy_pass in the block.
swap_port() { # file from [to]
  python3 - "$@" <<'PY'
import re, sys
path, src = sys.argv[1], sys.argv[2]
dst = sys.argv[3] if len(sys.argv) > 3 else ""
s = open(path, encoding="utf-8").read()
m = re.search(r'^([ \t]*)location\s+/deepwitya\s*\{', s, re.M)
if not m:
    print(f"  {path}: ไม่มี location /deepwitya — ไม่แตะ")
    sys.exit(0)
# the block ends at the first `}` on its own line at the same indentation
end = re.compile(r'^' + re.escape(m.group(1)) + r'\}', re.M).search(s, m.end())
assert end, f"{path}: หา closing brace ของ location /deepwitya ไม่เจอ"
block = s[m.start():end.end()]
hits = re.findall(r'proxy_pass\s+http://127\.0\.0\.1:(\d+);', block)
if not hits:
    print(f"  {path}: location /deepwitya ไม่มี proxy_pass (redirect?) — ไม่แตะ")
    sys.exit(0)
assert len(hits) == 1, f"{path}: มี proxy_pass {len(hits)} บรรทัดใน location /deepwitya — ต้องแก้มือ"
if hits[0] != src:
    print(f"  {path}: location /deepwitya ชี้ไป {hits[0]} ไม่ใช่ {src} ที่บอกมา — หยุด")
    sys.exit(2)
if not dst:
    print(f"  {path}: location /deepwitya → {hits[0]}")
    sys.exit(0)
new_block = block.replace(f"127.0.0.1:{src};", f"127.0.0.1:{dst};", 1)
open(path, "w", encoding="utf-8").write(s[:m.start()] + new_block + s[end.end():])
print(f"  {path}: location /deepwitya {src} → {dst}")
PY
}

include_studio() { # add the include line inside the :443 server block, once
  python3 - "$SSL" "$SNIP_STUDIO" <<'PY'
import sys
path, snip = sys.argv[1], sys.argv[2]
s = open(path, encoding="utf-8").read()
if snip in s:
    print(f"  ข้าม {path} (include studio อยู่แล้ว)")
    sys.exit(0)
i = s.rstrip().rfind("}")
assert i != -1, f"{path}: หา closing brace ไม่เจอ"
block = f"\n    # DeepWitya Course Studio — see deploy/apply-nginx-golive.sh\n    include {snip};\n"
open(path, "w", encoding="utf-8").write(s[:i] + block + s[i:])
print(f"  แก้ {path} (+3 บรรทัด: include studio)")
PY
}

remove_include_studio() {
  python3 - "$SSL" "$SNIP_STUDIO" <<'PY'
import re, sys
path, snip = sys.argv[1], sys.argv[2]
s = open(path, encoding="utf-8").read()
s2 = re.sub(r'\n *# DeepWitya Course Studio[^\n]*\n *include ' + re.escape(snip) + r';\n', '', s)
open(path, "w", encoding="utf-8").write(s2)
print(f"  {'เอา include studio ออกจาก' if s2 != s else 'ไม่มี include studio ใน'} {path}")
PY
}

# :80 — make `location /deepwitya` redirect to HTTPS by adding one line at the
# top of the block. Reports and exits 0 when the block already redirects or
# does not exist. With "--check" it only reports what the block does today.
redirect_http() { # [--check]
  python3 - "$HTTP" "${1:-}" <<'PY'
import re, sys
path, mode = sys.argv[1], sys.argv[2]
MARK = "# DeepWitya go-live — see deploy/apply-nginx-golive.sh"
s = open(path, encoding="utf-8").read()
m = re.search(r'^([ \t]*)location\s+/deepwitya\s*\{[ \t]*\n', s, re.M)
if not m:
    print(f"  {path}: ไม่มี location /deepwitya — ไม่แตะ")
    sys.exit(0)
end = re.compile(r'^' + re.escape(m.group(1)) + r'\}', re.M).search(s, m.end())
assert end, f"{path}: หา closing brace ของ location /deepwitya ไม่เจอ"
block = s[m.start():end.end()]
if MARK in block:
    print(f"  {path}: location /deepwitya redirect ไป https อยู่แล้ว (ของ go-live) — ข้าม")
    sys.exit(0)
if re.search(r'^\s*return\s+30[12]\s', block, re.M):
    print(f"  {path}: location /deepwitya เป็น redirect อยู่แล้ว — ไม่แตะ")
    sys.exit(0)
hits = re.findall(r'proxy_pass\s+http://127\.0\.0\.1:(\d+);', block)
what = f"proxy ไป {hits[0]}" if hits else "ไม่มี proxy_pass"
if mode == "--check":
    print(f"  {path}: location /deepwitya {what} บน :80 — cutover จะเพิ่ม return 301 ไป https")
    sys.exit(0)
indent = m.group(1) + "    "
ins = f"{indent}{MARK}\n{indent}return 301 https://$host$request_uri;\n"
open(path, "w", encoding="utf-8").write(s[:m.end()] + ins + s[m.end():])
print(f"  {path}: location /deepwitya ({what}) + return 301 https (+2 บรรทัด)")
PY
}

unredirect_http() {
  python3 - "$HTTP" <<'PY'
import re, sys
path = sys.argv[1]
s = open(path, encoding="utf-8").read()
s2 = re.sub(r'^[ \t]*# DeepWitya go-live — see deploy/apply-nginx-golive\.sh\n[ \t]*return 301 https://\$host\$request_uri;\n', '', s, count=1, flags=re.M)
open(path, "w", encoding="utf-8").write(s2)
print(f"  {'เอา return 301 ของ go-live ออกจาก' if s2 != s else 'ไม่มี return 301 ของ go-live ใน'} {path}")
PY
}

cert_lines() { # the certificate the :443 server already uses
  grep -E '^[[:space:]]*ssl_certificate(_key)?[[:space:]]' "$SSL" | head -2
}

listening() { # port -- is anything listening on 127.0.0.1:<port> or *:<port>
  ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1$"
}

preview_file_port() { # the port the preview file declares, if the file exists
  [ -f "$PREVIEW" ] && grep -oE 'listen 127\.0\.0\.1:[0-9]+' "$PREVIEW" | grep -oE '[0-9]+$' || true
}

# A preview file whose port nginx is not listening on means the last reload
# failed at bind() and nginx is still on the config before it; the next
# reload fails the same way. Refuse to build on that.
refuse_stale_preview() {
  local pp; pp=$(preview_file_port)
  if [ -n "$pp" ] && ! listening "$pp"; then
    echo "!! $PREVIEW ตั้ง listen $pp แต่ nginx ไม่ได้ฟังพอร์ตนั้น — reload ครั้งก่อน bind ไม่สำเร็จ" >&2
    echo "   (ดู: tail -n 30 /var/log/nginx/error.log | grep bind)" >&2
    echo "   รัน: sudo bash deploy/apply-nginx-golive.sh --remove-preview  ก่อน แล้วค่อยทำต่อ" >&2
    exit 1
  fi
}

case "${1:-}" in
  --preview)
    NEW_PORT="${2:-10320}"
    PREVIEW_PORT="${3:-$PREVIEW_PORT}"
    echo "== preview: 127.0.0.1:$PREVIEW_PORT → /deepwitya:$NEW_PORT, /deepwitya/studio:$GATEKEEPER_PORT =="
    echo "== 0. ตรวจก่อนแตะ =="
    refuse_stale_preview
    if [ "$(preview_file_port)" = "$PREVIEW_PORT" ]; then
      echo "  preview ของเราฟังที่ $PREVIEW_PORT อยู่แล้ว — เขียนทับด้วยค่าใหม่"
    elif listening "$PREVIEW_PORT"; then
      echo "!! พอร์ต $PREVIEW_PORT บน host มีคนฟังอยู่แล้ว:" >&2
      ss -ltnp 2>/dev/null | grep -E "[:.]$PREVIEW_PORT[[:space:]]" | head -3 >&2
      echo "   เลือกพอร์ตอื่น: sudo bash deploy/apply-nginx-golive.sh --preview $NEW_PORT <port>   (เช่น 9443)" >&2
      exit 1
    else
      echo "  พอร์ต $PREVIEW_PORT ว่าง"
    fi
    write_studio_snippet
    CERT=$(cert_lines)
    [ -n "$CERT" ] || { echo "หา ssl_certificate ใน $SSL ไม่เจอ" >&2; exit 1; }
    {
      echo "# DeepWitya go-live PREVIEW — loopback only, reachable through an SSH tunnel."
      echo "# Owned by the DeepWitya checkout: deploy/apply-nginx-golive.sh --preview"
      echo "# Remove after cutover: deploy/apply-nginx-golive.sh --remove-preview"
      echo "server {"
      echo "    listen 127.0.0.1:${PREVIEW_PORT} ssl;"
      echo "    server_name 203.185.144.41 localhost;"
      printf '%s\n' "$CERT" | sed 's/^[[:space:]]*/    /'
      echo "    client_max_body_size 200m;"
      echo
      echo "    include ${SNIP_STUDIO};"
      echo
      echo "    location /deepwitya {"
      echo "        proxy_pass http://127.0.0.1:${NEW_PORT};"
      echo "        proxy_http_version 1.1;"
      echo '        proxy_set_header Upgrade $http_upgrade;'
      echo '        proxy_set_header Connection "upgrade";'
      echo '        proxy_set_header Host $host;'
      echo '        proxy_set_header X-Real-IP $remote_addr;'
      echo '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;'
      echo '        proxy_set_header X-Forwarded-Proto $scheme;'
      echo "        proxy_buffering off;"
      echo "        proxy_read_timeout 3600s;"
      echo "        proxy_send_timeout 3600s;"
      echo "    }"
      echo
      echo "    location = / { return 302 /deepwitya; }"
      echo "}"
    } > "$PREVIEW"
    ln -sf "$PREVIEW" "$PREVIEW_LINK"
    echo "  wrote $PREVIEW (+ enabled)"
    CLEANUP_ON_FAIL="$PREVIEW $PREVIEW_LINK"
    test_and_reload
    sleep 1
    if ! listening "$PREVIEW_PORT"; then
      echo "!! reload แล้วแต่ nginx ไม่ได้ฟังที่ 127.0.0.1:$PREVIEW_PORT — bind ล้ม (ดู tail -n 30 /var/log/nginx/error.log)" >&2
      echo "   เอาไฟล์ที่ bind ไม่ได้ออกก่อน ไม่งั้น reload ครั้งถัดไปล้มเหมือนกัน: --remove-preview" >&2
      exit 1
    fi
    echo "  nginx ฟังที่ 127.0.0.1:$PREVIEW_PORT แล้ว"
    echo
    echo "เสร็จ — จากเครื่องคุณ:  ssh -L 18443:127.0.0.1:$PREVIEW_PORT <user>@203.185.144.41"
    echo "แล้วเปิด https://localhost:18443/deepwitya (เบราว์เซอร์เตือน cert ไม่ตรงชื่อ — กดผ่านได้ cert เป็นของ IP)"
    ;;

  --cutover)
    FROM="${2:?usage: --cutover <old-frontend-port> <new-frontend-port>}"
    TO="${3:?usage: --cutover <old-frontend-port> <new-frontend-port>}"
    echo "== cutover: :443 /deepwitya $FROM → $TO, + /deepwitya/studio → $GATEKEEPER_PORT; :80 /deepwitya → 301 https =="
    echo "== 0. ตรวจก่อนแตะ =="
    refuse_stale_preview
    swap_port "$SSL" "$FROM"
    redirect_http --check
    echo "== 1. backup =="
    backup "$SSL"; backup "$HTTP"
    echo "== 2. snippet =="
    write_studio_snippet
    echo "== 3. แก้ shared files =="
    swap_port "$SSL" "$FROM" "$TO"
    include_studio
    redirect_http
    printf 'FROM=%s\nTO=%s\nSTAMP=%s\n' "$FROM" "$TO" "$STAMP" > "$STATE"
    test_and_reload
    echo
    echo "เสร็จ — https://203.185.144.41/deepwitya ชี้ไป $TO แล้ว, /deepwitya/studio ชี้ไป gatekeeper, http://…/deepwitya → 301 https"
    echo "ถอย: sudo bash deploy/apply-nginx-golive.sh --revert"
    ;;

  --revert)
    [ -f "$STATE" ] || { echo "ไม่มี $STATE — ยังไม่เคย cutover หรือ revert ไปแล้ว" >&2; exit 1; }
    # shellcheck disable=SC1090
    . "$STATE"
    echo "== revert: :443 /deepwitya $TO → $FROM, เอา studio include ออก; :80 เอา return 301 ออก =="
    echo "== 0. ตรวจก่อนแตะ =="
    if listening "$FROM"; then
      echo "  พอร์ต $FROM (stack เก่า) มีคนฟังอยู่ — ถอยได้"
    elif [ "${2:-}" = "--force" ]; then
      echo "  !! พอร์ต $FROM ไม่มีใครฟัง แต่สั่ง --force — /deepwitya จะเป็น 502 จนกว่าจะมีอะไรฟังที่ $FROM"
    else
      echo "!! พอร์ต $FROM (stack เก่า) ไม่มีใครฟัง — stack เก่าถูกถอนแล้ว (§8)? revert จะทำให้ /deepwitya เป็น 502" >&2
      echo "   ทางถอยที่เหลือคือ GO-LIVE.md §7.3 (ตั้ง stack เดิมกลับมาก่อน แล้วค่อย revert) หรือ --revert --force ถ้าตั้งใจ" >&2
      exit 1
    fi
    backup "$SSL"; backup "$HTTP"
    swap_port "$SSL" "$TO" "$FROM"
    remove_include_studio
    unredirect_http
    test_and_reload
    rm -f "$STATE"
    echo "revert เรียบร้อย — /deepwitya กลับไปที่ $FROM (stack เก่าต้องยังรันอยู่)"
    ;;

  --remove-preview)
    pp=$(preview_file_port)
    rm -f "$PREVIEW_LINK" "$PREVIEW"
    nginx -t && systemctl reload nginx && echo "เอา preview ${pp:-?} ออกแล้ว"
    ;;

  *)
    sed -n '2,37p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
