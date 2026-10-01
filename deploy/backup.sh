#!/bin/sh
# Nightly Postgres backup: custom-format dump, 14 days kept.
# Cron (host):  15 3 * * *  cd /opt/tenderlens && ./deploy/backup.sh >> backups/backup.log 2>&1
set -eu
cd "$(dirname "$0")/.."
COMPOSE="${COMPOSE:-docker compose}"
DIR="${BACKUP_DIR:-backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p "$DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
OUT="$DIR/tenderlens-$STAMP.dump"
$COMPOSE exec -T postgres pg_dump -U tenderlens -d tenderlens -Fc > "$OUT.partial"
mv "$OUT.partial" "$OUT"   # a half-written dump never looks like a good one
# Verify the archive is readable before trusting it.
$COMPOSE exec -T postgres pg_restore --list < "$OUT" > /dev/null
find "$DIR" -name 'tenderlens-*.dump' -mtime +"$KEEP_DAYS" -delete
echo "$(date -Iseconds) backup ok: $OUT ($(du -h "$OUT" | cut -f1))"
