#!/usr/bin/env bash
# ============================================
# Back up the Course Studio — the PostgreSQL database and the /app/data volume.
#
#   bash deploy/backup-studio.sh [dest-dir]        default ../_deeptutor_backup/studio
#   bash deploy/backup-studio.sh --verify <file>   list what a .dump contains
#   KEEP_DAYS=14 bash deploy/backup-studio.sh      prune backups older than N days (default 30)
#
# Needs docker only (no sudo). Runs from any directory. Safe to run while the
# studio is serving: pg_dump takes a consistent snapshot, and the data volume
# is read through a throwaway container mounted read-only.
#
# What the studio keeps where (2026-09-11 audit, F8 — measured, not assumed):
#   documents, scenes, stage_meta, credentials  PostgreSQL `openmaic`
#   asset bytes (no ASSET_S3_BUCKET set)        PostgreSQL, `asset_blobs`
#   uploaded material bytes, usage/*.jsonl      the /app/data volume
# So the two artifacts below are the whole studio. DeepWitya's own data/ is a
# separate backup (GO-LIVE.md §2).
#
# Restore (the order matters — the volume first, then the database):
#   1. stop the studio:   docker compose ... stop openmaic gatekeeper
#   2. volume:            docker run --rm -v <volume>:/d -v <dest>:/in:ro alpine \
#                           sh -c 'rm -rf /d/* && tar -C /d -xzf /in/openmaic-data-<stamp>.tar.gz'
#   3. database:          docker exec -i deeptutor-openmaic-postgres \
#                           pg_restore -U openmaic -d openmaic --clean --if-exists --no-owner \
#                           < <dest>/openmaic-<stamp>.dump
#   4. start:             docker compose ... up -d openmaic gatekeeper
#   Restoring into a database the app has since migrated forward is not
#   supported: restore onto the same image tag the dump was taken under.
#
# Cron (host, as the user in the docker group), daily at 03:30:
#   30 3 * * * cd /home/search/Thoughtmind/Upstream_Deeptutor_v2 && bash deploy/backup-studio.sh >> ../_deeptutor_backup/studio/backup.log 2>&1
# ============================================
set -euo pipefail

PG_CONTAINER=deeptutor-openmaic-postgres
STUDIO_CONTAINER=deeptutor-openmaic
DB_USER=openmaic
DB_NAME=openmaic
KEEP_DAYS="${KEEP_DAYS:-30}"

if [ "${1:-}" = "--verify" ]; then
  FILE="${2:?usage: --verify <file.dump>}"
  echo "== $FILE =="
  docker run --rm -i postgres:16 pg_restore --list < "$FILE" | grep -E "TABLE DATA" | awk '{print "  " $(NF-1)}' | sort  # `; id oid oid TABLE DATA schema table owner`
  exit 0
fi

DEST="${1:-$(dirname "$0")/../../_deeptutor_backup/studio}"
mkdir -p "$DEST"
# `pwd -W` is Git Bash's Windows-style path (what docker on Windows wants);
# everywhere else it fails and plain pwd is right.
DEST="$(cd "$DEST" && { pwd -W 2>/dev/null || pwd; })"
STAMP="$(date +%Y%m%d-%H%M%S)"

# The volume's real name depends on the compose project (the checkout folder);
# read it from the running container rather than guess.
VOLUME="$(docker inspect "$STUDIO_CONTAINER" --format '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{.Name}}{{end}}{{end}}')"
[ -n "$VOLUME" ] || { echo "!! $STUDIO_CONTAINER has no volume at /app/data" >&2; exit 1; }

echo "== studio backup $STAMP → $DEST =="

DUMP="$DEST/openmaic-$STAMP.dump"
docker exec "$PG_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > "$DUMP"
echo "  db      $(du -h "$DUMP" | cut -f1)  $DUMP"

TAR="$DEST/openmaic-data-$STAMP.tar.gz"
MSYS_NO_PATHCONV=1 docker run --rm -v "$VOLUME:/d:ro" -v "$DEST:/out" alpine \
  tar -C /d -czf "/out/$(basename "$TAR")" .
[ -s "$TAR" ] || { echo "!! $TAR was not written — the volume archive is missing" >&2; exit 1; }
echo "  volume  $(du -h "$TAR" | cut -f1)  $TAR  (volume $VOLUME)"

# A dump that pg_restore cannot list is not a backup.
TABLES="$(docker run --rm -i postgres:16 pg_restore --list < "$DUMP" | grep -c 'TABLE DATA' || true)"
[ "$TABLES" -gt 0 ] || { echo "!! $DUMP lists no table data — refusing to count this as a backup" >&2; exit 1; }
echo "  verify  $TABLES tables with data in the dump"

if [ "$KEEP_DAYS" -gt 0 ]; then
  PRUNED="$(find "$DEST" -maxdepth 1 -type f \( -name 'openmaic-*.dump' -o -name 'openmaic-data-*.tar.gz' \) -mtime +"$KEEP_DAYS" -print -delete | wc -l)"
  echo "  pruned  $PRUNED file(s) older than $KEEP_DAYS days"
fi
echo "done"
